-- Knowledge Foundry — intake core, corrected under closure v1.1 P0 (§2.1–2.6).
-- Rebuild of the relevant slice of the v1 reference DDL. Postgres 17/18 + pgvector.
-- Implements: RawBlob/Occurrence/Version split, events vs projections, junction tables,
-- RLS forced from day one, explicit EmbeddingProfile. This is the production target of
-- the Rust `kf-intake` slice (which proves the same invariants offline on filesystem CAS).

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid
-- CREATE EXTENSION IF NOT EXISTS vector;  -- enable when the embedding slice lands

-- ---------------------------------------------------------------------------
-- §2.1  Global deduplicated bytes  !=  project-scoped occurrence  !=  version
-- ---------------------------------------------------------------------------

-- RawBlob: one row per unique byte stream. NO project_id here — bytes are global.
CREATE TABLE raw_blob (
    blob_id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sha256              char(64) NOT NULL UNIQUE,       -- content address
    byte_size           bigint  NOT NULL CHECK (byte_size >= 0),
    storage_uri         text    NOT NULL,               -- CAS path / s3:// when adapter fires
    storage_version_id  text,                           -- object-store version handle if any
    media_type_detected text,
    created_at          timestamptz NOT NULL DEFAULT now()
    -- immutable: no UPDATE path is granted (see policies below)
);

CREATE TABLE project (
    project_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ArtifactOccurrence: a project's/source's observation of some bytes.
-- Access to a blob is granted THROUGH an authorized occurrence, never blob identity alone.
CREATE TABLE artifact_occurrence (
    occurrence_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(project_id),
    source_system_id  text NOT NULL,
    source_native_id  text NOT NULL,                    -- stable per-source key (path, drive id, sha…)
    observed_path_uri text,
    blob_id           uuid NOT NULL REFERENCES raw_blob(blob_id),
    data_class        text NOT NULL DEFAULT 'INTERNAL'
                       CHECK (data_class IN ('PUBLIC','INTERNAL','CONFIDENTIAL','FINANCIAL_SENSITIVE','SECRET','CREDENTIAL')),
    observed_at       timestamptz NOT NULL DEFAULT now(),
    -- idempotency key: same observation of a source is one occurrence
    UNIQUE (project_id, source_system_id, source_native_id)
);

CREATE TABLE artifact_version (
    version_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurrence_id       uuid NOT NULL REFERENCES artifact_occurrence(occurrence_id),
    blob_id             uuid NOT NULL REFERENCES raw_blob(blob_id),
    source_revision_key text NOT NULL,                  -- e.g. content sha, git sha, drive revision
    parent_version_id   uuid REFERENCES artifact_version(version_id),
    tombstone           boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (occurrence_id, source_revision_key)
);

CREATE TABLE logical_document (
    logical_document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES project(project_id),
    preferred_version_id uuid REFERENCES artifact_version(version_id),  -- mutable projection
    identity_rationale  text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- §2.2  Immutable append-only events  +  mutable projections
-- ---------------------------------------------------------------------------

-- Per-project hash-chained event ledger (KD-07: canonical bytes hashed, prev-hash link).
CREATE TABLE event_ledger (
    event_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(project_id),
    seq          bigint NOT NULL,
    kind         text NOT NULL,               -- blob.created | occurrence.created | version.created | ...
    payload_jcs  bytea NOT NULL,              -- RFC 8785 canonical JSON bytes
    payload_sha  char(64) NOT NULL,           -- SHA-256 over payload_jcs
    prev_hash    char(64) NOT NULL,
    hash         char(64) NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, seq)
);

-- IngestionRun is a MUTABLE projection (status changes) — no content_hash on it (§2.2).
CREATE TABLE ingestion_run (
    run_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(project_id),
    source_system_id text NOT NULL,
    status        text NOT NULL DEFAULT 'RUNNING'
                   CHECK (status IN ('RUNNING','COMPLETED','FAILED','INTERRUPTED')),
    cursor_state  jsonb,
    idempotency_key text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);

-- ---------------------------------------------------------------------------
-- §2.6  Explicit embedding profile (one in MVP; new generation on model change)
-- ---------------------------------------------------------------------------
CREATE TABLE embedding_profile (
    profile_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider     text NOT NULL,
    model        text NOT NULL,
    revision     text NOT NULL,
    dimensions   int  NOT NULL,
    normalization text NOT NULL DEFAULT 'none',
    data_class_policy text NOT NULL DEFAULT 'INTERNAL',
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, model, revision)
);
-- EmbeddingChunk uses vector(N) matching ONE profile; enable with pgvector:
-- CREATE TABLE embedding_chunk (
--   search_document_id uuid NOT NULL,
--   profile_id uuid NOT NULL REFERENCES embedding_profile(profile_id),
--   generation_id uuid NOT NULL,
--   embedding vector(1024) NOT NULL   -- dims must equal profile.dimensions
-- );

-- ---------------------------------------------------------------------------
-- §2.3  Junction tables for authority/lineage edges (no UUID arrays)
--        (decision layer stubs — filled by the decision slice)
-- ---------------------------------------------------------------------------
-- Example provenance edge as a junction, PROV-compatible (§2.8):
CREATE TABLE provenance_parent (
    child_object_id  uuid NOT NULL,
    parent_object_id uuid NOT NULL,
    relation         text NOT NULL DEFAULT 'wasDerivedFrom'
                      CHECK (relation IN ('wasDerivedFrom','used','wasGeneratedBy','wasAssociatedWith','actedOnBehalfOf')),
    PRIMARY KEY (child_object_id, parent_object_id, relation)
);

-- ---------------------------------------------------------------------------
-- §2.5  Row-Level Security: forced from day one
-- ---------------------------------------------------------------------------
-- Session context (set by the service per request): app.project_ids = csv of allowed project uuids.
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

CREATE OR REPLACE FUNCTION kf_allowed_projects() RETURNS uuid[]
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    string_to_array(current_setting('app.project_ids', true), ',')::uuid[],
    ARRAY[]::uuid[])
$$;

CREATE POLICY occ_project_isolation ON artifact_occurrence
    USING (project_id = ANY (kf_allowed_projects()));
CREATE POLICY ver_project_isolation ON artifact_version
    USING (occurrence_id IN (SELECT occurrence_id FROM artifact_occurrence));
CREATE POLICY doc_project_isolation ON logical_document
    USING (project_id = ANY (kf_allowed_projects()));
CREATE POLICY run_project_isolation ON ingestion_run
    USING (project_id = ANY (kf_allowed_projects()));
CREATE POLICY evt_project_isolation ON event_ledger
    USING (project_id = ANY (kf_allowed_projects()));

-- Global deduplication does not imply global metadata visibility.  A runtime
-- may see blob metadata only through an occurrence already admitted by the
-- project policy above.
CREATE POLICY blob_via_authorized_occurrence ON raw_blob
    USING (EXISTS (
        SELECT 1 FROM artifact_occurrence AS occurrence
        WHERE occurrence.blob_id = raw_blob.blob_id
    ));
CREATE POLICY project_scope ON project
    USING (project_id = ANY (kf_allowed_projects()));

-- provenance_parent intentionally has no runtime grant: the current schema
-- carries no project_id and therefore cannot enforce tenant-safe lineage.

CREATE INDEX ON artifact_occurrence (blob_id);
CREATE INDEX ON artifact_version (occurrence_id);
CREATE INDEX ON event_ledger (project_id, seq);
