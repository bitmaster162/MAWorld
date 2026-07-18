//! Metadata store: append-only hash-chained event ledger + rebuildable projections.
//! Demonstrates closure v1.1 KD-03 (immutable events + mutable projections) and the
//! hash-chain integrity of ContinuityOS-style audit. Phase-0 impl = local JSONL file;
//! production swaps a Postgres/sqlx impl behind the same MetaStore surface.
use crate::identity::{ArtifactOccurrence, ArtifactVersion, RawBlob};
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs::{File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};

const GENESIS: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const META_MARKER_NAME: &str = ".meta-ledger.initialized";
const META_MARKER_BYTES: &[u8] = b"maworld.kf.meta-ledger.initialized.v1\n";
const MAX_LEDGER_BYTES: u64 = 64 * 1024 * 1024;
const MAX_EVENT_BYTES: usize = 1024 * 1024;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    seq: u64,
    kind: String,
    payload: serde_json::Value,
    prev_hash: String,
    hash: String,
}

struct ValidatedReplay {
    blobs_by_hash: HashMap<String, RawBlob>,
    occurrences: HashMap<String, ArtifactOccurrence>,
    versions: Vec<ArtifactVersion>,
    last_hash: String,
    seq: u64,
}

impl ValidatedReplay {
    fn genesis() -> Self {
        Self {
            blobs_by_hash: HashMap::new(),
            occurrences: HashMap::new(),
            versions: Vec::new(),
            last_hash: GENESIS.to_string(),
            seq: 0,
        }
    }
}

fn event_hash(
    prev_hash: &str,
    kind: &str,
    seq: u64,
    payload: &serde_json::Value,
) -> Result<String> {
    let body = serde_json::to_string(payload)?;
    let mut h = Sha256::new();
    h.update(prev_hash.as_bytes());
    h.update(kind.as_bytes());
    h.update(seq.to_string().as_bytes());
    h.update(body.as_bytes());
    Ok(hex::encode(h.finalize()))
}

fn apply_projection(
    blobs_by_hash: &mut HashMap<String, RawBlob>,
    occurrences: &mut HashMap<String, ArtifactOccurrence>,
    versions: &mut Vec<ArtifactVersion>,
    kind: &str,
    payload: &serde_json::Value,
) -> Result<()> {
    match kind {
        "blob.created" => {
            let blob = serde_json::from_value::<RawBlob>(payload.clone())
                .context("invalid blob.created payload")?;
            if blob.blob_id.trim().is_empty()
                || blob.sha256.len() != 64
                || !blob
                    .sha256
                    .as_bytes()
                    .iter()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
                || blob.storage_uri.trim().is_empty()
                || blob.media_type_detected.trim().is_empty()
            {
                bail!("invalid blob identity or metadata");
            }
            if blobs_by_hash.contains_key(&blob.sha256)
                || blobs_by_hash
                    .values()
                    .any(|existing| existing.blob_id == blob.blob_id)
            {
                bail!("duplicate blob identity");
            }
            blobs_by_hash.insert(blob.sha256.clone(), blob);
        }
        "occurrence.created" => {
            let occurrence = serde_json::from_value::<ArtifactOccurrence>(payload.clone())
                .context("invalid occurrence.created payload")?;
            if occurrence.occurrence_id.trim().is_empty()
                || occurrence.project_id.trim().is_empty()
                || occurrence.source_system_id.trim().is_empty()
                || occurrence.source_native_id.trim().is_empty()
                || occurrence.blob_id.trim().is_empty()
                || !blobs_by_hash
                    .values()
                    .any(|blob| blob.blob_id == occurrence.blob_id)
            {
                bail!("invalid occurrence identity or blob reference");
            }
            if occurrences.contains_key(&occurrence.occurrence_id)
                || occurrences.values().any(|existing| {
                    existing.project_id == occurrence.project_id
                        && existing.source_system_id == occurrence.source_system_id
                        && existing.source_native_id == occurrence.source_native_id
                })
            {
                bail!("duplicate occurrence identity or idempotency key");
            }
            occurrences.insert(occurrence.occurrence_id.clone(), occurrence);
        }
        "version.created" => {
            let version = serde_json::from_value::<ArtifactVersion>(payload.clone())
                .context("invalid version.created payload")?;
            if version.version_id.trim().is_empty()
                || version.occurrence_id.trim().is_empty()
                || version.blob_id.trim().is_empty()
                || version.source_revision_key.trim().is_empty()
                || !occurrences.contains_key(&version.occurrence_id)
                || !blobs_by_hash
                    .values()
                    .any(|blob| blob.blob_id == version.blob_id)
                || version
                    .parent_version_id
                    .as_ref()
                    .is_some_and(|parent| !versions.iter().any(|item| &item.version_id == parent))
            {
                bail!("invalid version identity or reference");
            }
            if versions.iter().any(|existing| {
                existing.version_id == version.version_id
                    || (existing.occurrence_id == version.occurrence_id
                        && existing.source_revision_key == version.source_revision_key)
            }) {
                bail!("duplicate version identity or revision key");
            }
            versions.push(version);
        }
        _ => bail!("unknown event kind: {kind}"),
    }
    Ok(())
}

