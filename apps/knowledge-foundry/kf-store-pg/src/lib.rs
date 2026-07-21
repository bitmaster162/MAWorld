//! Tenant-scoped PostgreSQL intake boundary for Knowledge Foundry.
//!
//! A separately admitted registrar converts a consumed, signed `kf-intake` authority into an
//! opaque one-time database grant. Runtime credentials cannot create grants, select raw tenant
//! tables, or choose a project GUC. The SECURITY DEFINER boundary locks the grant, derives its
//! project and exact source/content binding server-side, and consumes it atomically with intake.
//!
//! This boundary still requires the ignored disposable-database acceptance test before release;
//! local unit tests only prove validation and the shape of the SQL contract.
use anyhow::{bail, Context, Result};
use async_trait::async_trait;
use kf_intake::authority::{self, StoredIngestAuthority};
use sqlx_core::{
    pool::{Pool, PoolOptions},
    query::query,
    row::Row,
};
use sqlx_postgres::{PgRow, Postgres};
use std::sync::{Arc, OnceLock};
use tokio::sync::Semaphore;
use uuid::Uuid;

const MAX_RAW_BLOB_BYTES: i64 = 256 * 1024 * 1024;
const MAX_SOURCE_SYSTEM_BYTES: usize = 128;
const MAX_SOURCE_NATIVE_BYTES: usize = 4096;
const MAX_CONCURRENT_CAS_REVALIDATIONS: usize = 2;

fn cas_revalidation_semaphore() -> Arc<Semaphore> {
    static SEMAPHORE: OnceLock<Arc<Semaphore>> = OnceLock::new();
    Arc::clone(SEMAPHORE.get_or_init(|| Arc::new(Semaphore::new(MAX_CONCURRENT_CAS_REVALIDATIONS))))
}

