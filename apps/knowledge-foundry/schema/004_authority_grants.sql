-- Knowledge Foundry -- database-enforced, one-time ingest authority grants.
-- Apply as a dedicated migration superuser after 001, 002, and 003.
--
-- The generic runtime credential is deliberately not project authority.  A separately
-- authenticated registrar records an already-verified, exact signed mandate.  The runtime
-- can then invoke only kf_ingest_authorized(), which derives project scope and the complete
-- observation payload from the locked server-side grant row.

BEGIN;

DO $migration_authority_guard$
BEGIN
  IF CURRENT_USER IS DISTINCT FROM SESSION_USER
     OR NOT EXISTS (
       SELECT 1
         FROM pg_catalog.pg_roles AS migration_role
        WHERE migration_role.rolname = SESSION_USER
          AND migration_role.rolsuper
     ) THEN
    RAISE EXCEPTION '004_authority_grants.sql requires a direct dedicated migration superuser';
  END IF;
END
$migration_authority_guard$;

DO $one_shot_guard$
BEGIN
  IF pg_catalog.to_regclass('public.kf_ingest_authority_grant') IS NOT NULL THEN
    RAISE EXCEPTION
      '004_authority_grants.sql is a one-shot migration and is already applied'
      USING ERRCODE = '55000';
  END IF;
END
$one_shot_guard$;

DO $roles$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kf_authority_owner'
  ) THEN
    CREATE ROLE kf_authority_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                                   NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kf_authority_registrar'
  ) THEN
    CREATE ROLE kf_authority_registrar NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                                       NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
END
$roles$;

-- Before this one-shot migration creates any object, repair dangerous role-attribute drift.
-- Incoming registrar memberships are deployment state and are checked rather than removed.
ALTER ROLE kf_authority_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                              NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE kf_authority_registrar NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                                  NOREPLICATION NOBYPASSRLS NOINHERIT;
ALTER ROLE kf_ingest_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                           NOREPLICATION NOBYPASSRLS NOINHERIT;

DO $remove_owner_memberships$
DECLARE
  membership RECORD;
BEGIN
  FOR membership IN
    SELECT granted.rolname AS granted_role, member.rolname AS member_role
      FROM pg_catalog.pg_auth_members AS link
      JOIN pg_catalog.pg_roles AS granted ON granted.oid = link.roleid
      JOIN pg_catalog.pg_roles AS member ON member.oid = link.member
     WHERE granted.rolname = 'kf_authority_owner'
        OR member.rolname = 'kf_authority_owner'
        OR member.rolname = 'kf_authority_registrar'
        OR granted.rolname = 'kf_ingest_owner'
        OR member.rolname = 'kf_ingest_owner'
  LOOP
    EXECUTE pg_catalog.format(
      'REVOKE %I FROM %I', membership.granted_role, membership.member_role
    );
  END LOOP;
END
$remove_owner_memberships$;

DO $registrar_membership_guard$
BEGIN
  IF EXISTS (
    SELECT 1
      FROM pg_catalog.pg_auth_members AS membership
      JOIN pg_catalog.pg_roles AS registrar ON registrar.oid = membership.roleid
      JOIN pg_catalog.pg_roles AS member_role ON member_role.oid = membership.member
     WHERE registrar.rolname = 'kf_authority_registrar'
       AND (
         membership.admin_option
         OR membership.inherit_option
         OR NOT membership.set_option
         OR NOT member_role.rolcanlogin
         OR member_role.rolsuper
         OR member_role.rolbypassrls
         OR member_role.rolinherit
         OR member_role.rolcreatedb
         OR member_role.rolcreaterole
         OR member_role.rolreplication
       )
  ) THEN
    RAISE EXCEPTION
      'kf_authority_registrar members must be safe NOINHERIT logins with ADMIN/INHERIT false and SET true';
  END IF;
END
$registrar_membership_guard$;

-- Provisioning deliberately supplies this stable logical security-domain UUID after the
-- migration.  There is no generated default: an unprovisioned database fails closed, while an
-- HA/DR replica keeps the same identity.  A forked clone must rotate the row before admission.
CREATE TABLE public.kf_authority_domain (
    singleton           boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    authority_domain_id uuid NOT NULL UNIQUE,
    provisioned_at      timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    CONSTRAINT kf_authority_domain_id_non_nil CHECK (
      authority_domain_id <> '00000000-0000-0000-0000-000000000000'::uuid
    )
);

