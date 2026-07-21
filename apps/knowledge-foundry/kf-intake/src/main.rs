//! `kf` — fail-closed local Knowledge Foundry intake CLI.
//!   kf ingest <file> --authority-domain <uuid> --project <uuid> --database-grant <uuid>
//!       --database-session-user <role> --source-system <s> --source-id <id>
//!       --root <existing-dir> --authority <envelope.json>
//!       --authority-registry <operator-owned-trust.json>
//!   kf verify --root <dir>  # read-only append-chain verification
#[cfg(test)]
#[allow(dead_code)]
mod authority;
#[cfg(test)]
#[allow(dead_code)]
mod cas;
mod identity;
#[cfg(test)]
#[allow(dead_code)]
mod jcs;
mod meta;

#[cfg(not(test))]
use kf_intake::{authority, cas};

use anyhow::{bail, Context, Result};
use authority::{AuthorityRequest, ConsumedIngestAuthority};
use cas::{inspect_source, Cas, SourceDigest};
use identity::{ArtifactOccurrence, ArtifactVersion, RawBlob};
use meta::MetaStore;
use serde::Serialize;
use std::path::{Path, PathBuf};

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
    authority_domain_id: String,
    project_id: String,
    database_grant_id: String,
    database_session_user: String,
    source_system_id: String,
    source_native_id: String,
    root: PathBuf,
    authority: PathBuf,
    authority_registry: PathBuf,
}

#[derive(Debug, Clone, Copy)]
struct IngestParameters<'a> {
    store_dir: &'a Path,
    file: &'a Path,
    authority_domain_id: &'a str,
    project_id: &'a str,
    database_grant_id: &'a str,
    database_session_user: &'a str,
    source_system_id: &'a str,
    source_native_id: &'a str,
    envelope_path: &'a Path,
    trust_registry: &'a Path,
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
fn ingest_authorized(parameters: &IngestParameters<'_>) -> Result<IngestResult> {
    // Refuse an ordinary developer build before source inspection or any scoped side effect.
    authority::compiled_trust_registry_digest()?;
    validate_ingest_identity(
        parameters.authority_domain_id,
        parameters.project_id,
        parameters.database_grant_id,
        parameters.database_session_user,
        parameters.source_system_id,
        parameters.source_native_id,
    )?;
    let source = inspect_source(parameters.file)?;
    let request = authority_request(
        parameters.authority_domain_id,
        parameters.project_id,
        parameters.database_grant_id,
        parameters.database_session_user,
        parameters.source_system_id,
        parameters.source_native_id,
        &source,
    );
    let consumed_authority = authority::authorize_and_consume(
        parameters.store_dir,
        parameters.trust_registry,
        parameters.envelope_path,
        &request,
    )?;
    ingest_after_authority(parameters.file, consumed_authority)
}

#[cfg(test)]
fn ingest_authorized_with_registry_digest(
    parameters: &IngestParameters<'_>,
    expected_registry_sha256: &str,
) -> Result<IngestResult> {
    validate_ingest_identity(
        parameters.authority_domain_id,
        parameters.project_id,
        parameters.database_grant_id,
        parameters.database_session_user,
        parameters.source_system_id,
        parameters.source_native_id,
    )?;
    let source = inspect_source(parameters.file)?;
    let request = authority_request(
        parameters.authority_domain_id,
        parameters.project_id,
        parameters.database_grant_id,
        parameters.database_session_user,
        parameters.source_system_id,
        parameters.source_native_id,
        &source,
    );
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .context("system clock is before Unix epoch")?;
    let now =
        i64::try_from(now.as_secs()).context("system clock exceeds signed timestamp range")?;
    let consumed_authority = authority::authorize_and_consume_at_for_test(
        parameters.store_dir,
        parameters.trust_registry,
        expected_registry_sha256,
        parameters.envelope_path,
        &request,
        now,
    )?;
    ingest_after_authority(parameters.file, consumed_authority)
}

fn validate_ingest_identity(
    authority_domain_id: &str,
    project_id: &str,
    database_grant_id: &str,
    database_session_user: &str,
    source_system_id: &str,
    source_native_id: &str,
) -> Result<()> {
    validate_canonical_uuid("authority_domain_id", authority_domain_id)?;
    validate_canonical_uuid("project_id", project_id)?;
    validate_canonical_uuid("database_grant_id", database_grant_id)?;
    validate_id("database_session_user", database_session_user, 63)?;
    validate_id("source_system_id", source_system_id, 128)?;
    validate_id("source_native_id", source_native_id, 4_096)?;
    Ok(())
}