const SET_LOCAL_RUNTIME_ROLE_SQL: &str = "SET LOCAL ROLE kf_runtime";
const SET_LOCAL_REGISTRAR_ROLE_SQL: &str = "SET LOCAL ROLE kf_authority_registrar";
const SET_LOCAL_TIMEOUTS_SQL: &str = "SELECT
    pg_catalog.set_config('lock_timeout', '5s', true),
    pg_catalog.set_config('statement_timeout', '30s', true)";
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
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                 WHERE namespace.nspname = 'public'
                   AND function.proowner = runtime.oid
            ) AS runtime_owns_public_functions,
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
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                 WHERE namespace.nspname = 'public'
                   AND function.proowner = login.oid
            ) AS login_owns_public_functions,
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
                    AND relation_acl.grantee IN (runtime.oid, 0)
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
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          function.proacl,
                          pg_catalog.acldefault('f', function.proowner)
                      )
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function_acl.grantee IN (login.oid, 0)
            ) AS login_or_public_has_function_acl,
            NOT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          function.proacl,
                          pg_catalog.acldefault('f', function.proowner)
                      )
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function.oid = pg_catalog.to_regprocedure(
                       'public.kf_ingest_authorized(uuid,uuid)'
                   )
                   AND function_acl.grantee = runtime.oid
                   AND function_acl.privilege_type = 'EXECUTE'
                   AND NOT function_acl.is_grantable
            ) OR EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                      COALESCE(
                          function.proacl,
                          pg_catalog.acldefault('f', function.proowner)
                      )
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function_acl.grantee = runtime.oid
                   AND (
                       function.oid IS DISTINCT FROM pg_catalog.to_regprocedure(
                           'public.kf_ingest_authorized(uuid,uuid)'
                       )
                       OR function_acl.privilege_type <> 'EXECUTE'
                       OR function_acl.is_grantable
                   )
            ) AS runtime_function_acl_drift,
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
const VERIFY_REGISTRAR_ROLE_SQL: &str = "SELECT login.rolname AS login_name,
            CURRENT_USER::text AS current_name,
            SESSION_USER::text AS session_name,
            login.rolcanlogin AS login_can_login,
            login.rolsuper AS login_super,
            login.rolbypassrls AS login_bypassrls,
            login.rolinherit AS login_inherit,
            login.rolcreatedb AS login_createdb,
            login.rolcreaterole AS login_createrole,
            login.rolreplication AS login_replication,
            registrar.rolcanlogin AS registrar_can_login,
            registrar.rolsuper AS registrar_super,
            registrar.rolbypassrls AS registrar_bypassrls,
            registrar.rolinherit AS registrar_inherit,
            registrar.rolcreatedb AS registrar_createdb,
            registrar.rolcreaterole AS registrar_createrole,
            registrar.rolreplication AS registrar_replication,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = login.oid
                   AND membership.roleid = registrar.oid
                   AND NOT membership.admin_option
                   AND NOT membership.inherit_option
                   AND membership.set_option
            ) AS registrar_member,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = login.oid
                   AND membership.roleid <> registrar.oid
            ) AS login_has_other_memberships,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_auth_members AS membership
                 WHERE membership.member = registrar.oid
            ) AS registrar_has_memberships,
            pg_catalog.has_schema_privilege(login.oid, 'public', 'CREATE')
                AS login_can_create_public,
            pg_catalog.has_database_privilege(
                login.oid, pg_catalog.current_database(), 'CREATE'
            ) AS login_can_create_database_objects,
            pg_catalog.has_schema_privilege(registrar.oid, 'public', 'CREATE')
                AS registrar_can_create_public,
            pg_catalog.has_database_privilege(
                registrar.oid, pg_catalog.current_database(), 'CREATE'
            ) AS registrar_can_create_database_objects,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_database AS database
                 WHERE database.datname = pg_catalog.current_database()
                   AND database.datdba IN (login.oid, registrar.oid)
            ) AS authority_role_owns_database,
            EXISTS (
                SELECT 1 FROM pg_catalog.pg_namespace AS namespace
                 WHERE namespace.nspname = 'public'
                   AND namespace.nspowner IN (login.oid, registrar.oid)
            ) AS authority_role_owns_public_schema,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                 WHERE namespace.nspname = 'public'
                   AND relation.relowner IN (login.oid, registrar.oid)
            ) OR EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                 WHERE namespace.nspname = 'public'
                   AND function.proowner IN (login.oid, registrar.oid)
            ) AS authority_role_owns_public_objects,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_class AS relation
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(
                      relation.relacl,
                      pg_catalog.acldefault(
                        CASE WHEN relation.relkind = 'S'
                          THEN 's'::\"char\" ELSE 'r'::\"char\"
                        END,
                        relation.relowner
                      )
                    )
                  ) AS relation_acl
                 WHERE namespace.nspname = 'public'
                   AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
                   AND relation_acl.grantee IN (login.oid, registrar.oid, 0)
            ) AS unexpected_authority_relation_acl,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_attribute AS attribute
                  JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS column_acl
                 WHERE namespace.nspname = 'public'
                   AND attribute.attnum > 0
                   AND NOT attribute.attisdropped
                   AND column_acl.grantee IN (login.oid, registrar.oid, 0)
            ) AS unexpected_authority_column_acl,
            EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(function.proacl, pg_catalog.acldefault('f', function.proowner))
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function_acl.grantee IN (login.oid, 0)
            ) AS login_or_public_has_function_acl,
            NOT EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(function.proacl, pg_catalog.acldefault('f', function.proowner))
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function.oid = pg_catalog.to_regprocedure(
                     'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)'
                   )
                   AND function_acl.grantee = registrar.oid
                   AND function_acl.privilege_type = 'EXECUTE'
                   AND NOT function_acl.is_grantable
            ) OR EXISTS (
                SELECT 1
                  FROM pg_catalog.pg_proc AS function
                  JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = function.pronamespace
                  CROSS JOIN LATERAL pg_catalog.aclexplode(
                    COALESCE(function.proacl, pg_catalog.acldefault('f', function.proowner))
                  ) AS function_acl
                 WHERE namespace.nspname = 'public'
                   AND function_acl.grantee = registrar.oid
                   AND (
                     function.oid IS DISTINCT FROM pg_catalog.to_regprocedure(
                       'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)'
                     )
                     OR function_acl.privilege_type <> 'EXECUTE'
                     OR function_acl.is_grantable
                   )
            ) AS registrar_function_acl_drift
       FROM pg_catalog.pg_roles AS login
       JOIN pg_catalog.pg_roles AS registrar ON registrar.rolname = 'kf_authority_registrar'
      WHERE login.rolname = SESSION_USER";
