//! RawBlob content-addressed store: bounded streaming SHA-256, no-overwrite, byte recovery.
//! Phase 0 is a local filesystem CAS. Every public lookup validates its content identifier,
//! every existing destination is re-hashed, and every successful publish is verified again.
use anyhow::{bail, Context, Result};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{self, ErrorKind, Read, Write};
use std::path::{Path, PathBuf};

pub const MAX_BLOB_BYTES: u64 = 256 * 1024 * 1024;

pub struct Cas {
    root: PathBuf,
}

#[derive(Debug, Clone)]
pub struct BlobInfo {
    pub sha256: String,
    pub byte_size: u64,
    pub storage_uri: String,
    pub deduplicated: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceDigest {
    pub sha256: String,
    pub byte_size: u64,
}

/// Read-only preflight used to bind an authority envelope to the exact source bytes.
/// The source is opened and bounded exactly as it will be during the later CAS write.
pub fn inspect_source(src: &Path) -> Result<SourceDigest> {
    let (mut input, metadata_size) = open_source(src)?;
    let (sha256, byte_size) = hash_reader(&mut input)?;
    if byte_size != metadata_size {
        bail!("source changed while being inspected");
    }
    Ok(SourceDigest { sha256, byte_size })
}

impl Cas {
    pub fn open(root: impl AsRef<Path>) -> Result<Self> {
        let requested = root.as_ref();
        fs::create_dir_all(requested)?;
        let link_metadata = fs::symlink_metadata(requested)
            .with_context(|| format!("inspect CAS root {requested:?}"))?;
        if link_metadata.file_type().is_symlink() || !link_metadata.is_dir() {
            bail!("CAS root must be a non-symlink directory: {requested:?}");
        }
        let root = fs::canonicalize(requested)
            .with_context(|| format!("canonicalize CAS root {:?}", root.as_ref()))?;
        if !fs::metadata(&root)?.is_dir() {
            bail!("CAS root is not a directory: {root:?}");
        }
        Ok(Self { root })
    }

    /// Open the fixed CAS child directly beneath the already-authorized store root.
    /// A pre-created symlink/junction must never redirect signed-root side effects.
    pub fn open_scoped(store_root: &Path) -> Result<Self> {
        require_durable_scoped_filesystem()?;
        let root_metadata = fs::symlink_metadata(store_root)
            .with_context(|| format!("inspect authorized store root {store_root:?}"))?;
        if root_metadata.file_type().is_symlink() || !root_metadata.is_dir() {
            bail!("authorized store root must be a non-symlink directory");
        }
        let canonical_store = fs::canonicalize(store_root)?;
        let requested = canonical_store.join("cas");
        let cas = Self::open(&requested)?;
        if cas.root.parent() != Some(canonical_store.as_path()) {
            bail!("CAS root escapes the signed store root");
        }
        Ok(cas)
    }

    fn path_for(&self, hash: &str) -> Result<PathBuf> {
        validate_hash(hash)?;
        Ok(self.root.join(&hash[0..2]).join(&hash[2..4]).join(hash))
    }

    fn prepare_parent(&self, dest: &Path, create_missing: bool) -> Result<()> {
        let parent = dest
            .parent()
            .ok_or_else(|| anyhow::anyhow!("CAS destination has no parent"))?;
        let prefix = parent
            .parent()
            .ok_or_else(|| anyhow::anyhow!("CAS destination has no hash-prefix parent"))?;
        ensure_direct_child(&self.root, prefix, create_missing)?;
        ensure_direct_child(prefix, parent, create_missing)?;
        let canonical_parent = fs::canonicalize(parent)?;
        if !canonical_parent.starts_with(&self.root) {
            bail!("CAS destination escapes configured root");
        }
        Ok(())
    }

    /// Stream to a private temp, require the signed digest, then publish. A source
    /// mutation can burn the one-time authority but can never publish different bytes.
    pub fn put_file_expected(&self, src: &Path, expected_hash: &str) -> Result<BlobInfo> {
        validate_hash(expected_hash)?;
        let tmp = self.root.join(format!(".tmp-{}", uuid::Uuid::now_v7()));
        let result = self.put_file_inner(src, &tmp, expected_hash);
        if result.is_err() {
            fs::remove_file(&tmp).ok();
        }
        result
    }