fn load_validated_replay(log_path: &Path) -> Result<ValidatedReplay> {
    let link_metadata = std::fs::symlink_metadata(log_path)
        .with_context(|| format!("inspect event ledger {}", log_path.display()))?;
    if link_metadata.file_type().is_symlink() || !link_metadata.is_file() {
        bail!("event ledger must be a regular, non-symlink file");
    }
    if link_metadata.len() > MAX_LEDGER_BYTES {
        bail!("event ledger exceeds {MAX_LEDGER_BYTES} byte limit");
    }
    let mut file = File::open(log_path)?;
    let opened_size = file.metadata()?.len();
    if opened_size > MAX_LEDGER_BYTES {
        bail!("opened event ledger exceeds {MAX_LEDGER_BYTES} byte limit");
    }
    let capacity = usize::try_from(opened_size)
        .context("event ledger cannot fit in memory on this platform")?;
    let mut bytes = Vec::with_capacity(capacity);
    Read::by_ref(&mut file)
        .take(MAX_LEDGER_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != opened_size || bytes.len() as u64 > MAX_LEDGER_BYTES {
        bail!("event ledger changed or exceeded its limit while being read");
    }
    let mut replay = ValidatedReplay::genesis();
    if bytes.is_empty() {
        return Ok(replay);
    }
    if !bytes.ends_with(b"\n") {
        bail!("event ledger has a partial terminal line");
    }

    for (line_index, encoded_line) in bytes[..bytes.len() - 1]
        .split(|byte| *byte == b'\n')
        .enumerate()
    {
        let line_number = line_index + 1;
        if encoded_line.is_empty() {
            bail!("empty event line {line_number}");
        }
        if encoded_line.len() > MAX_EVENT_BYTES {
            bail!("event line {line_number} exceeds {MAX_EVENT_BYTES} byte limit");
        }
        let line = std::str::from_utf8(encoded_line)
            .with_context(|| format!("event line {line_number} is not UTF-8"))?;

        let ev: Event = serde_json::from_str(line)
            .with_context(|| format!("corrupt event line {line_number}"))?;
        let expected_seq = replay
            .seq
            .checked_add(1)
            .context("event sequence overflow")?;
        if ev.seq != expected_seq {
            bail!(
                "non-contiguous event sequence at line {line_number}: expected {expected_seq}, got {}",
                ev.seq
            );
        }
        if ev.prev_hash != replay.last_hash {
            bail!("previous hash mismatch at event sequence {}", ev.seq);
        }

        let expected_hash = event_hash(&ev.prev_hash, &ev.kind, ev.seq, &ev.payload)?;
        if ev.hash != expected_hash {
            bail!("event hash mismatch at event sequence {}", ev.seq);
        }

        apply_projection(
            &mut replay.blobs_by_hash,
            &mut replay.occurrences,
            &mut replay.versions,
            &ev.kind,
            &ev.payload,
        )
        .with_context(|| format!("invalid projection at event sequence {}", ev.seq))?;

        replay.last_hash = ev.hash;
        replay.seq = ev.seq;
    }

    Ok(replay)
}

fn load_current_replay(log_path: &Path) -> Result<ValidatedReplay> {
    match std::fs::symlink_metadata(log_path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("event ledger must be a regular, non-symlink file")
        }
        Ok(_) => load_validated_replay(log_path),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(ValidatedReplay::genesis()),
        Err(error) => Err(error.into()),
    }
}

