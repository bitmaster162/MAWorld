//! Ignored acceptance against a live, explicitly disposable PostgreSQL 16 cluster.
//!
//! The test rebuilds the database with migrations 001 through 004, creates real NOINHERIT
//! registrar/runtime login roles, verifies an Ed25519 authority-v3 envelope through `kf-intake`,
//! and exercises only the production-shaped registrar and runtime adapters. It never runs in the
//! default inventory.
use kf_intake::authority::{
    authorize_and_consume, compiled_trust_registry_digest, publish_authorized_source,
    signing_message, AuthorityClaims, AuthorityRequest, StoredIngestAuthority,
};
use kf_store_pg::{
    validate_disposable_database_url, IngestOutcome, MetaStore, PostgresAuthorityStore,
    PostgresMetaStore,
};
use sqlx_core::{
    pool::{Pool, PoolOptions},
    query::query,
    raw_sql,
    row::Row,
};
use sqlx_postgres::{PgConnection, Postgres};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Command,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use uuid::Uuid;

const CONFIRMATION: &str = "MAWORLD_DISPOSABLE_DB_CONFIRMED";
const CLUSTER_CONFIRMATION: &str = "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER";
const MIGRATION_001: &str = include_str!("../../schema/001_intake_core_v1_1.sql");
const MIGRATION_002: &str = include_str!("../../schema/002_rls_roles.sql");
const MIGRATION_003: &str = include_str!("../../schema/003_atomic_intake.sql");
const MIGRATION_004: &str = include_str!("../../schema/004_authority_grants.sql");

const CLAIMS_VERSION: &str = "maworld.kf.ingest-authority.v3";
const PRIVATE_KEY_PEM: &str = "-----BEGIN PRIVATE KEY-----\n\
MC4CAQAwBQYDK2VwBCIEIJ1hsZ3v/VpguoRK9JLsLMREScVpezJpGXA7rAMcrn9g\n\
-----END PRIVATE KEY-----\n";
const ISSUER: &str = "maworld.acceptance";
const KEY_ID: &str = "ed25519:21fe31dfa154a261626bf854046fd2271b7bed4b6abe45aa58877ef47f9721b9";
const ACTOR: &str = "acceptance-operator";
const RUNTIME_ROLE: &str = "kf_acceptance_runtime";
const WRONG_RUNTIME_ROLE: &str = "kf_acceptance_wrong_runtime";
const REUSED_RUNTIME_ROLE: &str = "kf_acceptance_reused_runtime";
const REGISTRAR_ROLE: &str = "kf_acceptance_registrar";
const UNSAFE_REGISTRAR_ROLE: &str = "kf_acceptance_unsafe_registrar";
const AUTHORITY_DOMAIN_ID: &str = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const OTHER_AUTHORITY_DOMAIN_ID: &str = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const PROJECT_A: &str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const PROJECT_B: &str = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const FIXTURE_BASE: &str = "/tmp/maworld-kf-pg-authority";
const REGISTRY_BYTES: &[u8] = include_bytes!("authority_registry_v3.json");

const RESET_SQL: &str = r#"
DO $reset_roles$
DECLARE
  target RECORD;
BEGIN
  FOR target IN
    SELECT role.rolname
      FROM pg_catalog.pg_roles AS role
     WHERE role.rolname <> SESSION_USER
       AND (
         role.rolname IN (
           'kf_runtime', 'kf_ingest_owner', 'kf_authority_owner',
           'kf_authority_registrar'
         )
         OR role.rolname LIKE 'kf_acceptance_%'
       )
     ORDER BY CASE WHEN role.rolname LIKE 'kf_acceptance_%' THEN 0 ELSE 1 END
  LOOP
    EXECUTE pg_catalog.format('REASSIGN OWNED BY %I TO %I', target.rolname, SESSION_USER);
    EXECUTE pg_catalog.format('DROP OWNED BY %I', target.rolname);
    EXECUTE pg_catalog.format('DROP ROLE %I', target.rolname);
  END LOOP;
END
$reset_roles$;

DROP SCHEMA IF EXISTS public CASCADE;
CREATE SCHEMA public AUTHORIZATION CURRENT_USER;
GRANT USAGE ON SCHEMA public TO PUBLIC;
"#;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct TableCounts {
    blobs: i64,
    occurrences: i64,
    versions: i64,
}

struct AuthoritySpec<'a> {
    project_id: Uuid,
    grant_id: Uuid,
    source_native_id: &'a str,
    content_sha256: &'a str,
    content: &'a [u8],
    nonce: &'a str,
    store_root: &'a str,
}

fn unique_hash() -> String {
    let half = Uuid::now_v7().simple().to_string();
    format!("{half}{half}")
}

fn unique_nonce(label: &str) -> String {
    format!("{label}-{}", Uuid::now_v7().simple())
}

fn assert_sqlstate(error: &sqlx_core::Error, expected: &str) {
    match error {
        sqlx_core::Error::Database(database) => {
            assert_eq!(database.code().as_deref(), Some(expected));
        }
        other => panic!("expected PostgreSQL SQLSTATE {expected}, got {other}"),
    }
}

fn assert_anyhow_sqlstate(error: &anyhow::Error, expected: &str) {
    let sqlx_error = error
        .chain()
        .find_map(|cause| cause.downcast_ref::<sqlx_core::Error>())
        .unwrap_or_else(|| panic!("expected PostgreSQL SQLSTATE {expected}, got {error:#}"));
    assert_sqlstate(sqlx_error, expected);
}

