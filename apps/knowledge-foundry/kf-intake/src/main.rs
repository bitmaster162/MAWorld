//! `kf` — fail-closed local Knowledge Foundry intake CLI.
//!   kf ingest <file> --project <p> --source-system <s> --source-id <id>
//!       --root <existing-dir> --authority <envelope.json>
//!       --authority-registry <operator-owned-trust.json>
//!   kf verify --root <dir>  # read-only append-chain verification
mod authority;
mod cas;
mod identity;
mod jcs;
mod meta;

use anyhow::{bail, Context, Result};
use authority::AuthorityRequest;
use cas::{inspect_source, Cas, SourceDigest};
use identity::{ArtifactOccurrence, ArtifactVersion, RawBlob};
use meta::MetaStore;
use serde::Serialize;
use std::path::{Path, PathBuf};

const COMPILED_TRUST_REGISTRY_SHA256: Option<&str> =
    option_env!("MAWORLD_KF_TRUST_REGISTRY_SHA256");

#[derive(Debug, Serialize)]
pub struct IngestResult {
    pub blob_id: String,
    pub occurrence_id: String,
    pub version_id: String,
    pub sha256: String,
    pub byte_size: u64,
    pub raw_recovery_verified: bool,
    pub deduplicated_bytes: bool,
    pub idempotent_hit: bool,
    pub state: String,
}

#[derive(Debug)]
struct IngestCli {
    file: PathBuf,
    project: String,
    source_system_id: String,
    source_native_id: String,
    root: PathBuf,
    authority: PathBuf,
    authority_registry: PathBuf,
}

fn validate_id(label: &str, value: &str, max_bytes: usize) -> Result<()> {
    if value.trim().is_empty()
        || value.trim() != value
        || value.len() > max_bytes
        || value.chars().any(char::is_control)
    {
        bail!("{label} is empty, oversized, padded, or contains control characters");
    }
    Ok(())
}

fn media_type(path: &Path) -> String {
    match path.extension().and_then(|extension| extension.to_str()) {
        Some("md") => "text/markdown",
        Some("txt") => "text/plain",
        Some("json") => "application/json",
        Some("pdf") => "application/pdf",
        Some("rs") => "text/x-rust",
        _ => "application/octet-stream",
    }
    .to_string()
}

/// The only intake entry point: inspect exact bytes, verify and durably consume a
/// signed one-time authority, then perform CAS/meta side effects.
pub fn ingest_authorized(
    store_dir: &Path,
    file: &Path,
    project: &str,
    source_system_id: &str,
    source_native_id: &str,
    envelope_path: &Path,
    trust_registry: &Path,
) -> Result<IngestResult> {
    let expected_registry_sha256 = compiled_trust_registry_digest()?;
    validate_ingest_identity(project, source_system_id, source_native_id)?;
    let source = inspect_source(file)?;
    let request = authority_request(project, source_system_id, source_native_id, &source);
    let canonical_root = authority::authorize_and_consume(
        store_dir,
        trust_registry,
        expected_registry_sha256,
        envelope_path,
        &request,
    )?;
    ingest_after_authority(
        &canonical_root,
        file,
        project,
        source_system_id,
        source_native_id,
        &source,
    )
}

#[cfg(test)]
fn ingest_authorized_at(
    store_dir: &Path,
    file: &Path,
    project: &str,
    source_system_id: &str,
    source_native_id: &str,
    authority_files: (&Path, &Path, &str),
    now: i64,
) -> Result<IngestResult> {
    validate_ingest_identity(project, source_system_id, source_native_id)?;
    let source = inspect_source(file)?;
    let request = authority_request(project, source_system_id, source_native_id, &source);
    let canonical_root = authority::authorize_and_consume_at_for_test(
        store_dir,
        authority_files.1,
        authority_files.2,
        authority_files.0,
        &request,
        now,
    )?;
    ingest_after_authority(
        &canonical_root,
        file,
        project,
        source_system_id,
        source_native_id,
        &source,
    )
}

fn compiled_trust_registry_digest() -> Result<&'static str> {
    let digest = COMPILED_TRUST_REGISTRY_SHA256.context(
        "kf-intake binary was compiled without MAWORLD_KF_TRUST_REGISTRY_SHA256; ingest is disabled",
    )?;
    authority::validate_registry_digest(digest)?;
    Ok(digest)
}

