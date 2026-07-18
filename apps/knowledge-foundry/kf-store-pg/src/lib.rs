//! Tenant-scoped PostgreSQL intake boundary for Knowledge Foundry.
//!
//! Every domain query owns a transaction and installs one project UUID with a bound,
//! transaction-local `set_config` call. Blob deduplication, occurrence identity, and version
//! lineage are exposed only as one atomic operation backed by the narrow
//! `public.kf_ingest_observation` database function. The pool and transaction never escape this
//! crate.
//!
//! `project_id` remains a scope claim, not authentication. It must come from the separately
//! verified authority boundary; possession of runtime database credentials is not tenant
//! authority. Until that wiring and the disposable DB acceptance exist, this crate remains HOLD.
//!
//! This boundary still requires the ignored disposable-database acceptance test before release;
//! local unit tests only prove validation and the shape of the SQL contract.
use anyhow::{bail, Context, Result};
use async_trait::async_trait;
use sqlx_core::{
    pool::{Pool, PoolOptions},
    query::query,
    row::Row,
};
use sqlx_postgres::{PgRow, Postgres};
use uuid::Uuid;

const MAX_RAW_BLOB_BYTES: i64 = 256 * 1024 * 1024;
const MAX_SOURCE_SYSTEM_BYTES: usize = 128;
const MAX_SOURCE_NATIVE_BYTES: usize = 4096;
const MAX_SOURCE_REVISION_BYTES: usize = 4096;
const MAX_STORAGE_URI_BYTES: usize = 4096;

// The setting name is a constant and the value is always a bound parameter. `true` makes the
// setting transaction-local, so a pooled connection cannot retain tenant state after commit or
// rollback.
const SET_LOCAL_PROJECT_SQL: &str =
    "SELECT pg_catalog.set_config('app.project_ids', $1, true) AS project_context,
            pg_catalog.set_config('lock_timeout', '5s', true) AS lock_timeout,
            pg_catalog.set_config('statement_timeout', '30s', true) AS statement_timeout";
