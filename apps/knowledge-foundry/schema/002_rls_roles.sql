-- Knowledge Foundry — runtime/admin role separation for RLS (closure v1.1 §2.5, v1.3 §7).
-- The migration/admin role owns tables and can seed (superuser bypasses RLS). The runtime
-- role is NON-owner, NON-superuser, subject to FORCE RLS, and is the ONLY effective role for
-- request handling. On pinned PostgreSQL 16, a credential-bearing service login must be NOINHERIT
-- and its only membership must be granted with ADMIN FALSE, INHERIT FALSE, SET TRUE. The adapter
-- performs SET LOCAL ROLE kf_runtime in every transaction. Project scope
-- is also transaction-local, never unbounded session state -> no pool-reuse leakage.

BEGIN;

DO $migration_authority_guard$
BEGIN
  IF NOT EXISTS (
      SELECT 1
        FROM pg_catalog.pg_roles AS migration_role
       WHERE migration_role.rolname = SESSION_USER
         AND migration_role.rolsuper
  ) THEN
    RAISE EXCEPTION '002_rls_roles.sql requires a dedicated migration superuser';
  END IF;
END
$migration_authority_guard$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kf_runtime') THEN
    CREATE ROLE kf_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                           NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
END$$;

-- Re-applying this migration must also repair unsafe attribute drift on an existing role.
ALTER ROLE kf_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                      NOREPLICATION NOBYPASSRLS NOINHERIT;
DO $runtime_membership_guard$
BEGIN
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS runtime_role ON runtime_role.oid = membership.member
       WHERE runtime_role.rolname = 'kf_runtime'
  ) THEN
    RAISE EXCEPTION 'kf_runtime must not inherit or SET ROLE to another role';
  END IF;
END
$runtime_membership_guard$;

-- Repair all ACL drift before granting the exact read surface. Runtime writes are exposed only
-- through narrow functions; it cannot construct any state row in separate statements.
DO $database_acl_reset$
BEGIN
  EXECUTE pg_catalog.format(
      'REVOKE CREATE ON DATABASE %I FROM PUBLIC', pg_catalog.current_database()
  );
  EXECUTE pg_catalog.format(
      'REVOKE CREATE ON DATABASE %I FROM kf_runtime', pg_catalog.current_database()
  );
END
$database_acl_reset$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM kf_runtime;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_runtime;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM kf_runtime;
GRANT USAGE ON SCHEMA public TO kf_runtime;
GRANT SELECT ON raw_blob, artifact_occurrence, artifact_version, logical_document,
                ingestion_run, event_ledger, project, embedding_profile TO kf_runtime;
REVOKE ALL ON provenance_parent FROM kf_runtime;
REVOKE ALL ON FUNCTION public.kf_allowed_projects() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.kf_allowed_projects() TO kf_runtime;

DO $runtime_ownership_guard$
BEGIN
  IF pg_catalog.has_database_privilege(
         'kf_runtime', pg_catalog.current_database(), 'CREATE'
     ) THEN
    RAISE EXCEPTION 'kf_runtime must not CREATE objects in the current database';
  END IF;
  IF pg_catalog.has_schema_privilege('kf_runtime', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'kf_runtime must not CREATE objects in schema public';
  END IF;
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_database AS database
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = database.datdba
       WHERE database.datname = pg_catalog.current_database()
         AND owner_role.rolname = 'kf_runtime'
  ) THEN
    RAISE EXCEPTION 'kf_runtime must not own the current database';
  END IF;
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
       WHERE namespace.nspname = 'public'
         AND owner_role.rolname = 'kf_runtime'
  ) THEN
    RAISE EXCEPTION 'kf_runtime must not own schema public';
  END IF;
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
       WHERE namespace.nspname = 'public'
         AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
         AND owner_role.rolname = 'kf_runtime'
  ) THEN
    RAISE EXCEPTION 'kf_runtime must not own relations in schema public';
  END IF;
END
$runtime_ownership_guard$;

-- runtime must NOT bypass RLS; ensure it is not superuser and RLS is FORCED on scoped tables
ALTER TABLE artifact_occurrence ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_occurrence FORCE ROW LEVEL SECURITY;
ALTER TABLE artifact_version    ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_version    FORCE ROW LEVEL SECURITY;
ALTER TABLE logical_document    ENABLE ROW LEVEL SECURITY;
ALTER TABLE logical_document    FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_run       ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_run       FORCE ROW LEVEL SECURITY;
ALTER TABLE event_ledger        ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_ledger        FORCE ROW LEVEL SECURITY;
ALTER TABLE raw_blob            ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_blob            FORCE ROW LEVEL SECURITY;
ALTER TABLE project             ENABLE ROW LEVEL SECURITY;
ALTER TABLE project             FORCE ROW LEVEL SECURITY;

-- Blob/project SELECT is filtered by the RLS policies in 001.  Lineage remains
-- admin-only until provenance_parent has an explicit tenant key and policy.

COMMIT;