fn validate_ingest_identity(
    project: &str,
    source_system_id: &str,
    source_native_id: &str,
) -> Result<()> {
    validate_id("project", project, 256)?;
    validate_id("source_system_id", source_system_id, 256)?;
    validate_id("source_native_id", source_native_id, 4_096)?;
    Ok(())
}

fn authority_request(
    project: &str,
    source_system_id: &str,
    source_native_id: &str,
    source: &SourceDigest,
) -> AuthorityRequest {
    AuthorityRequest {
        project: project.to_string(),
        content_sha256: source.sha256.clone(),
        content_size: source.byte_size,
        source_system_id: source_system_id.to_string(),
        source_native_id: source_native_id.to_string(),
    }
}

fn ingest_after_authority(
    store_dir: &Path,
    file: &Path,
    project: &str,
    source_system_id: &str,
    source_native_id: &str,
    authorized_source: &SourceDigest,
) -> Result<IngestResult> {
    let cas = Cas::open_scoped(store_dir)?;
    let mut meta = MetaStore::open_scoped(store_dir)?;

    // Re-open and stream the source only after nonce consumption. CAS refuses to
    // publish unless these bytes still match the digest in the signed authority.
    let blob_info = cas.put_file_expected(file, &authorized_source.sha256)?;
    if blob_info.byte_size != authorized_source.byte_size {
        bail!("source size changed after authority consumption");
    }

    let blob_id = match meta.blob_by_hash(&blob_info.sha256) {
        Some(blob) => blob.blob_id.clone(),
        None => {
            let blob = RawBlob {
                blob_id: format!("blob-{}", uuid::Uuid::now_v7()),
                sha256: blob_info.sha256.clone(),
                byte_size: blob_info.byte_size,
                storage_uri: blob_info.storage_uri.clone(),
                media_type_detected: media_type(file),
            };
            meta.upsert_blob(&blob)?;
            blob.blob_id
        }
    };

    let idempotent_hit;
    let occurrence_id;
    let version_id;
    if let Some(existing) = meta.find_occurrence(project, source_system_id, source_native_id) {
        if let Some(existing_version) =
            meta.version_for_occurrence_blob(&existing.occurrence_id, &blob_id)
        {
            idempotent_hit = true;
            occurrence_id = existing.occurrence_id.clone();
            version_id = existing_version.version_id.clone();
        } else {
            // This also repairs a crash after occurrence append but before version append.
            idempotent_hit = false;
            occurrence_id = existing.occurrence_id.clone();
            let parent_version_id = meta
                .latest_version_for_occurrence(&occurrence_id)
                .map(|version| version.version_id.clone());
            let version = ArtifactVersion {
                version_id: format!("ver-{}", uuid::Uuid::now_v7()),
                occurrence_id: occurrence_id.clone(),
                blob_id: blob_id.clone(),
                source_revision_key: blob_info.sha256.clone(),
                parent_version_id,
            };
            version_id = version.version_id.clone();
            meta.add_version(&version)?;
        }
    } else {
        idempotent_hit = false;
        let occurrence = ArtifactOccurrence {
            occurrence_id: format!("occ-{}", uuid::Uuid::now_v7()),
            project_id: project.to_string(),
            source_system_id: source_system_id.to_string(),
            source_native_id: source_native_id.to_string(),
            observed_path: file.to_string_lossy().into_owned(),
            blob_id: blob_id.clone(),
        };
        occurrence_id = occurrence.occurrence_id.clone();
        meta.add_occurrence(&occurrence)?;
        let version = ArtifactVersion {
            version_id: format!("ver-{}", uuid::Uuid::now_v7()),
            occurrence_id: occurrence_id.clone(),
            blob_id: blob_id.clone(),
            source_revision_key: blob_info.sha256.clone(),
            parent_version_id: None,
        };
        version_id = version.version_id.clone();
        meta.add_version(&version)?;
    }

    let recovered = cas.get_verified(&blob_info.sha256)?;
    let raw_recovery_verified = recovered.len() as u64 == blob_info.byte_size;

    Ok(IngestResult {
        blob_id,
        occurrence_id,
        version_id,
        sha256: blob_info.sha256,
        byte_size: blob_info.byte_size,
        raw_recovery_verified,
        deduplicated_bytes: blob_info.deduplicated,
        idempotent_hit,
        state: "RAW".to_string(),
    })
}