const REGISTER_GRANT_SQL: &str = "SELECT public.kf_register_ingest_authority_grant(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) AS grant_id";
const INGEST_SQL: &str = "SELECT occurrence_id, version_id, parent_version_id
       FROM public.kf_ingest_authorized($1,$2)";

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
    let runtime_owns_public_functions: bool = role.try_get("runtime_owns_public_functions")?;
    let runtime_member: bool = role.try_get("runtime_member")?;
    let login_has_other_memberships: bool = role.try_get("login_has_other_memberships")?;
    let runtime_has_other_memberships: bool = role.try_get("runtime_has_other_memberships")?;
    let login_can_create_public: bool = role.try_get("login_can_create_public")?;
    let login_can_create_database_objects: bool =
        role.try_get("login_can_create_database_objects")?;
    let login_owns_database: bool = role.try_get("login_owns_database")?;
    let login_owns_public_schema: bool = role.try_get("login_owns_public_schema")?;
    let login_owns_public_relations: bool = role.try_get("login_owns_public_relations")?;
    let login_owns_public_functions: bool = role.try_get("login_owns_public_functions")?;
    let login_has_direct_relation_acl: bool = role.try_get("login_has_direct_relation_acl")?;
    let unexpected_column_acl: bool = role.try_get("unexpected_column_acl")?;
    let runtime_has_forbidden_relation_acl: bool =
        role.try_get("runtime_has_forbidden_relation_acl")?;
    let unexpected_sequence_acl: bool = role.try_get("unexpected_sequence_acl")?;
    let login_or_public_has_function_acl: bool =
        role.try_get("login_or_public_has_function_acl")?;
    let runtime_function_acl_drift: bool = role.try_get("runtime_function_acl_drift")?;
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
        && !runtime_owns_public_functions
        && !login_has_other_memberships
        && !login_can_create_public
        && !login_can_create_database_objects
        && !login_owns_database
        && !login_owns_public_schema
        && !login_owns_public_relations
        && !login_owns_public_functions
        && !login_has_direct_relation_acl
        && !unexpected_column_acl
        && !runtime_has_forbidden_relation_acl
        && !unexpected_sequence_acl
        && !login_or_public_has_function_acl
        && !runtime_function_acl_drift
        && !scoped_rls_drift;
    Ok((safe, role_name))
}