CREATE TABLE public.kf_ingest_authority_grant (
    grant_id                   uuid PRIMARY KEY,
    authority_domain_id        uuid NOT NULL,
    issuer                     text NOT NULL,
    key_id                     text NOT NULL,
    actor                      text NOT NULL,
    project_id                 uuid NOT NULL
                               REFERENCES public.project(project_id)
                               ON UPDATE RESTRICT ON DELETE RESTRICT,
    database_session_user      text NOT NULL,
    database_session_role_oid  oid NOT NULL,
    source_system_id           text NOT NULL,
    source_native_id           text NOT NULL,
    content_sha256             text NOT NULL,
    content_size               bigint NOT NULL,
    nonce                      text NOT NULL,
    claims_sha256              text NOT NULL,
    issued_at_unix             bigint NOT NULL,
    expires_at_unix            bigint NOT NULL,
    registered_at              timestamptz NOT NULL DEFAULT pg_catalog.clock_timestamp(),
    revoked_at                 timestamptz,
    consumed_at                timestamptz,
    requested_occurrence_id    uuid,
    requested_version_id       uuid,
    outcome_blob_id            uuid,
    outcome_occurrence_id      uuid,
    outcome_version_id         uuid,
    outcome_parent_version_id  uuid,
    outcome_blob_created       boolean,
    outcome_occurrence_created boolean,
    outcome_version_created    boolean,

    CONSTRAINT kf_ingest_authority_grant_id_non_nil CHECK (
      grant_id <> '00000000-0000-0000-0000-000000000000'::uuid
    ),
    CONSTRAINT kf_ingest_authority_domain_id_non_nil CHECK (
      authority_domain_id <> '00000000-0000-0000-0000-000000000000'::uuid
    ),
    CONSTRAINT kf_ingest_authority_project_id_non_nil CHECK (
      project_id <> '00000000-0000-0000-0000-000000000000'::uuid
    ),
    CONSTRAINT kf_ingest_authority_issuer_check CHECK (
      pg_catalog.octet_length(issuer) BETWEEN 1 AND 128
      AND issuer = pg_catalog.btrim(issuer)
      AND issuer ~ '^[A-Za-z0-9._:-]+$'
    ),
    CONSTRAINT kf_ingest_authority_key_id_check CHECK (
      pg_catalog.octet_length(key_id) BETWEEN 1 AND 96
      AND key_id = pg_catalog.btrim(key_id)
      AND key_id ~ '^[A-Za-z0-9._:-]+$'
    ),
    CONSTRAINT kf_ingest_authority_actor_check CHECK (
      pg_catalog.octet_length(actor) BETWEEN 1 AND 256
      AND actor = pg_catalog.btrim(actor)
      AND actor !~ '[[:cntrl:]]'
    ),
    CONSTRAINT kf_ingest_authority_session_user_check CHECK (
      pg_catalog.octet_length(database_session_user) BETWEEN 1 AND 63
      AND database_session_user = pg_catalog.btrim(database_session_user)
      AND database_session_user !~ '[[:cntrl:]]'
    ),
    CONSTRAINT kf_ingest_authority_session_role_oid_check CHECK (
      database_session_role_oid <> 0::oid
    ),
    CONSTRAINT kf_ingest_authority_source_system_check CHECK (
      pg_catalog.octet_length(source_system_id) BETWEEN 1 AND 128
      AND source_system_id = pg_catalog.btrim(source_system_id)
      AND source_system_id !~ '[[:cntrl:]]'
    ),
    CONSTRAINT kf_ingest_authority_source_native_check CHECK (
      pg_catalog.octet_length(source_native_id) BETWEEN 1 AND 4096
      AND source_native_id = pg_catalog.btrim(source_native_id)
      AND source_native_id !~ '[[:cntrl:]]'
    ),
    CONSTRAINT kf_ingest_authority_content_hash_check CHECK (
      content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT kf_ingest_authority_content_size_check CHECK (
      content_size BETWEEN 0 AND 268435456
    ),
    CONSTRAINT kf_ingest_authority_nonce_check CHECK (
      pg_catalog.octet_length(nonce) BETWEEN 16 AND 128
      AND nonce = pg_catalog.btrim(nonce)
      AND nonce ~ '^[A-Za-z0-9._:-]+$'
    ),
    CONSTRAINT kf_ingest_authority_claims_hash_check CHECK (
      claims_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT kf_ingest_authority_ttl_check CHECK (
      issued_at_unix >= 0
      AND expires_at_unix > issued_at_unix
      AND expires_at_unix - issued_at_unix <= 300
    ),
    CONSTRAINT kf_ingest_authority_consumption_shape_check CHECK (
      (
        consumed_at IS NULL
        AND requested_occurrence_id IS NULL
        AND requested_version_id IS NULL
        AND outcome_blob_id IS NULL
        AND outcome_occurrence_id IS NULL
        AND outcome_version_id IS NULL
        AND outcome_parent_version_id IS NULL
        AND outcome_blob_created IS NULL
        AND outcome_occurrence_created IS NULL
        AND outcome_version_created IS NULL
      ) OR (
        consumed_at IS NOT NULL
        AND requested_occurrence_id IS NOT NULL
        AND requested_occurrence_id <> '00000000-0000-0000-0000-000000000000'::uuid
        AND requested_version_id IS NOT NULL
        AND requested_version_id <> '00000000-0000-0000-0000-000000000000'::uuid
        AND outcome_blob_id IS NOT NULL
        AND outcome_blob_id <> '00000000-0000-0000-0000-000000000000'::uuid
        AND outcome_occurrence_id IS NOT NULL
        AND outcome_occurrence_id <> '00000000-0000-0000-0000-000000000000'::uuid
        AND outcome_version_id IS NOT NULL
        AND outcome_version_id <> '00000000-0000-0000-0000-000000000000'::uuid
        AND (
          outcome_parent_version_id IS NULL
          OR outcome_parent_version_id <> '00000000-0000-0000-0000-000000000000'::uuid
        )
        AND outcome_blob_created IS NOT NULL
        AND outcome_occurrence_created IS NOT NULL
        AND outcome_version_created IS NOT NULL
      )
    ),
    CONSTRAINT kf_ingest_authority_nonce_unique UNIQUE (issuer, key_id, nonce),
    CONSTRAINT kf_ingest_authority_claims_unique UNIQUE (claims_sha256)
);

-- A relation owner must temporarily have CREATE on the containing schema for ownership transfer.
GRANT CREATE ON SCHEMA public TO kf_authority_owner;
ALTER TABLE public.kf_authority_domain OWNER TO kf_authority_owner;
ALTER TABLE public.kf_ingest_authority_grant OWNER TO kf_authority_owner;
REVOKE CREATE ON SCHEMA public FROM kf_authority_owner;

CREATE OR REPLACE FUNCTION public.kf_register_ingest_authority_grant(
    p_grant_id uuid,
    p_authority_domain_id uuid,
    p_issuer text,
    p_key_id text,
    p_actor text,
    p_project_id uuid,
    p_database_session_user text,
    p_source_system_id text,
    p_source_native_id text,
    p_content_sha256 text,
    p_content_size bigint,
    p_nonce text,
    p_claims_sha256 text,
    p_issued_at_unix bigint,
    p_expires_at_unix bigint
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = on
SET lock_timeout = '5s'
SET statement_timeout = '30s'
AS $function$
DECLARE
    v_now_unix bigint;
    v_runtime_role_id oid;
    v_registrar_role_id oid;
    v_session_role_id oid;
    v_registrar_session_safe boolean := false;
    v_target_role_id oid;
    v_target_role_safe boolean := false;
    v_current_authority_domain_id uuid;
    v_inserted bigint;
    v_collision_count bigint;
    v_exact_retry boolean;
BEGIN
    IF p_grant_id IS NULL
       OR p_grant_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_authority_domain_id IS NULL
       OR p_authority_domain_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_project_id IS NULL
       OR p_project_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RAISE EXCEPTION 'invalid authority grant UUID' USING ERRCODE = '22023';
    END IF;

    IF p_issuer IS NULL
       OR pg_catalog.octet_length(p_issuer) NOT BETWEEN 1 AND 128
       OR p_issuer <> pg_catalog.btrim(p_issuer)
       OR p_issuer !~ '^[A-Za-z0-9._:-]+$' THEN
        RAISE EXCEPTION 'invalid authority issuer' USING ERRCODE = '22023';
    END IF;
    IF p_key_id IS NULL
       OR pg_catalog.octet_length(p_key_id) NOT BETWEEN 1 AND 96
       OR p_key_id <> pg_catalog.btrim(p_key_id)
       OR p_key_id !~ '^[A-Za-z0-9._:-]+$' THEN
        RAISE EXCEPTION 'invalid authority key_id' USING ERRCODE = '22023';
    END IF;
    IF p_actor IS NULL
       OR pg_catalog.octet_length(p_actor) NOT BETWEEN 1 AND 256
       OR p_actor <> pg_catalog.btrim(p_actor)
       OR p_actor ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid authority actor' USING ERRCODE = '22023';
    END IF;
    IF p_database_session_user IS NULL
       OR pg_catalog.octet_length(p_database_session_user) NOT BETWEEN 1 AND 63
       OR p_database_session_user <> pg_catalog.btrim(p_database_session_user)
       OR p_database_session_user ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid authority database session user' USING ERRCODE = '22023';
    END IF;
    IF p_source_system_id IS NULL
       OR pg_catalog.octet_length(p_source_system_id) NOT BETWEEN 1 AND 128
       OR p_source_system_id <> pg_catalog.btrim(p_source_system_id)
       OR p_source_system_id ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid authority source_system_id' USING ERRCODE = '22023';
    END IF;
    IF p_source_native_id IS NULL
       OR pg_catalog.octet_length(p_source_native_id) NOT BETWEEN 1 AND 4096
       OR p_source_native_id <> pg_catalog.btrim(p_source_native_id)
       OR p_source_native_id ~ '[[:cntrl:]]' THEN
        RAISE EXCEPTION 'invalid authority source_native_id' USING ERRCODE = '22023';
    END IF;
    IF p_content_sha256 IS NULL OR p_content_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid authority content_sha256' USING ERRCODE = '22023';
    END IF;
    IF p_content_size IS NULL OR p_content_size NOT BETWEEN 0 AND 268435456 THEN
        RAISE EXCEPTION 'invalid authority content_size' USING ERRCODE = '22023';
    END IF;
    IF p_nonce IS NULL
       OR pg_catalog.octet_length(p_nonce) NOT BETWEEN 16 AND 128
       OR p_nonce <> pg_catalog.btrim(p_nonce)
       OR p_nonce !~ '^[A-Za-z0-9._:-]+$' THEN
        RAISE EXCEPTION 'invalid authority nonce' USING ERRCODE = '22023';
    END IF;
    IF p_claims_sha256 IS NULL OR p_claims_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid authority claims_sha256' USING ERRCODE = '22023';
    END IF;
    IF p_issued_at_unix IS NULL
       OR p_expires_at_unix IS NULL
       OR p_issued_at_unix < 0
       OR p_expires_at_unix <= p_issued_at_unix
       OR p_expires_at_unix - p_issued_at_unix > 300 THEN
        RAISE EXCEPTION 'invalid authority timestamps' USING ERRCODE = '22023';
    END IF;

    SELECT registrar.oid
      INTO v_registrar_role_id
      FROM pg_catalog.pg_roles AS registrar
     WHERE registrar.rolname = 'kf_authority_registrar'
       AND NOT registrar.rolcanlogin
       AND NOT registrar.rolsuper
       AND NOT registrar.rolbypassrls
       AND NOT registrar.rolinherit
       AND NOT registrar.rolcreatedb
       AND NOT registrar.rolcreaterole
       AND NOT registrar.rolreplication;
    IF NOT FOUND OR EXISTS (
      SELECT 1
        FROM pg_catalog.pg_auth_members AS registrar_membership
       WHERE registrar_membership.member = v_registrar_role_id
    ) THEN
        RAISE EXCEPTION 'authority registrar session denied' USING ERRCODE = '42501';
    END IF;

    SELECT login.oid,
           login.rolcanlogin
           AND NOT login.rolsuper
           AND NOT login.rolbypassrls
           AND NOT login.rolinherit
           AND NOT login.rolcreatedb
           AND NOT login.rolcreaterole
           AND NOT login.rolreplication
           AND NOT pg_catalog.has_schema_privilege(login.oid, 'public', 'CREATE')
           AND NOT pg_catalog.has_database_privilege(
             login.oid, pg_catalog.current_database(), 'CREATE'
           )
           AND EXISTS (
             SELECT 1
               FROM pg_catalog.pg_auth_members AS exact_membership
              WHERE exact_membership.member = login.oid
                AND exact_membership.roleid = v_registrar_role_id
                AND NOT exact_membership.admin_option
                AND NOT exact_membership.inherit_option
                AND exact_membership.set_option
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_auth_members AS any_membership
              WHERE any_membership.member = login.oid
                AND (
                  any_membership.roleid <> v_registrar_role_id
                  OR any_membership.admin_option
                  OR any_membership.inherit_option
                  OR NOT any_membership.set_option
                )
           )
           AND NOT EXISTS (
             SELECT 1 FROM pg_catalog.pg_database AS owned_database
              WHERE owned_database.datname = pg_catalog.current_database()
                AND owned_database.datdba = login.oid
           )
           AND NOT EXISTS (
             SELECT 1 FROM pg_catalog.pg_namespace AS owned_namespace
              WHERE owned_namespace.nspname = 'public'
                AND owned_namespace.nspowner = login.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_class AS owned_relation
               JOIN pg_catalog.pg_namespace AS owned_namespace
                 ON owned_namespace.oid = owned_relation.relnamespace
              WHERE owned_namespace.nspname = 'public'
                AND owned_relation.relowner = login.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_proc AS owned_function
               JOIN pg_catalog.pg_namespace AS owned_namespace
                 ON owned_namespace.oid = owned_function.pronamespace
              WHERE owned_namespace.nspname = 'public'
                AND owned_function.proowner = login.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_class AS direct_relation
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_relation.relnamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(direct_relation.relacl) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_acl.grantee = login.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_attribute AS direct_attribute
               JOIN pg_catalog.pg_class AS direct_relation
                 ON direct_relation.oid = direct_attribute.attrelid
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_relation.relnamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(direct_attribute.attacl) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_attribute.attnum > 0
                AND NOT direct_attribute.attisdropped
                AND direct_acl.grantee = login.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_proc AS direct_function
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_function.pronamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(direct_function.proacl) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_acl.grantee = login.oid
           )
      INTO v_session_role_id, v_registrar_session_safe
      FROM pg_catalog.pg_roles AS login
     WHERE login.rolname = SESSION_USER;
    IF NOT FOUND OR NOT COALESCE(v_registrar_session_safe, false) THEN
        RAISE EXCEPTION 'authority registrar session denied' USING ERRCODE = '42501';
    END IF;

    SELECT runtime.oid
      INTO v_runtime_role_id
      FROM pg_catalog.pg_roles AS runtime
     WHERE runtime.rolname = 'kf_runtime'
       AND NOT runtime.rolcanlogin
       AND NOT runtime.rolsuper
       AND NOT runtime.rolbypassrls
       AND NOT runtime.rolinherit
       AND NOT runtime.rolcreatedb
       AND NOT runtime.rolcreaterole
       AND NOT runtime.rolreplication;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'runtime authority role is absent or unsafe' USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_auth_members AS runtime_membership
       WHERE runtime_membership.member = v_runtime_role_id
    ) THEN
        RAISE EXCEPTION 'runtime authority role is absent or unsafe' USING ERRCODE = '42501';
    END IF;

    SELECT target.oid,
           target.rolcanlogin
           AND NOT target.rolsuper
           AND NOT target.rolbypassrls
           AND NOT target.rolinherit
           AND NOT target.rolcreatedb
           AND NOT target.rolcreaterole
           AND NOT target.rolreplication
           AND NOT pg_catalog.has_schema_privilege(target.oid, 'public', 'CREATE')
           AND NOT pg_catalog.has_database_privilege(
             target.oid, pg_catalog.current_database(), 'CREATE'
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_class AS direct_relation
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_relation.relnamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(direct_relation.relacl) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_acl.grantee = target.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_attribute AS direct_attribute
               JOIN pg_catalog.pg_class AS direct_relation
                 ON direct_relation.oid = direct_attribute.attrelid
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_relation.relnamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(direct_attribute.attacl) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_attribute.attnum > 0
                AND NOT direct_attribute.attisdropped
                AND direct_acl.grantee = target.oid
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_proc AS direct_function
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_function.pronamespace
               CROSS JOIN LATERAL pg_catalog.aclexplode(
                 COALESCE(
                   direct_function.proacl,
                   pg_catalog.acldefault('f'::"char", direct_function.proowner)
                 )
               ) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                AND direct_acl.grantee IN (target.oid, 0)
           )
           AND EXISTS (
             SELECT 1
               FROM pg_catalog.pg_auth_members AS exact_membership
              WHERE exact_membership.member = target.oid
                AND exact_membership.roleid = v_runtime_role_id
                AND NOT exact_membership.admin_option
                AND NOT exact_membership.inherit_option
                AND exact_membership.set_option
           )
           AND NOT EXISTS (
             SELECT 1
               FROM pg_catalog.pg_auth_members AS any_membership
              WHERE any_membership.member = target.oid
                AND (
                  any_membership.roleid <> v_runtime_role_id
                  OR any_membership.admin_option
                  OR any_membership.inherit_option
                  OR NOT any_membership.set_option
                )
           )
      INTO v_target_role_id, v_target_role_safe
      FROM pg_catalog.pg_roles AS target
     WHERE target.rolname = p_database_session_user;

    IF NOT FOUND OR NOT v_target_role_safe THEN
        RAISE EXCEPTION 'authority target database session role is absent or unsafe'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_database AS database
       WHERE database.datname = pg_catalog.current_database()
         AND database.datdba = v_target_role_id
    ) OR EXISTS (
      SELECT 1
        FROM pg_catalog.pg_namespace AS namespace
       WHERE namespace.nspname = 'public'
         AND namespace.nspowner = v_target_role_id
    ) OR EXISTS (
      SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
       WHERE namespace.nspname = 'public'
         AND relation.relowner = v_target_role_id
    ) OR EXISTS (
      SELECT 1
        FROM pg_catalog.pg_proc AS function
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
       WHERE namespace.nspname = 'public'
         AND function.proowner = v_target_role_id
    ) THEN
        RAISE EXCEPTION 'authority target database session role owns protected objects'
            USING ERRCODE = '42501';
    END IF;

    SELECT domain.authority_domain_id
      INTO v_current_authority_domain_id
      FROM public.kf_authority_domain AS domain
     WHERE domain.singleton
     FOR SHARE;
    IF NOT FOUND
       OR v_current_authority_domain_id IS DISTINCT FROM p_authority_domain_id THEN
        RAISE EXCEPTION 'authority domain denied' USING ERRCODE = '42501';
    END IF;

    -- An exact, already durable registration is a read-only retry and remains recoverable after
    -- authority expiry. Conflicting unique keys are always the same permission denial.
    SELECT pg_catalog.count(*),
           COALESCE(pg_catalog.bool_and(
             existing.grant_id = p_grant_id
             AND existing.authority_domain_id = p_authority_domain_id
             AND existing.issuer = p_issuer
             AND existing.key_id = p_key_id
             AND existing.actor = p_actor
             AND existing.project_id = p_project_id
             AND existing.database_session_user = p_database_session_user
             AND existing.database_session_role_oid = v_target_role_id
             AND existing.source_system_id = p_source_system_id
             AND existing.source_native_id = p_source_native_id
             AND existing.content_sha256 = p_content_sha256
             AND existing.content_size = p_content_size
             AND existing.nonce = p_nonce
             AND existing.claims_sha256 = p_claims_sha256
             AND existing.issued_at_unix = p_issued_at_unix
             AND existing.expires_at_unix = p_expires_at_unix
           ), false)
      INTO v_collision_count, v_exact_retry
      FROM public.kf_ingest_authority_grant AS existing
     WHERE existing.grant_id = p_grant_id
        OR (
          existing.issuer = p_issuer
          AND existing.key_id = p_key_id
          AND existing.nonce = p_nonce
        )
        OR existing.claims_sha256 = p_claims_sha256;
    IF v_collision_count > 0 THEN
        IF v_collision_count = 1 AND v_exact_retry THEN
            RETURN p_grant_id;
        END IF;
        RAISE EXCEPTION 'authority grant registration conflict' USING ERRCODE = '42501';
    END IF;

    v_now_unix := pg_catalog.floor(
      pg_catalog.date_part('epoch', pg_catalog.clock_timestamp())
    )::bigint;
    IF p_issued_at_unix > v_now_unix OR p_expires_at_unix <= v_now_unix THEN
        RAISE EXCEPTION 'authority grant is not currently valid' USING ERRCODE = '42501';
    END IF;

    INSERT INTO public.kf_ingest_authority_grant(
      grant_id, authority_domain_id, issuer, key_id, actor, project_id, database_session_user,
      database_session_role_oid,
      source_system_id, source_native_id, content_sha256, content_size,
      nonce, claims_sha256, issued_at_unix, expires_at_unix
    ) VALUES (
      p_grant_id, p_authority_domain_id, p_issuer, p_key_id, p_actor, p_project_id,
      p_database_session_user, v_target_role_id,
      p_source_system_id, p_source_native_id, p_content_sha256, p_content_size,
      p_nonce, p_claims_sha256, p_issued_at_unix, p_expires_at_unix
    )
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    IF v_inserted = 1 THEN
        RETURN p_grant_id;
    END IF;

    -- Every unique key must resolve to the same row and every immutable signed field must match.
    -- All other collisions deliberately produce the same error.
    SELECT pg_catalog.count(*),
           COALESCE(pg_catalog.bool_and(
             existing.grant_id = p_grant_id
             AND existing.authority_domain_id = p_authority_domain_id
             AND existing.issuer = p_issuer
             AND existing.key_id = p_key_id
             AND existing.actor = p_actor
             AND existing.project_id = p_project_id
             AND existing.database_session_user = p_database_session_user
             AND existing.database_session_role_oid = v_target_role_id
             AND existing.source_system_id = p_source_system_id
             AND existing.source_native_id = p_source_native_id
             AND existing.content_sha256 = p_content_sha256
             AND existing.content_size = p_content_size
             AND existing.nonce = p_nonce
             AND existing.claims_sha256 = p_claims_sha256
             AND existing.issued_at_unix = p_issued_at_unix
             AND existing.expires_at_unix = p_expires_at_unix
           ), false)
      INTO v_collision_count, v_exact_retry
      FROM public.kf_ingest_authority_grant AS existing
     WHERE existing.grant_id = p_grant_id
        OR (
          existing.issuer = p_issuer
          AND existing.key_id = p_key_id
          AND existing.nonce = p_nonce
        )
        OR existing.claims_sha256 = p_claims_sha256;

    IF v_collision_count = 1 AND v_exact_retry THEN
        RETURN p_grant_id;
    END IF;
    RAISE EXCEPTION 'authority grant registration conflict' USING ERRCODE = '42501';
END
$function$;

GRANT CREATE ON SCHEMA public TO kf_authority_owner;
ALTER FUNCTION public.kf_register_ingest_authority_grant(
  uuid, uuid, text, text, text, uuid, text, text, text, text, bigint, text, text, bigint, bigint
) OWNER TO kf_authority_owner;
REVOKE CREATE ON SCHEMA public FROM kf_authority_owner;

-- Retire the caller-scoped function.  Reapplication accepts only the already-renamed state;
-- having both names or neither name is migration drift and fails closed.
DO $rename_old_ingest$
DECLARE
  old_function regprocedure := pg_catalog.to_regprocedure(
    'public.kf_ingest_observation(uuid,uuid,uuid,text,text,text,text,bigint,text)'
  );
  internal_function regprocedure := pg_catalog.to_regprocedure(
    'public.kf_ingest_observation_internal(uuid,uuid,uuid,text,text,text,text,bigint,text)'
  );
BEGIN
  IF old_function IS NOT NULL AND internal_function IS NULL THEN
    REVOKE ALL ON FUNCTION public.kf_ingest_observation(
      uuid, uuid, uuid, text, text, text, text, bigint, text
    ) FROM PUBLIC, kf_runtime;
    ALTER FUNCTION public.kf_ingest_observation(
      uuid, uuid, uuid, text, text, text, text, bigint, text
    ) RENAME TO kf_ingest_observation_internal;
  ELSIF old_function IS NULL AND internal_function IS NOT NULL THEN
    NULL;
  ELSE
    RAISE EXCEPTION 'caller-scoped ingest function rename state is invalid';
  END IF;
END
$rename_old_ingest$;

-- PostgreSQL treats RETURNS TABLE names as PL/pgSQL variables.  The v003 function's final
-- `ON CONFLICT (occurrence_id, ...)` is therefore ambiguous on first real execution.  Recompile
-- the renamed internal function with the exact named constraint so the new authority wrapper is
-- executable without weakening plpgsql.variable_conflict globally.
CREATE OR REPLACE FUNCTION public.kf_ingest_observation_internal(
    p_project_id uuid,
    p_occurrence_id uuid,
    p_version_id uuid,
    p_source_system_id text,
    p_source_native_id text,
    p_source_revision_key text,
    p_sha256 text,
    p_byte_size bigint,
    p_storage_uri text
) RETURNS TABLE (
    blob_id uuid,
    occurrence_id uuid,
    version_id uuid,
    parent_version_id uuid,
    blob_created boolean,
    occurrence_created boolean,
    version_created boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = on
SET lock_timeout = '5s'
SET statement_timeout = '30s'
AS $function$
DECLARE
    v_allowed_projects uuid[];
    v_blob_id uuid;
    v_occurrence_id uuid;
    v_version_id uuid;
    v_parent_version_id uuid;
    v_existing_blob_id uuid;
    v_existing_byte_size bigint;
    v_existing_storage_uri text;
    v_lineage_tails uuid[];
    v_rows bigint;
BEGIN
    v_allowed_projects := public.kf_allowed_projects();
    IF pg_catalog.cardinality(v_allowed_projects) <> 1
       OR v_allowed_projects[1] IS DISTINCT FROM p_project_id THEN
        RAISE EXCEPTION 'one exact transaction-local project context is required'
            USING ERRCODE = '42501';
    END IF;

    IF p_project_id IS NULL
       OR p_project_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_occurrence_id IS NULL
       OR p_occurrence_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_version_id IS NULL
       OR p_version_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RAISE EXCEPTION 'project_id, occurrence_id, and version_id must be non-nil'
            USING ERRCODE = '22023';
    END IF;
    IF p_source_system_id IS NULL
       OR p_source_system_id <> pg_catalog.btrim(p_source_system_id)
       OR p_source_system_id = ''
       OR p_source_system_id ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_source_system_id) > 128 THEN
        RAISE EXCEPTION 'invalid source_system_id' USING ERRCODE = '22023';
    END IF;
    IF p_source_native_id IS NULL
       OR p_source_native_id <> pg_catalog.btrim(p_source_native_id)
       OR p_source_native_id = ''
       OR p_source_native_id ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_source_native_id) > 4096 THEN
        RAISE EXCEPTION 'invalid source_native_id' USING ERRCODE = '22023';
    END IF;
    IF p_source_revision_key IS NULL
       OR p_source_revision_key <> pg_catalog.btrim(p_source_revision_key)
       OR p_source_revision_key = ''
       OR p_source_revision_key ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_source_revision_key) > 4096 THEN
        RAISE EXCEPTION 'invalid source_revision_key' USING ERRCODE = '22023';
    END IF;
    IF p_sha256 IS NULL OR p_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid sha256' USING ERRCODE = '22023';
    END IF;
    IF p_byte_size IS NULL OR p_byte_size < 0 OR p_byte_size > 268435456 THEN
        RAISE EXCEPTION 'byte_size is outside the supported intake bound'
            USING ERRCODE = '22023';
    END IF;
    IF p_storage_uri IS NULL
       OR p_storage_uri <> pg_catalog.btrim(p_storage_uri)
       OR p_storage_uri = ''
       OR p_storage_uri ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_storage_uri) > 4096 THEN
        RAISE EXCEPTION 'invalid storage_uri' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.project AS scoped_project
         WHERE scoped_project.project_id = p_project_id
    ) THEN
        RAISE EXCEPTION 'project is absent or outside the current scope'
            USING ERRCODE = '23503';
    END IF;

    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_project_id::text || ':' ||
            pg_catalog.octet_length(p_source_system_id)::text || ':' ||
            p_source_system_id || ':' ||
            pg_catalog.octet_length(p_source_native_id)::text || ':' ||
            p_source_native_id,
            0
        )
    );

    v_blob_id := pg_catalog.gen_random_uuid();
    INSERT INTO public.raw_blob(blob_id, sha256, byte_size, storage_uri)
    VALUES (v_blob_id, p_sha256, p_byte_size, p_storage_uri)
    ON CONFLICT (sha256) DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    blob_created := v_rows = 1;

    IF NOT blob_created THEN
        SELECT existing_blob.blob_id, existing_blob.byte_size, existing_blob.storage_uri
          INTO STRICT v_blob_id, v_existing_byte_size, v_existing_storage_uri
          FROM public.raw_blob AS existing_blob
         WHERE existing_blob.sha256 = p_sha256;
        IF v_existing_byte_size IS DISTINCT FROM p_byte_size
           OR v_existing_storage_uri IS DISTINCT FROM p_storage_uri THEN
            RAISE EXCEPTION 'sha256 already exists with conflicting immutable metadata'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    v_occurrence_id := p_occurrence_id;
    INSERT INTO public.artifact_occurrence(
        occurrence_id, project_id, source_system_id, source_native_id, blob_id
    ) VALUES (
        v_occurrence_id, p_project_id, p_source_system_id, p_source_native_id, v_blob_id
    )
    ON CONFLICT (project_id, source_system_id, source_native_id) DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    occurrence_created := v_rows = 1;

    IF NOT occurrence_created THEN
        SELECT existing_occurrence.occurrence_id
          INTO STRICT v_occurrence_id
          FROM public.artifact_occurrence AS existing_occurrence
         WHERE existing_occurrence.project_id = p_project_id
           AND existing_occurrence.source_system_id = p_source_system_id
           AND existing_occurrence.source_native_id = p_source_native_id;
    END IF;

    SELECT existing_version.version_id,
           existing_version.blob_id,
           existing_version.parent_version_id
      INTO v_version_id, v_existing_blob_id, v_parent_version_id
      FROM public.artifact_version AS existing_version
     WHERE existing_version.occurrence_id = v_occurrence_id
       AND existing_version.source_revision_key = p_source_revision_key;
    IF FOUND THEN
        IF v_existing_blob_id IS DISTINCT FROM v_blob_id THEN
            RAISE EXCEPTION 'source revision already exists for a different blob'
                USING ERRCODE = '23505';
        END IF;
        version_created := false;
        blob_id := v_blob_id;
        occurrence_id := v_occurrence_id;
        version_id := v_version_id;
        parent_version_id := v_parent_version_id;
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT pg_catalog.array_agg(tail_version.version_id ORDER BY tail_version.version_id)
      INTO v_lineage_tails
      FROM public.artifact_version AS tail_version
     WHERE tail_version.occurrence_id = v_occurrence_id
       AND NOT EXISTS (
           SELECT 1
             FROM public.artifact_version AS child_version
            WHERE child_version.occurrence_id = v_occurrence_id
              AND child_version.parent_version_id = tail_version.version_id
       );
    IF v_lineage_tails IS NULL AND EXISTS (
        SELECT 1
          FROM public.artifact_version AS existing_lineage
         WHERE existing_lineage.occurrence_id = v_occurrence_id
    ) THEN
        RAISE EXCEPTION 'version lineage has no tail' USING ERRCODE = '23000';
    ELSIF pg_catalog.cardinality(v_lineage_tails) > 1 THEN
        RAISE EXCEPTION 'version lineage has multiple tails' USING ERRCODE = '23000';
    END IF;
    v_parent_version_id := v_lineage_tails[1];

    v_version_id := p_version_id;
    INSERT INTO public.artifact_version(
        version_id, occurrence_id, blob_id, source_revision_key, parent_version_id
    ) VALUES (
        v_version_id, v_occurrence_id, v_blob_id, p_source_revision_key, v_parent_version_id
    )
    ON CONFLICT ON CONSTRAINT artifact_version_occurrence_id_source_revision_key_key
    DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    version_created := v_rows = 1;

    IF NOT version_created THEN
        SELECT existing_version.version_id,
               existing_version.blob_id,
               existing_version.parent_version_id
          INTO STRICT v_version_id, v_existing_blob_id, v_parent_version_id
          FROM public.artifact_version AS existing_version
         WHERE existing_version.occurrence_id = v_occurrence_id
           AND existing_version.source_revision_key = p_source_revision_key;
        IF v_existing_blob_id IS DISTINCT FROM v_blob_id THEN
            RAISE EXCEPTION 'source revision already exists for a different blob'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    blob_id := v_blob_id;
    occurrence_id := v_occurrence_id;
    version_id := v_version_id;
    parent_version_id := v_parent_version_id;
    RETURN NEXT;
