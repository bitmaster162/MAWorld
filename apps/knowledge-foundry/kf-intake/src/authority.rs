//! Fail-closed local authority gate for intake.
//!
//! A mandate signs RFC 8785/JCS claims behind a versioned domain separator. The
//! trusted Ed25519 key comes only from an existing operator registry outside the
//! writable intake root. A nonce is durably consumed under an exclusive sidecar
//! lock before CAS or metadata state is created.
use crate::cas::{BlobInfo, Cas};
use crate::jcs;
use anyhow::{bail, Context, Result};
use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs::{File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

const CLAIMS_VERSION: &str = "maworld.kf.ingest-authority.v3";
const SIGNATURE_ALGORITHM: &str = "Ed25519";
const SIGNATURE_DOMAIN: &[u8] = b"MAWORLD\0KF-INTAKE\0AUTHORITY\0V3\0";
const REGISTRY_VERSION: &str = "maworld.kf.ed25519-key-registry.v3";
const AUDIENCE: &str = "maworld.kf-intake";
const ACTION: &str = "ingest";
const REPLAY_VERSION: &str = "maworld.kf.authority-consume.v1";
const REPLAY_HASH_DOMAIN: &[u8] = b"MAWORLD\0KF-INTAKE\0AUTHORITY-REPLAY\0V1\0";
const REPLAY_GENESIS: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const REPLAY_MARKER_NAME: &str = ".authority-replay.initialized";
const REPLAY_MARKER_BYTES: &[u8] = b"maworld.kf.authority-replay.initialized.v1\n";
const MAX_ENVELOPE_BYTES: u64 = 32 * 1024;
const MAX_REGISTRY_BYTES: u64 = 64 * 1024;
const MAX_REPLAY_BYTES: u64 = 64 * 1024 * 1024;
const MAX_REPLAY_EVENT_BYTES: usize = 16 * 1024;
const MAX_TRUSTED_KEYS: usize = 64;
const MAX_POLICY_VALUES: usize = 64;
const MAX_TTL_SECONDS: i64 = 5 * 60;
const MAX_CONTENT_BYTES: u64 = 256 * 1024 * 1024;
const COMPILED_TRUST_REGISTRY_SHA256: Option<&str> =
    option_env!("MAWORLD_KF_TRUST_REGISTRY_SHA256");

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorityClaims {
    pub version: String,
    pub issuer: String,
    pub key_id: String,
    pub actor: String,
    pub authority_domain_id: String,
    pub project_id: String,
    pub database_grant_id: String,
    pub database_session_user: String,
    pub store_root: String,
    pub content_sha256: String,
    pub content_size: u64,
    pub source_system_id: String,
    pub source_native_id: String,
    pub nonce: String,
    pub issued_at_unix: i64,
    pub expires_at_unix: i64,
    pub audience: String,
    pub action: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignedAuthorityEnvelope {
    pub algorithm: String,
    pub claims: AuthorityClaims,
    pub signature_hex: String,
}

#[derive(Debug, Clone)]
pub struct AuthorityRequest {
    authority_domain_id: String,
    project_id: String,
    database_grant_id: String,
    database_session_user: String,
    content_sha256: String,
    content_size: u64,
    source_system_id: String,
    source_native_id: String,
}

impl AuthorityRequest {
    // Keeping every signed binding explicit at the trust-boundary call site is safer than hiding
    // security-relevant values in a loosely populated builder.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        authority_domain_id: String,
        project_id: String,
        database_grant_id: String,
        database_session_user: String,
        content_sha256: String,
        content_size: u64,
        source_system_id: String,
        source_native_id: String,
    ) -> Self {
        Self {
            authority_domain_id,
            project_id,
            database_grant_id,
            database_session_user,
            content_sha256,
            content_size,
            source_system_id,
            source_native_id,
        }
    }

    pub fn authority_domain_id(&self) -> &str {
        &self.authority_domain_id
    }
}

/// Unforgeable in-process proof that a signed, policy-allowed ingest authority was verified and
/// its replay key was durably consumed. Fields are deliberately private and the type is neither
/// cloneable nor deserializable; downstream code must derive scope from its getters.
#[derive(Debug)]
pub struct ConsumedIngestAuthority {
    canonical_root: PathBuf,
    authority_domain_id: Uuid,
    project_id: Uuid,
    database_grant_id: Uuid,
    database_session_user: String,
    issuer: String,
    key_id: String,
    actor: String,
    content_sha256: String,
    content_size: u64,
    source_system_id: String,
    source_native_id: String,
    nonce: String,
    issued_at_unix: i64,
    expires_at_unix: i64,
    claims_sha256: String,
    registry_sha256: String,
}

impl ConsumedIngestAuthority {
    pub fn canonical_root(&self) -> &Path {
        &self.canonical_root
    }

    pub fn authority_domain_id(&self) -> Uuid {
        self.authority_domain_id
    }

    pub fn project_id(&self) -> Uuid {
        self.project_id
    }

    pub fn database_grant_id(&self) -> Uuid {
        self.database_grant_id
    }

    pub fn database_session_user(&self) -> &str {
        &self.database_session_user
    }

    pub fn issuer(&self) -> &str {
        &self.issuer
    }

    pub fn key_id(&self) -> &str {
        &self.key_id
    }

    pub fn actor(&self) -> &str {
        &self.actor
    }

    pub fn content_sha256(&self) -> &str {
        &self.content_sha256
    }

    pub fn content_size(&self) -> u64 {
        self.content_size
    }

    pub fn source_system_id(&self) -> &str {
        &self.source_system_id
    }

    pub fn source_native_id(&self) -> &str {
        &self.source_native_id
    }

    pub fn nonce(&self) -> &str {
        &self.nonce
    }

    pub fn issued_at_unix(&self) -> i64 {
        self.issued_at_unix
    }

    pub fn expires_at_unix(&self) -> i64 {
        self.expires_at_unix
    }

    pub fn claims_sha256(&self) -> &str {
        &self.claims_sha256
    }

    pub fn registry_sha256(&self) -> &str {
        &self.registry_sha256
    }
}

/// Proof that the exact authorized bytes were durably published to the scoped CAS. PostgreSQL
/// registration accepts this type, never a merely verified mandate, preventing claims-only blob
/// registration and supporting immediate pre-registration revalidation.
#[derive(Debug)]
pub struct StoredIngestAuthority {
    authority: ConsumedIngestAuthority,
    blob: BlobInfo,
}

/// Owned, one-shot CAS verification work item. Its private owned fields make it `Send + 'static`
/// without exposing a way for callers to replace the signed root, hash, size or logical URI.
#[derive(Debug)]
pub struct StoredCasRevalidation {
    canonical_root: PathBuf,
    content_sha256: String,
    content_size: u64,
    storage_uri: String,
}

impl StoredIngestAuthority {
    pub fn authority(&self) -> &ConsumedIngestAuthority {
        &self.authority
    }

    pub fn blob(&self) -> &BlobInfo {
        &self.blob
    }

    /// Build an owned work item suitable for `spawn_blocking` immediately before registration.
    pub fn revalidation(&self) -> Result<StoredCasRevalidation> {
        let authority = self.authority();
        let expected_uri = format!("cas://sha256/{}", authority.content_sha256());
        if self.blob.sha256 != authority.content_sha256()
            || self.blob.byte_size != authority.content_size()
            || self.blob.storage_uri != expected_uri
        {
            bail!("stored authority metadata no longer matches its signed content binding");
        }

        Ok(StoredCasRevalidation {
            canonical_root: authority.canonical_root().to_path_buf(),
            content_sha256: authority.content_sha256().to_string(),
            content_size: authority.content_size(),
            storage_uri: self.blob.storage_uri.clone(),
        })
    }

    /// Synchronous convenience for non-async callers and focused verification tests.
    pub fn revalidate_cas(&self) -> Result<()> {
        self.revalidation()?.verify()
    }
}

impl StoredCasRevalidation {
    /// Re-open the signed CAS scope and stream the stored bytes through SHA-256. Consuming the
    /// snapshot discourages accidental reuse after another asynchronous boundary.
    pub fn verify(self) -> Result<()> {
        let expected_uri = format!("cas://sha256/{}", self.content_sha256);
        if self.storage_uri != expected_uri {
            bail!("stored CAS logical URI is not canonical");
        }

        let cas = Cas::open_scoped(&self.canonical_root)?;
        let digest = cas.verify_stored(&self.content_sha256)?;
        if digest.sha256 != self.content_sha256 || digest.byte_size != self.content_size {
            bail!("stored CAS bytes no longer match the consumed authority");
        }
        Ok(())
    }
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TrustedKeyRegistry {
    version: String,
    keys: Vec<TrustedKey>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TrustedKey {
    issuer: String,
    key_id: String,
    public_key_hex: String,
    allowed_actors: Vec<String>,
    allowed_authority_domain_ids: Vec<String>,
    allowed_projects: Vec<String>,
    allowed_database_session_users: Vec<String>,
    allowed_store_roots: Vec<String>,
    max_ttl_seconds: i64,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ReplayEvent {
    seq: u64,
    version: String,
    issuer: String,
    key_id: String,
    nonce: String,
    claims_sha256: String,
    consumed_at_unix: i64,
    prev_hash: String,
    hash: String,
}

#[derive(Serialize)]
struct ReplayEventBody<'a> {
    seq: u64,
    version: &'a str,
    issuer: &'a str,
    key_id: &'a str,
    nonce: &'a str,
    claims_sha256: &'a str,
    consumed_at_unix: i64,
    prev_hash: &'a str,
}

struct ReplayState {
    seq: u64,
    last_hash: String,
    consumed: HashSet<(String, String, String)>,
    byte_size: u64,
}

impl ReplayState {
    fn genesis() -> Self {
        Self {
            seq: 0,
            last_hash: REPLAY_GENESIS.to_string(),
            consumed: HashSet::new(),
            byte_size: 0,
        }
    }
}

/// Verify a mandate against an external registry whose exact bytes match the build-time digest
/// pin, then consume its nonce. The returned capability carries only signed, policy-checked
/// values; callers must not continue using their pre-verification request fields.
pub fn authorize_and_consume(
    store_root: &Path,
    trust_registry: &Path,
    envelope_path: &Path,
    request: &AuthorityRequest,
) -> Result<ConsumedIngestAuthority> {
    let expected_registry_sha256 = compiled_trust_registry_digest()?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock is before Unix epoch")?;
    let now =
        i64::try_from(now.as_secs()).context("system clock exceeds signed timestamp range")?;
    authorize_and_consume_at(
        store_root,
        trust_registry,
        expected_registry_sha256,
        envelope_path,
        request,
        now,
    )
}

/// Publish exact source bytes after mandate consumption and return the only capability accepted
/// by the PostgreSQL registrar. A changed source burns authority but never creates database state.
pub fn publish_authorized_source(
    authority: ConsumedIngestAuthority,
    source: &Path,
) -> Result<StoredIngestAuthority> {
    let cas = Cas::open_scoped(authority.canonical_root())?;
    let blob = cas.put_file_expected(source, authority.content_sha256())?;
    if blob.byte_size != authority.content_size() {
        bail!("source size changed after authority consumption");
    }
    if blob.storage_uri != format!("cas://sha256/{}", authority.content_sha256()) {
        bail!("CAS returned a non-canonical storage URI");
    }
    Ok(StoredIngestAuthority { authority, blob })
}

pub fn compiled_trust_registry_digest() -> Result<&'static str> {
    let digest = COMPILED_TRUST_REGISTRY_SHA256.context(
        "kf-intake was compiled without MAWORLD_KF_TRUST_REGISTRY_SHA256; authority is disabled",
    )?;
    validate_registry_digest(digest)?;
    Ok(digest)
}

#[cfg(test)]
pub(crate) fn authorize_and_consume_at_for_test(
    store_root: &Path,
    trust_registry: &Path,
    expected_registry_sha256: &str,
    envelope_path: &Path,
    request: &AuthorityRequest,
    now: i64,
) -> Result<ConsumedIngestAuthority> {
    authorize_and_consume_at(
        store_root,
        trust_registry,
        expected_registry_sha256,
        envelope_path,
        request,
        now,
    )
}

fn authorize_and_consume_at(
    store_root: &Path,
    trust_registry: &Path,
    expected_registry_sha256: &str,
    envelope_path: &Path,
    request: &AuthorityRequest,
    now: i64,
) -> Result<ConsumedIngestAuthority> {
    if now < 0 {
        bail!("authority verification time must be non-negative");
    }
    let canonical_root = canonical_store_root(store_root)?;
    let canonical_root_text = path_text(&canonical_root, "canonical store root")?;

    validate_registry_digest(expected_registry_sha256)?;
    let registry_path = canonical_external_registry(trust_registry, &canonical_root)?;
    let registry_bytes =
        read_bounded_regular(&registry_path, MAX_REGISTRY_BYTES, "trust registry")?;
    if sha256_hex(&registry_bytes) != expected_registry_sha256 {
        bail!("trust registry SHA-256 does not match the build-time pin");
    }
    let registry: TrustedKeyRegistry =
        serde_json::from_slice(&registry_bytes).context("invalid trust registry JSON")?;
    validate_registry(&registry)?;

    let envelope_bytes =
        read_bounded_regular(envelope_path, MAX_ENVELOPE_BYTES, "authority envelope")?;
    let envelope: SignedAuthorityEnvelope =
        serde_json::from_slice(&envelope_bytes).context("invalid authority envelope JSON")?;
    validate_claims(&envelope, request, &canonical_root_text, now)?;

    let trusted_key = registry
        .keys
        .iter()
        .find(|key| key.key_id == envelope.claims.key_id)
        .context("authority key_id is not present in the trusted registry")?;
    if trusted_key.issuer != envelope.claims.issuer {
        bail!("authority issuer does not own the selected trusted key");
    }
    enforce_key_policy(trusted_key, &envelope.claims, &canonical_root_text)?;

    let public_key_bytes =
        decode_lower_hex_array::<32>(&trusted_key.public_key_hex, "trusted Ed25519 public key")?;
    let verifying_key = VerifyingKey::from_bytes(&public_key_bytes)
        .context("trusted Ed25519 public key is invalid")?;
    if verifying_key.is_weak() {
        bail!("weak Ed25519 public keys are forbidden");
    }
    let signature_bytes =
        decode_lower_hex_array::<64>(&envelope.signature_hex, "Ed25519 signature")?;
    let signature = Signature::from_bytes(&signature_bytes);
    let message = signing_message(&envelope.claims)?;
    verifying_key
        .verify_strict(&message, &signature)
        .context("authority signature verification failed")?;

    let claims_sha256 = sha256_hex(&message);
    let authority_domain_id = canonical_uuid(
        &envelope.claims.authority_domain_id,
        "authority authority_domain_id",
    )?;
    let project_id = canonical_uuid(&envelope.claims.project_id, "authority project_id")?;
    let database_grant_id = canonical_uuid(
        &envelope.claims.database_grant_id,
        "authority database_grant_id",
    )?;
    consume_nonce(&canonical_root, &envelope.claims, &claims_sha256, now)?;
    let claims = envelope.claims;
    Ok(ConsumedIngestAuthority {
        canonical_root,
        authority_domain_id,
        project_id,
        database_grant_id,
        database_session_user: claims.database_session_user,
        issuer: claims.issuer,
        key_id: claims.key_id,
        actor: claims.actor,
        content_sha256: claims.content_sha256,
        content_size: claims.content_size,
        source_system_id: claims.source_system_id,
        source_native_id: claims.source_native_id,
        nonce: claims.nonce,
        issued_at_unix: claims.issued_at_unix,
        expires_at_unix: claims.expires_at_unix,
        claims_sha256,
        registry_sha256: expected_registry_sha256.to_owned(),
    })
}

pub fn validate_registry_digest(value: &str) -> Result<()> {
    validate_hash(value, "build-time trust registry SHA-256")
}

fn canonical_store_root(path: &Path) -> Result<PathBuf> {
    let metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect pre-provisioned store root {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        bail!("store root must be an existing, non-symlink directory");
    }
    let canonical = std::fs::canonicalize(path)
        .with_context(|| format!("canonicalize store root {}", path.display()))?;
    if !std::fs::metadata(&canonical)?.is_dir() {
        bail!("canonical store root is not a directory");
    }
    path_text(&canonical, "canonical store root")?;
    Ok(canonical)
}

fn canonical_external_registry(path: &Path, canonical_root: &Path) -> Result<PathBuf> {
    let metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect trust registry {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        bail!("trust registry must be an existing, regular, non-symlink file");
    }
    let canonical = std::fs::canonicalize(path)
        .with_context(|| format!("canonicalize trust registry {}", path.display()))?;
    if canonical.starts_with(canonical_root) {
        bail!("trust registry must be outside the writable intake store root");
    }
    Ok(canonical)
}

fn validate_registry(registry: &TrustedKeyRegistry) -> Result<()> {
    if registry.version != REGISTRY_VERSION {
        bail!("unsupported trust registry version");
    }
    if registry.keys.is_empty() || registry.keys.len() > MAX_TRUSTED_KEYS {
        bail!("trust registry key count is outside the accepted range");
    }
    let mut key_ids = HashSet::new();
    for key in &registry.keys {
        validate_token("trusted issuer", &key.issuer, 128, 1)?;
        validate_token("trusted key_id", &key.key_id, 96, 1)?;
        let public_key =
            decode_lower_hex_array::<32>(&key.public_key_hex, "trusted Ed25519 public key")?;
        let verifying_key = VerifyingKey::from_bytes(&public_key)
            .context("trust registry contains an invalid Ed25519 public key")?;
        if verifying_key.is_weak() {
            bail!("trust registry contains a weak Ed25519 public key");
        }
        let derived_key_id = key_id_for_public_key(&public_key);
        if key.key_id != derived_key_id {
            bail!("trusted key_id does not match its public key digest");
        }
        if !key_ids.insert(key.key_id.clone()) {
            bail!("duplicate key_id in trust registry");
        }
        validate_policy_values("allowed_actors", &key.allowed_actors, 256, false)?;
        validate_policy_values(
            "allowed_authority_domain_ids",
            &key.allowed_authority_domain_ids,
            36,
            false,
        )?;
        for authority_domain_id in &key.allowed_authority_domain_ids {
            canonical_uuid(authority_domain_id, "allowed_authority_domain_ids entry")?;
        }
        validate_policy_values("allowed_projects", &key.allowed_projects, 256, false)?;
        for project_id in &key.allowed_projects {
            canonical_uuid(project_id, "allowed_projects entry")?;
        }
        validate_policy_values(
            "allowed_database_session_users",
            &key.allowed_database_session_users,
            63,
            false,
        )?;
        for session_user in &key.allowed_database_session_users {
            validate_token("allowed database session user", session_user, 63, 1)?;
        }
        validate_policy_values("allowed_store_roots", &key.allowed_store_roots, 4_096, true)?;
        if key.max_ttl_seconds <= 0 || key.max_ttl_seconds > MAX_TTL_SECONDS {
            bail!("trusted key max_ttl_seconds is outside the accepted range");
        }
    }
    Ok(())
}

fn validate_policy_values(
    label: &str,
    values: &[String],
    max_bytes: usize,
    require_absolute_path: bool,
) -> Result<()> {
    if values.is_empty() || values.len() > MAX_POLICY_VALUES {
        bail!("{label} count is outside the accepted range");
    }
    let mut unique = HashSet::new();
    for value in values {
        validate_text(label, value, max_bytes, 1)?;
        if require_absolute_path {
            let policy_path = Path::new(value);
            if !policy_path.is_absolute() {
                bail!("{label} entries must be absolute canonical path strings");
            }
            let metadata = std::fs::symlink_metadata(policy_path)
                .with_context(|| format!("inspect {label} entry {value}"))?;
            if metadata.file_type().is_symlink() || !metadata.is_dir() {
                bail!("{label} entries must be existing non-symlink directories");
            }
            let canonical = std::fs::canonicalize(policy_path)
                .with_context(|| format!("canonicalize {label} entry {value}"))?;
            if path_text(&canonical, label)? != *value {
                bail!("{label} entries must use their exact canonical path strings");
            }
        }
        if !unique.insert(value) {
            bail!("{label} contains a duplicate value");
        }
    }
    Ok(())
}

fn enforce_key_policy(
    key: &TrustedKey,
    claims: &AuthorityClaims,
    canonical_root: &str,
) -> Result<()> {
    if !key.allowed_actors.contains(&claims.actor) {
        bail!("authority actor is outside the trusted key policy");
    }
    if !key
        .allowed_authority_domain_ids
        .contains(&claims.authority_domain_id)
    {
        bail!("authority domain is outside the trusted key policy");
    }
    if !key.allowed_projects.contains(&claims.project_id) {
        bail!("authority project is outside the trusted key policy");
    }
    if !key
        .allowed_database_session_users
        .contains(&claims.database_session_user)
    {
        bail!("authority database session user is outside the trusted key policy");
    }
    if !key
        .allowed_store_roots
        .iter()
        .any(|allowed| allowed == canonical_root)
    {
        bail!("authority store root is outside the trusted key policy");
    }
    let ttl = claims
        .expires_at_unix
        .checked_sub(claims.issued_at_unix)
        .context("authority key-policy TTL overflow")?;
    if ttl > key.max_ttl_seconds {
        bail!("authority TTL exceeds the trusted key policy");
    }
    Ok(())
}

fn validate_claims(
    envelope: &SignedAuthorityEnvelope,
    request: &AuthorityRequest,
    canonical_root: &str,
    now: i64,
) -> Result<()> {
    let claims = &envelope.claims;
    if envelope.algorithm != SIGNATURE_ALGORITHM {
        bail!("unsupported authority signature algorithm");
    }
    if claims.version != CLAIMS_VERSION {
        bail!("unsupported authority claims version");
    }
    validate_token("issuer", &claims.issuer, 128, 1)?;
    validate_token("key_id", &claims.key_id, 96, 1)?;
    validate_text("actor", &claims.actor, 256, 1)?;
    canonical_uuid(&claims.authority_domain_id, "authority authority_domain_id")?;
    canonical_uuid(&claims.project_id, "authority project_id")?;
    canonical_uuid(&claims.database_grant_id, "authority database_grant_id")?;
    validate_token(
        "database_session_user",
        &claims.database_session_user,
        63,
        1,
    )?;
    validate_text("store_root", &claims.store_root, 4_096, 1)?;
    validate_hash(&claims.content_sha256, "authority content_sha256")?;
    if claims.content_size > MAX_CONTENT_BYTES {
        bail!("authority content_size exceeds the intake limit");
    }
    validate_text("source_system_id", &claims.source_system_id, 128, 1)?;
    validate_text("source_native_id", &claims.source_native_id, 4_096, 1)?;
    validate_token("nonce", &claims.nonce, 128, 16)?;
    if claims.audience != AUDIENCE {
        bail!("authority audience mismatch");
    }
    if claims.action != ACTION {
        bail!("authority action mismatch");
    }
    if claims.issued_at_unix < 0 || claims.expires_at_unix < 0 {
        bail!("authority timestamps must be non-negative");
    }
    if claims.issued_at_unix > now {
        bail!("authority is issued in the future");
    }
    if claims.expires_at_unix <= claims.issued_at_unix {
        bail!("authority expiry must be after issuance");
    }
    let ttl = claims
        .expires_at_unix
        .checked_sub(claims.issued_at_unix)
        .context("authority TTL overflow")?;
    if ttl > MAX_TTL_SECONDS {
        bail!("authority TTL exceeds {MAX_TTL_SECONDS} seconds");
    }
    if now >= claims.expires_at_unix {
        bail!("authority has expired");
    }

    if claims.authority_domain_id != request.authority_domain_id {
        bail!("authority domain binding mismatch");
    }
    if claims.project_id != request.project_id {
        bail!("authority project binding mismatch");
    }
    if claims.database_grant_id != request.database_grant_id {
        bail!("authority database grant binding mismatch");
    }
    if claims.database_session_user != request.database_session_user {
        bail!("authority database session binding mismatch");
    }
    if claims.store_root != canonical_root {
        bail!("authority store_root binding mismatch");
    }
    if claims.content_sha256 != request.content_sha256
        || claims.content_size != request.content_size
    {
        bail!("authority content binding mismatch");
    }
    if claims.source_system_id != request.source_system_id
        || claims.source_native_id != request.source_native_id
    {
        bail!("authority source identity binding mismatch");
    }
    Ok(())
}

/// Canonical domain-separated bytes that an authority issuer signs.
pub fn signing_message(claims: &AuthorityClaims) -> Result<Vec<u8>> {
    let canonical = jcs::canonical_bytes(claims)?;
    let mut message = Vec::with_capacity(SIGNATURE_DOMAIN.len() + canonical.len());
    message.extend_from_slice(SIGNATURE_DOMAIN);
    message.extend_from_slice(&canonical);
    Ok(message)
}

fn key_id_for_public_key(public_key: &[u8; 32]) -> String {
    format!("ed25519:{}", sha256_hex(public_key))
}

fn consume_nonce(
    canonical_root: &Path,
    claims: &AuthorityClaims,
    claims_sha256: &str,
    now: i64,
) -> Result<()> {
    require_durable_scoped_filesystem()?;
    let replay_dir = canonical_root.join(".authority");
    ensure_replay_dir(canonical_root, &replay_dir)?;
    let ledger_path = replay_dir.join("consumed.jsonl");
    let lock_path = replay_dir.join("consumed.lock");
    validate_optional_regular(&lock_path, "authority replay lock")?;
    let lock_file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)
        .with_context(|| format!("open authority replay lock {}", lock_path.display()))?;
    if !lock_file.metadata()?.is_file() {
        bail!("opened authority replay lock is not a regular file");
    }
    lock_file
        .lock()
        .with_context(|| format!("acquire authority replay lock {}", lock_path.display()))?;

    let operation_result = (|| -> Result<()> {
        let replay = load_replay(&ledger_path)?;
        let replay_key = (
            claims.issuer.clone(),
            claims.key_id.clone(),
            claims.nonce.clone(),
        );
        if replay.consumed.contains(&replay_key) {
            bail!("authority nonce has already been consumed");
        }
        let seq = replay
            .seq
            .checked_add(1)
            .context("replay sequence overflow")?;
        let mut event = ReplayEvent {
            seq,
            version: REPLAY_VERSION.to_string(),
            issuer: claims.issuer.clone(),
            key_id: claims.key_id.clone(),
            nonce: claims.nonce.clone(),
            claims_sha256: claims_sha256.to_string(),
            consumed_at_unix: now,
            prev_hash: replay.last_hash,
            hash: String::new(),
        };
        event.hash = replay_event_hash(&event)?;
        let mut encoded = jcs::canonical_bytes(&event)?;
        encoded.push(b'\n');
        if encoded.len() > MAX_REPLAY_EVENT_BYTES {
            bail!("authority replay event exceeds its size limit");
        }
        let encoded_len = u64::try_from(encoded.len()).context("replay event size overflow")?;
        if replay
            .byte_size
            .checked_add(encoded_len)
            .context("replay ledger size overflow")?
            > MAX_REPLAY_BYTES
        {
            bail!("authority replay ledger exceeds its size limit");
        }

        validate_optional_regular(&ledger_path, "authority replay ledger")?;
        let mut ledger = OpenOptions::new()
            .create(true)
            .append(true)
            .read(true)
            .open(&ledger_path)
            .with_context(|| format!("open authority replay ledger {}", ledger_path.display()))?;
        let opened = ledger.metadata()?;
        if !opened.is_file() || opened.len() != replay.byte_size {
            bail!("authority replay ledger changed before append");
        }
        ledger.write_all(&encoded)?;
        ledger.sync_data()?;
        sync_directory(&replay_dir)?;
        Ok(())
    })();

    let unlock_result = lock_file
        .unlock()
        .with_context(|| format!("release authority replay lock {}", lock_path.display()));
    match (operation_result, unlock_result) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(error), Ok(())) => Err(error),
        (Ok(()), Err(error)) => Err(error),
        (Err(error), Err(unlock_error)) => Err(error.context(format!(
            "authority operation failed and lock release also failed: {unlock_error:#}"
        ))),
    }
}