fn validate_canonical_uuid(label: &str, value: &str) -> Result<()> {
    let parsed = uuid::Uuid::parse_str(value).with_context(|| format!("{label} must be a UUID"))?;
    if parsed.is_nil() || parsed.to_string() != value {
        bail!("{label} must be a canonical non-nil lowercase UUID");
    }
    Ok(())
}

fn authority_request(
    authority_domain_id: &str,
    project_id: &str,
    database_grant_id: &str,
    database_session_user: &str,
    source_system_id: &str,
    source_native_id: &str,
    source: &SourceDigest,
) -> AuthorityRequest {
    AuthorityRequest::new(
        authority_domain_id.to_string(),
        project_id.to_string(),
        database_grant_id.to_string(),
        database_session_user.to_string(),
        source.sha256.clone(),
        source.byte_size,
        source_system_id.to_string(),
        source_native_id.to_string(),
    )
}

fn ingest_after_authority(file: &Path, authority: ConsumedIngestAuthority) -> Result<IngestResult> {
    let stored_authority = authority::publish_authorized_source(authority, file)?;
    stored_authority.revalidate_cas()?;
    let authority = stored_authority.authority();
    let blob_info = stored_authority.blob();
    let cas = Cas::open_scoped(authority.canonical_root())?;
    let mut meta = MetaStore::open_scoped(authority.canonical_root())?;
    let project_id = authority.project_id().to_string();
    let source_system_id = authority.source_system_id();
    let source_native_id = authority.source_native_id();

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
    if let Some(existing) = meta.find_occurrence(&project_id, source_system_id, source_native_id) {
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
            project_id,
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
        sha256: blob_info.sha256.clone(),
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
    let mut authority_domain_id = None;
    let mut project_id = None;
    let mut database_grant_id = None;
    let mut database_session_user = None;
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
            "--authority-domain" => &mut authority_domain_id,
            "--project" => &mut project_id,
            "--database-grant" => &mut database_grant_id,
            "--database-session-user" => &mut database_session_user,
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
        authority_domain_id: authority_domain_id.context("ingest requires --authority-domain")?,
        project_id: project_id.context("ingest requires --project")?,
        database_grant_id: database_grant_id.context("ingest requires --database-grant")?,
        database_session_user: database_session_user
            .context("ingest requires --database-session-user")?,
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
            let result = ingest_authorized(&IngestParameters {
                store_dir: &cli.root,
                file: &cli.file,
                authority_domain_id: &cli.authority_domain_id,
                project_id: &cli.project_id,
                database_grant_id: &cli.database_grant_id,
                database_session_user: &cli.database_session_user,
                source_system_id: &cli.source_system_id,
                source_native_id: &cli.source_native_id,
                envelope_path: &cli.authority,
                trust_registry: &cli.authority_registry,
            })?;
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
                "usage: kf ingest <file> --authority-domain <uuid> --project <uuid> \
                 --database-grant <uuid> \
                 --database-session-user <role> --source-system <s> --source-id <id> \
                 --root <existing-dir> --authority <envelope.json> \
                 --authority-registry <operator-trust.json> | kf verify --root <dir>"
            );
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::authority::{AuthorityClaims, SignedAuthorityEnvelope};
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use sha2::{Digest, Sha256};
    use std::time::{SystemTime, UNIX_EPOCH};

    const AUTHORITY_DOMAIN_ID: &str = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    const PROJECT_ID: &str = "11111111-1111-4111-8111-111111111111";
    const DATABASE_GRANT_ID: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const DATABASE_SESSION_USER: &str = "kf_runtime_test";

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
        project_id: &str,
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
                "version": "maworld.kf.ed25519-key-registry.v3",
                "keys": [{
                    "issuer": "test-operator",
                    "key_id": key_id,
                    "public_key_hex": hex::encode(public_key),
                    "allowed_actors": ["test-actor"],
                    "allowed_authority_domain_ids": [AUTHORITY_DOMAIN_ID],
                    "allowed_projects": [project_id],
                    "allowed_database_session_users": [DATABASE_SESSION_USER],
                    "allowed_store_roots": [std::fs::canonicalize(store).unwrap().to_str().unwrap()],
                    "max_ttl_seconds": 120
                }]
            }))
            .unwrap(),
        )
        .unwrap();
        let source_digest = inspect_source(source).unwrap();
        let now = i64::try_from(
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_secs(),
        )
        .unwrap();
        let claims = AuthorityClaims {
            version: "maworld.kf.ingest-authority.v3".to_string(),
            issuer: "test-operator".to_string(),
            key_id,
            actor: "test-actor".to_string(),
            authority_domain_id: AUTHORITY_DOMAIN_ID.to_string(),
            project_id: project_id.to_string(),
            database_grant_id: DATABASE_GRANT_ID.to_string(),
            database_session_user: DATABASE_SESSION_USER.to_string(),
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
            issued_at_unix: now - 10,
            expires_at_unix: now + 60,
            audience: "maworld.kf-intake".to_string(),
            action: "ingest".to_string(),
        };
        let message = authority::signing_message(&claims).unwrap();
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

    fn ingest_with_authority(
        store: &Path,
        source: &Path,
        project_id: &str,
        source_system_id: &str,
        source_native_id: &str,
        authority_files: (&Path, &Path, &str),
    ) -> Result<IngestResult> {
        ingest_authorized_with_registry_digest(
            &IngestParameters {
                store_dir: store,
                file: source,
                authority_domain_id: AUTHORITY_DOMAIN_ID,
                project_id,
                database_grant_id: DATABASE_GRANT_ID,
                database_session_user: DATABASE_SESSION_USER,
                source_system_id,
                source_native_id,
                envelope_path: authority_files.0,
                trust_registry: authority_files.1,
            },
            authority_files.2,
        )
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
            PROJECT_ID,
            "folder",
            "doc-1",
            "nonce-0000000000000101",
        );
        let first = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
        )
        .unwrap();
        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            "nonce-0000000000000102",
        );
        let retry = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
        )
        .unwrap();
        assert!(retry.idempotent_hit);
        assert_eq!(retry.occurrence_id, first.occurrence_id);
        assert_eq!(retry.version_id, first.version_id);

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            PROJECT_ID,
            "drive",
            "doc-1",
            "nonce-0000000000000103",
        );
        let other_system = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "drive",
            "doc-1",
            (&authority, &registry, &registry_sha256),
        )
        .unwrap();
        assert_ne!(other_system.occurrence_id, first.occurrence_id);

        std::fs::write(&source, b"version two").unwrap();
        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            "nonce-0000000000000104",
        );
        let updated = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
        )
        .unwrap();
        assert!(!updated.idempotent_hit);
        assert_eq!(updated.occurrence_id, first.occurrence_id);
        assert_ne!(updated.version_id, first.version_id);

        let (authority, registry, registry_sha256) = write_authority(
            &temp,
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            "nonce-0000000000000105",
        );
        let updated_retry = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            (&authority, &registry, &registry_sha256),
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

        assert!(ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-1",
            (&missing, &missing, &"0".repeat(64))
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
            PROJECT_ID.to_string(),
            "--database-grant".to_string(),
            DATABASE_GRANT_ID.to_string(),
            "--database-session-user".to_string(),
            DATABASE_SESSION_USER.to_string(),
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
        assert!(parse_ingest_args(&with_envelope).is_err());

        with_envelope.extend([
            "--authority-domain".to_string(),
            AUTHORITY_DOMAIN_ID.to_string(),
        ]);
        assert_eq!(
            parse_ingest_args(&with_envelope)
                .unwrap()
                .authority_domain_id,
            AUTHORITY_DOMAIN_ID
        );
    }

    #[test]
    fn ordinary_unpinned_build_is_incapable_of_ingest() {
        let temp = TestDir::new();
        let missing_store = temp.0.join("missing-store");
        let missing_source = temp.0.join("missing-source");
        let missing_authority = temp.0.join("missing-authority");
        let missing_registry = temp.0.join("missing-registry");
        let error = ingest_authorized(&IngestParameters {
            store_dir: &missing_store,
            file: &missing_source,
            authority_domain_id: AUTHORITY_DOMAIN_ID,
            project_id: PROJECT_ID,
            database_grant_id: DATABASE_GRANT_ID,
            database_session_user: DATABASE_SESSION_USER,
            source_system_id: "folder",
            source_native_id: "doc-1",
            envelope_path: &missing_authority,
            trust_registry: &missing_registry,
        })
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
            project_id: PROJECT_ID.to_string(),
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
            PROJECT_ID,
            "folder",
            "doc-crash",
            "nonce-0000000000000201",
        );
        let repaired = ingest_with_authority(
            &store,
            &source,
            PROJECT_ID,
            "folder",
            "doc-crash",
            (&authority, &registry, &registry_sha256),
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