END
$function$;

-- Ownership is reasserted before the wrapper is created.  The internal function remains
-- unreachable by the runtime and is callable only by the wrapper's NOLOGIN owner.
GRANT CREATE ON SCHEMA public TO kf_ingest_owner;
ALTER FUNCTION public.kf_ingest_observation_internal(
  uuid, uuid, uuid, text, text, text, text, bigint, text
) OWNER TO kf_ingest_owner;
REVOKE CREATE ON SCHEMA public FROM kf_ingest_owner;
REVOKE ALL ON FUNCTION public.kf_ingest_observation_internal(
  uuid, uuid, uuid, text, text, text, text, bigint, text
) FROM PUBLIC, kf_runtime, kf_authority_registrar;
GRANT EXECUTE ON FUNCTION public.kf_ingest_observation_internal(
  uuid, uuid, uuid, text, text, text, text, bigint, text
) TO kf_ingest_owner;

REVOKE ALL ON FUNCTION public.kf_allowed_projects() FROM PUBLIC, kf_runtime,
                                                               kf_authority_registrar;
GRANT EXECUTE ON FUNCTION public.kf_allowed_projects() TO kf_ingest_owner;

CREATE OR REPLACE FUNCTION public.kf_ingest_authorized(
    p_grant_id uuid,
    p_authority_domain_id uuid
) RETURNS TABLE (
    occurrence_id uuid,
    version_id uuid,
    parent_version_id uuid
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
SET row_security = on
SET lock_timeout = '5s'
SET statement_timeout = '30s'
AS $function$
DECLARE
    v_grant public.kf_ingest_authority_grant%ROWTYPE;
    v_grant_found boolean;
    v_now_unix bigint;
    v_session_role_id oid;
    v_session_safe boolean := false;
    v_applied_project text;
    v_outcome RECORD;
    v_updated bigint;
    v_occurrence_id uuid;
    v_version_id uuid;
    v_current_authority_domain_id uuid;
    v_authority_domain_found boolean;
BEGIN
    IF p_grant_id IS NULL
       OR p_grant_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_authority_domain_id IS NULL
       OR p_authority_domain_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501';
    END IF;

    SELECT domain.authority_domain_id
      INTO v_current_authority_domain_id
      FROM public.kf_authority_domain AS domain
     WHERE domain.singleton
     FOR SHARE;
    v_authority_domain_found := FOUND;

    SELECT authority_grant.*
      INTO v_grant
      FROM public.kf_ingest_authority_grant AS authority_grant
     WHERE authority_grant.grant_id = p_grant_id
     FOR UPDATE;
    v_grant_found := FOUND;

    v_now_unix := pg_catalog.floor(
      pg_catalog.date_part('epoch', pg_catalog.clock_timestamp())
    )::bigint;
    IF v_grant_found THEN
      SELECT login.oid,
             login.rolcanlogin
             AND NOT login.rolsuper
             AND NOT login.rolbypassrls
             AND NOT login.rolinherit
             AND NOT login.rolcreatedb
             AND NOT login.rolcreaterole
             AND NOT login.rolreplication
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_database AS owned_database
                WHERE owned_database.datname = pg_catalog.current_database()
                  AND owned_database.datdba = login.oid
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_namespace AS owned_namespace
                WHERE owned_namespace.nspname = 'public'
                  AND owned_namespace.nspowner = login.oid
             )
             AND NOT pg_catalog.has_schema_privilege(login.oid, 'public', 'CREATE')
             AND NOT pg_catalog.has_database_privilege(
               login.oid, pg_catalog.current_database(), 'CREATE'
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_class AS owned_relation
                 JOIN pg_catalog.pg_namespace AS owned_namespace
                   ON owned_namespace.oid = owned_relation.relnamespace
                WHERE owned_namespace.nspname = 'public'
                  AND owned_relation.relowner = login.oid
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_proc AS owned_function
                 JOIN pg_catalog.pg_namespace AS owned_namespace
                   ON owned_namespace.oid = owned_function.pronamespace
                WHERE owned_namespace.nspname = 'public'
                  AND owned_function.proowner = login.oid
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_class AS direct_relation
                 JOIN pg_catalog.pg_namespace AS direct_namespace
                   ON direct_namespace.oid = direct_relation.relnamespace
                 CROSS JOIN LATERAL pg_catalog.aclexplode(direct_relation.relacl) AS direct_acl
                WHERE direct_namespace.nspname = 'public'
                  AND direct_acl.grantee = login.oid
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_attribute AS direct_attribute
                 JOIN pg_catalog.pg_class AS direct_relation
                   ON direct_relation.oid = direct_attribute.attrelid
                 JOIN pg_catalog.pg_namespace AS direct_namespace
                   ON direct_namespace.oid = direct_relation.relnamespace
                 CROSS JOIN LATERAL pg_catalog.aclexplode(direct_attribute.attacl) AS direct_acl
                WHERE direct_namespace.nspname = 'public'
                  AND direct_attribute.attnum > 0
                  AND NOT direct_attribute.attisdropped
                  AND direct_acl.grantee = login.oid
             )
             AND NOT EXISTS (
               SELECT 1
               FROM pg_catalog.pg_proc AS direct_function
               JOIN pg_catalog.pg_namespace AS direct_namespace
                 ON direct_namespace.oid = direct_function.pronamespace
                 CROSS JOIN LATERAL pg_catalog.aclexplode(
                   COALESCE(
                     direct_function.proacl,
                     pg_catalog.acldefault('f'::"char", direct_function.proowner)
                   )
                 ) AS direct_acl
              WHERE direct_namespace.nspname = 'public'
                  AND direct_acl.grantee IN (login.oid, 0)
             )
             AND EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_proc AS allowed_function
                 JOIN pg_catalog.pg_namespace AS allowed_namespace
                   ON allowed_namespace.oid = allowed_function.pronamespace
                 JOIN pg_catalog.pg_roles AS runtime
                   ON runtime.rolname = 'kf_runtime'
                 CROSS JOIN LATERAL pg_catalog.aclexplode(
                   COALESCE(
                     allowed_function.proacl,
                     pg_catalog.acldefault('f'::"char", allowed_function.proowner)
                   )
                 ) AS allowed_acl
                WHERE allowed_namespace.nspname = 'public'
                  AND allowed_function.oid = pg_catalog.to_regprocedure(
                     'public.kf_ingest_authorized(uuid,uuid)'
                  )
                  AND allowed_acl.grantee = runtime.oid
                  AND allowed_acl.privilege_type = 'EXECUTE'
                  AND NOT allowed_acl.is_grantable
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_proc AS granted_function
                 JOIN pg_catalog.pg_namespace AS granted_namespace
                   ON granted_namespace.oid = granted_function.pronamespace
                 JOIN pg_catalog.pg_roles AS runtime
                   ON runtime.rolname = 'kf_runtime'
                 CROSS JOIN LATERAL pg_catalog.aclexplode(
                   COALESCE(
                     granted_function.proacl,
                     pg_catalog.acldefault('f'::"char", granted_function.proowner)
                   )
                 ) AS granted_acl
                WHERE granted_namespace.nspname = 'public'
                  AND granted_acl.grantee = runtime.oid
                  AND (
                    granted_function.oid IS DISTINCT FROM pg_catalog.to_regprocedure(
                       'public.kf_ingest_authorized(uuid,uuid)'
                    )
                    OR granted_acl.privilege_type <> 'EXECUTE'
                    OR granted_acl.is_grantable
                  )
             )
             AND EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_auth_members AS exact_membership
                 JOIN pg_catalog.pg_roles AS runtime
                   ON runtime.oid = exact_membership.roleid
                  AND runtime.rolname = 'kf_runtime'
                  AND NOT runtime.rolcanlogin
                  AND NOT runtime.rolsuper
                  AND NOT runtime.rolbypassrls
                  AND NOT runtime.rolinherit
                  AND NOT runtime.rolcreatedb
                  AND NOT runtime.rolcreaterole
                  AND NOT runtime.rolreplication
                WHERE exact_membership.member = login.oid
                  AND NOT exact_membership.admin_option
                  AND NOT exact_membership.inherit_option
                  AND exact_membership.set_option
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_auth_members AS any_membership
                 LEFT JOIN pg_catalog.pg_roles AS runtime
                   ON runtime.oid = any_membership.roleid
                  AND runtime.rolname = 'kf_runtime'
                WHERE any_membership.member = login.oid
                  AND (
                    runtime.oid IS NULL
                    OR any_membership.admin_option
                    OR any_membership.inherit_option
                    OR NOT any_membership.set_option
                  )
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_auth_members AS runtime_membership
                 JOIN pg_catalog.pg_roles AS runtime
                   ON runtime.oid = runtime_membership.member
                  AND runtime.rolname = 'kf_runtime'
             )
             AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_roles AS runtime
                WHERE runtime.rolname = 'kf_runtime'
                  AND (
                    pg_catalog.has_schema_privilege(runtime.oid, 'public', 'CREATE')
                    OR pg_catalog.has_database_privilege(
                      runtime.oid, pg_catalog.current_database(), 'CREATE'
                    )
                    OR EXISTS (
                      SELECT 1 FROM pg_catalog.pg_database AS owned_database
                       WHERE owned_database.datname = pg_catalog.current_database()
                         AND owned_database.datdba = runtime.oid
                    )
                    OR EXISTS (
                      SELECT 1 FROM pg_catalog.pg_namespace AS owned_namespace
                       WHERE owned_namespace.nspname = 'public'
                         AND owned_namespace.nspowner = runtime.oid
                    )
                    OR EXISTS (
                      SELECT 1
                        FROM pg_catalog.pg_class AS owned_relation
                        JOIN pg_catalog.pg_namespace AS owned_namespace
                          ON owned_namespace.oid = owned_relation.relnamespace
                       WHERE owned_namespace.nspname = 'public'
                         AND owned_relation.relowner = runtime.oid
                    )
                    OR EXISTS (
                      SELECT 1
                        FROM pg_catalog.pg_proc AS owned_function
                        JOIN pg_catalog.pg_namespace AS owned_namespace
                          ON owned_namespace.oid = owned_function.pronamespace
                       WHERE owned_namespace.nspname = 'public'
                         AND owned_function.proowner = runtime.oid
                    )
                  )
             )
        INTO v_session_role_id, v_session_safe
        FROM pg_catalog.pg_roles AS login
       WHERE login.rolname = SESSION_USER;
    END IF;

    IF NOT v_authority_domain_found
       OR NOT v_grant_found
       OR v_current_authority_domain_id IS DISTINCT FROM p_authority_domain_id
       OR v_grant.authority_domain_id IS DISTINCT FROM v_current_authority_domain_id
       OR v_grant.database_session_user IS DISTINCT FROM SESSION_USER::text
       OR v_grant.database_session_role_oid IS DISTINCT FROM v_session_role_id
       OR NOT COALESCE(v_session_safe, false) THEN
        RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501';
    END IF;

    IF v_grant.consumed_at IS NOT NULL THEN
        occurrence_id := v_grant.outcome_occurrence_id;
        version_id := v_grant.outcome_version_id;
        parent_version_id := v_grant.outcome_parent_version_id;
        RETURN NEXT;
        RETURN;
    END IF;

    IF v_grant.revoked_at IS NOT NULL OR v_now_unix >= v_grant.expires_at_unix THEN
        RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501';
    END IF;

    v_occurrence_id := pg_catalog.gen_random_uuid();
    v_version_id := pg_catalog.gen_random_uuid();

    v_applied_project := pg_catalog.set_config(
      'app.project_ids', v_grant.project_id::text, true
    );
    IF v_applied_project IS DISTINCT FROM v_grant.project_id::text THEN
        RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501';
    END IF;

    SELECT internal.blob_id,
           internal.occurrence_id,
           internal.version_id,
           internal.parent_version_id,
           internal.blob_created,
           internal.occurrence_created,
           internal.version_created
      INTO STRICT v_outcome
      FROM public.kf_ingest_observation_internal(
        v_grant.project_id,
        v_occurrence_id,
        v_version_id,
        v_grant.source_system_id,
        v_grant.source_native_id,
        v_grant.content_sha256,
        v_grant.content_sha256,
        v_grant.content_size,
        'cas://sha256/' || v_grant.content_sha256
      ) AS internal;

    UPDATE public.kf_ingest_authority_grant AS authority_grant
       SET consumed_at = pg_catalog.clock_timestamp(),
           requested_occurrence_id = v_occurrence_id,
           requested_version_id = v_version_id,
           outcome_blob_id = v_outcome.blob_id,
           outcome_occurrence_id = v_outcome.occurrence_id,
           outcome_version_id = v_outcome.version_id,
           outcome_parent_version_id = v_outcome.parent_version_id,
           outcome_blob_created = v_outcome.blob_created,
           outcome_occurrence_created = v_outcome.occurrence_created,
           outcome_version_created = v_outcome.version_created
     WHERE authority_grant.grant_id = v_grant.grant_id
       AND authority_grant.consumed_at IS NULL;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RAISE EXCEPTION 'ingest authority denied' USING ERRCODE = '42501';
    END IF;

    occurrence_id := v_outcome.occurrence_id;
    version_id := v_outcome.version_id;
    parent_version_id := v_outcome.parent_version_id;
    RETURN NEXT;