fn parse_ingest_args(args: &[String]) -> Result<IngestCli> {
    let file = args
        .first()
        .filter(|value| !value.starts_with("--"))
        .map(PathBuf::from)
        .context("ingest requires an explicit source file")?;
    let mut project = None;
    let mut source_system_id = None;
    let mut source_native_id = None;
    let mut root = None;
    let mut authority = None;
    let mut authority_registry = None;

    let mut index = 1;
    while index < args.len() {
        let flag = &args[index];
        let value = args
            .get(index + 1)
            .with_context(|| format!("missing value for {flag}"))?;
        if value.starts_with("--") {
            bail!("missing value for {flag}");
        }
        let target = match flag.as_str() {
            "--project" => &mut project,
            "--source-system" => &mut source_system_id,
            "--source-id" => &mut source_native_id,
            "--root" => &mut root,
            "--authority" => &mut authority,
            "--authority-registry" => &mut authority_registry,
            _ => bail!("unknown ingest argument: {flag}"),
        };
        if target.replace(value.clone()).is_some() {
            bail!("duplicate ingest argument: {flag}");
        }
        index += 2;
    }

    Ok(IngestCli {
        file,
        project: project.context("ingest requires --project")?,
        source_system_id: source_system_id.context("ingest requires --source-system")?,
        source_native_id: source_native_id.context("ingest requires --source-id")?,
        root: root.map(PathBuf::from).context("ingest requires --root")?,
        authority: authority
            .map(PathBuf::from)
            .context("ingest requires --authority")?,
        authority_registry: authority_registry
            .map(PathBuf::from)
            .context("ingest requires --authority-registry")?,
    })
}