const SET_LOCAL_RUNTIME_ROLE_SQL: &str = "SET LOCAL ROLE kf_runtime";
const VERIFY_RUNTIME_ROLE_SQL: &str = "SELECT login.rolname AS login_name,
            CURRENT_USER::text AS current_name,
            SESSION_USER::text AS session_name,
            login.rolcanlogin AS login_can_login,
            login.rolsuper AS login_super,
            login.rolbypassrls AS login_bypassrls,
            login.rolinherit AS login_inherit,
            login.rolcreatedb AS login_createdb,
            login.rolcreaterole AS login_createrole,
            login.rolreplication AS login_replication,
            runtime.rolsuper AS runtime_super,
            runtime.rolbypassrls AS runtime_bypassrls,
            runtime.rolcanlogin AS runtime_can_login,
            runtime.rolinherit AS runtime_inherit,
            runtime.rolcreatedb AS runtime_createdb,
            runtime.rolcreaterole AS runtime_createrole,
            runtime.rolreplication AS runtime_replication,
            pg_catalog.has_schema_privilege(runtime.oid, 'public', 'CREATE')
                AS runtime_can_create_public,
            pg_catalog.has_database_privilege(
                runtime.oid, pg_catalog.current_database(), 'CREATE'
            ) AS runtime_can_create_database_objects,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_database AS database
                 WHERE database.datname = pg_catalog.current_database()
                   AND database.datdba = runtime.oid
            ) AS runtime_owns_database,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_namespace AS namespace
                 WHERE namespace.nspname = 'public'
                   AND namespace.nspowner = runtime.oid
            ) AS runtime_owns_public_schema,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                 WHERE namespace.nspname = 'public'
                   AND relation.relowner = runtime.oid
            ) AS runtime_owns_public_relations,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = login.oid
                   AND membership.roleid = runtime.oid
                   AND NOT membership.admin_option
                   AND NOT membership.inherit_option
                   AND membership.set_option
            ) AND NOT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = login.oid
                   AND membership.roleid = runtime.oid
                   AND (
                       membership.admin_option
                       OR membership.inherit_option
                       OR NOT membership.set_option
                   )
            ) AS runtime_member,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = login.oid
                   AND membership.roleid <> runtime.oid
            ) AS login_has_other_memberships,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = runtime.oid
            ) AS runtime_has_other_memberships,
            pg_catalog.has_schema_privilege(login.oid, 'public', 'CREATE')
                AS login_can_create_public,
            pg_catalog.has_database_privilege(
                login.oid, pg_catalog.current_database(), 'CREATE'
            ) AS login_can_create_database_objects,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_database AS database
                 WHERE database.datname = pg_catalog.current_database()
                   AND database.datdba = login.oid
            ) AS login_owns_database,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_namespace AS namespace
                 WHERE namespace.nspname = 'public'
                   AND namespace.nspowner = login.oid
            ) AS login_owns_public_schema,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                 WHERE namespace.nspname = 'public'
                   AND relation.relowner = login.oid
            ) AS login_owns_public_relations,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          relation.relacl,
                          pg_catalog.acldefault('r', relation.relowner)
                      )
                  ) AS relation_acl
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                   AND relation_acl.grantee IN (login.oid, 0)
            ) AS login_has_direct_relation_acl,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_attribute AS attribute
                  JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS column_acl
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                   AND column_acl.grantee IN (login.oid, runtime.oid, 0)
            ) AS unexpected_column_acl,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          relation.relacl,
                          pg_catalog.acldefault('r', relation.relowner)
                      )
                  ) AS relation_acl
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                   AND (
                       relation_acl.grantee = 0
                       OR (
                           relation_acl.grantee = runtime.oid
                           AND (
                               relation_acl.privilege_type <> 'SELECT'
                               OR relation_acl.is_grantable
                               OR relation.relname NOT IN (
                                   'raw_blob', 'artifact_occurrence', 'artifact_version',
                                   'logical_document', 'ingestion_run', 'event_ledger',
                                   'project', 'embedding_profile'
                               )
                           )
                       )
                   )
            ) AS runtime_has_forbidden_relation_acl,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          relation.relacl,
                          pg_catalog.acldefault('s', relation.relowner)
                      )
                  ) AS sequence_acl
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind = 'S'
                   AND sequence_acl.grantee IN (login.oid, runtime.oid, 0)
            ) AS unexpected_sequence_acl,
            EXISTS (
                SELECT 1
                  FROM (VALUES
                       ('artifact_occurrence'), ('artifact_version'), ('logical_document'),
                       ('ingestion_run'), ('event_ledger'), ('raw_blob'), ('project')
                  ) AS expected(table_name)
                 WHERE NOT EXISTS (
                     SELECT 1
                       FROM pg_catalog.pg_class AS relation
                       JOIN pg_catalog.pg_namespace AS namespace
                         ON namespace.oid = relation.relnamespace
                      WHERE namespace.nspname = 'public'
                        AND relation.relname = expected.table_name
                        AND relation.relkind IN ('r', 'p')
                        AND relation.relrowsecurity
                        AND relation.relforcerowsecurity
                 )
            ) AS scoped_rls_drift
       FROM pg_catalog.pg_roles AS login
       JOIN pg_catalog.pg_roles AS runtime ON runtime.rolname = 'kf_runtime'
      WHERE login.rolname = SESSION_USER";
const VERIFY_DISPOSABLE_ADMIN_SQL: &str = "SELECT role.rolname AS login_name,
            CURRENT_USER::text AS current_name,
            SESSION_USER::text AS session_name,
            role.rolsuper AS login_super,
            pg_catalog.current_database()::text AS database_name,
            pg_catalog.host(pg_catalog.inet_server_addr()) AS server_address,
            pg_catalog.pg_is_in_recovery() AS in_recovery,
            (
                SELECT pg_catalog.count(*)
                  FROM pg_catalog.pg_database AS database
                 WHERE database.datname NOT IN (
                     'template0', 'template1', 'postgres', pg_catalog.current_database()
                 )
            ) AS other_user_databases
       FROM pg_catalog.pg_roles AS role
      WHERE role.rolname = SESSION_USER";
const INGEST_SQL: &str = "SELECT blob_id, occurrence_id, version_id, parent_version_id,
            blob_created, occurrence_created, version_created
       FROM public.kf_ingest_observation($1,$2,$3,$4,$5,$6,$7,$8,$9)";