fn ensure_replay_dir(canonical_root: &Path, replay_dir: &Path) -> Result<()> {
    let marker_path = canonical_root.join(REPLAY_MARKER_NAME);
    let marker_exists = match std::fs::symlink_metadata(&marker_path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("authority replay marker must be a regular, non-symlink file")
        }
        Ok(_) => true,
        Err(error) if error.kind() == ErrorKind::NotFound => false,
        Err(error) => return Err(error.into()),
    };
    let replay_exists = match std::fs::symlink_metadata(replay_dir) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            bail!("authority replay path must be a non-symlink directory")
        }
        Ok(_) => true,
        Err(error) if error.kind() == ErrorKind::NotFound => false,
        Err(error) => return Err(error.into()),
    };

    match (marker_exists, replay_exists) {
        (false, false) => initialize_replay_storage(canonical_root, replay_dir, &marker_path)?,
        (true, true) => {}
        _ => bail!("authority replay initialization is incomplete or was deleted"),
    }

    let marker = read_bounded_regular(&marker_path, 128, "authority replay marker")?;
    if marker != REPLAY_MARKER_BYTES {
        bail!("authority replay marker is invalid");
    }
    let metadata = std::fs::symlink_metadata(replay_dir)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        bail!("authority replay path must be a non-symlink directory");
    }
    let canonical_replay = std::fs::canonicalize(replay_dir)?;
    if !canonical_replay.starts_with(canonical_root) {
        bail!("authority replay path escapes the store root");
    }
    validate_optional_regular(
        &replay_dir.join("consumed.jsonl"),
        "authority replay ledger",
    )?;
    Ok(())
}