fn with_ledger_lock<T>(log_path: &Path, operation: impl FnOnce() -> Result<T>) -> Result<T> {
    // Lock a sidecar rather than events.jsonl itself. In particular, this avoids
    // opening a second handle to the locked journal during replay on Windows.
    let lock_path = log_path.with_extension("jsonl.lock");
    match std::fs::symlink_metadata(&lock_path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("ledger lock must be a regular, non-symlink file")
        }
        Ok(_) => {}
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let lock_file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)
        .with_context(|| format!("failed to open ledger lock {}", lock_path.display()))?;
    if !lock_file.metadata()?.is_file() {
        bail!("opened ledger lock is not a regular file");
    }
    lock_file
        .lock()
        .with_context(|| format!("failed to acquire ledger lock {}", lock_path.display()))?;

    let operation_result = operation();
    let unlock_result = lock_file
        .unlock()
        .with_context(|| format!("failed to release ledger lock {}", lock_path.display()));

    match (operation_result, unlock_result) {
        (Ok(value), Ok(())) => Ok(value),
        (Err(error), Ok(())) => Err(error),
        (Ok(_), Err(unlock_error)) => Err(unlock_error),
        (Err(error), Err(unlock_error)) => Err(error.context(format!(
            "ledger operation failed and lock release also failed: {unlock_error:#}"
        ))),
    }
}

pub struct MetaStore {
    log_path: PathBuf,
    // projections rebuilt from the event log
    blobs_by_hash: HashMap<String, RawBlob>,
    occurrences: HashMap<String, ArtifactOccurrence>, // occurrence_id -> occ
    versions: Vec<ArtifactVersion>,
    last_hash: String,
    seq: u64,
}