END
$function$;

GRANT CREATE ON SCHEMA public TO kf_ingest_owner;
ALTER FUNCTION public.kf_ingest_authorized(uuid, uuid) OWNER TO kf_ingest_owner;
REVOKE CREATE ON SCHEMA public FROM kf_ingest_owner;

-- Reset all ambient access before granting the two narrow entry points.  In particular, a
-- runtime session may still set arbitrary custom GUC text, but it can neither read raw tables nor
-- invoke the internal project-parameter function, so that text carries no authority.
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_runtime;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM kf_authority_registrar;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM kf_runtime;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM kf_authority_registrar;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM kf_runtime;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM kf_authority_registrar;

-- A named grantee from an older deployment must not retain EXECUTE when the caller-scoped
-- function is renamed. Reset every non-owner ACL on the complete authority surface, then grant
-- the exact allowlist below.
DO $function_acl_reset$
DECLARE
  stale_acl RECORD;
  revoke_sql text;
BEGIN
  FOR stale_acl IN
    SELECT DISTINCT namespace.nspname AS schema_name,
           function.proname AS function_name,
           pg_catalog.pg_get_function_identity_arguments(function.oid) AS identity_arguments,
           acl.grantee,
           grantee_role.rolname AS grantee_name
      FROM pg_catalog.pg_proc AS function
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
      CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
          function.proacl,
          pg_catalog.acldefault('f'::"char", function.proowner)
        )
      ) AS acl
      LEFT JOIN pg_catalog.pg_roles AS grantee_role ON grantee_role.oid = acl.grantee
     WHERE function.oid IN (
       pg_catalog.to_regprocedure(
         'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)'
       ),
       pg_catalog.to_regprocedure(
         'public.kf_ingest_observation_internal(uuid,uuid,uuid,text,text,text,text,bigint,text)'
       ),
       pg_catalog.to_regprocedure('public.kf_allowed_projects()'),
       pg_catalog.to_regprocedure('public.kf_ingest_authorized(uuid,uuid)')
     )
       AND acl.grantee <> function.proowner
  LOOP
    IF stale_acl.grantee = 0 THEN
      revoke_sql := pg_catalog.format(
        'REVOKE ALL PRIVILEGES ON FUNCTION %I.%I(%s) FROM PUBLIC',
        stale_acl.schema_name,
        stale_acl.function_name,
        stale_acl.identity_arguments
      );
    ELSIF stale_acl.grantee_name IS NOT NULL THEN
      revoke_sql := pg_catalog.format(
        'REVOKE ALL PRIVILEGES ON FUNCTION %I.%I(%s) FROM %I',
        stale_acl.schema_name,
        stale_acl.function_name,
        stale_acl.identity_arguments,
        stale_acl.grantee_name
      );
    ELSE
      RAISE EXCEPTION 'authority function ACL references an unknown role';
    END IF;
    EXECUTE revoke_sql;
  END LOOP;