fn initialize_replay_storage(
    canonical_root: &Path,
    replay_dir: &Path,
    marker_path: &Path,
) -> Result<()> {
    let mut marker = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(marker_path)
        .context("create authority replay initialization marker")?;
    marker.write_all(REPLAY_MARKER_BYTES)?;
    marker.sync_all()?;
    sync_directory(canonical_root)?;

    std::fs::create_dir(replay_dir).context("create authority replay directory")?;
    sync_directory(canonical_root)?;

    let ledger_path = replay_dir.join("consumed.jsonl");
    let ledger = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&ledger_path)
        .context("create authority replay ledger")?;
    ledger.sync_all()?;
    sync_directory(replay_dir)?;
    Ok(())
}

fn load_replay(path: &Path) -> Result<ReplayState> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("authority replay ledger must be a regular, non-symlink file")
        }
        Ok(_) => {}
        Err(error) if error.kind() == ErrorKind::NotFound => {
            bail!("authority replay ledger is missing after initialization")
        }
        Err(error) => return Err(error.into()),
    }
    let bytes = read_bounded_regular(path, MAX_REPLAY_BYTES, "authority replay ledger")?;
    if bytes.is_empty() {
        return Ok(ReplayState::genesis());
    }
    if !bytes.ends_with(b"\n") {
        bail!("authority replay ledger has a partial terminal line");
    }

    let mut state = ReplayState::genesis();
    state.byte_size = u64::try_from(bytes.len()).context("replay ledger size overflow")?;
    for (line_index, line) in bytes[..bytes.len() - 1]
        .split(|byte| *byte == b'\n')
        .enumerate()
    {
        if line.is_empty() || line.len() > MAX_REPLAY_EVENT_BYTES {
            bail!(
                "invalid authority replay event size at line {}",
                line_index + 1
            );
        }
        let event: ReplayEvent = serde_json::from_slice(line).with_context(|| {
            format!("invalid authority replay event at line {}", line_index + 1)
        })?;
        if jcs::canonical_bytes(&event)?.as_slice() != line {
            bail!(
                "authority replay event is not canonical at line {}",
                line_index + 1
            );
        }
        let expected_seq = state
            .seq
            .checked_add(1)
            .context("replay sequence overflow")?;
        if event.seq != expected_seq || event.version != REPLAY_VERSION {
            bail!(
                "invalid authority replay sequence or version at line {}",
                line_index + 1
            );
        }
        validate_token("replay issuer", &event.issuer, 128, 1)?;
        validate_token("replay key_id", &event.key_id, 96, 1)?;
        validate_token("replay nonce", &event.nonce, 128, 16)?;
        validate_hash(&event.claims_sha256, "replay claims_sha256")?;
        validate_hash(&event.prev_hash, "replay prev_hash")?;
        validate_hash(&event.hash, "replay hash")?;
        if event.consumed_at_unix < 0 || event.prev_hash != state.last_hash {
            bail!(
                "invalid authority replay timestamp or chain at line {}",
                line_index + 1
            );
        }
        if event.hash != replay_event_hash(&event)? {
            bail!("authority replay hash mismatch at line {}", line_index + 1);
        }
        let replay_key = (
            event.issuer.clone(),
            event.key_id.clone(),
            event.nonce.clone(),
        );
        if !state.consumed.insert(replay_key) {
            bail!("duplicate authority replay key at line {}", line_index + 1);
        }
        state.seq = event.seq;
        state.last_hash = event.hash;
    }
    Ok(state)
}