fn parse_verify_root(args: &[String]) -> Result<PathBuf> {
    if args.len() != 2 || args[0] != "--root" {
        bail!("verify requires exactly --root <existing-store>");
    }
    Ok(PathBuf::from(&args[1]))
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("ingest") => {
            let cli = parse_ingest_args(&args[1..])?;
            let result = ingest_authorized(
                &cli.root,
                &cli.file,
                &cli.project,
                &cli.source_system_id,
                &cli.source_native_id,
                &cli.authority,
                &cli.authority_registry,
            )?;
            println!("{}", serde_json::to_string_pretty(&result)?);
            Ok(())
        }
        Some("verify") => {
            let root = parse_verify_root(&args[1..])?;
            let (ok, event_count) = MetaStore::verify_existing(root.join("meta"))?;
            println!("audit chain ok={ok} events={event_count}");
            Ok(())
        }
        _ => {
            eprintln!(
                "usage: kf ingest <file> --project <p> --source-system <s> --source-id <id> \
                 --root <existing-dir> --authority <envelope.json> \
                 --authority-registry <operator-trust.json> | kf verify --root <dir>"
            );
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::authority::{AuthorityClaims, SignedAuthorityEnvelope};
    use ed25519_dalek::{Signer, SigningKey};
    use sha2::{Digest, Sha256};

    const NOW: i64 = 1_900_000_000;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let path =
                std::env::temp_dir().join(format!("kf-ingest-test-{}", uuid::Uuid::now_v7()));
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).ok();
        }
    }

    fn write_authority(
        temp: &TestDir,
        store: &Path,
        source: &Path,
        project: &str,
        source_system: &str,
        source_id: &str,
        nonce: &str,
    ) -> (PathBuf, PathBuf, String) {
        let signing_key = SigningKey::from_bytes(&[11_u8; 32]);
        let public_key = signing_key.verifying_key().to_bytes();
        let key_id = format!("ed25519:{}", hex::encode(Sha256::digest(public_key)));
        let trust_dir = temp.0.join("operator-trust");
        std::fs::create_dir_all(&trust_dir).unwrap();
        let registry = trust_dir.join(format!("registry-{nonce}.json"));
        std::fs::write(
            &registry,
            serde_json::to_vec(&serde_json::json!({
                "version": "maworld.kf.ed25519-key-registry.v1",
                "keys": [{
                    "issuer": "test-operator",
                    "key_id": key_id,
                    "public_key_hex": hex::encode(public_key),
                    "allowed_actors": ["test-actor"],
                    "allowed_projects": [project],
                    "allowed_store_roots": [std::fs::canonicalize(store).unwrap().to_str().unwrap()],
                    "max_ttl_seconds": 120
                }]
            }))
            .unwrap(),
        )
        .unwrap();
        let source_digest = inspect_source(source).unwrap();
        let claims = AuthorityClaims {
            version: "maworld.kf.ingest-authority.v1".to_string(),
            issuer: "test-operator".to_string(),
            key_id,
            actor: "test-actor".to_string(),
            project: project.to_string(),
            store_root: std::fs::canonicalize(store)
                .unwrap()
                .to_str()
                .unwrap()
                .to_string(),
            content_sha256: source_digest.sha256,
            content_size: source_digest.byte_size,
            source_system_id: source_system.to_string(),
            source_native_id: source_id.to_string(),
            nonce: nonce.to_string(),
            issued_at_unix: NOW - 10,
            expires_at_unix: NOW + 60,
            audience: "maworld.kf-intake".to_string(),
            action: "ingest".to_string(),
        };
        let mut message = b"MAWORLD\0KF-INTAKE\0AUTHORITY\0V1\0".to_vec();
        message.extend_from_slice(&jcs::canonical_bytes(&claims).unwrap());
        let envelope = SignedAuthorityEnvelope {
            algorithm: "Ed25519".to_string(),
            claims,
            signature_hex: hex::encode(signing_key.sign(&message).to_bytes()),
        };
        let envelope_path = temp.0.join(format!("authority-{nonce}.json"));
        std::fs::write(&envelope_path, serde_json::to_vec(&envelope).unwrap()).unwrap();
        let registry_sha256 = hex::encode(Sha256::digest(std::fs::read(&registry).unwrap()));
        (envelope_path, registry, registry_sha256)
    }

    #[test]
    fn authorized_retry_reuses_real_version_and_source_system_is_part_of_key() {
        let temp = TestDir::new();
        let source = temp.0.join("document.txt");
        let store = temp.0.join("store");
        std::fs::create_dir(&store).unwrap();
        std::fs::write(&source, b"version one").unwrap();

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            "nonce-0000000000000101",
        );
        let first = ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            "nonce-0000000000000102",
        );
        let retry = ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        assert!(retry.idempotent_hit);
        assert_eq!(retry.occurrence_id, first.occurrence_id);
        assert_eq!(retry.version_id, first.version_id);

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "drive",
            "doc-1",
            "nonce-0000000000000103",
        );
        let other_system = ingest_authorized_at(
            &store,
            &source,
            "project",
            "drive",
            "doc-1",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        assert_ne!(other_system.occurrence_id, first.occurrence_id);

        std::fs::write(&source, b"version two").unwrap();
        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            "nonce-0000000000000104",
        );
        let updated = ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        assert!(!updated.idempotent_hit);
        assert_eq!(updated.occurrence_id, first.occurrence_id);
        assert_ne!(updated.version_id, first.version_id);

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            "nonce-0000000000000105",
        );
        let updated_retry = ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        assert!(updated_retry.idempotent_hit);
        assert_eq!(updated_retry.version_id, updated.version_id);

        let meta = MetaStore::open(store.join("meta")).unwrap();
        let latest = meta
            .latest_version_for_occurrence(&first.occurrence_id)
            .unwrap();
        assert_eq!(latest.version_id, updated.version_id);
        assert_eq!(
            latest.parent_version_id.as_deref(),
            Some(first.version_id.as_str())
        );
    }

    #[test]
    fn invalid_or_missing_authority_creates_no_cas_or_meta() {
        let temp = TestDir::new();
        let source = temp.0.join("document.txt");
        let store = temp.0.join("store");
        std::fs::create_dir(&store).unwrap();
        std::fs::write(&source, b"safe bytes").unwrap();
        let missing = temp.0.join("missing.json");

        assert!(ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-1",
            (&missing, &missing, &"0".repeat(64)),
            NOW
        )
        .is_err());
        assert!(!store.join("cas").exists());
        assert!(!store.join("meta").exists());
        assert!(!store.join(".authority").exists());
    }

    #[test]
    fn cli_ingest_requires_every_authority_argument() {
        let base = vec![
            "file.txt".to_string(),
            "--project".to_string(),
            "project".to_string(),
            "--source-system".to_string(),
            "folder".to_string(),
            "--source-id".to_string(),
            "doc-1".to_string(),
            "--root".to_string(),
            "store".to_string(),
        ];
        assert!(parse_ingest_args(&base).is_err());

        let mut with_envelope = base.clone();
        with_envelope.extend(["--authority".to_string(), "authority.json".to_string()]);
        assert!(parse_ingest_args(&with_envelope).is_err());

        with_envelope.extend(["--authority-registry".to_string(), "trust.json".to_string()]);
        assert!(parse_ingest_args(&with_envelope).is_ok());
    }

    #[test]
    fn ordinary_unpinned_build_is_incapable_of_ingest() {
        let temp = TestDir::new();
        let missing_store = temp.0.join("missing-store");
        assert!(
            COMPILED_TRUST_REGISTRY_SHA256.is_none(),
            "the ordinary verification build must not inject a production trust pin"
        );
        let error = ingest_authorized(
            &missing_store,
            &temp.0.join("missing-source"),
            "project",
            "folder",
            "doc-1",
            &temp.0.join("missing-authority"),
            &temp.0.join("missing-registry"),
        )
        .unwrap_err()
        .to_string();
        assert!(error.contains("compiled without MAWORLD_KF_TRUST_REGISTRY_SHA256"));
        assert!(!missing_store.exists());
    }

    #[test]
    fn valid_mandate_repairs_occurrence_missing_version_after_crash() {
        let temp = TestDir::new();
        let source = temp.0.join("document.txt");
        let store = temp.0.join("store");
        std::fs::create_dir(&store).unwrap();
        std::fs::write(&source, b"crash recovery bytes").unwrap();

        let digest = inspect_source(&source).unwrap();
        let cas = Cas::open_scoped(&store).unwrap();
        let blob_info = cas.put_file_expected(&source, &digest.sha256).unwrap();
        let mut meta = MetaStore::open_scoped(&store).unwrap();
        let blob = RawBlob {
            blob_id: "blob-crash-recovery".to_string(),
            sha256: blob_info.sha256.clone(),
            byte_size: blob_info.byte_size,
            storage_uri: blob_info.storage_uri,
            media_type_detected: "text/plain".to_string(),
        };
        meta.upsert_blob(&blob).unwrap();
        meta.add_occurrence(&ArtifactOccurrence {
            occurrence_id: "occ-crash-recovery".to_string(),
            project_id: "project".to_string(),
            source_system_id: "folder".to_string(),
            source_native_id: "doc-crash".to_string(),
            observed_path: source.to_string_lossy().into_owned(),
            blob_id: blob.blob_id,
        })
        .unwrap();
        drop(meta);

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            "project",
            "folder",
            "doc-crash",
            "nonce-0000000000000201",
        );
        let repaired = ingest_authorized_at(
            &store,
            &source,
            "project",
            "folder",
            "doc-crash",
            (&authority, &registry, &registry_sha256),
            NOW,
        )
        .unwrap();
        assert!(!repaired.idempotent_hit);
        assert_eq!(repaired.occurrence_id, "occ-crash-recovery");
        assert_eq!(
            MetaStore::open_scoped(&store)
                .unwrap()
                .version_for_occurrence_blob(&repaired.occurrence_id, &repaired.blob_id)
                .unwrap()
                .version_id,
            repaired.version_id
        );
    }

    #[cfg(unix)]
    #[test]
    fn scoped_store_children_and_dangling_ledger_cannot_escape_signed_root() {
        use std::os::unix::fs::symlink;

        let temp = TestDir::new();
        let store = temp.0.join("store");
        let outside = temp.0.join("outside");
        std::fs::create_dir(&store).unwrap();
        std::fs::create_dir(&outside).unwrap();

        symlink(&outside, store.join("cas")).unwrap();
        assert!(Cas::open_scoped(&store).is_err());
        std::fs::remove_file(store.join("cas")).unwrap();

        symlink(&outside, store.join("meta")).unwrap();
        assert!(MetaStore::open_scoped(&store).is_err());
        std::fs::remove_file(store.join("meta")).unwrap();

        let meta = store.join("meta");
        std::fs::create_dir(&meta).unwrap();
        symlink(outside.join("missing-ledger"), meta.join("events.jsonl")).unwrap();
        assert!(MetaStore::open_scoped(&store).is_err());
        assert!(!outside.join("missing-ledger").exists());

        let initialized_store = temp.0.join("initialized-store");
        std::fs::create_dir(&initialized_store).unwrap();
        drop(MetaStore::open_scoped(&initialized_store).unwrap());
        std::fs::remove_file(initialized_store.join("meta/events.jsonl")).unwrap();
        assert!(MetaStore::open_scoped(&initialized_store).is_err());

        let initialized_store = temp.0.join("deleted-meta-store");
        std::fs::create_dir(&initialized_store).unwrap();
        drop(MetaStore::open_scoped(&initialized_store).unwrap());
        std::fs::remove_dir_all(initialized_store.join("meta")).unwrap();
        assert!(MetaStore::open_scoped(&initialized_store).is_err());
    }
}