END
$function_acl_reset$;

-- Table-level REVOKE does not remove column-only grants.  Remove those separately so an old
-- direct column ACL cannot outlive this boundary migration.
DO $column_acl_reset$
DECLARE
  protected_column RECORD;
BEGIN
  FOR protected_column IN
    SELECT namespace.nspname AS schema_name,
           relation.relname AS relation_name,
           attribute.attname AS column_name
      FROM pg_catalog.pg_attribute AS attribute
      JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'public'
       AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
       AND attribute.attnum > 0
       AND NOT attribute.attisdropped
  LOOP
    EXECUTE pg_catalog.format(
      'REVOKE SELECT (%I) ON TABLE %I.%I FROM PUBLIC, kf_runtime, kf_authority_registrar',
      protected_column.column_name,
      protected_column.schema_name,
      protected_column.relation_name
    );
    EXECUTE pg_catalog.format(
      'REVOKE INSERT (%I) ON TABLE %I.%I FROM PUBLIC, kf_runtime, kf_authority_registrar',
      protected_column.column_name,
      protected_column.schema_name,
      protected_column.relation_name
    );
    EXECUTE pg_catalog.format(
      'REVOKE UPDATE (%I) ON TABLE %I.%I FROM PUBLIC, kf_runtime, kf_authority_registrar',
      protected_column.column_name,
      protected_column.schema_name,
      protected_column.relation_name
    );
    EXECUTE pg_catalog.format(
      'REVOKE REFERENCES (%I) ON TABLE %I.%I FROM PUBLIC, kf_runtime, kf_authority_registrar',
      protected_column.column_name,
      protected_column.schema_name,
      protected_column.relation_name
    );
  END LOOP;