fn replay_event_hash(event: &ReplayEvent) -> Result<String> {
    let body = ReplayEventBody {
        seq: event.seq,
        version: &event.version,
        issuer: &event.issuer,
        key_id: &event.key_id,
        nonce: &event.nonce,
        claims_sha256: &event.claims_sha256,
        consumed_at_unix: event.consumed_at_unix,
        prev_hash: &event.prev_hash,
    };
    let canonical = jcs::canonical_bytes(&body)?;
    let mut hasher = Sha256::new();
    hasher.update(REPLAY_HASH_DOMAIN);
    hasher.update(canonical);
    Ok(hex::encode(hasher.finalize()))
}

fn read_bounded_regular(path: &Path, max_bytes: u64, label: &str) -> Result<Vec<u8>> {
    let link_metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect {label} {}", path.display()))?;
    if link_metadata.file_type().is_symlink() || !link_metadata.is_file() {
        bail!("{label} must be a regular, non-symlink file");
    }
    if link_metadata.len() > max_bytes {
        bail!("{label} exceeds {max_bytes} byte limit");
    }
    let mut file = File::open(path).with_context(|| format!("open {label} {}", path.display()))?;
    let opened = file.metadata()?;
    if !opened.is_file() || opened.len() > max_bytes {
        bail!("opened {label} is not admissible");
    }
    let capacity = usize::try_from(opened.len()).context("bounded file does not fit in memory")?;
    let mut bytes = Vec::with_capacity(capacity);
    Read::by_ref(&mut file)
        .take(max_bytes + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != opened.len() || bytes.len() as u64 > max_bytes {
        bail!("{label} changed or exceeded its limit while being read");
    }
    Ok(bytes)
}

fn validate_optional_regular(path: &Path, label: &str) -> Result<()> {
    match std::fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("{label} must be a regular, non-symlink file")
        }
        Ok(_) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error.into()),
    }
}