    fn put_file_inner(&self, src: &Path, tmp: &Path, expected_hash: &str) -> Result<BlobInfo> {
        let (mut input, opened_size) = open_source(src)?;

        let mut output = OpenOptions::new().write(true).create_new(true).open(tmp)?;
        let mut hasher = Sha256::new();
        let mut buffer = [0_u8; 65_536];
        let mut size = 0_u64;
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            size = size
                .checked_add(count as u64)
                .ok_or_else(|| anyhow::anyhow!("blob size overflow"))?;
            if size > MAX_BLOB_BYTES {
                bail!("source exceeds {MAX_BLOB_BYTES} byte CAS limit while reading");
            }
            hasher.update(&buffer[..count]);
            output.write_all(&buffer[..count])?;
        }
        output.sync_all()?;
        drop(output);

        let hash = hex::encode(hasher.finalize());
        if size != opened_size {
            bail!("source changed while being copied");
        }
        if hash != expected_hash {
            bail!("source SHA-256 does not match consumed authority");
        }
        let dest = self.path_for(&hash)?;
        self.prepare_parent(&dest, true)?;

        match fs::symlink_metadata(&dest) {
            Ok(_) => {
                verify_blob_file(&dest, &hash, Some(size))?;
                fs::remove_file(tmp).ok();
                return Ok(blob_info(hash, size, dest, true));
            }
            Err(error) if error.kind() == ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }

        let published = match fs::hard_link(tmp, &dest) {
            Ok(()) => true,
            Err(error) if error.kind() == ErrorKind::AlreadyExists => false,
            Err(_) => publish_by_exclusive_copy(tmp, &dest)?,
        };

        // A racing writer is acceptable only when it published the exact expected bytes.
        verify_blob_file(&dest, &hash, Some(size))?;
        fs::remove_file(tmp).ok();

        if published {
            let mut permissions = fs::metadata(&dest)?.permissions();
            permissions.set_readonly(true);
            fs::set_permissions(&dest, permissions)?;
            File::open(&dest)?.sync_all()?;
            sync_directory(
                dest.parent()
                    .ok_or_else(|| anyhow::anyhow!("CAS destination has no parent"))?,
            )?;
        }

        Ok(blob_info(hash, size, dest, !published))
    }

    /// Exact bounded byte recovery, re-verifying stored bytes against the requested id.
    pub fn get_verified(&self, hash: &str) -> Result<Vec<u8>> {
        let path = self.path_for(hash)?;
        self.prepare_parent(&path, false)?;
        read_verified_blob(&path, hash)
    }
}

fn ensure_direct_child(parent: &Path, child: &Path, create_missing: bool) -> Result<()> {
    let canonical_parent = fs::canonicalize(parent)
        .with_context(|| format!("canonicalize CAS path parent {parent:?}"))?;
    let created = match fs::symlink_metadata(child) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            bail!("CAS path component must be a non-symlink directory: {child:?}")
        }
        Ok(_) => false,
        Err(error) if error.kind() == ErrorKind::NotFound && create_missing => {
            fs::create_dir(child)
                .with_context(|| format!("create direct CAS path component {child:?}"))?;
            true
        }
        Err(error) if error.kind() == ErrorKind::NotFound => {
            bail!("CAS path component is absent: {child:?}")
        }
        Err(error) => return Err(error.into()),
    };
    if created {
        sync_directory(parent)?;
    }
    let metadata = fs::symlink_metadata(child)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        bail!("CAS path component must be a non-symlink directory: {child:?}");
    }
    let canonical_child = fs::canonicalize(child)?;
    if canonical_child.parent() != Some(canonical_parent.as_path()) {
        bail!("CAS path component escapes its expected parent");
    }
    Ok(())
}

#[cfg(windows)]
fn require_durable_scoped_filesystem() -> Result<()> {
    bail!("scoped durable intake is disabled on Windows; use the pinned Linux gate/runtime")
}

#[cfg(not(windows))]
fn require_durable_scoped_filesystem() -> Result<()> {
    Ok(())
}

fn open_source(src: &Path) -> Result<(File, u64)> {
    let source_link_metadata =
        fs::symlink_metadata(src).with_context(|| format!("inspect source {src:?}"))?;
    if source_link_metadata.file_type().is_symlink() || !source_link_metadata.is_file() {
        bail!("source must be a regular, non-symlink file: {src:?}");
    }
    if source_link_metadata.len() > MAX_BLOB_BYTES {
        bail!("source exceeds {MAX_BLOB_BYTES} byte CAS limit");
    }
    let input = File::open(src).with_context(|| format!("open source {src:?}"))?;
    let opened_metadata = input.metadata()?;
    if !opened_metadata.is_file() || opened_metadata.len() > MAX_BLOB_BYTES {
        bail!("opened source is not an admissible regular file");
    }
    Ok((input, opened_metadata.len()))
}