async fn verify_disposable_admin_connection(
    connection: &mut PgConnection,
    expected_database: &str,
) -> Result<(), sqlx_core::Error> {
    let verification = query(
        "SELECT role.rolname AS login_name,
                CURRENT_USER::text AS current_name,
                SESSION_USER::text AS session_name,
                role.rolsuper AS login_super,
                pg_catalog.current_database()::text AS database_name,
                pg_catalog.host(pg_catalog.inet_server_addr()) AS server_address,
                pg_catalog.pg_is_in_recovery() AS in_recovery,
                pg_catalog.current_setting('server_version_num')::integer AS server_version_num,
                (
                    SELECT pg_catalog.count(*)
                      FROM pg_catalog.pg_database AS database
                     WHERE database.datname NOT IN (
                           'template0', 'template1', 'postgres',
                           pg_catalog.current_database()
                       )
                ) AS other_user_databases
           FROM pg_catalog.pg_roles AS role
          WHERE role.rolname = SESSION_USER",
    )
    .fetch_optional(&mut *connection)
    .await?
    .ok_or_else(|| {
        sqlx_core::Error::Protocol(
            "disposable PostgreSQL administrator is absent from pg_roles".to_owned(),
        )
    })?;
    let login_name: String = verification.try_get("login_name")?;
    let current_name: String = verification.try_get("current_name")?;
    let session_name: String = verification.try_get("session_name")?;
    let actual_database: String = verification.try_get("database_name")?;
    let server_address: Option<String> = verification.try_get("server_address")?;
    let in_recovery: bool = verification.try_get("in_recovery")?;
    let is_superuser: bool = verification.try_get("login_super")?;
    let server_version_num: i32 = verification.try_get("server_version_num")?;
    let other_user_databases: i64 = verification.try_get("other_user_databases")?;
    let server_is_loopback = server_address
        .as_deref()
        .and_then(|address| address.parse::<std::net::IpAddr>().ok())
        .is_some_and(|address| address.is_loopback());
    if login_name != session_name
        || current_name != session_name
        || actual_database != expected_database
        || !server_is_loopback
        || in_recovery
        || !is_superuser
        || !(160_000..170_000).contains(&server_version_num)
        || other_user_databases != 0
    {
        return Err(sqlx_core::Error::Protocol(
            "admin connection escaped the disposable PostgreSQL 16 target boundary".to_owned(),
        ));
    }
    Ok(())
}

fn credential_url(admin_url: &str, role: &str, password: &str) -> String {
    let mut url = sqlx_core::Url::parse(admin_url).expect("parse guarded database URL");
    url.set_username(role)
        .expect("generated PostgreSQL role is URL-safe");
    url.set_password(Some(password))
        .expect("generated PostgreSQL password is URL-safe");
    url.to_string()
}

async fn create_login(admin_pool: &Pool<Postgres>, role: &str, password: &str, granted_role: &str) {
    let create = format!(
        "CREATE ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB \
         NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT"
    );
    query(&create)
        .execute(admin_pool)
        .await
        .unwrap_or_else(|error| panic!("create safe login {role}: {error}"));
    let grant = format!("GRANT {granted_role} TO {role} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE");
    query(&grant)
        .execute(admin_pool)
        .await
        .unwrap_or_else(|error| panic!("grant exact role {granted_role} to {role}: {error}"));
}

async fn table_counts(pool: &Pool<Postgres>) -> TableCounts {
    let row = query(
        "SELECT (SELECT pg_catalog.count(*) FROM public.raw_blob) AS blobs,
                (SELECT pg_catalog.count(*) FROM public.artifact_occurrence) AS occurrences,
                (SELECT pg_catalog.count(*) FROM public.artifact_version) AS versions",
    )
    .fetch_one(pool)
    .await
    .expect("count durable identity rows");
    TableCounts {
        blobs: row.try_get("blobs").expect("blob count"),
        occurrences: row.try_get("occurrences").expect("occurrence count"),
        versions: row.try_get("versions").expect("version count"),
    }
}

async fn assert_source_absent(pool: &Pool<Postgres>, source_native_id: &str) {
    let row = query(
        "SELECT pg_catalog.count(*) AS n
           FROM public.artifact_occurrence
          WHERE source_system_id = 'acceptance'
            AND source_native_id = $1",
    )
    .bind(source_native_id)
    .fetch_one(pool)
    .await
    .expect("check denied source absence");
    assert_eq!(row.try_get::<i64, _>("n").expect("source count"), 0);
}

fn json_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for character in value.chars() {
        match character {
            '"' => escaped.push_str("\\\""),
            '\\' => escaped.push_str("\\\\"),
            '\u{08}' => escaped.push_str("\\b"),
            '\u{0c}' => escaped.push_str("\\f"),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            control if control <= '\u{1f}' => {
                escaped.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => escaped.push(other),
        }
    }
    escaped.push('"');
    escaped
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        encoded.push(HEX[(byte >> 4) as usize] as char);
        encoded.push(HEX[(byte & 0x0f) as usize] as char);
    }
    encoded
}