fn registrar_role_row_is_safe(
    role: &PgRow,
) -> std::result::Result<(bool, String), sqlx_core::Error> {
    let role_name: String = role.try_get("login_name")?;
    let current_name: String = role.try_get("current_name")?;
    let session_name: String = role.try_get("session_name")?;
    let login_can_login: bool = role.try_get("login_can_login")?;
    let login_super: bool = role.try_get("login_super")?;
    let login_bypassrls: bool = role.try_get("login_bypassrls")?;
    let login_inherit: bool = role.try_get("login_inherit")?;
    let login_createdb: bool = role.try_get("login_createdb")?;
    let login_createrole: bool = role.try_get("login_createrole")?;
    let login_replication: bool = role.try_get("login_replication")?;
    let registrar_can_login: bool = role.try_get("registrar_can_login")?;
    let registrar_super: bool = role.try_get("registrar_super")?;
    let registrar_bypassrls: bool = role.try_get("registrar_bypassrls")?;
    let registrar_inherit: bool = role.try_get("registrar_inherit")?;
    let registrar_createdb: bool = role.try_get("registrar_createdb")?;
    let registrar_createrole: bool = role.try_get("registrar_createrole")?;
    let registrar_replication: bool = role.try_get("registrar_replication")?;
    let registrar_member: bool = role.try_get("registrar_member")?;
    let login_has_other_memberships: bool = role.try_get("login_has_other_memberships")?;
    let registrar_has_memberships: bool = role.try_get("registrar_has_memberships")?;
    let login_can_create_public: bool = role.try_get("login_can_create_public")?;
    let login_can_create_database_objects: bool =
        role.try_get("login_can_create_database_objects")?;
    let registrar_can_create_public: bool = role.try_get("registrar_can_create_public")?;
    let registrar_can_create_database_objects: bool =
        role.try_get("registrar_can_create_database_objects")?;
    let authority_role_owns_database: bool = role.try_get("authority_role_owns_database")?;
    let authority_role_owns_public_schema: bool =
        role.try_get("authority_role_owns_public_schema")?;
    let authority_role_owns_public_objects: bool =
        role.try_get("authority_role_owns_public_objects")?;
    let unexpected_authority_relation_acl: bool =
        role.try_get("unexpected_authority_relation_acl")?;
    let unexpected_authority_column_acl: bool = role.try_get("unexpected_authority_column_acl")?;
    let login_or_public_has_function_acl: bool =
        role.try_get("login_or_public_has_function_acl")?;
    let registrar_function_acl_drift: bool = role.try_get("registrar_function_acl_drift")?;
    let safe = current_name == session_name
        && login_can_login
        && !login_super
        && !login_bypassrls
        && !login_inherit
        && !login_createdb
        && !login_createrole
        && !login_replication
        && registrar_member
        && !login_has_other_memberships
        && !registrar_has_memberships
        && !registrar_can_login
        && !registrar_super
        && !registrar_bypassrls
        && !registrar_inherit
        && !registrar_createdb
        && !registrar_createrole
        && !registrar_replication
        && !login_can_create_public
        && !login_can_create_database_objects
        && !registrar_can_create_public
        && !registrar_can_create_database_objects
        && !authority_role_owns_database
        && !authority_role_owns_public_schema
        && !authority_role_owns_public_objects
        && !unexpected_authority_relation_acl
        && !unexpected_authority_column_acl
        && !login_or_public_has_function_acl
        && !registrar_function_acl_drift;
    Ok((safe, role_name))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestOutcome {
    pub occurrence_id: Uuid,
    pub version_id: Uuid,
    pub parent_version_id: Option<Uuid>,
}

/// Tenant-safe runtime surface. There is deliberately no caller-selected project, independent
/// blob upsert, raw SELECT, pool, connection, or transaction accessor.
#[async_trait]
pub trait MetaStore {
    async fn ingest_authorized(&self, grant_id: Uuid) -> Result<IngestOutcome>;
}

pub struct PostgresAuthorityStore {
    pool: Pool<Postgres>,
    authority_domain_id: Uuid,
}

pub struct PostgresMetaStore {
    pool: Pool<Postgres>,
    authority_domain_id: Uuid,
}

impl PostgresAuthorityStore {
    /// Connect with a dedicated NOINHERIT login whose only SET-capable membership is
    /// `kf_authority_registrar`. Runtime credentials are rejected here and registrar credentials
    /// are rejected by the runtime constructor.
    pub async fn connect_registrar(url: &str, authority_domain_id: Uuid) -> Result<Self> {
        authority::compiled_trust_registry_digest()
            .context("authority registrar requires a build-time trust-registry pin")?;
        if authority_domain_id.is_nil() {
            bail!("authority domain identifier must be non-nil");
        }
        let pool = PoolOptions::<Postgres>::new()
            .max_connections(2)
            .after_connect(|connection, _metadata| {
                Box::pin(async move {
                    let role = query(VERIFY_REGISTRAR_ROLE_SQL)
                        .fetch_optional(&mut *connection)
                        .await?
                        .ok_or_else(|| {
                            sqlx_core::Error::Protocol(
                                "current PostgreSQL registrar login is absent from pg_roles"
                                    .to_owned(),
                            )
                        })?;
                    let (safe, role_name) = registrar_role_row_is_safe(&role)?;
                    if !safe {
                        return Err(sqlx_core::Error::Protocol(format!(
                            "PostgreSQL authority login {role_name} failed the registrar admission gate"
                        )));
                    }
                    Ok(())
                })
            })
            .connect(url)
            .await?;
        Ok(Self {
            pool,
            authority_domain_id,
        })
    }

    /// Register an authority only after exact bytes are durably present in CAS. Borrowing the
    /// endpoint-bound proof permits an exact retry after an ambiguous network result; PostgreSQL
    /// enforces immutable idempotency and global `(issuer,key_id,nonce)` replay uniqueness.
    pub async fn register_ingest_authority(
        &self,
        stored_authority: &StoredIngestAuthority,
    ) -> Result<Uuid> {
        let authority = stored_authority.authority();
        let compiled_registry_sha256 = authority::compiled_trust_registry_digest()
            .context("authority registrar requires a build-time trust-registry pin")?;
        if authority.registry_sha256() != compiled_registry_sha256 {
            bail!("consumed authority registry does not match the build-time pin");
        }
        if authority.authority_domain_id() != self.authority_domain_id {
            bail!("consumed authority is bound to a different database security domain");
        }
        validate_project_id(authority.project_id())?;
        validate_source_key(authority.source_system_id(), authority.source_native_id())?;
        validate_sha256(authority.content_sha256())?;
        let byte_size = i64::try_from(authority.content_size())
            .context("authorized content size exceeds PostgreSQL bigint")?;
        if !(0..=MAX_RAW_BLOB_BYTES).contains(&byte_size) {
            bail!("authorized byte_size is outside the supported intake bound");
        }
        if stored_authority.blob().sha256 != authority.content_sha256()
            || stored_authority.blob().byte_size != authority.content_size()
            || stored_authority.blob().storage_uri
                != format!("cas://sha256/{}", authority.content_sha256())
        {
            bail!("stored authority CAS proof does not match signed content");
        }
        let revalidation = stored_authority.revalidation()?;
        let permit = cas_revalidation_semaphore()
            .acquire_owned()
            .await
            .context("CAS revalidation semaphore was closed")?;
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            revalidation.verify()
        })
        .await
        .context("join bounded CAS revalidation worker")??;
        let expected_grant_id = authority.database_grant_id();
        let mut transaction = self.pool.begin().await?;
        query(SET_LOCAL_REGISTRAR_ROLE_SQL)
            .execute(&mut *transaction)
            .await
            .context("set transaction-local authority registrar role")?;
        query(SET_LOCAL_TIMEOUTS_SQL)
            .execute(&mut *transaction)
            .await
            .context("set registrar lock and statement timeouts before registration")?;
        let row = query(REGISTER_GRANT_SQL)
            .bind(expected_grant_id)
            .bind(authority.authority_domain_id())
            .bind(authority.issuer())
            .bind(authority.key_id())
            .bind(authority.actor())
            .bind(authority.project_id())
            .bind(authority.database_session_user())
            .bind(authority.source_system_id())
            .bind(authority.source_native_id())
            .bind(authority.content_sha256())
            .bind(byte_size)
            .bind(authority.nonce())
            .bind(authority.claims_sha256())
            .bind(authority.issued_at_unix())
            .bind(authority.expires_at_unix())
            .fetch_one(&mut *transaction)
            .await
            .context("register consumed ingest authority")?;
        let registered_grant_id: Uuid = row.try_get("grant_id")?;
        if registered_grant_id != expected_grant_id {
            bail!("PostgreSQL returned a different authority grant identifier");
        }
        transaction.commit().await?;
        Ok(registered_grant_id)
    }
}