impl MetaStore {
    pub fn open(dir: impl AsRef<Path>) -> Result<Self> {
        let requested = dir.as_ref();
        std::fs::create_dir_all(requested)?;
        let metadata = std::fs::symlink_metadata(requested)
            .with_context(|| format!("inspect metadata directory {}", requested.display()))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            bail!("metadata path must be a non-symlink directory");
        }
        let canonical_dir = std::fs::canonicalize(requested)
            .with_context(|| format!("canonicalize metadata directory {}", requested.display()))?;
        let log_path = canonical_dir.join("events.jsonl");
        let mut s = MetaStore {
            log_path: log_path.clone(),
            blobs_by_hash: HashMap::new(),
            occurrences: HashMap::new(),
            versions: Vec::new(),
            last_hash: GENESIS.to_string(),
            seq: 0,
        };
        s.replay()?;
        Ok(s)
    }

    /// Open the fixed metadata child directly beneath the already-authorized store root.
    pub fn open_scoped(store_root: &Path) -> Result<Self> {
        require_durable_scoped_filesystem()?;
        let root_metadata = std::fs::symlink_metadata(store_root)
            .with_context(|| format!("inspect authorized store root {}", store_root.display()))?;
        if root_metadata.file_type().is_symlink() || !root_metadata.is_dir() {
            bail!("authorized store root must be a non-symlink directory");
        }
        let canonical_store = std::fs::canonicalize(store_root)?;
        let requested = canonical_store.join("meta");
        let marker_path = canonical_store.join(META_MARKER_NAME);
        let marker_exists = regular_file_exists(&marker_path, "metadata initialization marker")?;
        let meta_exists = directory_exists(&requested, "metadata directory")?;
        match (marker_exists, meta_exists) {
            (false, false) => {
                initialize_scoped_metadata(&canonical_store, &requested, &marker_path)?
            }
            (true, true) => {}
            _ => bail!("metadata ledger initialization is incomplete or was deleted"),
        }
        verify_marker(&marker_path)?;
        if !regular_file_exists(&requested.join("events.jsonl"), "event ledger")? {
            bail!("event ledger is missing after metadata initialization");
        }
        let store = Self::open(&requested)?;
        if store.log_path.parent() != Some(requested.as_path()) {
            bail!("metadata directory escapes the signed store root");
        }
        Ok(store)
    }

    /// Read-only CLI verification. Unlike `open`, this never creates a directory,
    /// ledger, or lock sidecar. A concurrent mutation is rejected by the bounded
    /// reader's size checks rather than serialized through a writable lock file.
    pub fn verify_existing(dir: impl AsRef<Path>) -> Result<(bool, u64)> {
        let dir = dir.as_ref();
        let metadata = std::fs::symlink_metadata(dir)
            .with_context(|| format!("inspect metadata directory {}", dir.display()))?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            bail!("metadata path must be an existing, non-symlink directory");
        }
        let marker_path = dir
            .parent()
            .context("metadata directory has no store-root parent")?
            .join(META_MARKER_NAME);
        let scoped_initialized =
            regular_file_exists(&marker_path, "metadata initialization marker")?;
        if !scoped_initialized {
            bail!("metadata store is not initialized by the scoped intake boundary");
        }
        verify_marker(&marker_path)?;
        let log_path = dir.join("events.jsonl");
        match std::fs::symlink_metadata(&log_path) {
            Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
                bail!("event ledger must be a regular, non-symlink file")
            }
            Ok(_) => {
                let replay = load_validated_replay(&log_path)?;
                Ok((true, replay.seq))
            }
            Err(error) if error.kind() == ErrorKind::NotFound => {
                bail!("event ledger is missing after metadata initialization")
            }
            Err(error) => Err(error.into()),
        }
    }

    fn replay(&mut self) -> Result<()> {
        // Build an isolated snapshot first. A late malformed/tampered event must not
        // expose any projection derived from an earlier line in the same replay.
        let replay = with_ledger_lock(&self.log_path, || load_current_replay(&self.log_path))?;
        self.blobs_by_hash = replay.blobs_by_hash;
        self.occurrences = replay.occurrences;
        self.versions = replay.versions;
        self.last_hash = replay.last_hash;
        self.seq = replay.seq;
        Ok(())
    }

    fn append(&mut self, kind: &str, payload: serde_json::Value) -> Result<String> {
        let log_path = self.log_path.clone();
        with_ledger_lock(&log_path, || {
            // A MetaStore may have been opened before another process appended.
            // Validate the complete disk chain while holding the lock and refuse
            // to branch from a stale in-memory tail.
            let disk = load_current_replay(&log_path)?;
            if disk.seq != self.seq || disk.last_hash != self.last_hash {
                bail!(
                    "stale metadata state: memory tail ({}, {}) does not match disk tail ({}, {})",
                    self.seq,
                    self.last_hash,
                    disk.seq,
                    disk.last_hash
                );
            }

            let next_seq = self.seq.checked_add(1).context("event sequence overflow")?;
            let hash = event_hash(&self.last_hash, kind, next_seq, &payload)?;
            let mut next_blobs = self.blobs_by_hash.clone();
            let mut next_occurrences = self.occurrences.clone();
            let mut next_versions = self.versions.clone();
            apply_projection(
                &mut next_blobs,
                &mut next_occurrences,
                &mut next_versions,
                kind,
                &payload,
            )?;
            let ev = Event {
                seq: next_seq,
                kind: kind.to_string(),
                payload: payload.clone(),
                prev_hash: self.last_hash.clone(),
                hash: hash.clone(),
            };
            let mut f = OpenOptions::new()
                .create(true)
                .append(true)
                .open(&log_path)?;
            writeln!(f, "{}", serde_json::to_string(&ev)?)?;
            f.sync_data()?;
            sync_directory(
                log_path
                    .parent()
                    .context("event ledger has no parent directory")?,
            )?;
            self.blobs_by_hash = next_blobs;
            self.occurrences = next_occurrences;
            self.versions = next_versions;
            self.seq = next_seq;
            self.last_hash = hash.clone();
            Ok(hash)
        })
    }

    /// Returns true if the blob is newly recorded, false if it already existed (dedup).
    pub fn upsert_blob(&mut self, b: &RawBlob) -> Result<bool> {
        if self.blobs_by_hash.contains_key(&b.sha256) {
            return Ok(false);
        }
        self.append("blob.created", serde_json::to_value(b)?)?;
        Ok(true)
    }

    pub fn blob_by_hash(&self, sha: &str) -> Option<&RawBlob> {
        self.blobs_by_hash.get(sha)
    }

    /// Idempotency key: (project_id, source_system_id, source_native_id).
    pub fn find_occurrence(
        &self,
        project: &str,
        source_system_id: &str,
        source_native_id: &str,
    ) -> Option<&ArtifactOccurrence> {
        self.occurrences.values().find(|occurrence| {
            occurrence.project_id == project
                && occurrence.source_system_id == source_system_id
                && occurrence.source_native_id == source_native_id
        })
    }

    pub fn add_occurrence(&mut self, o: &ArtifactOccurrence) -> Result<()> {
        self.append("occurrence.created", serde_json::to_value(o)?)?;
        Ok(())
    }

    pub fn add_version(&mut self, v: &ArtifactVersion) -> Result<()> {
        self.append("version.created", serde_json::to_value(v)?)?;
        Ok(())
    }

    pub fn version_for_occurrence_blob(
        &self,
        occurrence_id: &str,
        blob_id: &str,
    ) -> Option<&ArtifactVersion> {
        self.versions
            .iter()
            .rev()
            .find(|version| version.occurrence_id == occurrence_id && version.blob_id == blob_id)
    }

    pub fn latest_version_for_occurrence(&self, occurrence_id: &str) -> Option<&ArtifactVersion> {
        self.versions
            .iter()
            .rev()
            .find(|version| version.occurrence_id == occurrence_id)
    }

    #[cfg(test)]
    pub fn count_blobs(&self) -> usize {
        self.blobs_by_hash.len()
    }

    /// Verify the append-only hash chain end to end.
    #[cfg(test)]
    pub fn verify_chain(&self) -> Result<(bool, u64)> {
        with_ledger_lock(&self.log_path, || {
            let replay = load_current_replay(&self.log_path)?;
            Ok((true, replay.seq))
        })
    }
}