END
$column_acl_reset$;

REVOKE ALL PRIVILEGES ON public.kf_ingest_authority_grant FROM PUBLIC, kf_runtime,
                                                                  kf_authority_registrar;
REVOKE ALL PRIVILEGES ON public.kf_authority_domain FROM PUBLIC, kf_runtime,
                                                            kf_authority_registrar;
GRANT SELECT ON public.kf_authority_domain TO kf_ingest_owner;
-- PostgreSQL requires some UPDATE privilege for SELECT ... FOR SHARE.  Restrict it to the
-- non-security timestamp column; the NOLOGIN owner cannot rotate authority_domain_id.
GRANT UPDATE (provisioned_at) ON public.kf_authority_domain TO kf_ingest_owner;
GRANT SELECT ON public.kf_ingest_authority_grant TO kf_ingest_owner;
GRANT UPDATE (
  consumed_at,
  requested_occurrence_id,
  requested_version_id,
  outcome_blob_id,
  outcome_occurrence_id,
  outcome_version_id,
  outcome_parent_version_id,
  outcome_blob_created,
  outcome_occurrence_created,
  outcome_version_created
) ON public.kf_ingest_authority_grant TO kf_ingest_owner;

GRANT USAGE ON SCHEMA public TO kf_runtime, kf_ingest_owner,
                                      kf_authority_owner, kf_authority_registrar;
