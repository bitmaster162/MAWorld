-- Knowledge Foundry -- atomic tenant-scoped observation intake boundary.
-- Apply as migration administrator after 001_intake_core_v1_1.sql and 002_rls_roles.sql.
-- One call atomically deduplicates RawBlob, preserves stable ArtifactOccurrence identity, and
-- appends ArtifactVersion lineage. Runtime has EXECUTE only, never direct identity-table INSERT.

BEGIN;

DO $migration_authority_guard$
BEGIN
  IF NOT EXISTS (
      SELECT 1
        FROM pg_catalog.pg_roles AS migration_role
       WHERE migration_role.rolname = SESSION_USER
         AND migration_role.rolsuper
  ) THEN
    RAISE EXCEPTION '003_atomic_intake.sql requires a dedicated migration superuser';
  END IF;
END
$migration_authority_guard$;

DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'kf_ingest_owner') THEN
    CREATE ROLE kf_ingest_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                                NOREPLICATION NOBYPASSRLS NOINHERIT;
  END IF;
END
$role$;

-- Repair unsafe attribute drift and fail if the definer inherited any other role.
ALTER ROLE kf_ingest_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                           NOREPLICATION NOBYPASSRLS NOINHERIT;
REVOKE kf_ingest_owner FROM kf_runtime;
DO $membership_guard$
BEGIN
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid IN (membership.member, membership.roleid)
       WHERE owner_role.rolname = 'kf_ingest_owner'
  ) THEN
    RAISE EXCEPTION 'kf_ingest_owner must have no incoming or outgoing role memberships';
  END IF;
END
$membership_guard$;

REVOKE CREATE ON SCHEMA public FROM kf_ingest_owner;
GRANT USAGE ON SCHEMA public TO kf_ingest_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM kf_ingest_owner;
GRANT SELECT ON public.project TO kf_ingest_owner;
GRANT SELECT, INSERT ON public.raw_blob, public.artifact_occurrence,
                        public.artifact_version TO kf_ingest_owner;
GRANT EXECUTE ON FUNCTION public.kf_allowed_projects() TO kf_ingest_owner;

-- The user-facing blob SELECT policy requires an already-authorized occurrence. These two
-- policies break that circular dedup dependency only for the NOLOGIN function owner and only
-- while exactly one transaction-local project context exists.
DROP POLICY IF EXISTS blob_atomic_intake_select ON public.raw_blob;
CREATE POLICY blob_atomic_intake_select ON public.raw_blob
    FOR SELECT TO kf_ingest_owner
    USING (pg_catalog.cardinality(public.kf_allowed_projects()) = 1);

DROP POLICY IF EXISTS blob_atomic_intake_insert ON public.raw_blob;
CREATE POLICY blob_atomic_intake_insert ON public.raw_blob
    FOR INSERT TO kf_ingest_owner
    WITH CHECK (pg_catalog.cardinality(public.kf_allowed_projects()) = 1);

-- Occurrence.blob_id intentionally preserves the first observation. Runtime visibility for later
-- immutable versions is derived through a version joined to an RLS-authorized occurrence.
DROP POLICY IF EXISTS blob_via_authorized_version ON public.raw_blob;
CREATE POLICY blob_via_authorized_version ON public.raw_blob
    FOR SELECT TO kf_runtime
    USING (EXISTS (
        SELECT 1
          FROM public.artifact_version AS visible_version
          JOIN public.artifact_occurrence AS visible_occurrence
            ON visible_occurrence.occurrence_id = visible_version.occurrence_id
         WHERE visible_version.blob_id = raw_blob.blob_id
    ));

CREATE INDEX IF NOT EXISTS artifact_version_blob_id_idx
    ON public.artifact_version (blob_id);
CREATE INDEX IF NOT EXISTS artifact_version_occurrence_parent_idx
    ON public.artifact_version (occurrence_id, parent_version_id);

-- The original single-column parent FK proves existence but not that parent and child belong to
-- the same occurrence. Add the composite invariant before the write function can create lineage.
DO $lineage_constraints$
BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_constraint
       WHERE conrelid = 'public.artifact_version'::regclass
         AND conname = 'artifact_version_identity_unique'
  ) THEN
    ALTER TABLE public.artifact_version
      ADD CONSTRAINT artifact_version_identity_unique UNIQUE (version_id, occurrence_id);
  END IF;
  IF NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_constraint
       WHERE conrelid = 'public.artifact_version'::regclass
         AND conname = 'artifact_version_parent_same_occurrence_fk'
  ) THEN
    ALTER TABLE public.artifact_version
      ADD CONSTRAINT artifact_version_parent_same_occurrence_fk
      FOREIGN KEY (parent_version_id, occurrence_id)
      REFERENCES public.artifact_version(version_id, occurrence_id);
  END IF;
END
$lineage_constraints$;