fn regular_file_exists(path: &Path, label: &str) -> Result<bool> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("{label} must be a regular, non-symlink file")
        }
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

fn directory_exists(path: &Path, label: &str) -> Result<bool> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            bail!("{label} must be a non-symlink directory")
        }
        Ok(_) => Ok(true),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error.into()),
    }
}

fn initialize_scoped_metadata(
    canonical_store: &Path,
    metadata_dir: &Path,
    marker_path: &Path,
) -> Result<()> {
    let mut marker = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(marker_path)
        .context("create metadata initialization marker")?;
    marker.write_all(META_MARKER_BYTES)?;
    marker.sync_all()?;
    sync_directory(canonical_store)?;

    std::fs::create_dir(metadata_dir).context("create scoped metadata directory")?;
    sync_directory(canonical_store)?;
    let ledger = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(metadata_dir.join("events.jsonl"))
        .context("create scoped metadata ledger")?;
    ledger.sync_all()?;
    sync_directory(metadata_dir)?;
    Ok(())
}

fn verify_marker(marker_path: &Path) -> Result<()> {
    let mut marker = File::open(marker_path).context("open metadata initialization marker")?;
    let mut bytes = Vec::with_capacity(META_MARKER_BYTES.len());
    Read::by_ref(&mut marker)
        .take(129)
        .read_to_end(&mut bytes)?;
    if bytes != META_MARKER_BYTES {
        bail!("metadata initialization marker is invalid");
    }
    Ok(())
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<()> {
    let directory = File::open(path)
        .with_context(|| format!("open directory for durability sync {}", path.display()))?;
    directory
        .sync_all()
        .with_context(|| format!("durably sync directory {}", path.display()))
}

#[cfg(windows)]
fn sync_directory(_path: &Path) -> Result<()> {
    bail!("durable scoped metadata is disabled on Windows")
}

#[cfg(not(any(unix, windows)))]
fn sync_directory(_path: &Path) -> Result<()> {
    bail!("durable metadata requires directory fsync support")
}

#[cfg(windows)]
fn require_durable_scoped_filesystem() -> Result<()> {
    bail!("durable scoped metadata is disabled on Windows; use the pinned Linux runtime")
}

#[cfg(not(windows))]
fn require_durable_scoped_filesystem() -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path =
                std::env::temp_dir().join(format!("kf-meta-{label}-{}", uuid::Uuid::now_v7()));
            std::fs::create_dir_all(&path).expect("create test directory");
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }

        fn log_path(&self) -> PathBuf {
            self.0.join("events.jsonl")
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn blob() -> RawBlob {
        blob_named("blob-1", 'a')
    }

    fn blob_named(blob_id: &str, hash_char: char) -> RawBlob {
        RawBlob {
            blob_id: blob_id.to_string(),
            sha256: hash_char.to_string().repeat(64),
            byte_size: 7,
            storage_uri: format!("cas://{hash_char}{hash_char}/{blob_id}"),
            media_type_detected: "text/plain".to_string(),
        }
    }

    fn occurrence() -> ArtifactOccurrence {
        ArtifactOccurrence {
            occurrence_id: "occ-1".to_string(),
            project_id: "project-1".to_string(),
            source_system_id: "local".to_string(),
            source_native_id: "source-1".to_string(),
            observed_path: "input.txt".to_string(),
            blob_id: "blob-1".to_string(),
        }
    }

    fn version() -> ArtifactVersion {
        ArtifactVersion {
            version_id: "version-1".to_string(),
            occurrence_id: "occ-1".to_string(),
            blob_id: "blob-1".to_string(),
            source_revision_key: "revision-1".to_string(),
            parent_version_id: None,
        }
    }

    fn make_event(seq: u64, kind: &str, payload: serde_json::Value, prev_hash: &str) -> Event {
        let hash = event_hash(prev_hash, kind, seq, &payload).expect("hash event");
        Event {
            seq,
            kind: kind.to_string(),
            payload,
            prev_hash: prev_hash.to_string(),
            hash,
        }
    }

    fn write_events(path: &Path, events: &[Event]) {
        let body = events
            .iter()
            .map(|event| serde_json::to_string(event).expect("serialize event"))
            .collect::<Vec<_>>()
            .join("\n");
        std::fs::write(path, format!("{body}\n")).expect("write event log");
    }

    #[test]
    fn valid_log_replays_all_projections() {
        let dir = TestDir::new("valid");
        let mut store = MetaStore::open(dir.path()).expect("open empty store");
        assert!(store.upsert_blob(&blob()).expect("append blob"));
        store
            .add_occurrence(&occurrence())
            .expect("append occurrence");
        store.add_version(&version()).expect("append version");
        drop(store);

        let replayed = MetaStore::open(dir.path()).expect("replay valid log");
        assert_eq!(replayed.count_blobs(), 1);
        assert_eq!(replayed.occurrences.len(), 1);
        assert_eq!(replayed.versions.len(), 1);
        assert_eq!(
            replayed.verify_chain().expect("verify valid log"),
            (true, 3)
        );
    }

    #[test]
    fn tampered_hash_is_rejected() {
        let dir = TestDir::new("hash");
        let event = make_event(
            1,
            "blob.created",
            serde_json::to_value(blob()).expect("serialize blob"),
            GENESIS,
        );
        let mut tampered = event;
        tampered.hash = "f".repeat(64);
        write_events(&dir.log_path(), &[tampered]);

        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn non_contiguous_sequence_is_rejected_even_with_matching_hash() {
        let dir = TestDir::new("seq");
        let event = make_event(
            2,
            "blob.created",
            serde_json::to_value(blob()).expect("serialize blob"),
            GENESIS,
        );
        write_events(&dir.log_path(), &[event]);

        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn unknown_event_kind_is_rejected_even_with_matching_hash() {
        let dir = TestDir::new("kind");
        let event = make_event(1, "future.unrecognized", serde_json::json!({}), GENESIS);
        write_events(&dir.log_path(), &[event]);

        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn malformed_known_payload_is_rejected_even_with_matching_hash() {
        let dir = TestDir::new("payload");
        let event = make_event(
            1,
            "blob.created",
            serde_json::json!({"sha256": "a"}),
            GENESIS,
        );
        write_events(&dir.log_path(), &[event]);

        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn partial_terminal_line_is_rejected() {
        let dir = TestDir::new("partial-line");
        std::fs::write(dir.log_path(), b"{\"seq\":1}").expect("write partial event");
        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn oversized_event_line_is_rejected_before_json_parsing() {
        let dir = TestDir::new("oversized-line");
        let mut line = vec![b'a'; MAX_EVENT_BYTES + 1];
        line.push(b'\n');
        std::fs::write(dir.log_path(), line).expect("write oversized event");
        assert!(MetaStore::open(dir.path()).is_err());
    }

    #[test]
    fn late_failure_does_not_publish_partial_replay() {
        let dir = TestDir::new("atomic");
        let mut store = MetaStore::open(dir.path()).expect("open empty store");
        assert_eq!(store.count_blobs(), 0);
        assert_eq!(store.occurrences.len(), 0);

        let first = make_event(
            1,
            "blob.created",
            serde_json::to_value(blob()).expect("serialize blob"),
            GENESIS,
        );
        let second = make_event(
            2,
            "occurrence.created",
            serde_json::to_value(occurrence()).expect("serialize occurrence"),
            &first.hash,
        );
        let invalid = make_event(3, "unknown.late", serde_json::json!({}), &second.hash);
        write_events(&dir.log_path(), &[first, second, invalid]);

        assert!(store.replay().is_err());
        assert_eq!(store.count_blobs(), 0);
        assert_eq!(store.occurrences.len(), 0);
        assert_eq!(store.versions.len(), 0);
        assert_eq!(store.seq, 0);
        assert_eq!(store.last_hash, GENESIS);
    }

    #[test]
    fn concurrent_stale_writers_cannot_fork_the_chain() {
        use std::sync::{Arc, Barrier};

        let dir = TestDir::new("concurrent-stale");
        let path = Arc::new(dir.path().to_path_buf());
        let ready = Arc::new(Barrier::new(3));
        let mut workers = Vec::new();

        for (blob_id, hash_char) in [("blob-a", 'a'), ("blob-b", 'b')] {
            let path = Arc::clone(&path);
            let ready = Arc::clone(&ready);
            workers.push(std::thread::spawn(move || {
                let mut store = MetaStore::open(path.as_path()).expect("open worker store");
                ready.wait();
                store.upsert_blob(&blob_named(blob_id, hash_char))
            }));
        }

        // Both stores have replayed the same genesis tail before either append.
        ready.wait();
        let results = workers
            .into_iter()
            .map(|worker| worker.join().expect("worker did not panic"))
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);
        let stale_error = results
            .iter()
            .find_map(|result| result.as_ref().err())
            .expect("one stale writer must be rejected")
            .to_string();
        assert!(stale_error.contains("stale metadata state"));

        let replayed = MetaStore::open(dir.path()).expect("replay surviving chain");
        assert_eq!(replayed.count_blobs(), 1);
        assert_eq!(
            replayed.verify_chain().expect("verify surviving chain"),
            (true, 1)
        );
    }

    #[test]
    fn read_only_verify_does_not_create_missing_paths_or_lock_files() {
        let dir = TestDir::new("read-only-verify");
        let missing = dir.path().join("missing-meta");
        assert!(MetaStore::verify_existing(&missing).is_err());
        assert!(!missing.exists());

        let existing = dir.path().join("existing-meta");
        std::fs::create_dir(&existing).unwrap();
        assert!(MetaStore::verify_existing(&existing).is_err());
        assert_eq!(std::fs::read_dir(&existing).unwrap().count(), 0);
    }
}