impl PostgresMetaStore {
    /// Production-shaped constructor. It refuses an administrative, owner, superuser, or
    /// BYPASSRLS connection. On PostgreSQL 16, the login must be a NOINHERIT member of only
    /// `kf_runtime`, granted with ADMIN/INHERIT false and SET true. Every new physical connection
    /// repeats admission before any domain transaction can perform the transaction-local switch.
    pub async fn connect_runtime(url: &str, authority_domain_id: Uuid) -> Result<Self> {
        if authority_domain_id.is_nil() {
            bail!("authority domain identifier must be non-nil");
        }
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
        Ok(Self {
            pool,
            authority_domain_id,
        })
    }

    /// Test-only administrative constructor. The URL guard makes accidental connection to a
    /// non-loopback or non-disposable database fail before any network operation.
    pub async fn connect_for_disposable_admin_test(
        url: &str,
        confirmation: &str,
        cluster_confirmation: &str,
        authority_domain_id: Uuid,
    ) -> Result<Self> {
        if confirmation != "MAWORLD_DISPOSABLE_DB_CONFIRMED" {
            bail!("explicit disposable-database confirmation is required");
        }
        if cluster_confirmation != "RESET_GLOBAL_KF_ROLES_IN_DISPOSABLE_POSTGRES_CLUSTER" {
            bail!("explicit disposable-cluster confirmation is required");
        }
        if authority_domain_id.is_nil() {
            bail!("authority domain identifier must be non-nil");
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
        Ok(Self {
            pool,
            authority_domain_id,
        })
    }
}

#[async_trait]
impl MetaStore for PostgresMetaStore {
    async fn ingest_authorized(&self, grant_id: Uuid) -> Result<IngestOutcome> {
        if grant_id.is_nil() {
            bail!("authority grant_id must not be nil");
        }

        let mut transaction = self.pool.begin().await?;
        query(SET_LOCAL_RUNTIME_ROLE_SQL)
            .execute(&mut *transaction)
            .await
            .context("set transaction-local runtime role")?;
        query(SET_LOCAL_TIMEOUTS_SQL)
            .execute(&mut *transaction)
            .await
            .context("set runtime lock and statement timeouts before grant lock")?;
        let row = query(INGEST_SQL)
            .bind(grant_id)
            .bind(self.authority_domain_id)
            .fetch_one(&mut *transaction)
            .await
            .context("atomically ingest authority-bound observation")?;
        let outcome = IngestOutcome {
            occurrence_id: row.try_get("occurrence_id")?,
            version_id: row.try_get("version_id")?,
            parent_version_id: row.try_get("parent_version_id")?,
        };
        transaction.commit().await?;
        Ok(outcome)
    }
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

pub fn validate_disposable_database_url(database_url: &str) -> Result<String> {
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
    const AUTHORITY_GRANT_MIGRATION: &str = include_str!("../../schema/004_authority_grants.sql");

    #[test]
    fn registrar_validation_is_strict_and_bounded() {
        assert!(validate_project_id(Uuid::nil()).is_err());
        assert!(validate_source_key("drive", "document-1").is_ok());
        assert!(
            validate_source_key(&"x".repeat(MAX_SOURCE_SYSTEM_BYTES + 1), "document-1").is_err()
        );
        assert!(validate_source_key("drive", " padded").is_err());
    }

    #[test]
    fn sha256_validation_is_strict() {
        assert!(validate_sha256(&"a".repeat(64)).is_ok());
        for invalid in ["", "abc", &"A".repeat(64), &"g".repeat(64)] {
            assert!(validate_sha256(invalid).is_err());
        }
    }

    #[test]
    fn runtime_api_accepts_only_an_opaque_grant() {
        assert_eq!(SET_LOCAL_RUNTIME_ROLE_SQL, "SET LOCAL ROLE kf_runtime");
        assert_eq!(
            SET_LOCAL_REGISTRAR_ROLE_SQL,
            "SET LOCAL ROLE kf_authority_registrar"
        );
        assert_eq!(REGISTER_GRANT_SQL.matches('$').count(), 15);
        assert_eq!(INGEST_SQL.matches('$').count(), 2);
        assert!(INGEST_SQL.contains("kf_ingest_authorized"));
        assert!(!INGEST_SQL.contains("project_id"));
        assert!(!INGEST_SQL.contains("blob_id"));
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
            "runtime_owns_public_functions",
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
            "login_owns_public_functions",
            "login_has_direct_relation_acl",
            "pg_catalog.pg_attribute",
            "unexpected_column_acl",
            "runtime_has_forbidden_relation_acl",
            "unexpected_sequence_acl",
            "relation.relkind = 'S'",
            "login_or_public_has_function_acl",
            "runtime_function_acl_drift",
            "function_acl.is_grantable",
            "scoped_rls_drift",
            "relation.relrowsecurity",
            "relation.relforcerowsecurity",
            "pg_catalog.aclexplode",
        ] {
            assert!(
                VERIFY_RUNTIME_ROLE_SQL.contains(required),
                "missing runtime admission guard: {required}"
            );
        }
    }