// Kept local to this ignored test so the production crate does not gain a test-only hashing API.
fn sha256_hex(input: &[u8]) -> String {
    const INITIAL: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    const ROUND: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    let bit_len = (input.len() as u64) * 8;
    let mut padded = input.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    let mut state = INITIAL;
    for block in padded.chunks_exact(64) {
        let mut words = [0_u32; 64];
        for (index, word) in words[..16].iter_mut().enumerate() {
            *word = u32::from_be_bytes(
                block[index * 4..index * 4 + 4]
                    .try_into()
                    .expect("exact SHA-256 word"),
            );
        }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7)
                ^ words[index - 15].rotate_right(18)
                ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17)
                ^ words[index - 2].rotate_right(19)
                ^ (words[index - 2] >> 10);
            words[index] = words[index - 16]
                .wrapping_add(s0)
                .wrapping_add(words[index - 7])
                .wrapping_add(s1);
        }

        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for index in 0..64 {
            let choice = (e & f) ^ ((!e) & g);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let sum0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let sum1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let temp1 = h
                .wrapping_add(sum1)
                .wrapping_add(choice)
                .wrapping_add(ROUND[index])
                .wrapping_add(words[index]);
            let temp2 = sum0.wrapping_add(majority);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        for (slot, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *slot = slot.wrapping_add(value);
        }
    }

    let mut digest = [0_u8; 32];
    for (index, word) in state.into_iter().enumerate() {
        digest[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    hex_encode(&digest)
}

fn sign_with_openssl(base: &Path, message: &[u8]) -> Vec<u8> {
    let operation = Uuid::now_v7().simple().to_string();
    let key_path = base.join("acceptance-ed25519.pem");
    let message_path = base.join(format!("message-{operation}.bin"));
    let signature_path = base.join(format!("signature-{operation}.bin"));
    fs::write(&key_path, PRIVATE_KEY_PEM).expect("write deterministic acceptance private key");
    fs::write(&message_path, message).expect("write authority signing message");
    let openssl = std::env::var_os("KF_TEST_OPENSSL").unwrap_or_else(|| "openssl".into());
    let output = Command::new(openssl)
        .args(["pkeyutl", "-sign", "-rawin", "-inkey"])
        .arg(&key_path)
        .args(["-in"])
        .arg(&message_path)
        .args(["-out"])
        .arg(&signature_path)
        .output()
        .expect("run OpenSSL 3 for Ed25519 acceptance signing (or set KF_TEST_OPENSSL)");
    assert!(
        output.status.success(),
        "OpenSSL Ed25519 signing failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let signature = fs::read(&signature_path).expect("read Ed25519 signature");
    assert_eq!(signature.len(), 64, "Ed25519 signature must be 64 bytes");
    signature
}

fn consume_authority(base: &Path, spec: AuthoritySpec<'_>) -> StoredIngestAuthority {
    consume_authority_for_session(base, spec, RUNTIME_ROLE)
}

fn consume_authority_for_session(
    base: &Path,
    spec: AuthoritySpec<'_>,
    database_session_user: &str,
) -> StoredIngestAuthority {
    let fixture_id = Uuid::now_v7().simple().to_string();
    assert_eq!(base, Path::new(FIXTURE_BASE));
    assert!(matches!(spec.store_root, "root-a" | "root-b"));
    assert!(database_session_user == RUNTIME_ROLE || database_session_user == REUSED_RUNTIME_ROLE);
    assert_eq!(sha256_hex(spec.content), spec.content_sha256);
    let store_root = base.join(spec.store_root);
    assert!(
        store_root.is_dir(),
        "authority store root must be pre-provisioned"
    );
    let canonical_root = fs::canonicalize(&store_root).expect("canonicalize authority store root");
    let canonical_root_text = canonical_root
        .to_str()
        .expect("authority root must be UTF-8")
        .to_owned();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("acceptance clock must follow Unix epoch")
        .as_secs() as i64;
    let claims = AuthorityClaims {
        version: CLAIMS_VERSION.to_owned(),
        issuer: ISSUER.to_owned(),
        key_id: KEY_ID.to_owned(),
        actor: ACTOR.to_owned(),
        authority_domain_id: AUTHORITY_DOMAIN_ID.to_owned(),
        project_id: spec.project_id.to_string(),
        database_grant_id: spec.grant_id.to_string(),
        database_session_user: database_session_user.to_owned(),
        store_root: canonical_root_text.clone(),
        content_sha256: spec.content_sha256.to_owned(),
        content_size: spec.content.len() as u64,
        source_system_id: "acceptance".to_owned(),
        source_native_id: spec.source_native_id.to_owned(),
        nonce: spec.nonce.to_owned(),
        issued_at_unix: now - 1,
        expires_at_unix: now + 240,
        audience: "maworld.kf-intake".to_owned(),
        action: "ingest".to_owned(),
    };
    let message = signing_message(&claims).expect("create canonical authority-v3 message");
    let signature_hex = hex_encode(&sign_with_openssl(base, &message));

    let registry_path = base.join("authority-registry-v3.json");
    fs::write(&registry_path, REGISTRY_BYTES).expect("write pinned authority registry");
    assert_eq!(
        compiled_trust_registry_digest().expect("acceptance build must embed registry pin"),
        sha256_hex(REGISTRY_BYTES)
    );

    let envelope = format!(
        "{{\"algorithm\":\"Ed25519\",\"claims\":{{\
         \"version\":{},\"issuer\":{},\"key_id\":{},\"actor\":{},\
         \"authority_domain_id\":{},\"project_id\":{},\
         \"database_grant_id\":{},\"database_session_user\":{},\"store_root\":{},\
         \"content_sha256\":{},\"content_size\":{},\"source_system_id\":\"acceptance\",\
         \"source_native_id\":{},\"nonce\":{},\"issued_at_unix\":{},\
         \"expires_at_unix\":{},\"audience\":\"maworld.kf-intake\",\"action\":\"ingest\"}},\
         \"signature_hex\":{}}}",
        json_string(CLAIMS_VERSION),
        json_string(ISSUER),
        json_string(KEY_ID),
        json_string(ACTOR),
        json_string(AUTHORITY_DOMAIN_ID),
        json_string(&spec.project_id.to_string()),
        json_string(&spec.grant_id.to_string()),
        json_string(database_session_user),
        json_string(&canonical_root_text),
        json_string(spec.content_sha256),
        spec.content.len(),
        json_string(spec.source_native_id),
        json_string(spec.nonce),
        claims.issued_at_unix,
        claims.expires_at_unix,
        json_string(&signature_hex),
    );
    let envelope_path = base.join(format!("envelope-{fixture_id}.json"));
    fs::write(&envelope_path, envelope.as_bytes()).expect("write signed authority envelope");

    let consumed = authorize_and_consume(
        &store_root,
        &registry_path,
        &envelope_path,
        &AuthorityRequest::new(
            AUTHORITY_DOMAIN_ID.to_owned(),
            spec.project_id.to_string(),
            spec.grant_id.to_string(),
            database_session_user.to_owned(),
            spec.content_sha256.to_owned(),
            spec.content.len() as u64,
            "acceptance".to_owned(),
            spec.source_native_id.to_owned(),
        ),
    )
    .expect("verify and consume exact authority-v3 envelope");
    let source_path = base.join(format!("source-{fixture_id}.bin"));
    fs::write(&source_path, spec.content).expect("write exact acceptance source bytes");
    publish_authorized_source(consumed, &source_path)
        .expect("publish and recover exact authority-bound CAS bytes")
}

async fn register_authority(
    authority_store: &PostgresAuthorityStore,
    base: &Path,
    spec: AuthoritySpec<'_>,
) -> Uuid {
    let expected = spec.grant_id;
    let authority = consume_authority(base, spec);
    let registered = authority_store
        .register_ingest_authority(&authority)
        .await
        .expect("register stored authority in PostgreSQL");
    assert_eq!(registered, expected);
    let exact_retry = authority_store
        .register_ingest_authority(&authority)
        .await
        .expect("retry exact durable authority registration");
    assert_eq!(exact_retry, expected);
    registered
}

async fn assert_exact_scope(
    admin_pool: &Pool<Postgres>,
    outcome: &IngestOutcome,
    project_id: Uuid,
    source_native_id: &str,
    content_sha256: &str,
    content_size: usize,
) {
    let row = query(
        "SELECT occurrence.project_id,
                occurrence.source_system_id,
                occurrence.source_native_id,
                blob.sha256::text AS sha256,
                blob.byte_size,
                blob.storage_uri,
                version.source_revision_key
           FROM public.artifact_occurrence AS occurrence
           JOIN public.raw_blob AS blob ON blob.blob_id = occurrence.blob_id
           JOIN public.artifact_version AS version
             ON version.occurrence_id = occurrence.occurrence_id
          WHERE occurrence.occurrence_id = $1
            AND version.version_id = $2",
    )
    .bind(outcome.occurrence_id)
    .bind(outcome.version_id)
    .fetch_one(admin_pool)
    .await
    .expect("read exact admin-side durable scope");
    assert_eq!(row.try_get::<Uuid, _>("project_id").unwrap(), project_id);
    assert_eq!(
        row.try_get::<String, _>("source_system_id").unwrap(),
        "acceptance"
    );
    assert_eq!(
        row.try_get::<String, _>("source_native_id").unwrap(),
        source_native_id
    );
    assert_eq!(row.try_get::<String, _>("sha256").unwrap(), content_sha256);
    assert_eq!(
        row.try_get::<i64, _>("byte_size").unwrap(),
        content_size as i64
    );
    assert_eq!(
        row.try_get::<String, _>("storage_uri").unwrap(),
        format!("cas://sha256/{content_sha256}")
    );
    assert_eq!(
        row.try_get::<String, _>("source_revision_key").unwrap(),
        content_sha256
    );
}

#[tokio::test]
#[ignore = "requires explicit disposable loopback PostgreSQL 16 and OpenSSL 3"]
async fn authority_bound_tenant_acceptance() {
    assert_eq!(
        sha256_hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    let confirmation = std::env::var("KF_TEST_DATABASE_CONFIRMATION")
        .expect("KF_TEST_DATABASE_CONFIRMATION is required for ignored database acceptance");
    assert_eq!(confirmation, CONFIRMATION);
    let cluster_confirmation = std::env::var("KF_TEST_CLUSTER_CONFIRMATION")
        .expect("KF_TEST_CLUSTER_CONFIRMATION is required for ignored database acceptance");
    assert_eq!(cluster_confirmation, CLUSTER_CONFIRMATION);
    let admin_url = std::env::var("KF_TEST_DATABASE_URL")
        .expect("KF_TEST_DATABASE_URL must name a dedicated disposable test database");
    let guarded_database = validate_disposable_database_url(&admin_url)
        .expect("test URL must pass the strict pre-network disposable database guard");
    let expected_database = sqlx_core::Url::parse(&admin_url)
        .expect("parse test database URL")
        .path()
        .trim_start_matches('/')
        .to_owned();
    assert_eq!(guarded_database, expected_database);
    let expected_database_for_connections = expected_database.clone();
    let admin_pool = PoolOptions::<Postgres>::new()
        .max_connections(8)
        .after_connect(move |connection, _metadata| {
            let expected_database = expected_database_for_connections.clone();
            Box::pin(async move {
                verify_disposable_admin_connection(connection, &expected_database).await
            })
        })
        .connect(&admin_url)
        .await
        .expect("connect guarded disposable administrator");

    raw_sql::raw_sql(RESET_SQL)
        .execute(&admin_pool)
        .await
        .expect("reset only the confirmed disposable database and KF roles");
    for (name, migration) in [
        ("001", MIGRATION_001),
        ("002", MIGRATION_002),
        ("003", MIGRATION_003),
    ] {
        raw_sql::raw_sql(migration)
            .execute(&admin_pool)
            .await
            .unwrap_or_else(|error| panic!("apply KF migration {name}: {error}"));
    }
    query(
        "CREATE ROLE kf_authority_registrar NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
         NOREPLICATION NOBYPASSRLS NOINHERIT",
    )
    .execute(&admin_pool)
    .await
    .expect("seed pre-004 named registrar role");
    query("GRANT SELECT ON public.raw_blob TO kf_authority_registrar")
        .execute(&admin_pool)
        .await
        .expect("seed stale registrar table ACL");
    query("GRANT UPDATE (storage_uri) ON public.raw_blob TO kf_authority_registrar")
        .execute(&admin_pool)
        .await
        .expect("seed stale registrar column ACL");
    query(
        "GRANT EXECUTE ON FUNCTION public.kf_ingest_observation(
           uuid,uuid,uuid,text,text,text,text,bigint,text
         ) TO kf_authority_registrar",
    )
    .execute(&admin_pool)
    .await
    .expect("seed stale registrar function ACL");
    raw_sql::raw_sql(MIGRATION_004)
        .execute(&admin_pool)
        .await
        .expect("apply KF migration 004 over seeded registrar ACL drift");

    let mut reapply_connection = admin_pool
        .acquire()
        .await
        .expect("acquire isolated 004 reapply probe connection");
    let reapply_error = raw_sql::raw_sql(MIGRATION_004)
        .execute(&mut *reapply_connection)
        .await
        .expect_err("one-shot migration 004 must refuse a second application");
    assert_sqlstate(&reapply_error, "55000");
    query("ROLLBACK")
        .execute(&mut *reapply_connection)
        .await
        .expect("recover connection after expected one-shot refusal");
    drop(reapply_connection);

    let authority_domain_id =
        Uuid::parse_str(AUTHORITY_DOMAIN_ID).expect("fixed authority-domain UUID");
    query(
        "INSERT INTO public.kf_authority_domain(singleton, authority_domain_id)
         VALUES (true, $1)",
    )
    .bind(authority_domain_id)
    .execute(&admin_pool)
    .await
    .expect("provision explicit acceptance authority domain");

    let runtime_password = Uuid::now_v7().simple().to_string();
    let wrong_runtime_password = Uuid::now_v7().simple().to_string();
    let reused_runtime_password = Uuid::now_v7().simple().to_string();
    let registrar_password = Uuid::now_v7().simple().to_string();
    let unsafe_registrar_password = Uuid::now_v7().simple().to_string();
    create_login(&admin_pool, RUNTIME_ROLE, &runtime_password, "kf_runtime").await;
    create_login(
        &admin_pool,
        WRONG_RUNTIME_ROLE,
        &wrong_runtime_password,
        "kf_runtime",
    )
    .await;
    create_login(
        &admin_pool,
        REUSED_RUNTIME_ROLE,
        &reused_runtime_password,
        "kf_runtime",
    )
    .await;
    create_login(
        &admin_pool,
        UNSAFE_REGISTRAR_ROLE,
        &unsafe_registrar_password,
        "kf_authority_registrar",
    )
    .await;
    query(&format!(
        "GRANT kf_runtime TO {UNSAFE_REGISTRAR_ROLE} WITH ADMIN FALSE, INHERIT FALSE, SET TRUE"
    ))
    .execute(&admin_pool)
    .await
    .expect("give adversarial registrar a forbidden second membership");
    create_login(
        &admin_pool,
        REGISTRAR_ROLE,
        &registrar_password,
        "kf_authority_registrar",
    )
    .await;

    let runtime_url = credential_url(&admin_url, RUNTIME_ROLE, &runtime_password);
    let wrong_runtime_url = credential_url(&admin_url, WRONG_RUNTIME_ROLE, &wrong_runtime_password);
    let registrar_url = credential_url(&admin_url, REGISTRAR_ROLE, &registrar_password);
    let unsafe_registrar_url = credential_url(
        &admin_url,
        UNSAFE_REGISTRAR_ROLE,
        &unsafe_registrar_password,
    );
    let runtime_store = Arc::new(
        PostgresMetaStore::connect_runtime(&runtime_url, authority_domain_id)
            .await
            .expect("admit real NOINHERIT runtime login"),
    );
    let wrong_runtime_store =
        PostgresMetaStore::connect_runtime(&wrong_runtime_url, authority_domain_id)
            .await
            .expect("admit second real NOINHERIT runtime login");
    let authority_store =
        PostgresAuthorityStore::connect_registrar(&registrar_url, authority_domain_id)
            .await
            .expect("admit real NOINHERIT authority registrar login");
    assert!(
        PostgresAuthorityStore::connect_registrar(&unsafe_registrar_url, authority_domain_id)
            .await
            .is_err(),
        "adapter must reject a registrar login with a second membership"
    );
    let direct_runtime_pool = PoolOptions::<Postgres>::new()
        .max_connections(2)
        .connect(&runtime_url)
        .await
        .expect("connect direct runtime-login adversarial pool");
    let unsafe_registrar_pool = PoolOptions::<Postgres>::new()
        .max_connections(1)
        .connect(&unsafe_registrar_url)
        .await
        .expect("connect raw dual-member registrar adversarial pool");

    assert_eq!(std::env::consts::OS, "linux");
    let fixture_base = PathBuf::from(FIXTURE_BASE);
    if fixture_base.exists() {
        fs::remove_dir_all(&fixture_base).expect("reset fixed disposable authority fixture");
    }
    fs::create_dir(&fixture_base).expect("create authority fixture base outside store roots");
    fs::create_dir(fixture_base.join("root-a")).expect("pre-provision authority root A");
    fs::create_dir(fixture_base.join("root-b")).expect("pre-provision authority root B");

    let project_a = Uuid::parse_str(PROJECT_A).expect("fixed project A UUID");
    let project_b = Uuid::parse_str(PROJECT_B).expect("fixed project B UUID");
    query("INSERT INTO public.project(project_id, slug) VALUES($1,$2),($3,$4)")
        .bind(project_a)
        .bind(format!(
            "authority-a-{}",
            &project_a.simple().to_string()[..12]
        ))
        .bind(project_b)
        .bind(format!(
            "authority-b-{}",
            &project_b.simple().to_string()[..12]
        ))
        .execute(&admin_pool)
        .await
        .expect("seed isolated acceptance projects");

    // The signed proof is bound to the configured database security domain. Simulate a
    // misrouted independent database by rotating its singleton identity: registration must fail
    // in SQL with no grant row, even though the same registrar credential and CAS proof are valid.
    let domain_probe_source = format!("domain-probe-{}", Uuid::now_v7().simple());
    let domain_probe_content = format!("domain-bound bytes {domain_probe_source}").into_bytes();
    let domain_probe_hash = sha256_hex(&domain_probe_content);
    let domain_probe_grant = Uuid::now_v7();
    let domain_probe = consume_authority(
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: domain_probe_grant,
            source_native_id: &domain_probe_source,
            content_sha256: &domain_probe_hash,
            content: &domain_probe_content,
            nonce: &unique_nonce("domain-probe"),
            store_root: "root-a",
        },
    );
    let other_authority_domain_id =
        Uuid::parse_str(OTHER_AUTHORITY_DOMAIN_ID).expect("fixed alternate authority-domain UUID");
    query(
        "UPDATE public.kf_authority_domain
            SET authority_domain_id = $1, provisioned_at = pg_catalog.clock_timestamp()
          WHERE singleton",
    )
    .bind(other_authority_domain_id)
    .execute(&admin_pool)
    .await
    .expect("simulate database authority-domain mismatch");
    let domain_error = authority_store
        .register_ingest_authority(&domain_probe)
        .await
        .expect_err("proof from a different authority domain must be denied");
    assert_anyhow_sqlstate(&domain_error, "42501");
    let domain_probe_count = query(
        "SELECT pg_catalog.count(*) AS n
           FROM public.kf_ingest_authority_grant
          WHERE grant_id = $1",
    )
    .bind(domain_probe_grant)
    .fetch_one(&admin_pool)
    .await
    .expect("count denied cross-domain grant");
    assert_eq!(domain_probe_count.try_get::<i64, _>("n").unwrap(), 0);
    query(
        "UPDATE public.kf_authority_domain
            SET authority_domain_id = $1, provisioned_at = pg_catalog.clock_timestamp()
          WHERE singleton",
    )
    .bind(authority_domain_id)
    .execute(&admin_pool)
    .await
    .expect("restore acceptance authority domain");

    // A StoredIngestAuthority is re-opened and streamed immediately before SQL. Deleting the
    // published CAS blob after proof creation must never create a phantom database grant.
    let missing_blob_source = format!("missing-blob-{}", Uuid::now_v7().simple());
    let missing_blob_content = format!("CAS revalidation bytes {missing_blob_source}").into_bytes();
    let missing_blob_hash = sha256_hex(&missing_blob_content);
    let missing_blob_grant = Uuid::now_v7();
    let missing_blob_authority = consume_authority(
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: missing_blob_grant,
            source_native_id: &missing_blob_source,
            content_sha256: &missing_blob_hash,
            content: &missing_blob_content,
            nonce: &unique_nonce("missing-blob"),
            store_root: "root-a",
        },
    );
    let missing_blob_path = fixture_base
        .join("root-a")
        .join("cas")
        .join(&missing_blob_hash[0..2])
        .join(&missing_blob_hash[2..4])
        .join(&missing_blob_hash);
    fs::remove_file(&missing_blob_path).expect("remove CAS blob after proof creation");
    let missing_blob_error = authority_store
        .register_ingest_authority(&missing_blob_authority)
        .await
        .expect_err("missing CAS bytes must block database registration");
    let missing_blob_error_text = format!("{missing_blob_error:#}");
    assert!(
        missing_blob_error_text.contains("revalidat")
            || missing_blob_error_text.contains("No such file"),
        "unexpected missing-CAS error: {missing_blob_error:#}"
    );
    let missing_blob_count = query(
        "SELECT pg_catalog.count(*) AS n
           FROM public.kf_ingest_authority_grant
          WHERE grant_id = $1",
    )
    .bind(missing_blob_grant)
    .fetch_one(&admin_pool)
    .await
    .expect("count phantom grant after missing CAS denial");
    assert_eq!(missing_blob_count.try_get::<i64, _>("n").unwrap(), 0);

    // A signed role name is not enough: registration pins the current PostgreSQL role OID.
    // Dropping and recreating a safe login under the same name must not inherit an old grant.
    let reused_source = format!("role-reuse-{}", Uuid::now_v7().simple());
    let reused_content = format!("role OID binding bytes {reused_source}").into_bytes();
    let reused_hash = sha256_hex(&reused_content);
    let reused_grant = Uuid::now_v7();
    let reused_authority = consume_authority_for_session(
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: reused_grant,
            source_native_id: &reused_source,
            content_sha256: &reused_hash,
            content: &reused_content,
            nonce: &unique_nonce("role-reuse"),
            store_root: "root-a",
        },
        REUSED_RUNTIME_ROLE,
    );
    authority_store
        .register_ingest_authority(&reused_authority)
        .await
        .expect("register grant bound to the original runtime role OID");
    let old_role =
        query("SELECT oid::bigint AS role_oid FROM pg_catalog.pg_roles WHERE rolname = $1")
            .bind(REUSED_RUNTIME_ROLE)
            .fetch_one(&admin_pool)
            .await
            .expect("read original runtime role OID")
            .try_get::<i64, _>("role_oid")
            .expect("decode original runtime role OID");
    query(&format!("REVOKE kf_runtime FROM {REUSED_RUNTIME_ROLE}"))
        .execute(&admin_pool)
        .await
        .expect("remove original runtime membership before role recreation");
    query(&format!("DROP ROLE {REUSED_RUNTIME_ROLE}"))
        .execute(&admin_pool)
        .await
        .expect("drop original runtime login");
    let replacement_runtime_password = Uuid::now_v7().simple().to_string();
    create_login(
        &admin_pool,
        REUSED_RUNTIME_ROLE,
        &replacement_runtime_password,
        "kf_runtime",
    )
    .await;
    let replacement_role =
        query("SELECT oid::bigint AS role_oid FROM pg_catalog.pg_roles WHERE rolname = $1")
            .bind(REUSED_RUNTIME_ROLE)
            .fetch_one(&admin_pool)
            .await
            .expect("read replacement runtime role OID")
            .try_get::<i64, _>("role_oid")
            .expect("decode replacement runtime role OID");
    assert_ne!(old_role, replacement_role);
    let replacement_runtime_url = credential_url(
        &admin_url,
        REUSED_RUNTIME_ROLE,
        &replacement_runtime_password,
    );
    let replacement_runtime_store =
        PostgresMetaStore::connect_runtime(&replacement_runtime_url, authority_domain_id)
            .await
            .expect("admit safely recreated runtime login");
    let role_reuse_error = replacement_runtime_store
        .ingest_authorized(reused_grant)
        .await
        .expect_err("recreated same-name principal must not inherit the old grant");
    assert_anyhow_sqlstate(&role_reuse_error, "42501");
    assert_source_absent(&admin_pool, &reused_source).await;

    // A missing grant is a uniform permission denial and cannot create any durable row.
    let before_missing = table_counts(&admin_pool).await;
    let missing_error = runtime_store
        .ingest_authorized(Uuid::now_v7())
        .await
        .expect_err("missing authority grant must be denied");
    assert_anyhow_sqlstate(&missing_error, "42501");
    assert_eq!(table_counts(&admin_pool).await, before_missing);

    // Caller-controlled custom GUC text is inert. It cannot make a random grant valid and the
    // real runtime login cannot issue raw SELECT after switching to its only effective role.
    let before_poison = table_counts(&admin_pool).await;
    let mut poisoned = direct_runtime_pool
        .begin()
        .await
        .expect("begin GUC poison test");
    query("SELECT pg_catalog.set_config('app.project_ids', $1, true)")
        .bind(project_b.to_string())
        .execute(&mut *poisoned)
        .await
        .expect("runtime login may set inert custom GUC text");
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut *poisoned)
        .await
        .expect("switch poisoned transaction to runtime role");
    let poison_error = query("SELECT * FROM public.kf_ingest_authorized($1,$2)")
        .bind(Uuid::now_v7())
        .bind(authority_domain_id)
        .fetch_one(&mut *poisoned)
        .await
        .expect_err("arbitrary project GUC must not create authority");
    assert_sqlstate(&poison_error, "42501");
    poisoned.rollback().await.expect("rollback GUC poison test");
    assert_eq!(table_counts(&admin_pool).await, before_poison);

    let mut raw_read = direct_runtime_pool
        .begin()
        .await
        .expect("begin raw read denial");
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut *raw_read)
        .await
        .expect("switch raw-read transaction to runtime role");
    let read_error = query("SELECT occurrence_id FROM public.artifact_occurrence LIMIT 1")
        .fetch_optional(&mut *raw_read)
        .await
        .expect_err("runtime raw SELECT must be denied");
    assert_sqlstate(&read_error, "42501");
    raw_read.rollback().await.expect("rollback denied raw read");

    // The generic runtime credential cannot bypass the grant table by invoking either the
    // registrar or the retired caller-scoped intake function directly.
    let before_direct_functions = table_counts(&admin_pool).await;
    let mut direct_functions = direct_runtime_pool
        .begin()
        .await
        .expect("begin direct function denial");
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut *direct_functions)
        .await
        .expect("switch direct-function transaction to runtime role");
    let internal_error = query(
        "SELECT * FROM public.kf_ingest_observation_internal(
            $1,$2,$3,$4,$5,$6,$7,$8,$9)",
    )
    .bind(project_a)
    .bind(Uuid::now_v7())
    .bind(Uuid::now_v7())
    .bind("acceptance")
    .bind("direct-internal-denied")
    .bind(unique_hash())
    .bind(unique_hash())
    .bind(27_i64)
    .bind("cas://sha256/direct-internal-denied")
    .fetch_one(&mut *direct_functions)
    .await
    .expect_err("runtime must not execute the internal caller-scoped intake function");
    assert_sqlstate(&internal_error, "42501");
    direct_functions
        .rollback()
        .await
        .expect("rollback denied internal function");

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("acceptance clock must follow Unix epoch")
        .as_secs() as i64;
    let mut direct_registration = direct_runtime_pool
        .begin()
        .await
        .expect("begin direct registration denial");
    query("SET LOCAL ROLE kf_runtime")
        .execute(&mut *direct_registration)
        .await
        .expect("switch direct-registration transaction to runtime role");
    let registration_error = query(
        "SELECT public.kf_register_ingest_authority_grant(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
    )
    .bind(Uuid::now_v7())
    .bind(authority_domain_id)
    .bind(ISSUER)
    .bind(KEY_ID)
    .bind(ACTOR)
    .bind(project_a)
    .bind(RUNTIME_ROLE)
    .bind("acceptance")
    .bind("direct-registration-denied")
    .bind(unique_hash())
    .bind(27_i64)
    .bind(unique_nonce("direct-registration"))
    .bind(unique_hash())
    .bind(now - 1)
    .bind(now + 60)
    .fetch_one(&mut *direct_registration)
    .await
    .expect_err("runtime must not register its own authority grant");
    assert_sqlstate(&registration_error, "42501");
    direct_registration
        .rollback()
        .await
        .expect("rollback denied direct registration");

    let mut dual_member_registration = unsafe_registrar_pool
        .begin()
        .await
        .expect("begin SQL-side dual-member registrar denial");
    query("SET LOCAL ROLE kf_authority_registrar")
        .execute(&mut *dual_member_registration)
        .await
        .expect("dual-member login can switch to registrar role");
    let dual_member_error = query(
        "SELECT public.kf_register_ingest_authority_grant(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
    )
    .bind(Uuid::now_v7())
    .bind(authority_domain_id)
    .bind(ISSUER)
    .bind(KEY_ID)
    .bind(ACTOR)
    .bind(project_a)
    .bind(RUNTIME_ROLE)
    .bind("acceptance")
    .bind("dual-member-registrar-denied")
    .bind(unique_hash())
    .bind(27_i64)
    .bind(unique_nonce("dual-member-registrar"))
    .bind(unique_hash())
    .bind(now - 1)
    .bind(now + 60)
    .fetch_one(&mut *dual_member_registration)
    .await
    .expect_err("SQL body must reject a registrar session with another membership");
    assert_sqlstate(&dual_member_error, "42501");
    dual_member_registration
        .rollback()
        .await
        .expect("rollback SQL-side dual-member denial");
    assert_eq!(table_counts(&admin_pool).await, before_direct_functions);

    // Valid authority registration and ingest preserve exact signed scope. PostgreSQL generates
    // row identities server-side, so the runtime cannot probe cross-tenant UUID membership.
    let exact_source = format!("exact-{}", Uuid::now_v7().simple());
    let exact_content = format!("exact authority-bound bytes {exact_source}").into_bytes();
    let exact_hash = sha256_hex(&exact_content);
    let exact_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &exact_source,
            content_sha256: &exact_hash,
            content: &exact_content,
            nonce: &unique_nonce("exact"),
            store_root: "root-a",
        },
    )
    .await;
    let misrouted_runtime_store =
        PostgresMetaStore::connect_runtime(&runtime_url, other_authority_domain_id)
            .await
            .expect("admit safe login before domain-bound request check");
    let misroute_error = misrouted_runtime_store
        .ingest_authorized(exact_grant)
        .await
        .expect_err("runtime adapter configured for another domain must fail closed");
    assert_anyhow_sqlstate(&misroute_error, "42501");
    assert_source_absent(&admin_pool, &exact_source).await;
    let exact_outcome = runtime_store
        .ingest_authorized(exact_grant)
        .await
        .expect("ingest exact registered authority");
    assert!(!exact_outcome.occurrence_id.is_nil());
    assert!(!exact_outcome.version_id.is_nil());
    assert_exact_scope(
        &admin_pool,
        &exact_outcome,
        project_a,
        &exact_source,
        &exact_hash,
        exact_content.len(),
    )
    .await;

    // A consumed exact result is a read-only recovery response even after TTL and revocation.
    query(
        "UPDATE public.kf_ingest_authority_grant
            SET issued_at_unix = 0,
                expires_at_unix = 1,
                revoked_at = pg_catalog.clock_timestamp()
          WHERE grant_id = $1",
    )
    .bind(exact_grant)
    .execute(&admin_pool)
    .await
    .expect("expire and revoke already-consumed retry fixture");
    let exact_retry = runtime_store
        .ingest_authorized(exact_grant)
        .await
        .expect("recover exact consumed outcome after expiry and revocation");
    assert_eq!(exact_retry, exact_outcome);

    // SESSION_USER, revocation, and expiry checks happen before consumption and leave zero rows.
    let wrong_source = format!("wrong-session-{}", Uuid::now_v7().simple());
    let wrong_content = format!("wrong session bytes {wrong_source}").into_bytes();
    let wrong_hash = sha256_hex(&wrong_content);
    let wrong_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &wrong_source,
            content_sha256: &wrong_hash,
            content: &wrong_content,
            nonce: &unique_nonce("wrong-session"),
            store_root: "root-a",
        },
    )
    .await;
    let wrong_error = wrong_runtime_store
        .ingest_authorized(wrong_grant)
        .await
        .expect_err("different SESSION_USER must be denied");
    assert_anyhow_sqlstate(&wrong_error, "42501");
    assert_source_absent(&admin_pool, &wrong_source).await;
    runtime_store
        .ingest_authorized(wrong_grant)
        .await
        .expect("correct SESSION_USER can consume grant after wrong-user denial");

    let revoked_source = format!("revoked-{}", Uuid::now_v7().simple());
    let revoked_content = format!("revoked bytes {revoked_source}").into_bytes();
    let revoked_hash = sha256_hex(&revoked_content);
    let revoked_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &revoked_source,
            content_sha256: &revoked_hash,
            content: &revoked_content,
            nonce: &unique_nonce("revoked"),
            store_root: "root-a",
        },
    )
    .await;
    query(
        "UPDATE public.kf_ingest_authority_grant
            SET revoked_at = pg_catalog.clock_timestamp()
          WHERE grant_id = $1",
    )
    .bind(revoked_grant)
    .execute(&admin_pool)
    .await
    .expect("revoke unconsumed test grant as migration administrator");
    let revoked_error = runtime_store
        .ingest_authorized(revoked_grant)
        .await
        .expect_err("revoked authority must be denied");
    assert_anyhow_sqlstate(&revoked_error, "42501");
    assert_source_absent(&admin_pool, &revoked_source).await;

    let expired_source = format!("expired-{}", Uuid::now_v7().simple());
    let expired_content = format!("expired bytes {expired_source}").into_bytes();
    let expired_hash = sha256_hex(&expired_content);
    let expired_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &expired_source,
            content_sha256: &expired_hash,
            content: &expired_content,
            nonce: &unique_nonce("expired"),
            store_root: "root-a",
        },
    )
    .await;
    query(
        "UPDATE public.kf_ingest_authority_grant
            SET issued_at_unix = 0, expires_at_unix = 1
          WHERE grant_id = $1",
    )
    .bind(expired_grant)
    .execute(&admin_pool)
    .await
    .expect("force test grant into a constraint-valid expired interval");
    let expired_error = runtime_store
        .ingest_authorized(expired_grant)
        .await
        .expect_err("expired authority must be denied");
    assert_anyhow_sqlstate(&expired_error, "42501");
    assert_source_absent(&admin_pool, &expired_source).await;

    // The adapter must install lock_timeout before the SECURITY DEFINER call. Hold the grant row
    // as administrator and prove the runtime gets PostgreSQL's bounded lock error before the
    // outer watchdog fires, rather than waiting indefinitely behind an attacker-held lock.
    let blocked_source = format!("blocked-lock-{}", Uuid::now_v7().simple());
    let blocked_content = format!("blocked lock bytes {blocked_source}").into_bytes();
    let blocked_hash = sha256_hex(&blocked_content);
    let blocked_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &blocked_source,
            content_sha256: &blocked_hash,
            content: &blocked_content,
            nonce: &unique_nonce("blocked-lock"),
            store_root: "root-a",
        },
    )
    .await;
    let mut blocker = admin_pool.begin().await.expect("begin grant-row blocker");
    query("SELECT grant_id FROM public.kf_ingest_authority_grant WHERE grant_id = $1 FOR UPDATE")
        .bind(blocked_grant)
        .fetch_one(&mut *blocker)
        .await
        .expect("hold unconsumed grant row lock");
    let bounded_error = tokio::time::timeout(
        Duration::from_secs(8),
        runtime_store.ingest_authorized(blocked_grant),
    )
    .await
    .expect("runtime lock wait exceeded the 8-second acceptance watchdog")
    .expect_err("runtime call must fail while the grant row remains locked");
    assert_anyhow_sqlstate(&bounded_error, "55P03");
    blocker.rollback().await.expect("release grant-row blocker");
    query("DELETE FROM public.kf_ingest_authority_grant WHERE grant_id = $1")
        .bind(blocked_grant)
        .execute(&admin_pool)
        .await
        .expect("remove unconsumed lock-timeout fixture");
    assert_source_absent(&admin_pool, &blocked_source).await;

    // Concurrent use of one unconsumed grant serializes at the grant row and returns one exact,
    // durable outcome to both callers.
    let concurrent_source = format!("concurrent-{}", Uuid::now_v7().simple());
    let concurrent_content = format!("concurrent bytes {concurrent_source}").into_bytes();
    let concurrent_hash = sha256_hex(&concurrent_content);
    let concurrent_grant = register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: Uuid::now_v7(),
            source_native_id: &concurrent_source,
            content_sha256: &concurrent_hash,
            content: &concurrent_content,
            nonce: &unique_nonce("concurrent"),
            store_root: "root-a",
        },
    )
    .await;
    let store_a = Arc::clone(&runtime_store);
    let store_b = Arc::clone(&runtime_store);
    let (outcome_a, outcome_b) = tokio::join!(
        store_a.ingest_authorized(concurrent_grant),
        store_b.ingest_authorized(concurrent_grant),
    );
    let outcome_a = outcome_a.expect("first concurrent authority call");
    let outcome_b = outcome_b.expect("second concurrent authority call");
    assert_eq!(outcome_a, outcome_b);
    let durable = query(
        "SELECT pg_catalog.count(DISTINCT occurrence.occurrence_id) AS occurrences,
                pg_catalog.count(DISTINCT version.version_id) AS versions,
                pg_catalog.count(DISTINCT blob.blob_id) AS blobs
           FROM public.artifact_occurrence AS occurrence
           JOIN public.artifact_version AS version
             ON version.occurrence_id = occurrence.occurrence_id
           JOIN public.raw_blob AS blob ON blob.blob_id = version.blob_id
          WHERE occurrence.source_system_id = 'acceptance'
            AND occurrence.source_native_id = $1",
    )
    .bind(&concurrent_source)
    .fetch_one(&admin_pool)
    .await
    .expect("inspect concurrent durable result");
    assert_eq!(durable.try_get::<i64, _>("occurrences").unwrap(), 1);
    assert_eq!(durable.try_get::<i64, _>("versions").unwrap(), 1);
    assert_eq!(durable.try_get::<i64, _>("blobs").unwrap(), 1);

    // Local replay ledgers are intentionally per-root. Two independently verified capabilities
    // with the same issuer/key/nonce therefore reach PostgreSQL, where global uniqueness admits
    // exactly one and returns a uniform 42501 for the conflicting second registration.
    let replay_nonce = unique_nonce("global-replay");
    let replay_content_a = b"global replay root A exact bytes".to_vec();
    let replay_content_b = b"global replay root B exact bytes".to_vec();
    let replay_hash_a = sha256_hex(&replay_content_a);
    let replay_hash_b = sha256_hex(&replay_content_b);
    let replay_grant_a = Uuid::now_v7();
    register_authority(
        &authority_store,
        &fixture_base,
        AuthoritySpec {
            project_id: project_a,
            grant_id: replay_grant_a,
            source_native_id: "global-replay-a",
            content_sha256: &replay_hash_a,
            content: &replay_content_a,
            nonce: &replay_nonce,
            store_root: "root-a",
        },
    )
    .await;
    let replay_authority_b = consume_authority(
        &fixture_base,
        AuthoritySpec {
            project_id: project_b,
            grant_id: Uuid::now_v7(),
            source_native_id: "global-replay-b",
            content_sha256: &replay_hash_b,
            content: &replay_content_b,
            nonce: &replay_nonce,
            store_root: "root-b",
        },
    );
    let replay_error = authority_store
        .register_ingest_authority(&replay_authority_b)
        .await
        .expect_err("global issuer/key/nonce replay must be denied");
    assert_anyhow_sqlstate(&replay_error, "42501");
    let replay_count = query(
        "SELECT pg_catalog.count(*) AS n
           FROM public.kf_ingest_authority_grant
          WHERE issuer = $1 AND key_id = $2 AND nonce = $3",
    )
    .bind(ISSUER)
    .bind(KEY_ID)
    .bind(&replay_nonce)
    .fetch_one(&admin_pool)
    .await
    .expect("count globally unique replay key");
    assert_eq!(replay_count.try_get::<i64, _>("n").unwrap(), 1);

    fs::remove_dir_all(&fixture_base).expect("remove local authority acceptance fixtures");
}