fn hash_reader(input: &mut File) -> Result<(String, u64)> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 65_536];
    let mut size = 0_u64;
    loop {
        let count = input.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        size = size
            .checked_add(count as u64)
            .ok_or_else(|| anyhow::anyhow!("blob size overflow"))?;
        if size > MAX_BLOB_BYTES {
            bail!("source exceeds {MAX_BLOB_BYTES} byte CAS limit while reading");
        }
        hasher.update(&buffer[..count]);
    }
    Ok((hex::encode(hasher.finalize()), size))
}

fn validate_hash(hash: &str) -> Result<()> {
    if hash.len() != 64
        || !hash
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
    {
        bail!("invalid SHA-256 content identifier");
    }
    Ok(())
}

fn blob_info(hash: String, size: u64, dest: PathBuf, deduplicated: bool) -> BlobInfo {
    BlobInfo {
        sha256: hash,
        byte_size: size,
        storage_uri: dest.to_string_lossy().into_owned(),
        deduplicated,
    }
}

fn publish_by_exclusive_copy(tmp: &Path, dest: &Path) -> Result<bool> {
    let mut destination = match OpenOptions::new().write(true).create_new(true).open(dest) {
        Ok(file) => file,
        Err(error) if error.kind() == ErrorKind::AlreadyExists => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    let copy_result = (|| -> Result<()> {
        let mut source = File::open(tmp)?;
        io::copy(&mut source, &mut destination)?;
        destination.sync_all()?;
        Ok(())
    })();
    if let Err(error) = copy_result {
        drop(destination);
        fs::remove_file(dest).ok();
        return Err(error);
    }
    Ok(true)
}

fn inspect_blob(path: &Path) -> Result<(File, u64)> {
    let link_metadata =
        fs::symlink_metadata(path).with_context(|| format!("inspect blob {path:?}"))?;
    if link_metadata.file_type().is_symlink() || !link_metadata.is_file() {
        bail!("CAS blob must be a regular, non-symlink file: {path:?}");
    }
    if link_metadata.len() > MAX_BLOB_BYTES {
        bail!("stored blob exceeds {MAX_BLOB_BYTES} byte CAS limit");
    }
    let file = File::open(path).with_context(|| format!("open blob {path:?}"))?;
    let opened_metadata = file.metadata()?;
    if !opened_metadata.is_file() || opened_metadata.len() > MAX_BLOB_BYTES {
        bail!("opened CAS blob is not admissible");
    }
    Ok((file, opened_metadata.len()))
}

fn verify_blob_file(path: &Path, expected_hash: &str, expected_size: Option<u64>) -> Result<()> {
    let (mut file, metadata_size) = inspect_blob(path)?;
    if let Some(size) = expected_size {
        if metadata_size != size {
            bail!("hash {expected_hash} maps to unexpected byte size");
        }
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 65_536];
    let mut size = 0_u64;
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        size = size
            .checked_add(count as u64)
            .ok_or_else(|| anyhow::anyhow!("blob size overflow"))?;
        if size > MAX_BLOB_BYTES {
            bail!("stored blob exceeds {MAX_BLOB_BYTES} byte CAS limit while reading");
        }
        hasher.update(&buffer[..count]);
    }
    if size != metadata_size || hex::encode(hasher.finalize()) != expected_hash {
        bail!("CAS blob integrity verification failed for {expected_hash}");
    }
    Ok(())
}

