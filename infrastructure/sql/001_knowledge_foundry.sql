-- Knowledge Foundry: ядро MVP (D7). Postgres 16 + pgvector + pg_trgm.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS artifact (
  artifact_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_hash     TEXT NOT NULL UNIQUE,            -- SHA-256 бинарного потока
  source_system_id TEXT NOT NULL,
  source_native_id TEXT,
  mime_type        TEXT,
  byte_size        BIGINT,
  storage_uri      TEXT NOT NULL,                   -- MinIO
  data_class       TEXT NOT NULL DEFAULT 'INTERNAL',
  observed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifact_version (
  version_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id          UUID NOT NULL REFERENCES artifact(artifact_id),
  logical_document_id  UUID,
  parent_version_id    UUID REFERENCES artifact_version(version_id),
  duplicate_cluster_id UUID,
  is_superseded        BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS provenance_record (
  provenance_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  derived_object_id UUID NOT NULL,
  activity_type     TEXT NOT NULL,        -- PROV-O Activity: parse | llm_extraction | transform
  agent_id          TEXT NOT NULL,        -- PROV-O Agent: model/connector/owner
  prompt_version_id TEXT,
  parent_artifact_ids UUID[],
  trust_level       TEXT NOT NULL,        -- PRIMARY_CODE | INDEPENDENT_RESEARCH | UNVERIFIED_IMPORT | VENDOR_CLAIM
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim (
  claim_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  normalized_assertion TEXT NOT NULL,
  exact_source_excerpt TEXT NOT NULL,
  subject TEXT, predicate TEXT, object TEXT,
  source_artifact_id   UUID NOT NULL REFERENCES artifact(artifact_id),
  confidence           REAL,
  status TEXT NOT NULL DEFAULT 'PROPOSED'
    CHECK (status IN ('PROPOSED','SUPPORTED','VERIFIED','DISPUTED','CONTRADICTED','STALE','SUPERSEDED','UNVERIFIABLE','REJECTED')),
  embedding            vector(1024),      -- производный индекс, перестраиваемый; НЕ истина
  fts                  tsvector GENERATED ALWAYS AS (to_tsvector('simple', normalized_assertion)) STORED,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS claim_fts_idx ON claim USING gin(fts);
CREATE INDEX IF NOT EXISTS claim_hnsw_idx ON claim USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS evidence_link (
  link_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id             UUID NOT NULL REFERENCES claim(claim_id),
  evidence_artifact_id UUID NOT NULL REFERENCES artifact(artifact_id),
  support_type TEXT NOT NULL CHECK (support_type IN ('SUPPORTS','REFUTES','NOT_ENOUGH_INFO')),
  independence TEXT, freshness TEXT, quality TEXT
);

CREATE TABLE IF NOT EXISTS contradiction_record (
  contradiction_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  affected_claim_ids UUID[] NOT NULL,
  severity           TEXT NOT NULL,
  owner              TEXT,
  resolution_state   TEXT NOT NULL DEFAULT 'DETECTED'
    CHECK (resolution_state IN ('DETECTED','TRIAGE','OPEN_QUESTION','REQUIRED_EXPERIMENT','FALSE_POSITIVE','RESOLVED')),
  proposed_tests     TEXT[]
);

CREATE TABLE IF NOT EXISTS canonical_decision (
  decision_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id                UUID REFERENCES claim(claim_id),
  decision_type           TEXT NOT NULL CHECK (decision_type IN ('ADR','SCHEMA','INVARIANT','GLOSSARY')),
  approved_by             TEXT NOT NULL,
  approved_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  cryptographic_signature TEXT,           -- обязательна для риск-классов HIGH+
  status TEXT NOT NULL DEFAULT 'CANONICAL' CHECK (status IN ('CANDIDATE_CANON','CANONICAL','SUPERSEDED','STALE','QUARANTINED')),
  supersedes_decision_id  UUID REFERENCES canonical_decision(decision_id)
);

CREATE TABLE IF NOT EXISTS research_run (
  run_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id                TEXT,
  exact_prompt           TEXT NOT NULL,
  context_manifest_hashes TEXT[],         -- ContextManifest: хеши всех входов (слепые прогоны)
  model_provider         TEXT NOT NULL,
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  raw_result_artifact_id UUID REFERENCES artifact(artifact_id),
  reviewer_decision      TEXT,
  status TEXT NOT NULL DEFAULT 'PLANNED'
    CHECK (status IN ('PLANNED','RUNNING','RESULT_RECEIVED','SOURCES_AUDITED','CLAIMS_EXTRACTED','DELTA_REVIEWED','MERGED_OR_REJECTED','ARCHIVED'))
);

-- Остальные 15 сущностей (ImplementationLink, ADRReference, OpenQuestion, ...) — миграция 002 по мере включения Phase 3 (D7 §16).