CREATE OR REPLACE FUNCTION public.kf_ingest_observation(
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
    -- The GUC is a scope claim, not authentication. The service must derive it from signed
    -- authority. Privileged work proceeds only for one exact project claim.
    v_allowed_projects := public.kf_allowed_projects();
    IF pg_catalog.cardinality(v_allowed_projects) <> 1
       OR v_allowed_projects[1] IS DISTINCT FROM p_project_id THEN
        RAISE EXCEPTION 'one exact transaction-local project context is required'
            USING ERRCODE = '42501';
    END IF;

    IF p_project_id IS NULL OR p_project_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_occurrence_id IS NULL OR p_occurrence_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR p_version_id IS NULL OR p_version_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RAISE EXCEPTION 'project_id, occurrence_id, and version_id must be non-nil'
            USING ERRCODE = '22023';
    END IF;
    IF p_source_system_id IS NULL OR p_source_system_id <> pg_catalog.btrim(p_source_system_id)
       OR p_source_system_id = '' OR p_source_system_id ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_source_system_id) > 128 THEN
        RAISE EXCEPTION 'invalid source_system_id' USING ERRCODE = '22023';
    END IF;
    IF p_source_native_id IS NULL OR p_source_native_id <> pg_catalog.btrim(p_source_native_id)
       OR p_source_native_id = '' OR p_source_native_id ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_source_native_id) > 4096 THEN
        RAISE EXCEPTION 'invalid source_native_id' USING ERRCODE = '22023';
    END IF;
    IF p_source_revision_key IS NULL
       OR p_source_revision_key <> pg_catalog.btrim(p_source_revision_key)
       OR p_source_revision_key = '' OR p_source_revision_key ~ '[[:cntrl:]]'
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
    IF p_storage_uri IS NULL OR p_storage_uri <> pg_catalog.btrim(p_storage_uri)
       OR p_storage_uri = '' OR p_storage_uri ~ '[[:cntrl:]]'
       OR pg_catalog.octet_length(p_storage_uri) > 4096 THEN
        RAISE EXCEPTION 'invalid storage_uri' USING ERRCODE = '22023';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.project AS scoped_project
         WHERE scoped_project.project_id = p_project_id
    ) THEN
        RAISE EXCEPTION 'project is absent or outside the current scope'
            USING ERRCODE = '23503';
    END IF;

    -- Serialize all revisions of one source identity before any global blob work. This makes
    -- latest-parent selection deterministic and turns same-revision races into exact retries.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_project_id::text || ':' ||
            pg_catalog.octet_length(p_source_system_id)::text || ':' || p_source_system_id || ':' ||
            pg_catalog.octet_length(p_source_native_id)::text || ':' || p_source_native_id,
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

    -- Exact revision retry: return the durable version and its original parent. A revision key
    -- may never be rebound to different content.
    SELECT existing_version.version_id, existing_version.blob_id,
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

    -- `created_at DEFAULT now()` reflects transaction start, not lock acquisition/commit order.
    -- The durable latest version is therefore the unique graph tail (a version with no child).
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
        SELECT 1 FROM public.artifact_version AS existing_lineage
         WHERE existing_lineage.occurrence_id = v_occurrence_id
    ) THEN
        RAISE EXCEPTION 'version lineage has no tail'
            USING ERRCODE = '23000';
    ELSIF pg_catalog.cardinality(v_lineage_tails) > 1 THEN
        RAISE EXCEPTION 'version lineage has multiple tails'
            USING ERRCODE = '23000';
    END IF;
    v_parent_version_id := v_lineage_tails[1];

    v_version_id := p_version_id;
    INSERT INTO public.artifact_version(
        version_id, occurrence_id, blob_id, source_revision_key, parent_version_id
    ) VALUES (
        v_version_id, v_occurrence_id, v_blob_id, p_source_revision_key, v_parent_version_id
    )
    ON CONFLICT (occurrence_id, source_revision_key) DO NOTHING;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    version_created := v_rows = 1;

    -- Defensive recovery if privileged migration work bypassed the advisory-lock convention.
    IF NOT version_created THEN
        SELECT existing_version.version_id, existing_version.blob_id,
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

-- PostgreSQL requires a prospective function owner to have CREATE on its schema. Grant it only
-- for this ownership transfer inside the migration transaction, then revoke it immediately.
GRANT CREATE ON SCHEMA public TO kf_ingest_owner;
ALTER FUNCTION public.kf_ingest_observation(uuid, uuid, uuid, text, text, text, text, bigint, text)
    OWNER TO kf_ingest_owner;
REVOKE CREATE ON SCHEMA public FROM kf_ingest_owner;
REVOKE ALL ON FUNCTION public.kf_ingest_observation(uuid, uuid, uuid, text, text, text, text, bigint, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.kf_ingest_observation(uuid, uuid, uuid, text, text, text, text, bigint, text)
    TO kf_runtime;

-- The definer must stay subject to RLS (it may not own any table it touches).
DO $ownership_guard$
BEGIN
  IF EXISTS (
      SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
       WHERE owner_role.rolname = 'kf_ingest_owner'
         AND relation.oid IN (
             'public.project'::regclass,
             'public.raw_blob'::regclass,
             'public.artifact_occurrence'::regclass,
             'public.artifact_version'::regclass
         )
  ) THEN
    RAISE EXCEPTION 'kf_ingest_owner must not own RLS-protected intake tables';
  END IF;
END
$ownership_guard$;

REVOKE ALL PRIVILEGES ON public.raw_blob, public.artifact_occurrence,
                         public.artifact_version FROM kf_runtime;
GRANT SELECT ON public.raw_blob, public.artifact_occurrence,
                public.artifact_version TO kf_runtime;

COMMIT;