fn path_text(path: &Path, label: &str) -> Result<String> {
    let value = path
        .to_str()
        .with_context(|| format!("{label} is not valid UTF-8"))?;
    validate_text(label, value, 4_096, 1)?;
    Ok(value.to_string())
}

fn validate_text(label: &str, value: &str, max_bytes: usize, min_bytes: usize) -> Result<()> {
    if value.len() < min_bytes
        || value.len() > max_bytes
        || value.trim() != value
        || value.chars().any(char::is_control)
    {
        bail!("{label} is empty, oversized, padded, or contains control characters");
    }
    Ok(())
}

fn validate_token(label: &str, value: &str, max_bytes: usize, min_bytes: usize) -> Result<()> {
    validate_text(label, value, max_bytes, min_bytes)?;
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        bail!("{label} contains characters outside the token allowlist");
    }
    Ok(())
}

fn validate_hash(value: &str, label: &str) -> Result<()> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        bail!("{label} must be a lowercase SHA-256 digest");
    }
    Ok(())
}

fn canonical_uuid(value: &str, label: &str) -> Result<Uuid> {
    let parsed = Uuid::parse_str(value).with_context(|| format!("{label} must be a UUID"))?;
    if parsed.is_nil() || parsed.to_string() != value {
        bail!("{label} must be a canonical non-nil lowercase UUID");
    }
    Ok(parsed)
}

fn decode_lower_hex_array<const N: usize>(value: &str, label: &str) -> Result<[u8; N]> {
    if value.len() != N * 2
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        bail!("{label} must be exactly {} lowercase hexadecimal bytes", N);
    }
    let mut bytes = [0_u8; N];
    hex::decode_to_slice(value, &mut bytes).with_context(|| format!("decode {label}"))?;
    Ok(bytes)
}

fn sha256_hex(bytes: impl AsRef<[u8]>) -> String {
    hex::encode(Sha256::digest(bytes.as_ref()))
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
    bail!("durable authority replay is disabled on Windows")
}