fn disposable_admin_row_is_safe(
    verification: &PgRow,
    expected_database: &str,
) -> std::result::Result<bool, sqlx_core::Error> {
    let login_name: String = verification.try_get("login_name")?;
    let current_name: String = verification.try_get("current_name")?;
    let session_name: String = verification.try_get("session_name")?;
    let actual_database: String = verification.try_get("database_name")?;
    let server_address: Option<String> = verification.try_get("server_address")?;
    let in_recovery: bool = verification.try_get("in_recovery")?;
    let is_superuser: bool = verification.try_get("login_super")?;
    let other_user_databases: i64 = verification.try_get("other_user_databases")?;
    let server_is_loopback = server_address
        .as_deref()
        .and_then(|address| address.parse::<std::net::IpAddr>().ok())
        .is_some_and(|address| address.is_loopback());
    Ok(login_name == session_name
        && current_name == session_name
        && actual_database == expected_database
        && server_is_loopback
        && !in_recovery
        && is_superuser
        && other_user_databases == 0)
}

fn runtime_role_row_is_safe(role: &PgRow) -> std::result::Result<(bool, String), sqlx_core::Error> {
    let role_name: String = role.try_get("login_name")?;
    let current_name: String = role.try_get("current_name")?;
    let session_name: String = role.try_get("session_name")?;
    let login_can_login: bool = role.try_get("login_can_login")?;
    let is_superuser: bool = role.try_get("login_super")?;
    let bypasses_rls: bool = role.try_get("login_bypassrls")?;
    let inherits_privileges: bool = role.try_get("login_inherit")?;
    let can_create_databases: bool = role.try_get("login_createdb")?;
    let can_create_roles: bool = role.try_get("login_createrole")?;
    let can_replicate: bool = role.try_get("login_replication")?;
    let runtime_superuser: bool = role.try_get("runtime_super")?;
    let runtime_bypasses_rls: bool = role.try_get("runtime_bypassrls")?;
    let runtime_can_login: bool = role.try_get("runtime_can_login")?;
    let runtime_inherits_privileges: bool = role.try_get("runtime_inherit")?;
    let runtime_can_create_databases: bool = role.try_get("runtime_createdb")?;
    let runtime_can_create_roles: bool = role.try_get("runtime_createrole")?;
    let runtime_can_replicate: bool = role.try_get("runtime_replication")?;
    let runtime_can_create_public: bool = role.try_get("runtime_can_create_public")?;
    let runtime_can_create_database_objects: bool =
        role.try_get("runtime_can_create_database_objects")?;
    let runtime_owns_database: bool = role.try_get("runtime_owns_database")?;
    let runtime_owns_public_schema: bool = role.try_get("runtime_owns_public_schema")?;
    let runtime_owns_public_relations: bool = role.try_get("runtime_owns_public_relations")?;
    let runtime_member: bool = role.try_get("runtime_member")?;
    let login_has_other_memberships: bool = role.try_get("login_has_other_memberships")?;
    let runtime_has_other_memberships: bool = role.try_get("runtime_has_other_memberships")?;
    let login_can_create_public: bool = role.try_get("login_can_create_public")?;
    let login_can_create_database_objects: bool =
        role.try_get("login_can_create_database_objects")?;
    let login_owns_database: bool = role.try_get("login_owns_database")?;
    let login_owns_public_schema: bool = role.try_get("login_owns_public_schema")?;
    let login_owns_public_relations: bool = role.try_get("login_owns_public_relations")?;
    let login_has_direct_relation_acl: bool = role.try_get("login_has_direct_relation_acl")?;
    let unexpected_column_acl: bool = role.try_get("unexpected_column_acl")?;
    let runtime_has_forbidden_relation_acl: bool =
        role.try_get("runtime_has_forbidden_relation_acl")?;
    let unexpected_sequence_acl: bool = role.try_get("unexpected_sequence_acl")?;
    let scoped_rls_drift: bool = role.try_get("scoped_rls_drift")?;
    let safe = current_name == session_name
        && login_can_login
        && !is_superuser
        && !bypasses_rls
        && !inherits_privileges
        && !can_create_databases
        && !can_create_roles
        && !can_replicate
        && runtime_member
        && !runtime_has_other_memberships
        && !runtime_superuser
        && !runtime_bypasses_rls
        && !runtime_can_login
        && !runtime_inherits_privileges
        && !runtime_can_create_databases
        && !runtime_can_create_roles
        && !runtime_can_replicate
        && !runtime_can_create_public
        && !runtime_can_create_database_objects
        && !runtime_owns_database
        && !runtime_owns_public_schema
        && !runtime_owns_public_relations
        && !login_has_other_memberships
        && !login_can_create_public
        && !login_can_create_database_objects
        && !login_owns_database
        && !login_owns_public_schema
        && !login_owns_public_relations
        && !login_has_direct_relation_acl
        && !unexpected_column_acl
        && !runtime_has_forbidden_relation_acl
        && !unexpected_sequence_acl
        && !scoped_rls_drift;
    Ok((safe, role_name))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawBlob {
    pub blob_id: Uuid,
    pub sha256: String,
    pub byte_size: i64,
    pub storage_uri: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Occurrence {
    pub occurrence_id: Uuid,
    pub project_id: Uuid,
    pub source_system_id: String,
    pub source_native_id: String,
    pub blob_id: Uuid,
}

/// Complete input for the one supported intake write boundary.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestObservation {
    pub occurrence_id: Uuid,
    pub version_id: Uuid,
    pub project_id: Uuid,
    pub source_system_id: String,
    pub source_native_id: String,
    pub source_revision_key: String,
    pub sha256: String,
    pub byte_size: i64,
    pub storage_uri: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestOutcome {
    pub blob_id: Uuid,
    pub occurrence_id: Uuid,
    pub version_id: Uuid,
    pub parent_version_id: Option<Uuid>,
    pub blob_created: bool,
    pub occurrence_created: bool,
    pub version_created: bool,
}

/// Tenant-safe MetaStore surface. There is deliberately no independent blob-upsert,
/// occurrence-insert, raw pool, connection, or transaction accessor.
#[async_trait]
pub trait MetaStore {
    async fn ingest_observation(&self, input: &IngestObservation) -> Result<IngestOutcome>;
    async fn blob_by_hash(&self, project_id: Uuid, sha256: &str) -> Result<Option<RawBlob>>;
    async fn find_occurrence(
        &self,
        project_id: Uuid,
        source_system_id: &str,
        source_native_id: &str,
    ) -> Result<Option<Occurrence>>;
    async fn occurrences_for_blob(&self, project_id: Uuid, blob_id: Uuid) -> Result<i64>;
}

pub struct PostgresMetaStore {
    pool: Pool<Postgres>,
}

impl PostgresMetaStore {
    /// Production-shaped constructor. It refuses an administrative, owner, superuser, or
    /// BYPASSRLS connection. On PostgreSQL 16, the login must be a NOINHERIT member of only
    /// `kf_runtime`, granted with ADMIN/INHERIT false and SET true. Every new physical connection
    /// repeats admission before any domain transaction can perform the transaction-local switch.
    pub async fn connect_runtime(url: &str) -> Result<Self> {
        let pool = PoolOptions::<Postgres>::new()
            .max_connections(4)
            .after_connect(|connection, _metadata| {
                Box::pin(async move {
                    let role = query(VERIFY_RUNTIME_ROLE_SQL)
                        .fetch_optional(&mut *connection)
                        .await?
                        .ok_or_else(|| {
                            sqlx_core::Error::Protocol(
                                "current PostgreSQL role is absent from pg_roles".to_owned(),
                            )
                        })?;
                    let (safe, role_name) = runtime_role_row_is_safe(&role)?;
                    if !safe {
                        return Err(sqlx_core::Error::Protocol(format!(
                            "PostgreSQL request pool login {role_name} failed the runtime admission gate"
                        )));
                    }
                    Ok(())
                })
            })
            .connect(url)
            .await?;
        Ok(Self { pool })
    }

    /// Test-only administrative constructor. The URL guard makes accidental connection to a
    /// non-loopback or non-disposable database fail before any network operation.
    pub async fn connect_for_disposable_admin_test(
        url: &str,
        confirmation: &str,
        cluster_confirmation: &str,
    ) -> Result<Self> {
        if confirmation != "MAWORLD_DISPOSABLE_DB_CONFIRMED" {
            bail!("explicit disposable-database confirmation is required");
        }
        if cluster_confirmation != "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER" {
            bail!("explicit disposable-cluster confirmation is required");
        }
        let expected_database = validate_disposable_database_url(url)?;
        let expected_database_for_connections = expected_database.clone();
        let pool = PoolOptions::<Postgres>::new()
            .max_connections(2)
            .after_connect(move |connection, _metadata| {
                let expected_database = expected_database_for_connections.clone();
                Box::pin(async move {
                    let verification = query(VERIFY_DISPOSABLE_ADMIN_SQL)
                        .fetch_optional(&mut *connection)
                        .await?
                        .ok_or_else(|| {
                            sqlx_core::Error::Protocol(
                                "disposable PostgreSQL administrator is absent from pg_roles"
                                    .to_owned(),
                            )
                        })?;
                    if !disposable_admin_row_is_safe(&verification, &expected_database)? {
                        return Err(sqlx_core::Error::Protocol(
                            "disposable acceptance target failed the connection safety gate"
                                .to_owned(),
                        ));
                    }
                    Ok(())
                })
            })
            .connect(url)
            .await?;
        Ok(Self { pool })
    }
}

#[async_trait]
impl MetaStore for PostgresMetaStore {
    async fn ingest_observation(&self, input: &IngestObservation) -> Result<IngestOutcome> {
        validate_ingest(input)?;

        let mut transaction = self.pool.begin().await?;
        set_local_project(&mut transaction, input.project_id).await?;
        let row = query(INGEST_SQL)
            .bind(input.project_id)
            .bind(input.occurrence_id)
            .bind(input.version_id)
            .bind(&input.source_system_id)
            .bind(&input.source_native_id)
            .bind(&input.source_revision_key)
            .bind(&input.sha256)
            .bind(input.byte_size)
            .bind(&input.storage_uri)
            .fetch_one(&mut *transaction)
            .await
            .context("atomically ingest blob occurrence")?;
        let outcome = IngestOutcome {
            blob_id: row.try_get("blob_id")?,
            occurrence_id: row.try_get("occurrence_id")?,
            version_id: row.try_get("version_id")?,
            parent_version_id: row.try_get("parent_version_id")?,
            blob_created: row.try_get("blob_created")?,
            occurrence_created: row.try_get("occurrence_created")?,
            version_created: row.try_get("version_created")?,
        };
        transaction.commit().await?;
        Ok(outcome)
    }

    async fn blob_by_hash(&self, project_id: Uuid, sha256: &str) -> Result<Option<RawBlob>> {
        validate_project_id(project_id)?;
        validate_sha256(sha256)?;
        let mut transaction = self.pool.begin().await?;
        set_local_project(&mut transaction, project_id).await?;
        let row = query(
            "SELECT blob_id, sha256, byte_size, storage_uri
               FROM public.raw_blob
              WHERE sha256=$1",
        )
        .bind(sha256)
        .fetch_optional(&mut *transaction)
        .await?;
        let blob = row
            .map(|row| {
                Ok::<RawBlob, sqlx_core::Error>(RawBlob {
                    blob_id: row.try_get("blob_id")?,
                    sha256: row.try_get("sha256")?,
                    byte_size: row.try_get("byte_size")?,
                    storage_uri: row.try_get("storage_uri")?,
                })
            })
            .transpose()?;
        transaction.commit().await?;
        Ok(blob)
    }

    async fn find_occurrence(
        &self,
        project_id: Uuid,
        source_system_id: &str,
        source_native_id: &str,
    ) -> Result<Option<Occurrence>> {
        validate_project_id(project_id)?;
        validate_source_key(source_system_id, source_native_id)?;
        let mut transaction = self.pool.begin().await?;
        set_local_project(&mut transaction, project_id).await?;
        let row = query(
            "SELECT occurrence_id, project_id, source_system_id, source_native_id, blob_id
               FROM public.artifact_occurrence
              WHERE project_id=$1 AND source_system_id=$2 AND source_native_id=$3",
        )
        .bind(project_id)
        .bind(source_system_id)
        .bind(source_native_id)
        .fetch_optional(&mut *transaction)
        .await?;
        let occurrence = row
            .map(|row| {
                Ok::<Occurrence, sqlx_core::Error>(Occurrence {
                    occurrence_id: row.try_get("occurrence_id")?,
                    project_id: row.try_get("project_id")?,
                    source_system_id: row.try_get("source_system_id")?,
                    source_native_id: row.try_get("source_native_id")?,
                    blob_id: row.try_get("blob_id")?,
                })
            })
            .transpose()?;
        transaction.commit().await?;
        Ok(occurrence)
    }

    async fn occurrences_for_blob(&self, project_id: Uuid, blob_id: Uuid) -> Result<i64> {
        validate_project_id(project_id)?;
        if blob_id.is_nil() {
            bail!("blob_id must not be nil");
        }
        let mut transaction = self.pool.begin().await?;
        set_local_project(&mut transaction, project_id).await?;
        let row = query(
            "SELECT count(*) AS n
               FROM public.artifact_occurrence
              WHERE project_id=$1 AND blob_id=$2",
        )
        .bind(project_id)
        .bind(blob_id)
        .fetch_one(&mut *transaction)
        .await?;
        let count = row.try_get::<i64, _>("n")?;
        transaction.commit().await?;
        Ok(count)
    }
}

async fn set_local_project(
    transaction: &mut sqlx_core::transaction::Transaction<'_, Postgres>,
    project_id: Uuid,
) -> Result<()> {
    validate_project_id(project_id)?;
    let expected = project_id.to_string();
    query(SET_LOCAL_RUNTIME_ROLE_SQL)
        .execute(&mut **transaction)
        .await
        .context("set transaction-local runtime role")?;
    let row = query(SET_LOCAL_PROJECT_SQL)
        .bind(&expected)
        .fetch_one(&mut **transaction)
        .await
        .context("set transaction-local project context")?;
    let applied: String = row.try_get("project_context")?;
    if applied != expected {
        bail!("PostgreSQL did not apply the requested project context");
    }
    Ok(())
}

fn validate_ingest(input: &IngestObservation) -> Result<()> {
    validate_project_id(input.project_id)?;
    if input.occurrence_id.is_nil() {
        bail!("occurrence_id must not be nil");
    }
    if input.version_id.is_nil() {
        bail!("version_id must not be nil");
    }
    validate_source_key(&input.source_system_id, &input.source_native_id)?;
    validate_text(
        &input.source_revision_key,
        MAX_SOURCE_REVISION_BYTES,
        "source_revision_key",
    )?;
    validate_sha256(&input.sha256)?;
    if !(0..=MAX_RAW_BLOB_BYTES).contains(&input.byte_size) {
        bail!("byte_size is outside the supported intake bound");
    }
    validate_text(&input.storage_uri, MAX_STORAGE_URI_BYTES, "storage_uri")?;
    Ok(())
}

fn validate_project_id(project_id: Uuid) -> Result<()> {
    if project_id.is_nil() {
        bail!("project_id must not be nil");
    }
    Ok(())
}

fn validate_sha256(sha256: &str) -> Result<()> {
    if sha256.len() != 64
        || !sha256
            .as_bytes()
            .iter()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
    {
        bail!("sha256 must be exactly 64 lowercase hexadecimal characters");
    }
    Ok(())
}

fn validate_source_key(source_system_id: &str, source_native_id: &str) -> Result<()> {
    validate_text(
        source_system_id,
        MAX_SOURCE_SYSTEM_BYTES,
        "source_system_id",
    )?;
    validate_text(
        source_native_id,
        MAX_SOURCE_NATIVE_BYTES,
        "source_native_id",
    )?;
    Ok(())
}

fn validate_text(value: &str, maximum_bytes: usize, field: &str) -> Result<()> {
    if value.is_empty()
        || value.trim() != value
        || value.len() > maximum_bytes
        || value.chars().any(char::is_control)
    {
        bail!("{field} must be unpadded, control-free, and at most {maximum_bytes} bytes");
    }
    Ok(())
}

fn validate_disposable_database_url(database_url: &str) -> Result<String> {
    let url = sqlx_core::Url::parse(database_url).context("invalid PostgreSQL test URL")?;
    if !matches!(url.scheme(), "postgres" | "postgresql")
        || url.query().is_some()
        || url.fragment().is_some()
    {
        bail!("disposable PostgreSQL URL must use a plain postgres scheme without overrides");
    }
    let host = url.host_str().context("PostgreSQL test URL has no host")?;
    if !matches!(host, "localhost" | "127.0.0.1" | "::1") {
        bail!("disposable PostgreSQL test database must be loopback-only");
    }
    let database = url.path().trim_start_matches('/');
    let prefix = "maworld_rls_test_";
    let suffix = database.strip_prefix(prefix).unwrap_or_default();
    if suffix.is_empty()
        || !suffix
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        bail!(
            "disposable PostgreSQL database name must be maworld_rls_test_ plus a safe identifier"
        );
    }
    Ok(database.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    const ROLE_MIGRATION: &str = include_str!("../../schema/002_rls_roles.sql");
    const ATOMIC_MIGRATION: &str = include_str!("../../schema/003_atomic_intake.sql");

    fn valid_ingest() -> IngestObservation {
        IngestObservation {
            occurrence_id: Uuid::now_v7(),
            version_id: Uuid::now_v7(),
            project_id: Uuid::now_v7(),
            source_system_id: "drive".into(),
            source_native_id: "document-1".into(),
            source_revision_key: "revision-1".into(),
            sha256: "a".repeat(64),
            byte_size: 27,
            storage_uri: "cas://sha256/aa".into(),
        }
    }

    #[test]
    fn ingest_validation_is_strict_and_bounded() {
        assert!(validate_ingest(&valid_ingest()).is_ok());

        let mut input = valid_ingest();
        input.project_id = Uuid::nil();
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.occurrence_id = Uuid::nil();
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.version_id = Uuid::nil();
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.byte_size = MAX_RAW_BLOB_BYTES + 1;
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.source_system_id = "x".repeat(MAX_SOURCE_SYSTEM_BYTES + 1);
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.storage_uri = "cas://bad\0uri".into();
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.source_native_id = " padded".into();
        assert!(validate_ingest(&input).is_err());
        let mut input = valid_ingest();
        input.source_revision_key = "revision\n2".into();
        assert!(validate_ingest(&input).is_err());
    }

    #[test]
    fn sha256_validation_is_strict() {
        assert!(validate_sha256(&"a".repeat(64)).is_ok());
        for invalid in ["", "abc", &"A".repeat(64), &"g".repeat(64)] {
            assert!(validate_sha256(invalid).is_err());
        }
    }

    #[test]
    fn project_context_is_bound_and_transaction_local() {
        assert_eq!(SET_LOCAL_RUNTIME_ROLE_SQL, "SET LOCAL ROLE kf_runtime");
        assert!(SET_LOCAL_PROJECT_SQL.contains("set_config('app.project_ids', $1, true)"));
        assert!(SET_LOCAL_PROJECT_SQL.contains("set_config('lock_timeout', '5s', true)"));
        assert!(SET_LOCAL_PROJECT_SQL.contains("set_config('statement_timeout', '30s', true)"));
        assert!(!SET_LOCAL_PROJECT_SQL.contains("SET LOCAL app.project_ids ="));
        assert_eq!(INGEST_SQL.matches('$').count(), 9);
    }

    #[test]
    fn runtime_role_verification_rejects_privilege_drift() {
        for required in [
            "CURRENT_USER::text AS current_name",
            "SESSION_USER::text AS session_name",
            "WHERE login.rolname = SESSION_USER",
            "login.rolcanlogin",
            "login.rolsuper",
            "login.rolbypassrls",
            "login.rolinherit",
            "login.rolcreatedb",
            "login.rolcreaterole",
            "login.rolreplication",
            "runtime.rolsuper",
            "runtime.rolbypassrls",
            "runtime.rolcanlogin",
            "runtime.rolinherit",
            "runtime.rolcreatedb",
            "runtime.rolcreaterole",
            "runtime.rolreplication",
            "runtime_can_create_public",
            "runtime_can_create_database_objects",
            "runtime_owns_database",
            "runtime_owns_public_schema",
            "runtime_owns_public_relations",
            "NOT membership.admin_option",
            "NOT membership.inherit_option",
            "membership.set_option",
            "login_has_other_memberships",
            "runtime_has_other_memberships",
            "login_can_create_public",
            "login_can_create_database_objects",
            "login_owns_database",
            "login_owns_public_schema",
            "login_owns_public_relations",
            "login_has_direct_relation_acl",
            "pg_catalog.pg_attribute",
            "unexpected_column_acl",
            "runtime_has_forbidden_relation_acl",
            "unexpected_sequence_acl",
            "relation.relkind = 'S'",
            "relation_acl.is_grantable",
            "embedding_profile",
            "scoped_rls_drift",
            "relation.relrowsecurity",
            "relation.relforcerowsecurity",
            "pg_catalog.aclexplode",
        ] {
            assert!(VERIFY_RUNTIME_ROLE_SQL.contains(required));
        }
    }

    #[test]
    fn atomic_migration_has_narrow_definer_boundary() {
        for required in [
            "SECURITY DEFINER",
            "SET search_path = pg_catalog",
            "OWNER TO kf_ingest_owner",
            "REVOKE ALL ON FUNCTION public.kf_ingest_observation",
            "GRANT EXECUTE ON FUNCTION public.kf_ingest_observation",
            "cardinality(v_allowed_projects) <> 1",
            "ON CONFLICT (sha256) DO NOTHING",
            "ON CONFLICT (project_id, source_system_id, source_native_id) DO NOTHING",
            "ON CONFLICT (occurrence_id, source_revision_key) DO NOTHING",
            "sha256 already exists with conflicting immutable metadata",
            "source revision already exists for a different blob",
            "CREATE POLICY blob_via_authorized_version",
            "JOIN public.artifact_occurrence AS visible_occurrence",
            "version lineage has multiple tails",
            "version lineage has no tail",
            "child_version.parent_version_id = tail_version.version_id",
            "CONSTRAINT artifact_version_parent_same_occurrence_fk",
            "FOREIGN KEY (parent_version_id, occurrence_id)",
            "p_source_system_id <> pg_catalog.btrim(p_source_system_id)",
            "p_source_revision_key ~ '[[:cntrl:]]'",
        ] {
            assert!(
                ATOMIC_MIGRATION.contains(required),
                "missing SQL guard: {required}"
            );
        }
    }

    #[test]
    fn runtime_cannot_directly_insert_intake_identity_rows() {
        assert!(ROLE_MIGRATION
            .contains("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_runtime"));
        assert!(ROLE_MIGRATION
            .contains("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM kf_runtime"));
        assert!(ROLE_MIGRATION.contains("REVOKE CREATE ON SCHEMA public FROM PUBLIC"));
        assert!(ROLE_MIGRATION.contains("REVOKE CREATE ON DATABASE %I FROM PUBLIC"));
        assert!(ROLE_MIGRATION.contains("requires a dedicated migration superuser"));
        assert!(ATOMIC_MIGRATION.contains("requires a dedicated migration superuser"));
        assert!(ROLE_MIGRATION.contains("kf_runtime must not own the current database"));
        assert!(ROLE_MIGRATION.contains("kf_runtime must not own schema public"));
        assert!(ROLE_MIGRATION.contains("artifact_occurrence ENABLE ROW LEVEL SECURITY"));
        assert!(ROLE_MIGRATION.contains("kf_runtime must not own relations in schema public"));
        assert!(ROLE_MIGRATION.contains("runtime_role.oid = membership.member"));
        assert!(ROLE_MIGRATION.contains("kf_runtime must not inherit or SET ROLE"));
        assert!(!ROLE_MIGRATION.contains("GRANT INSERT ON"));
        for role_guard in [
            "NOLOGIN",
            "NOSUPERUSER",
            "NOCREATEDB",
            "NOCREATEROLE",
            "NOREPLICATION",
            "NOBYPASSRLS",
            "NOINHERIT",
        ] {
            assert!(ROLE_MIGRATION.contains(role_guard));
            assert!(ATOMIC_MIGRATION.contains(role_guard));
        }
        assert!(ATOMIC_MIGRATION.contains("REVOKE kf_ingest_owner FROM kf_runtime"));
        assert!(ATOMIC_MIGRATION.contains("membership.member, membership.roleid"));
        assert!(ATOMIC_MIGRATION.contains("no incoming or outgoing role memberships"));
        assert!(ATOMIC_MIGRATION
            .contains("REVOKE ALL PRIVILEGES ON public.raw_blob, public.artifact_occurrence"));
        assert!(ATOMIC_MIGRATION.contains("GRANT CREATE ON SCHEMA public TO kf_ingest_owner"));
        assert!(ATOMIC_MIGRATION.contains("REVOKE CREATE ON SCHEMA public FROM kf_ingest_owner"));
    }

    #[test]
    fn disposable_database_guard_rejects_remote_and_generic_targets() {
        assert_eq!(
            validate_disposable_database_url(
                "postgres://user:pass@127.0.0.1/maworld_rls_test_case"
            )
            .unwrap(),
            "maworld_rls_test_case"
        );
        assert!(validate_disposable_database_url(
            "postgres://user:pass@db.example/maworld_rls_test_case"
        )
        .is_err());
        assert!(
            validate_disposable_database_url("postgres://user:pass@localhost/maworld").is_err()
        );
        assert!(validate_disposable_database_url(
            "postgres://user:pass@localhost/maworld_rls_test_"
        )
        .is_err());
        assert!(validate_disposable_database_url(
            "postgres://user:pass@localhost/maworld_rls_test_case?options=-c%20role%3Dpostgres"
        )
        .is_err());
        for required in [
            "CURRENT_USER::text AS current_name",
            "SESSION_USER::text AS session_name",
            "current_database()::text AS database_name",
            "inet_server_addr()",
            "pg_is_in_recovery()",
            "other_user_databases",
            "'template0', 'template1', 'postgres', pg_catalog.current_database()",
        ] {
            assert!(VERIFY_DISPOSABLE_ADMIN_SQL.contains(required));
        }
    }
}