    #[test]
    fn registrar_role_verification_rejects_privilege_drift() {
        for required in [
            "CURRENT_USER::text AS current_name",
            "SESSION_USER::text AS session_name",
            "registrar.rolcreatedb",
            "registrar.rolcreaterole",
            "registrar.rolreplication",
            "NOT membership.admin_option",
            "NOT membership.inherit_option",
            "membership.set_option",
            "login_has_other_memberships",
            "registrar_has_memberships",
            "registrar_can_create_public",
            "registrar_can_create_database_objects",
            "authority_role_owns_database",
            "authority_role_owns_public_schema",
            "authority_role_owns_public_objects",
            "unexpected_authority_relation_acl",
            "unexpected_authority_column_acl",
            "login_or_public_has_function_acl",
            "registrar_function_acl_drift",
            "kf_register_ingest_authority_grant",
            "function_acl.is_grantable",
        ] {
            assert!(
                VERIFY_REGISTRAR_ROLE_SQL.contains(required),
                "missing registrar admission guard: {required}"
            );
        }
    }

    #[test]
    fn authority_grant_migration_removes_caller_selected_scope() {
        for required in [
            "requires a direct dedicated migration superuser",
            "CREATE TABLE public.kf_authority_domain",
            "CREATE TABLE public.kf_ingest_authority_grant",
            "CONSTRAINT kf_ingest_authority_nonce_unique UNIQUE (issuer, key_id, nonce)",
            "CREATE OR REPLACE FUNCTION public.kf_register_ingest_authority_grant",
            "CREATE OR REPLACE FUNCTION public.kf_ingest_authorized",
            "FOR UPDATE",
            "authority registrar session denied",
            "SET lock_timeout = '5s'",
            "SET statement_timeout = '30s'",
            "v_current_authority_domain_id IS DISTINCT FROM p_authority_domain_id",
            "v_grant.authority_domain_id IS DISTINCT FROM v_current_authority_domain_id",
            "RAISE EXCEPTION 'authority domain denied' USING ERRCODE = '42501'",
            "database_session_user IS DISTINCT FROM SESSION_USER::text",
            "database_session_role_oid = v_target_role_id",
            "database_session_role_oid IS DISTINCT FROM v_session_role_id",
            "v_occurrence_id := pg_catalog.gen_random_uuid()",
            "v_version_id := pg_catalog.gen_random_uuid()",
            "v_grant.project_id",
            "v_grant.source_system_id",
            "v_grant.content_sha256",
            "authority_grant.consumed_at IS NULL",
            "RENAME TO kf_ingest_observation_internal",
            "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_runtime",
            "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_authority_registrar",
            "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM kf_authority_registrar",
            "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM kf_runtime",
            "GRANT EXECUTE ON FUNCTION public.kf_ingest_authorized(uuid, uuid) TO kf_runtime",
            "GRANT EXECUTE ON FUNCTION public.kf_register_ingest_authority_grant",
            "RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501'",
            "granted_acl.is_grantable",
            "DO $function_acl_reset$",
            "kf_ingest_owner attribute drift",
            "authority function exact ACL drift",
            "authority registrar ownership drift",
            "runtime or registrar retained raw column ACL",
            "one-shot migration and is already applied",
            "USING ERRCODE = '55000'",
        ] {
            assert!(
                AUTHORITY_GRANT_MIGRATION.contains(required),
                "missing authority migration guard: {required}"
            );
        }
        assert!(!AUTHORITY_GRANT_MIGRATION
            .contains("GRANT EXECUTE ON FUNCTION public.kf_ingest_observation("));
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