#[cfg(not(any(unix, windows)))]
fn sync_directory(_path: &Path) -> Result<()> {
    bail!("durable authority replay requires directory fsync support")
}

#[cfg(windows)]
fn require_durable_scoped_filesystem() -> Result<()> {
    bail!("durable authority replay is disabled on Windows; use the pinned Linux runtime")
}

#[cfg(not(windows))]
fn require_durable_scoped_filesystem() -> Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use std::sync::{Arc, Barrier};

    const NOW: i64 = 1_900_000_000;
    const AUTHORITY_DOMAIN_A: &str = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
    const AUTHORITY_DOMAIN_B: &str = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    const PROJECT_A: &str = "11111111-1111-4111-8111-111111111111";
    const PROJECT_B: &str = "22222222-2222-4222-8222-222222222222";
    const GRANT_A: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const SESSION_USER: &str = "kf_runtime_test";

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path =
                std::env::temp_dir().join(format!("kf-authority-{label}-{}", uuid::Uuid::now_v7()));
            std::fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).ok();
        }
    }

    struct Fixture {
        _temp: TestDir,
        root: PathBuf,
        registry: PathBuf,
        registry_sha256: String,
        envelope: PathBuf,
        source: PathBuf,
        signing_key: SigningKey,
        claims: AuthorityClaims,
        request: AuthorityRequest,
    }

    impl Fixture {
        fn new(label: &str) -> Self {
            let temp = TestDir::new(label);
            let root = temp.0.join("store");
            let operator = temp.0.join("operator-trust");
            std::fs::create_dir(&root).unwrap();
            std::fs::create_dir(&operator).unwrap();
            let source = temp.0.join("source.txt");
            std::fs::write(&source, b"authorized bytes").unwrap();
            let signing_key = SigningKey::from_bytes(&[7_u8; 32]);
            let public_key = signing_key.verifying_key().to_bytes();
            let key_id = key_id_for_public_key(&public_key);
            let registry = operator.join("trusted_keys.json");
            let registry_body = TrustedKeyRegistry {
                version: REGISTRY_VERSION.to_string(),
                keys: vec![TrustedKey {
                    issuer: "maworld-operator".to_string(),
                    key_id: key_id.clone(),
                    public_key_hex: hex::encode(public_key),
                    allowed_actors: vec!["operator-1".to_string()],
                    allowed_authority_domain_ids: vec![AUTHORITY_DOMAIN_A.to_string()],
                    allowed_projects: vec![PROJECT_A.to_string()],
                    allowed_database_session_users: vec![SESSION_USER.to_string()],
                    allowed_store_roots: vec![path_text(
                        &std::fs::canonicalize(&root).unwrap(),
                        "root",
                    )
                    .unwrap()],
                    max_ttl_seconds: 120,
                }],
            };
            std::fs::write(&registry, serde_json::to_vec(&registry_body).unwrap()).unwrap();
            let registry_sha256 = sha256_hex(std::fs::read(&registry).unwrap());
            let content_sha256 = sha256_hex(b"authorized bytes");
            let request = AuthorityRequest::new(
                AUTHORITY_DOMAIN_A.to_string(),
                PROJECT_A.to_string(),
                GRANT_A.to_string(),
                SESSION_USER.to_string(),
                content_sha256.clone(),
                16,
                "local-folder".to_string(),
                "project-a::document.txt".to_string(),
            );
            let claims = AuthorityClaims {
                version: CLAIMS_VERSION.to_string(),
                issuer: "maworld-operator".to_string(),
                key_id,
                actor: "operator-1".to_string(),
                authority_domain_id: request.authority_domain_id.clone(),
                project_id: request.project_id.clone(),
                database_grant_id: request.database_grant_id.clone(),
                database_session_user: request.database_session_user.clone(),
                store_root: path_text(&std::fs::canonicalize(&root).unwrap(), "root").unwrap(),
                content_sha256,
                content_size: request.content_size,
                source_system_id: request.source_system_id.clone(),
                source_native_id: request.source_native_id.clone(),
                nonce: "nonce-0000000000000001".to_string(),
                issued_at_unix: NOW - 10,
                expires_at_unix: NOW + 60,
                audience: AUDIENCE.to_string(),
                action: ACTION.to_string(),
            };
            let envelope = temp.0.join("authority.json");
            let fixture = Self {
                _temp: temp,
                root,
                registry,
                registry_sha256,
                envelope,
                source,
                signing_key,
                claims,
                request,
            };
            fixture.write_signed(&fixture.claims);
            fixture
        }

        fn write_signed(&self, claims: &AuthorityClaims) {
            let signature = self
                .signing_key
                .sign(&signing_message(claims).expect("canonical authority claims"));
            let envelope = SignedAuthorityEnvelope {
                algorithm: SIGNATURE_ALGORITHM.to_string(),
                claims: claims.clone(),
                signature_hex: hex::encode(signature.to_bytes()),
            };
            std::fs::write(&self.envelope, serde_json::to_vec(&envelope).unwrap()).unwrap();
        }

        fn authorize(&self) -> Result<ConsumedIngestAuthority> {
            authorize_and_consume_at_for_test(
                &self.root,
                &self.registry,
                &self.registry_sha256,
                &self.envelope,
                &self.request,
                NOW,
            )
        }
    }

    #[test]
    fn valid_signature_consumes_nonce_before_returning() {
        let fixture = Fixture::new("valid");
        assert_eq!(fixture.request.authority_domain_id(), AUTHORITY_DOMAIN_A);
        let authorized = fixture.authorize().unwrap();
        assert_eq!(
            authorized.canonical_root(),
            std::fs::canonicalize(&fixture.root).unwrap()
        );
        assert_eq!(
            authorized.authority_domain_id().to_string(),
            AUTHORITY_DOMAIN_A
        );
        assert_eq!(authorized.project_id().to_string(), PROJECT_A);
        assert_eq!(authorized.database_grant_id().to_string(), GRANT_A);
        assert_eq!(authorized.database_session_user(), SESSION_USER);
        assert_eq!(authorized.content_sha256(), fixture.claims.content_sha256);
        assert_eq!(authorized.source_system_id(), "local-folder");
        let ledger = fixture.root.join(".authority/consumed.jsonl");
        let body = std::fs::read(&ledger).unwrap();
        assert!(body.ends_with(b"\n"));
        assert_eq!(load_replay(&ledger).unwrap().seq, 1);
    }

    #[test]
    fn stored_revalidation_work_item_is_send_static() {
        fn assert_send_static<T: Send + 'static>() {}
        assert_send_static::<StoredCasRevalidation>();
    }

    #[cfg(unix)]
    #[test]
    fn stored_revalidation_rejects_noncanonical_logical_uri() {
        let fixture = Fixture::new("storage-uri");
        let mut stored =
            publish_authorized_source(fixture.authorize().unwrap(), fixture.source.as_path())
                .unwrap();
        stored.blob.storage_uri = "cas://sha256/not-the-signed-hash".to_string();
        assert!(stored.revalidation().is_err());
    }

    #[cfg(unix)]
    #[test]
    fn stored_authority_revalidation_rejects_missing_symlinked_or_corrupt_blob() {
        use std::os::unix::fs::symlink;

        for (label, replacement) in [
            ("missing", None),
            ("symlink", Some(true)),
            ("corrupt", Some(false)),
        ] {
            let fixture = Fixture::new(label);
            let stored =
                publish_authorized_source(fixture.authorize().unwrap(), fixture.source.as_path())
                    .unwrap();
            stored.revalidate_cas().unwrap();
            let hash = stored.blob().sha256.clone();
            let blob_path = fixture
                .root
                .join("cas")
                .join(&hash[0..2])
                .join(&hash[2..4])
                .join(&hash);
            std::fs::remove_file(&blob_path).unwrap();
            match replacement {
                Some(true) => symlink(&fixture.source, &blob_path).unwrap(),
                Some(false) => std::fs::write(&blob_path, b"corrupt bytes!!").unwrap(),
                None => {}
            }
            assert!(
                stored.revalidate_cas().is_err(),
                "{label} blob was accepted"
            );
        }
    }

    #[test]
    fn mutation_after_signing_is_rejected_without_replay_state() {
        let fixture = Fixture::new("mutation");
        let original_signature = {
            let bytes = std::fs::read(&fixture.envelope).unwrap();
            serde_json::from_slice::<SignedAuthorityEnvelope>(&bytes)
                .unwrap()
                .signature_hex
        };
        let mut mutated = fixture.claims.clone();
        mutated.project_id = PROJECT_B.to_string();
        let envelope = SignedAuthorityEnvelope {
            algorithm: SIGNATURE_ALGORITHM.to_string(),
            claims: mutated,
            signature_hex: original_signature,
        };
        std::fs::write(&fixture.envelope, serde_json::to_vec(&envelope).unwrap()).unwrap();

        assert!(fixture.authorize().is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn project_hash_and_source_bindings_are_exact() {
        let fixture = Fixture::new("request-bindings");
        let mut request = fixture.request.clone();
        request.authority_domain_id = AUTHORITY_DOMAIN_B.to_string();
        let error = authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW,
        )
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("authority domain binding mismatch"));

        let mut request = fixture.request.clone();
        request.project_id = PROJECT_B.to_string();
        let error = authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW,
        )
        .unwrap_err();
        assert!(error
            .to_string()
            .contains("authority project binding mismatch"));

        let mut request = fixture.request.clone();
        request.database_grant_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb".to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .unwrap_err()
        .to_string()
        .contains("authority database grant binding mismatch"));

        let mut request = fixture.request.clone();
        request.database_session_user = "other_runtime".to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .unwrap_err()
        .to_string()
        .contains("authority database session binding mismatch"));

        let mut request = fixture.request.clone();
        request.content_sha256 = "b".repeat(64);
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());

        let mut request = fixture.request.clone();
        request.source_native_id = "other-source".to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());
        assert!(!fixture.root.join(".authority").exists());
        assert_eq!(
            fixture.authorize().unwrap().project_id().to_string(),
            PROJECT_A
        );
        assert_eq!(
            load_replay(&fixture.root.join(".authority/consumed.jsonl"))
                .unwrap()
                .seq,
            1
        );
    }

    #[test]
    fn nil_or_noncanonical_database_scope_fails_before_replay() {
        let fixture = Fixture::new("canonical-database-scope");
        for invalid_domain in [
            "00000000-0000-0000-0000-000000000000",
            "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD",
        ] {
            let mut claims = fixture.claims.clone();
            claims.authority_domain_id = invalid_domain.to_string();
            fixture.write_signed(&claims);
            let mut request = fixture.request.clone();
            request.authority_domain_id = invalid_domain.to_string();
            assert!(authorize_and_consume_at(
                &fixture.root,
                &fixture.registry,
                &fixture.registry_sha256,
                &fixture.envelope,
                &request,
                NOW
            )
            .unwrap_err()
            .to_string()
            .contains("canonical non-nil lowercase UUID"));
            assert!(!fixture.root.join(".authority").exists());
        }

        for invalid_project in [
            "00000000-0000-0000-0000-000000000000",
            "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        ] {
            let mut claims = fixture.claims.clone();
            claims.project_id = invalid_project.to_string();
            fixture.write_signed(&claims);
            let mut request = fixture.request.clone();
            request.project_id = invalid_project.to_string();
            assert!(authorize_and_consume_at(
                &fixture.root,
                &fixture.registry,
                &fixture.registry_sha256,
                &fixture.envelope,
                &request,
                NOW
            )
            .unwrap_err()
            .to_string()
            .contains("canonical non-nil lowercase UUID"));
            assert!(!fixture.root.join(".authority").exists());
        }

        let mut claims = fixture.claims.clone();
        claims.database_grant_id = "00000000-0000-0000-0000-000000000000".to_string();
        fixture.write_signed(&claims);
        let mut request = fixture.request.clone();
        request.database_grant_id = claims.database_grant_id;
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn root_audience_and_action_bindings_are_exact() {
        let fixture = Fixture::new("policy-bindings");
        let other_root = fixture._temp.0.join("other-store");
        std::fs::create_dir(&other_root).unwrap();
        assert!(authorize_and_consume_at(
            &other_root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &fixture.request,
            NOW
        )
        .is_err());

        let mut claims = fixture.claims.clone();
        claims.audience = "other-service".to_string();
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());

        claims = fixture.claims.clone();
        claims.action = "verify".to_string();
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn valid_signatures_outside_key_policy_are_rejected() {
        let fixture = Fixture::new("key-policy");

        let mut claims = fixture.claims.clone();
        claims.actor = "other-actor".to_string();
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());

        claims = fixture.claims.clone();
        claims.authority_domain_id = AUTHORITY_DOMAIN_B.to_string();
        fixture.write_signed(&claims);
        let mut request = fixture.request.clone();
        request.authority_domain_id = AUTHORITY_DOMAIN_B.to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());

        claims = fixture.claims.clone();
        claims.project_id = PROJECT_B.to_string();
        fixture.write_signed(&claims);
        let mut request = fixture.request.clone();
        request.project_id = PROJECT_B.to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());

        claims = fixture.claims.clone();
        claims.database_session_user = "other_runtime".to_string();
        fixture.write_signed(&claims);
        let mut request = fixture.request.clone();
        request.database_session_user = "other_runtime".to_string();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &request,
            NOW
        )
        .is_err());

        let other_root = fixture._temp.0.join("untrusted-root");
        std::fs::create_dir(&other_root).unwrap();
        claims = fixture.claims.clone();
        claims.store_root =
            path_text(&std::fs::canonicalize(&other_root).unwrap(), "root").unwrap();
        fixture.write_signed(&claims);
        assert!(authorize_and_consume_at(
            &other_root,
            &fixture.registry,
            &fixture.registry_sha256,
            &fixture.envelope,
            &fixture.request,
            NOW
        )
        .is_err());

        claims = fixture.claims.clone();
        claims.issued_at_unix = NOW - 120;
        claims.expires_at_unix = NOW + 60;
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn expired_future_and_excessive_ttl_authorities_are_rejected() {
        for (label, issued, expires) in [
            ("expired", NOW - 60, NOW),
            ("future", NOW + 1, NOW + 60),
            ("ttl", NOW - 1, NOW + MAX_TTL_SECONDS + 1),
            ("reversed", NOW, NOW - 1),
        ] {
            let fixture = Fixture::new(label);
            let mut claims = fixture.claims.clone();
            claims.issued_at_unix = issued;
            claims.expires_at_unix = expires;
            fixture.write_signed(&claims);
            assert!(
                fixture.authorize().is_err(),
                "{label} authority was accepted"
            );
            assert!(!fixture.root.join(".authority").exists());
        }
    }

    #[test]
    fn replay_is_rejected_after_gate_restart() {
        let fixture = Fixture::new("restart-replay");
        fixture.authorize().unwrap();
        let error = fixture.authorize().unwrap_err().to_string();
        assert!(error.contains("already been consumed"));
        assert_eq!(
            load_replay(&fixture.root.join(".authority/consumed.jsonl"))
                .unwrap()
                .seq,
            1
        );
    }

    #[test]
    fn replay_key_cannot_be_rebound_to_another_project() {
        let fixture = Fixture::new("cross-project-replay");
        let mut registry: TrustedKeyRegistry =
            serde_json::from_slice(&std::fs::read(&fixture.registry).unwrap()).unwrap();
        registry.keys[0]
            .allowed_projects
            .push(PROJECT_B.to_string());
        std::fs::write(&fixture.registry, serde_json::to_vec(&registry).unwrap()).unwrap();
        let registry_sha256 = sha256_hex(std::fs::read(&fixture.registry).unwrap());

        authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &registry_sha256,
            &fixture.envelope,
            &fixture.request,
            NOW,
        )
        .unwrap();

        let mut claims = fixture.claims.clone();
        claims.project_id = PROJECT_B.to_string();
        claims.database_grant_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb".to_string();
        fixture.write_signed(&claims);
        let mut request = fixture.request.clone();
        request.project_id = claims.project_id;
        request.database_grant_id = claims.database_grant_id;
        let error = authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &registry_sha256,
            &fixture.envelope,
            &request,
            NOW,
        )
        .unwrap_err()
        .to_string();
        assert!(error.contains("already been consumed"));
        assert_eq!(
            load_replay(&fixture.root.join(".authority/consumed.jsonl"))
                .unwrap()
                .seq,
            1
        );
    }

    #[test]
    fn concurrent_replay_has_exactly_one_winner() {
        let fixture = Fixture::new("concurrent-replay");
        let root = Arc::new(fixture.root.clone());
        let registry = Arc::new(fixture.registry.clone());
        let registry_sha256 = Arc::new(fixture.registry_sha256.clone());
        let envelope = Arc::new(fixture.envelope.clone());
        let request = Arc::new(fixture.request.clone());
        let barrier = Arc::new(Barrier::new(3));
        let mut workers = Vec::new();
        for _ in 0..2 {
            let root = Arc::clone(&root);
            let registry = Arc::clone(&registry);
            let registry_sha256 = Arc::clone(&registry_sha256);
            let envelope = Arc::clone(&envelope);
            let request = Arc::clone(&request);
            let barrier = Arc::clone(&barrier);
            workers.push(std::thread::spawn(move || {
                barrier.wait();
                authorize_and_consume_at(
                    root.as_path(),
                    registry.as_path(),
                    registry_sha256.as_str(),
                    envelope.as_path(),
                    request.as_ref(),
                    NOW,
                )
            }));
        }
        barrier.wait();
        let results = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);
        assert_eq!(
            load_replay(&fixture.root.join(".authority/consumed.jsonl"))
                .unwrap()
                .seq,
            1
        );
    }

    #[test]
    fn malformed_replay_fails_closed_on_reopen() {
        let fixture = Fixture::new("malformed-replay");
        fixture.authorize().unwrap();
        let ledger = fixture.root.join(".authority/consumed.jsonl");
        OpenOptions::new()
            .append(true)
            .open(&ledger)
            .unwrap()
            .write_all(b"{\"partial\":true}")
            .unwrap();
        let mut claims = fixture.claims.clone();
        claims.nonce = "nonce-0000000000000002".to_string();
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());
    }

    #[test]
    fn deleted_replay_state_never_reinitializes_as_genesis() {
        let fixture = Fixture::new("deleted-replay-ledger");
        fixture.authorize().unwrap();
        std::fs::remove_file(fixture.root.join(".authority/consumed.jsonl")).unwrap();
        let mut claims = fixture.claims.clone();
        claims.nonce = "nonce-0000000000000002".to_string();
        fixture.write_signed(&claims);
        assert!(fixture
            .authorize()
            .unwrap_err()
            .to_string()
            .contains("replay ledger"));

        let fixture = Fixture::new("deleted-replay-directory");
        fixture.authorize().unwrap();
        std::fs::remove_dir_all(fixture.root.join(".authority")).unwrap();
        let mut claims = fixture.claims.clone();
        claims.nonce = "nonce-0000000000000002".to_string();
        fixture.write_signed(&claims);
        assert!(fixture
            .authorize()
            .unwrap_err()
            .to_string()
            .contains("incomplete or was deleted"));
    }

    #[test]
    fn noncanonical_replay_encoding_fails_closed() {
        let fixture = Fixture::new("noncanonical-replay");
        fixture.authorize().unwrap();
        let ledger = fixture.root.join(".authority/consumed.jsonl");
        let event: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&ledger).unwrap()).unwrap();
        let mut noncanonical = serde_json::to_vec_pretty(&event).unwrap();
        noncanonical.push(b'\n');
        std::fs::write(&ledger, noncanonical).unwrap();

        let mut claims = fixture.claims.clone();
        claims.nonce = "nonce-0000000000000002".to_string();
        fixture.write_signed(&claims);
        assert!(fixture.authorize().is_err());
    }

    #[test]
    fn unknown_envelope_fields_and_duplicate_registry_keys_are_rejected() {
        let fixture = Fixture::new("strict-inputs");
        let mut envelope: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&fixture.envelope).unwrap()).unwrap();
        envelope
            .as_object_mut()
            .unwrap()
            .insert("unexpected".to_string(), serde_json::json!(true));
        std::fs::write(&fixture.envelope, serde_json::to_vec(&envelope).unwrap()).unwrap();
        assert!(fixture.authorize().is_err());

        fixture.write_signed(&fixture.claims);
        let mut registry: TrustedKeyRegistry =
            serde_json::from_slice(&std::fs::read(&fixture.registry).unwrap()).unwrap();
        registry.keys.push(registry.keys[0].clone());
        std::fs::write(&fixture.registry, serde_json::to_vec(&registry).unwrap()).unwrap();
        assert!(fixture.authorize().is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn registry_contents_must_match_the_build_time_digest_pin() {
        let fixture = Fixture::new("registry-pin");
        let registry: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&fixture.registry).unwrap()).unwrap();
        // Same key, policy and valid signed envelope; only the registry byte encoding changes.
        std::fs::write(
            &fixture.registry,
            serde_json::to_vec_pretty(&registry).unwrap(),
        )
        .unwrap();
        assert_ne!(
            sha256_hex(std::fs::read(&fixture.registry).unwrap()),
            fixture.registry_sha256
        );

        let error = fixture.authorize().unwrap_err().to_string();
        assert!(error.contains("build-time pin"));
        assert!(!fixture.root.join(".authority").exists());

        assert!(authorize_and_consume_at(
            &fixture.root,
            &fixture.registry,
            &"A".repeat(64),
            &fixture.envelope,
            &fixture.request,
            NOW
        )
        .is_err());
        assert!(!fixture.root.join(".authority").exists());
    }

    #[test]
    fn trust_registry_inside_writable_store_is_rejected() {
        let fixture = Fixture::new("registry-boundary");
        let inside = fixture.root.join("trusted_keys.json");
        std::fs::copy(&fixture.registry, &inside).unwrap();
        assert!(authorize_and_consume_at(
            &fixture.root,
            &inside,
            &fixture.registry_sha256,
            &fixture.envelope,
            &fixture.request,
            NOW
        )
        .is_err());
        assert!(!fixture.root.join(".authority").exists());
    }
}