REVOKE CREATE ON SCHEMA public FROM kf_runtime, kf_ingest_owner,
                                       kf_authority_owner, kf_authority_registrar;

GRANT EXECUTE ON FUNCTION public.kf_register_ingest_authority_grant(
  uuid, uuid, text, text, text, uuid, text, text, text, text, bigint, text, text, bigint, bigint
) TO kf_authority_registrar;
GRANT EXECUTE ON FUNCTION public.kf_allowed_projects() TO kf_ingest_owner;
GRANT EXECUTE ON FUNCTION public.kf_ingest_observation_internal(
  uuid, uuid, uuid, text, text, text, text, bigint, text
) TO kf_ingest_owner;
GRANT EXECUTE ON FUNCTION public.kf_ingest_authorized(uuid, uuid) TO kf_runtime;

-- Final migration-time drift proof.  Runtime privileges inherited through PUBLIC are included by
-- has_*_privilege(), so these checks also catch accidental ambient grants.
DO $final_authority_boundary_guard$
DECLARE
  authority_owner oid;
  authority_registrar oid;
  ingest_owner oid;
  domain_table_owner name;
  grant_table_owner name;
BEGIN
  SELECT role.oid
    INTO authority_owner
    FROM pg_catalog.pg_roles AS role
   WHERE role.rolname = 'kf_authority_owner'
     AND NOT role.rolcanlogin
     AND NOT role.rolsuper
     AND NOT role.rolbypassrls
     AND NOT role.rolinherit
     AND NOT role.rolcreatedb
     AND NOT role.rolcreaterole
     AND NOT role.rolreplication;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'kf_authority_owner attribute drift';
  END IF;

  SELECT role.oid
    INTO authority_registrar
    FROM pg_catalog.pg_roles AS role
   WHERE role.rolname = 'kf_authority_registrar'
     AND NOT role.rolcanlogin
     AND NOT role.rolsuper
     AND NOT role.rolbypassrls
     AND NOT role.rolinherit
     AND NOT role.rolcreatedb
     AND NOT role.rolcreaterole
     AND NOT role.rolreplication;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'kf_authority_registrar attribute drift';
  END IF;

  SELECT role.oid
    INTO ingest_owner
    FROM pg_catalog.pg_roles AS role
   WHERE role.rolname = 'kf_ingest_owner'
     AND NOT role.rolcanlogin
     AND NOT role.rolsuper
     AND NOT role.rolbypassrls
     AND NOT role.rolinherit
     AND NOT role.rolcreatedb
     AND NOT role.rolcreaterole
     AND NOT role.rolreplication;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'kf_ingest_owner attribute drift';
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_auth_members AS membership
     WHERE membership.member = authority_owner OR membership.roleid = authority_owner
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_auth_members AS membership
     WHERE membership.member = authority_registrar
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_auth_members AS membership
     WHERE membership.member = ingest_owner OR membership.roleid = ingest_owner
  ) THEN
    RAISE EXCEPTION 'authority role membership drift';
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_catalog.pg_database AS database
     WHERE database.datname = pg_catalog.current_database()
       AND database.datdba = authority_registrar
  ) OR EXISTS (
    SELECT 1 FROM pg_catalog.pg_namespace AS namespace
     WHERE namespace.nspname = 'public'
       AND namespace.nspowner = authority_registrar
  ) OR EXISTS (
    SELECT 1
      FROM pg_catalog.pg_class AS relation
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'public'
       AND relation.relowner = authority_registrar
  ) OR EXISTS (
    SELECT 1
      FROM pg_catalog.pg_proc AS function
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
     WHERE namespace.nspname = 'public'
       AND function.proowner = authority_registrar
  ) THEN
    RAISE EXCEPTION 'authority registrar ownership drift';
  END IF;

  SELECT owner_role.rolname
    INTO domain_table_owner
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
   WHERE namespace.nspname = 'public'
     AND relation.relname = 'kf_authority_domain'
     AND relation.relkind IN ('r', 'p');
  IF domain_table_owner IS DISTINCT FROM 'kf_authority_owner' THEN
    RAISE EXCEPTION 'authority domain table ownership drift';
  END IF;

  SELECT owner_role.rolname
    INTO grant_table_owner
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
   WHERE namespace.nspname = 'public'
     AND relation.relname = 'kf_ingest_authority_grant'
     AND relation.relkind IN ('r', 'p');
  IF grant_table_owner IS DISTINCT FROM 'kf_authority_owner' THEN
    RAISE EXCEPTION 'authority grant table ownership drift';
  END IF;

  IF pg_catalog.to_regprocedure(
       'public.kf_ingest_observation(uuid,uuid,uuid,text,text,text,text,bigint,text)'
     ) IS NOT NULL
     OR pg_catalog.to_regprocedure(
       'public.kf_ingest_observation_internal(uuid,uuid,uuid,text,text,text,text,bigint,text)'
     ) IS NULL
     OR pg_catalog.to_regprocedure(
       'public.kf_ingest_authorized(uuid,uuid)'
     ) IS NULL THEN
    RAISE EXCEPTION 'authority function surface drift';
  END IF;

  IF pg_catalog.has_table_privilege(
       'kf_runtime', 'public.kf_ingest_authority_grant', 'SELECT'
     )
     OR pg_catalog.has_table_privilege(
       'kf_runtime', 'public.kf_authority_domain',
       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
     )
     OR pg_catalog.has_table_privilege(
       'kf_runtime', 'public.kf_ingest_authority_grant', 'INSERT'
     )
     OR pg_catalog.has_table_privilege(
       'kf_runtime', 'public.kf_ingest_authority_grant', 'UPDATE'
     )
     OR pg_catalog.has_table_privilege(
       'kf_runtime', 'public.kf_ingest_authority_grant', 'DELETE'
     )
     OR pg_catalog.has_table_privilege(
       'kf_authority_registrar', 'public.kf_ingest_authority_grant', 'SELECT'
     )
     OR pg_catalog.has_table_privilege(
       'kf_authority_registrar', 'public.kf_ingest_authority_grant', 'INSERT'
     )
     OR pg_catalog.has_table_privilege(
       'kf_authority_registrar', 'public.kf_ingest_authority_grant', 'UPDATE'
     )
     OR pg_catalog.has_table_privilege(
       'kf_authority_registrar', 'public.kf_ingest_authority_grant', 'DELETE'
     )
     OR pg_catalog.has_table_privilege(
       'kf_authority_registrar', 'public.kf_authority_domain',
       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
     )
     OR NOT pg_catalog.has_table_privilege(
       'kf_ingest_owner', 'public.kf_authority_domain', 'SELECT'
     )
     OR pg_catalog.has_table_privilege(
       'kf_ingest_owner', 'public.kf_authority_domain',
       'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
     )
     OR NOT pg_catalog.has_column_privilege(
       'kf_ingest_owner', 'public.kf_authority_domain', 'provisioned_at', 'UPDATE'
     )
     OR pg_catalog.has_column_privilege(
       'kf_ingest_owner', 'public.kf_authority_domain', 'authority_domain_id', 'UPDATE'
     )
     OR pg_catalog.has_any_column_privilege(
       'kf_runtime', 'public.kf_authority_domain', 'INSERT,UPDATE,REFERENCES'
     )
     OR pg_catalog.has_any_column_privilege(
       'kf_authority_registrar', 'public.kf_authority_domain',
       'INSERT,UPDATE,REFERENCES'
     )
     OR NOT pg_catalog.has_table_privilege(
       'kf_ingest_owner', 'public.kf_ingest_authority_grant', 'SELECT'
     ) THEN
    RAISE EXCEPTION 'authority grant table ACL drift';
  END IF;

  IF pg_catalog.has_function_privilege(
       'kf_runtime',
       'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)',
       'EXECUTE'
     )
     OR pg_catalog.has_function_privilege(
       'kf_runtime',
       'public.kf_ingest_observation_internal(uuid,uuid,uuid,text,text,text,text,bigint,text)',
       'EXECUTE'
     )
     OR pg_catalog.has_function_privilege(
       'kf_runtime', 'public.kf_allowed_projects()', 'EXECUTE'
     )
     OR NOT pg_catalog.has_function_privilege(
       'kf_runtime', 'public.kf_ingest_authorized(uuid,uuid)', 'EXECUTE'
     )
     OR NOT pg_catalog.has_function_privilege(
       'kf_authority_registrar',
       'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)',
       'EXECUTE'
     )
     OR pg_catalog.has_function_privilege(
       'kf_authority_registrar', 'public.kf_ingest_authorized(uuid,uuid)', 'EXECUTE'
     ) THEN
    RAISE EXCEPTION 'authority function ACL drift';
  END IF;

  IF pg_catalog.has_schema_privilege('kf_runtime', 'public', 'CREATE')
     OR pg_catalog.has_schema_privilege('kf_ingest_owner', 'public', 'CREATE')
     OR pg_catalog.has_schema_privilege('kf_authority_owner', 'public', 'CREATE')
     OR pg_catalog.has_schema_privilege('kf_authority_registrar', 'public', 'CREATE') THEN
    RAISE EXCEPTION 'authority schema CREATE privilege drift';
  END IF;

  IF EXISTS (
    SELECT 1
      FROM pg_catalog.pg_proc AS function
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function.pronamespace
      CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
          function.proacl,
          pg_catalog.acldefault('f'::"char", function.proowner)
        )
      ) AS acl
     WHERE function.oid IN (
       pg_catalog.to_regprocedure(
         'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)'
       ),
       pg_catalog.to_regprocedure(
         'public.kf_ingest_observation_internal(uuid,uuid,uuid,text,text,text,text,bigint,text)'
       ),
       pg_catalog.to_regprocedure('public.kf_allowed_projects()'),
       pg_catalog.to_regprocedure('public.kf_ingest_authorized(uuid,uuid)')
     )
       AND (
         acl.privilege_type <> 'EXECUTE'
         OR (
           acl.grantee <> function.proowner
           AND (
             acl.is_grantable
             OR NOT (
               (
                 function.oid = pg_catalog.to_regprocedure(
                   'public.kf_register_ingest_authority_grant(uuid,uuid,text,text,text,uuid,text,text,text,text,bigint,text,text,bigint,bigint)'
                 )
                 AND acl.grantee = authority_registrar
               )
               OR (
                 function.oid = pg_catalog.to_regprocedure('public.kf_allowed_projects()')
                 AND acl.grantee = ingest_owner
               )
               OR (
                 function.oid = pg_catalog.to_regprocedure(
                   'public.kf_ingest_authorized(uuid,uuid)'
                 )
                 AND acl.grantee = (
                   SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'kf_runtime'
                 )
               )
             )
           )
         )
       )
  ) THEN
    RAISE EXCEPTION 'authority function exact ACL drift';
  END IF;

  IF EXISTS (
    SELECT 1
      FROM pg_catalog.pg_class AS relation
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
      CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
          relation.relacl,
          pg_catalog.acldefault(
            CASE WHEN relation.relkind = 'S' THEN 's'::"char" ELSE 'r'::"char" END,
            relation.relowner
          )
        )
      ) AS acl
     WHERE namespace.nspname = 'public'
       AND relation.relkind IN ('r', 'p', 'S', 'v', 'm', 'f')
       AND acl.grantee IN (
         (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'kf_runtime'),
         authority_registrar
       )
  ) THEN
    RAISE EXCEPTION 'runtime or registrar retained raw relation or sequence ACL';
  END IF;

  IF EXISTS (
    SELECT 1
      FROM pg_catalog.pg_attribute AS attribute
      JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
      JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
      CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
     WHERE namespace.nspname = 'public'
       AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
       AND attribute.attnum > 0
       AND NOT attribute.attisdropped
       AND acl.grantee IN (
         (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = 'kf_runtime'),
         authority_registrar
       )
  ) THEN
    RAISE EXCEPTION 'runtime or registrar retained raw column ACL';
  END IF;
END
$final_authority_boundary_guard$;

COMMIT;