fn read_verified_blob(path: &Path, expected_hash: &str) -> Result<Vec<u8>> {
    let (mut file, metadata_size) = inspect_blob(path)?;
    let capacity = usize::try_from(metadata_size)
        .map_err(|_| anyhow::anyhow!("blob cannot fit in memory on this platform"))?;
    let mut bytes = Vec::with_capacity(capacity);
    Read::by_ref(&mut file)
        .take(MAX_BLOB_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata_size {
        bail!("CAS blob changed while being read");
    }
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    let actual_hash = hex::encode(hasher.finalize());
    if actual_hash != expected_hash {
        bail!("integrity failure: requested {expected_hash}, stored bytes hash {actual_hash}");
    }
    Ok(bytes)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<()> {
    let directory = File::open(path)
        .with_context(|| format!("open CAS directory for durability sync {path:?}"))?;
    directory
        .sync_all()
        .with_context(|| format!("durably sync CAS directory {path:?}"))
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<()> {
    bail!("durable CAS publication requires Unix directory fsync")
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!("kf-cas-test-{}", uuid::Uuid::now_v7()));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            make_tree_writable(&self.0);
            fs::remove_dir_all(&self.0).ok();
        }
    }

    fn make_tree_writable(path: &Path) {
        if let Ok(entries) = fs::read_dir(path) {
            for entry in entries.flatten() {
                let child = entry.path();
                if child.is_dir() {
                    make_tree_writable(&child);
                }
                make_owner_writable(&child);
            }
        }
    }

    #[cfg(unix)]
    fn make_owner_writable(path: &Path) {
        use std::os::unix::fs::PermissionsExt;

        if let Ok(metadata) = fs::metadata(path) {
            let mut permissions = metadata.permissions();
            permissions.set_mode(permissions.mode() | 0o200);
            fs::set_permissions(path, permissions).ok();
        }
    }

    #[cfg(windows)]
    fn make_owner_writable(path: &Path) {
        if let Ok(metadata) = fs::metadata(path) {
            let mut permissions = metadata.permissions();
            permissions.set_readonly(false);
            fs::set_permissions(path, permissions).ok();
        }
    }

    #[test]
    fn put_get_and_deduplicate_exact_bytes() {
        let temp = TestDir::new();
        let source = temp.0.join("source.txt");
        fs::write(&source, b"immutable bytes").unwrap();
        let cas = Cas::open(temp.0.join("cas")).unwrap();

        let expected = inspect_source(&source).unwrap();
        let first = cas.put_file_expected(&source, &expected.sha256).unwrap();
        assert!(!first.deduplicated);
        assert_eq!(cas.get_verified(&first.sha256).unwrap(), b"immutable bytes");

        let second = cas.put_file_expected(&source, &expected.sha256).unwrap();
        assert!(second.deduplicated);
        assert_eq!(first.sha256, second.sha256);
    }

    #[test]
    fn malformed_content_ids_are_errors_not_panics() {
        let temp = TestDir::new();
        let cas = Cas::open(temp.0.join("cas")).unwrap();
        for hash in ["", "abc", &"g".repeat(64), &"A".repeat(64)] {
            assert!(cas.get_verified(hash).is_err());
        }
    }

    #[test]
    fn same_length_corruption_is_not_accepted_as_deduplication() {
        let temp = TestDir::new();
        let source = temp.0.join("source.txt");
        fs::write(&source, b"correct bytes").unwrap();
        let cas = Cas::open(temp.0.join("cas")).unwrap();
        let expected = inspect_source(&source).unwrap();
        let stored = cas.put_file_expected(&source, &expected.sha256).unwrap();
        let destination = cas.path_for(&stored.sha256).unwrap();

        make_owner_writable(&destination);
        fs::write(&destination, b"corrupt bytes").unwrap();

        assert!(cas.put_file_expected(&source, &expected.sha256).is_err());
        assert!(cas.get_verified(&stored.sha256).is_err());
    }

    #[test]
    fn unexpected_bytes_are_never_published() {
        let temp = TestDir::new();
        let source = temp.0.join("source.txt");
        fs::write(&source, b"mutated after authority").unwrap();
        let cas = Cas::open(temp.0.join("cas")).unwrap();
        let wrong_hash = hex::encode(Sha256::digest(b"authorized bytes"));

        assert!(cas.put_file_expected(&source, &wrong_hash).is_err());
        assert!(cas.get_verified(&wrong_hash).is_err());
        assert!(walk_files(&cas.root).iter().all(|path| !path
            .file_name()
            .is_some_and(|name| name.to_string_lossy().len() == 64)));
    }

    #[cfg(unix)]
    #[test]
    fn hash_prefix_symlink_cannot_create_outside_cas_root() {
        use std::os::unix::fs::symlink;

        let temp = TestDir::new();
        let source = temp.0.join("source.txt");
        fs::write(&source, b"hash-prefix boundary").unwrap();
        let cas = Cas::open(temp.0.join("cas")).unwrap();
        let expected = inspect_source(&source).unwrap();
        let outside = temp.0.join("outside");
        fs::create_dir(&outside).unwrap();
        symlink(&outside, cas.root.join(&expected.sha256[0..2])).unwrap();

        assert!(cas.put_file_expected(&source, &expected.sha256).is_err());
        assert!(!outside.join(&expected.sha256[2..4]).exists());
        assert!(walk_files(&outside).is_empty());
    }

    fn walk_files(root: &Path) -> Vec<PathBuf> {
        let mut files = Vec::new();
        if let Ok(entries) = fs::read_dir(root) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    files.extend(walk_files(&path));
                } else {
                    files.push(path);
                }
            }
        }
        files
    }
}
