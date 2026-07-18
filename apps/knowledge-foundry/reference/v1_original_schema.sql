-- MAWorld Knowledge Foundry — PostgreSQL reference schema
-- TASK_ID: KNOWLEDGE_FOUNDRY_ARCHITECTURE_V1
-- Target: PostgreSQL 17+
-- Authoritative state lives in PostgreSQL; raw bytes live in immutable object storage.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Optional but recommended for the MVP semantic index. The index is derived and rebuildable.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS kf;
SET search_path = kf, public;

-- ---------------------------------------------------------------------------
-- Enumerations
-- ---------------------------------------------------------------------------

CREATE TYPE data_class_code AS ENUM (
  'PUBLIC',
  'INTERNAL',
  'CONFIDENTIAL',
  'RESTRICTED',
  'SECRET',
  'QUARANTINED'
);

CREATE TYPE artifact_state AS ENUM (
  'RAW',
  'PARSED',
  'INDEXED',
  'CLAIMS_EXTRACTED',
  'REVIEW_REQUIRED',
  'ACCEPTED_AS_EVIDENCE',
  'CANDIDATE_CANON',
  'CANONICAL',
  'SUPERSEDED',
  'ARCHIVED',
  'QUARANTINED'
);

CREATE TYPE claim_status AS ENUM (
  'PROPOSED',
  'SUPPORTED',
  'VERIFIED',
  'DISPUTED',
  'CONTRADICTED',
  'STALE',
  'SUPERSEDED',
  'UNVERIFIABLE',
  'REJECTED'
);

CREATE TYPE trust_class AS ENUM (
  'PRIMARY_OFFICIAL',
  'PRIMARY_CODE',
  'PRIMARY_RUNTIME_EVIDENCE',
  'USER_AUTHORED',
  'INDEPENDENT_RESEARCH',
  'VENDOR_CLAIM',
  'SECONDARY_SOURCE',
  'MODEL_INFERENCE',
  'UNVERIFIED_IMPORT',
  'MALICIOUS_OR_QUARANTINED'
);

CREATE TYPE support_type AS ENUM (
  'SUPPORTS',
  'PARTIALLY_SUPPORTS',
  'REFUTES',
  'CONTEXTUALIZES',
  'IMPLEMENTS',
  'VERIFIES',
  'CITES'
);

CREATE TYPE evidence_independence AS ENUM (
  'INDEPENDENT',
  'PARTIALLY_DEPENDENT',
  'SAME_ORIGIN',
  'DERIVED_FROM_CLAIM',
  'UNKNOWN'
);

CREATE TYPE relation_type AS ENUM (
  'EXACT_DUPLICATE',
  'NEAR_DUPLICATE',
  'VERSION_OF',
  'DERIVATIVE_OF',
  'CITES',
  'CONTRADICTS',
  'SUPERSEDES',
  'EXTRACTED_FROM',
  'ATTACHMENT_OF',
  'MERGED_FROM',
  'UNRELATED'
);

CREATE TYPE contradiction_type AS ENUM (
  'DIRECT_FACTUAL_CONTRADICTION',
  'INCOMPATIBLE_ARCHITECTURE_DECISION',
  'STALE_VENDOR_CAPABILITY',
  'SCHEMA_DRIFT',
  'CODE_DOCUMENT_MISMATCH',
  'RENAMED_CONCEPT',
  'CONFLICTING_RISK_VALUE',
  'IMPLEMENTATION_DIVERGENCE',
  'DUPLICATED_TICKET',
  'SUPERSEDED_PROMPT',
  'CONFLICTING_OWNERSHIP',
  'OTHER'
);

CREATE TYPE contradiction_state AS ENUM (
  'OPEN',
  'TRIAGED',
  'TEST_REQUIRED',
  'IN_REVIEW',
  'RESOLVED',
  'ACCEPTED_DIVERGENCE',
  'SUPERSEDED',
  'REJECTED'
);

CREATE TYPE review_status AS ENUM (
  'OPEN',
  'CLAIMED',
  'BLOCKED',
  'APPROVED',
  'REJECTED',
  'CANCELLED',
  'EXPIRED'
);

CREATE TYPE research_run_status AS ENUM (
  'PLANNED',
  'RUNNING',
  'RESULT_RECEIVED',
  'SOURCES_AUDITED',
  'CLAIMS_EXTRACTED',
  'DELTA_REVIEWED',
  'MERGED_OR_REJECTED',
  'ARCHIVED'
);

CREATE TYPE decision_risk_tier AS ENUM (
  'LOW',
  'MEDIUM',
  'HIGH',
  'CRITICAL'
);

CREATE TYPE decision_resolution AS ENUM (
  'ACCEPTED',
  'REJECTED',
  'DEFERRED',
  'EXPERIMENT_REQUIRED'
);

CREATE TYPE implementation_link_type AS ENUM (
  'IMPLEMENTS',
  'PARTIALLY_IMPLEMENTS',
  'VERIFIES',
  'DEPLOYS',
  'OBSERVES',
  'CONTRADICTS',
  'DEPRECATES'
);

CREATE TYPE job_status AS ENUM (
  'QUEUED',
  'RUNNING',
  'SUCCEEDED',
  'FAILED_RETRYABLE',
  'FAILED_TERMINAL',
  'CANCELLED'
);

CREATE TYPE source_change_kind AS ENUM (
  'CREATED',
  'MODIFIED',
  'RENAMED',
  'MOVED',
  'DELETED',
  'PERMISSION_CHANGED',
  'UNKNOWN'
);

-- ---------------------------------------------------------------------------
-- Root project and common derived-object envelope
-- ---------------------------------------------------------------------------

CREATE TABLE project (
  project_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_key             text NOT NULL UNIQUE,
  display_name            text NOT NULL,
  description             text,
  default_data_class      data_class_code NOT NULL DEFAULT 'INTERNAL',
  created_at              timestamptz NOT NULL DEFAULT now(),
  archived_at             timestamptz
);

CREATE TABLE object_registry (
  object_id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  object_type             text NOT NULL,
  schema_version          text NOT NULL,
  source_references       jsonb NOT NULL DEFAULT '[]'::jsonb,
  content_hash            char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at              timestamptz NOT NULL DEFAULT now(),
  created_by              jsonb NOT NULL,
  project_scope           uuid NOT NULL REFERENCES project(project_id),
  data_class              data_class_code NOT NULL,
  status                  text NOT NULL,
  provenance              jsonb NOT NULL DEFAULT '{}'::jsonb,
  policy_context          jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (object_type, content_hash, project_scope)
);

COMMENT ON TABLE object_registry IS
'Common immutable envelope required for every derived Knowledge Foundry object.';

-- ---------------------------------------------------------------------------
-- Source systems, classification, policies and connector cursors
-- ---------------------------------------------------------------------------

CREATE TABLE source_system (
  source_system_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  source_key              text NOT NULL UNIQUE,
  source_type             text NOT NULL,
  display_name            text NOT NULL,
  auth_method             text NOT NULL,
  auth_secret_ref         text,
  ingestion_mode          text NOT NULL CHECK (ingestion_mode IN ('POLL', 'PUSH', 'MANUAL', 'HYBRID')),
  native_namespace        text,
  connector_version       text NOT NULL,
  permission_mirroring    boolean NOT NULL DEFAULT true,
  deletion_policy         text NOT NULL DEFAULT 'TOMBSTONE',
  rate_limit_policy       jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled                 boolean NOT NULL DEFAULT true,
  last_success_at         timestamptz,
  last_error              jsonb
);

CREATE TABLE connector_cursor (
  connector_cursor_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_system_id        uuid NOT NULL REFERENCES source_system(source_system_id),
  scope_key               text NOT NULL,
  cursor_value            jsonb NOT NULL,
  observed_at             timestamptz NOT NULL DEFAULT now(),
  last_change_kind        source_change_kind,
  UNIQUE (source_system_id, scope_key)
);

CREATE TABLE data_classification (
  classification_id      uuid PRIMARY KEY REFERENCES object_registry(object_id),
  target_object_id        uuid NOT NULL REFERENCES object_registry(object_id),
  classification         data_class_code NOT NULL,
  reasons                jsonb NOT NULL,
  classifier_kind        text NOT NULL CHECK (classifier_kind IN ('HUMAN', 'RULE', 'MODEL', 'SECRET_SCANNER')),
  classifier_version     text,
  reviewed_by            jsonb,
  reviewed_at            timestamptz,
  effective_from         timestamptz NOT NULL DEFAULT now(),
  effective_until        timestamptz
);

CREATE TABLE access_policy (
  access_policy_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  policy_key              text NOT NULL,
  version                 text NOT NULL,
  effect                  text NOT NULL CHECK (effect IN ('ALLOW', 'DENY', 'REQUIRE_APPROVAL')),
  action_patterns         text[] NOT NULL,
  resource_conditions     jsonb NOT NULL,
  principal_conditions    jsonb NOT NULL,
  provider_routing        jsonb NOT NULL DEFAULT '{}'::jsonb,
  canonicalization_scope  jsonb NOT NULL DEFAULT '{}'::jsonb,
  effective_from          timestamptz NOT NULL DEFAULT now(),
  effective_until         timestamptz,
  UNIQUE (policy_key, version)
);

-- ---------------------------------------------------------------------------
-- Immutable raw artifacts, logical documents and source versions
-- ---------------------------------------------------------------------------

CREATE TABLE artifact (
  artifact_id             uuid PRIMARY KEY REFERENCES object_registry(object_id),
  content_hash            char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  hash_algorithm          text NOT NULL DEFAULT 'SHA-256',
  byte_size               bigint NOT NULL CHECK (byte_size >= 0),
  media_type              text NOT NULL,
  detected_file_type      text,
  original_filename       text,
  raw_storage_uri         text NOT NULL,
  storage_version_id      text,
  storage_etag            text,
  object_lock_mode        text,
  retain_until            timestamptz,
  malware_scan_status     text NOT NULL DEFAULT 'PENDING',
  secret_scan_status      text NOT NULL DEFAULT 'PENDING',
  content_disarm_status   text NOT NULL DEFAULT 'NOT_APPLICABLE',
  recoverability_verified_at timestamptz,
  created_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (content_hash, byte_size)
);

CREATE TABLE logical_document (
  logical_document_id     uuid PRIMARY KEY REFERENCES object_registry(object_id),
  document_key            text,
  canonical_title         text,
  document_kind           text,
  lifecycle_status        text NOT NULL DEFAULT 'ACTIVE',
  current_preferred_version_id uuid,
  identity_rationale      jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- document_key is globally unique in the MVP. For a multi-tenant deployment,
-- denormalize project_scope into this table and make the key project-scoped.
CREATE UNIQUE INDEX logical_document_key_uq
  ON logical_document(document_key)
  WHERE document_key IS NOT NULL;

CREATE TABLE ingestion_run (
  ingestion_run_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  source_system_id        uuid NOT NULL REFERENCES source_system(source_system_id),
  trigger_kind            text NOT NULL CHECK (trigger_kind IN ('MANUAL', 'POLL', 'PUSH', 'BACKFILL', 'RETRY')),
  cursor_before           jsonb,
  cursor_after            jsonb,
  idempotency_key         text NOT NULL,
  started_at              timestamptz NOT NULL,
  ended_at                timestamptz,
  run_status              job_status NOT NULL,
  discovered_count        integer NOT NULL DEFAULT 0,
  ingested_count          integer NOT NULL DEFAULT 0,
  skipped_count           integer NOT NULL DEFAULT 0,
  failed_count            integer NOT NULL DEFAULT 0,
  error_summary           jsonb,
  UNIQUE (source_system_id, idempotency_key)
);

CREATE TABLE artifact_version (
  version_id              uuid PRIMARY KEY REFERENCES object_registry(object_id),
  artifact_id             uuid NOT NULL REFERENCES artifact(artifact_id),
  logical_document_id     uuid REFERENCES logical_document(logical_document_id),
  source_system_id        uuid NOT NULL REFERENCES source_system(source_system_id),
  source_native_id        text NOT NULL,
  source_revision_key     text NOT NULL,
  parent_version_id       uuid REFERENCES artifact_version(version_id),
  duplicate_cluster_id    uuid,
  ingestion_run_id        uuid REFERENCES ingestion_run(ingestion_run_id),
  original_uri_or_path    text,
  display_path            text,
  observed_at             timestamptz NOT NULL,
  source_created_at       timestamptz,
  source_modified_at      timestamptz,
  source_deleted_at       timestamptz,
  source_metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
  permissions_snapshot   jsonb NOT NULL DEFAULT '{}'::jsonb,
  canonical_text_hash     char(64) CHECK (canonical_text_hash IS NULL OR canonical_text_hash ~ '^[0-9a-f]{64}$'),
  structure_hash          char(64) CHECK (structure_hash IS NULL OR structure_hash ~ '^[0-9a-f]{64}$'),
  supersession_status     text NOT NULL DEFAULT 'CURRENT',
  is_partial              boolean NOT NULL DEFAULT false,
  is_tombstone            boolean NOT NULL DEFAULT false,
  state                   artifact_state NOT NULL DEFAULT 'RAW',
  UNIQUE (source_system_id, source_native_id, source_revision_key)
);

ALTER TABLE logical_document
  ADD CONSTRAINT logical_document_current_version_fk
  FOREIGN KEY (current_preferred_version_id) REFERENCES artifact_version(version_id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX artifact_version_document_idx ON artifact_version(logical_document_id, observed_at DESC);
CREATE INDEX artifact_version_source_idx ON artifact_version(source_system_id, source_native_id);
CREATE INDEX artifact_version_state_idx ON artifact_version(state);
CREATE INDEX artifact_version_metadata_gin ON artifact_version USING gin(source_metadata);

-- ---------------------------------------------------------------------------
-- Extraction and provenance ledger
-- ---------------------------------------------------------------------------

CREATE TABLE extraction_record (
  extraction_record_id    uuid PRIMARY KEY REFERENCES object_registry(object_id),
  version_id              uuid NOT NULL REFERENCES artifact_version(version_id),
  extraction_kind         text NOT NULL,
  parser_name             text NOT NULL,
  parser_version          text NOT NULL,
  sandbox_image_digest    text,
  model_provider          text,
  model_name              text,
  prompt_version          text,
  started_at              timestamptz NOT NULL,
  ended_at                timestamptz,
  status                  job_status NOT NULL,
  normalized_text_uri     text,
  normalized_text_hash    char(64) CHECK (normalized_text_hash IS NULL OR normalized_text_hash ~ '^[0-9a-f]{64}$'),
  structure_uri           text,
  structure_hash          char(64) CHECK (structure_hash IS NULL OR structure_hash ~ '^[0-9a-f]{64}$'),
  page_count              integer,
  warnings                jsonb NOT NULL DEFAULT '[]'::jsonb,
  error_detail            jsonb,
  attempt_no              integer NOT NULL DEFAULT 1,
  UNIQUE (version_id, extraction_kind, parser_name, parser_version, attempt_no)
);

CREATE TABLE provenance_record (
  provenance_record_id    uuid PRIMARY KEY REFERENCES object_registry(object_id),
  target_object_id        uuid NOT NULL REFERENCES object_registry(object_id),
  source_system_id        uuid REFERENCES source_system(source_system_id),
  source_artifact_id      uuid REFERENCES artifact(artifact_id),
  source_version_id       uuid REFERENCES artifact_version(version_id),
  creator                 jsonb,
  ingestion_method        text,
  original_uri_or_path    text,
  observed_at             timestamptz,
  source_created_at       timestamptz,
  source_modified_at      timestamptz,
  parser_name             text,
  parser_version          text,
  model_provider          text,
  model_name              text,
  prompt_version          text,
  human_reviewer          jsonb,
  parent_object_ids       uuid[] NOT NULL DEFAULT '{}',
  trust_class             trust_class NOT NULL,
  provenance_detail       jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX provenance_target_idx ON provenance_record(target_object_id);
CREATE INDEX provenance_source_version_idx ON provenance_record(source_version_id);

-- ---------------------------------------------------------------------------
-- Duplicate, version and derivative relationships
-- ---------------------------------------------------------------------------

CREATE TABLE duplicate_cluster (
  duplicate_cluster_id    uuid PRIMARY KEY REFERENCES object_registry(object_id),
  cluster_kind            text NOT NULL CHECK (cluster_kind IN ('EXACT', 'NEAR', 'CROSS_FORMAT', 'POSSIBLE')),
  cluster_signature       text NOT NULL,
  representative_version_id uuid REFERENCES artifact_version(version_id),
  confidence              numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  resolution_status       review_status NOT NULL DEFAULT 'OPEN',
  rationale               jsonb NOT NULL,
  UNIQUE (cluster_signature)
);

ALTER TABLE artifact_version
  ADD CONSTRAINT artifact_version_duplicate_cluster_fk
  FOREIGN KEY (duplicate_cluster_id) REFERENCES duplicate_cluster(duplicate_cluster_id)
  DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE duplicate_cluster_member (
  duplicate_cluster_id    uuid NOT NULL REFERENCES duplicate_cluster(duplicate_cluster_id) ON DELETE CASCADE,
  version_id              uuid NOT NULL REFERENCES artifact_version(version_id),
  relation                relation_type NOT NULL,
  similarity              numeric(5,4) CHECK (similarity BETWEEN 0 AND 1),
  match_features          jsonb NOT NULL,
  PRIMARY KEY (duplicate_cluster_id, version_id)
);

CREATE TABLE artifact_relation (
  artifact_relation_id    uuid PRIMARY KEY REFERENCES object_registry(object_id),
  from_version_id         uuid NOT NULL REFERENCES artifact_version(version_id),
  to_version_id           uuid NOT NULL REFERENCES artifact_version(version_id),
  relation                relation_type NOT NULL,
  confidence              numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  detector                jsonb NOT NULL,
  review_status           review_status NOT NULL DEFAULT 'OPEN',
  rationale               jsonb NOT NULL,
  CHECK (from_version_id <> to_version_id),
  UNIQUE (from_version_id, to_version_id, relation)
);

-- ---------------------------------------------------------------------------
-- Atomic claims, evidence and claim-specific trust
-- ---------------------------------------------------------------------------

CREATE TABLE claim (
  claim_id                uuid PRIMARY KEY REFERENCES object_registry(object_id),
  normalized_assertion    text NOT NULL,
  assertion_hash          char(64) NOT NULL CHECK (assertion_hash ~ '^[0-9a-f]{64}$'),
  exact_source_excerpt    text NOT NULL,
  source_location         jsonb NOT NULL,
  scope                   jsonb NOT NULL,
  subject                 text NOT NULL,
  predicate               text NOT NULL,
  object_value            jsonb NOT NULL,
  valid_time              tstzrange,
  source_version_id       uuid NOT NULL REFERENCES artifact_version(version_id),
  author                  jsonb,
  extraction_confidence   numeric(4,3) NOT NULL CHECK (extraction_confidence BETWEEN 0 AND 1),
  status                  claim_status NOT NULL DEFAULT 'PROPOSED',
  claim_kind              text NOT NULL DEFAULT 'FACT',
  review_required         boolean NOT NULL DEFAULT true,
  search_vector           tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(normalized_assertion, '') || ' ' || coalesce(subject, '') || ' ' || coalesce(predicate, ''))
  ) STORED
);

CREATE UNIQUE INDEX claim_source_assertion_uq ON claim(source_version_id, assertion_hash, source_location);
CREATE INDEX claim_status_idx ON claim(status);
CREATE INDEX claim_search_gin ON claim USING gin(search_vector);
CREATE INDEX claim_subject_trgm ON claim USING gin(subject gin_trgm_ops);

CREATE TABLE trust_assessment (
  trust_assessment_id     uuid PRIMARY KEY REFERENCES object_registry(object_id),
  claim_id                uuid NOT NULL REFERENCES claim(claim_id),
  evidence_object_id      uuid REFERENCES object_registry(object_id),
  domain                  text NOT NULL,
  trust_class             trust_class NOT NULL,
  authenticity            numeric(4,3) CHECK (authenticity BETWEEN 0 AND 1),
  directness              numeric(4,3) CHECK (directness BETWEEN 0 AND 1),
  independence            numeric(4,3) CHECK (independence BETWEEN 0 AND 1),
  freshness               numeric(4,3) CHECK (freshness BETWEEN 0 AND 1),
  reproducibility         numeric(4,3) CHECK (reproducibility BETWEEN 0 AND 1),
  scope_fit               numeric(4,3) CHECK (scope_fit BETWEEN 0 AND 1),
  assessor                jsonb NOT NULL,
  limitations             jsonb NOT NULL DEFAULT '[]'::jsonb,
  UNIQUE (claim_id, evidence_object_id, domain)
);

CREATE TABLE evidence_link (
  evidence_link_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  claim_id                uuid NOT NULL REFERENCES claim(claim_id),
  evidence_artifact_id    uuid REFERENCES artifact(artifact_id),
  evidence_version_id     uuid REFERENCES artifact_version(version_id),
  evidence_object_id      uuid REFERENCES object_registry(object_id),
  support                 support_type NOT NULL,
  independence            evidence_independence NOT NULL,
  freshness_score         numeric(4,3) CHECK (freshness_score BETWEEN 0 AND 1),
  quality_score           numeric(4,3) CHECK (quality_score BETWEEN 0 AND 1),
  exact_evidence_excerpt  text,
  evidence_location       jsonb,
  limitations             jsonb NOT NULL DEFAULT '[]'::jsonb,
  valid_from              timestamptz,
  valid_until             timestamptz,
  reviewer_status         review_status NOT NULL DEFAULT 'OPEN',
  CHECK (num_nonnulls(evidence_artifact_id, evidence_version_id, evidence_object_id) >= 1)
);

CREATE INDEX evidence_claim_idx ON evidence_link(claim_id, support);

-- ---------------------------------------------------------------------------
-- Contradictions, conflicts, open questions and experiments
-- ---------------------------------------------------------------------------

CREATE TABLE contradiction_record (
  contradiction_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  contradiction_kind      contradiction_type NOT NULL,
  title                   text NOT NULL,
  description             text NOT NULL,
  affected_decision_ids   uuid[] NOT NULL DEFAULT '{}',
  severity                decision_risk_tier NOT NULL,
  owner                   jsonb,
  resolution_state        contradiction_state NOT NULL DEFAULT 'OPEN',
  detection_method        jsonb NOT NULL,
  proposed_tests          jsonb NOT NULL DEFAULT '[]'::jsonb,
  final_resolution        jsonb,
  resolved_at             timestamptz,
  resolved_by             jsonb
);

CREATE TABLE contradiction_claim (
  contradiction_id        uuid NOT NULL REFERENCES contradiction_record(contradiction_id) ON DELETE CASCADE,
  claim_id                uuid NOT NULL REFERENCES claim(claim_id),
  role                    text NOT NULL CHECK (role IN ('A', 'B', 'CONTEXT', 'RESOLUTION')),
  PRIMARY KEY (contradiction_id, claim_id)
);

CREATE TABLE decision_conflict (
  contradiction_id        uuid PRIMARY KEY REFERENCES contradiction_record(contradiction_id),
  decision_a_id           uuid NOT NULL,
  decision_b_id           uuid NOT NULL,
  incompatibility         jsonb NOT NULL
);

CREATE TABLE schema_conflict (
  contradiction_id        uuid PRIMARY KEY REFERENCES contradiction_record(contradiction_id),
  schema_a_ref            jsonb NOT NULL,
  schema_b_ref            jsonb NOT NULL,
  breaking_changes        jsonb NOT NULL
);

CREATE TABLE implementation_mismatch (
  contradiction_id        uuid PRIMARY KEY REFERENCES contradiction_record(contradiction_id),
  expected_object_id      uuid REFERENCES object_registry(object_id),
  observed_object_id      uuid REFERENCES object_registry(object_id),
  mismatch_kind           text NOT NULL,
  runtime_evidence        jsonb
);

CREATE TABLE open_question (
  open_question_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  question                text NOT NULL,
  rationale               text NOT NULL,
  affected_object_ids     uuid[] NOT NULL DEFAULT '{}',
  priority                decision_risk_tier NOT NULL,
  owner                   jsonb,
  due_at                  timestamptz,
  resolution_criteria     jsonb NOT NULL,
  answer                  jsonb,
  status                  text NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE required_experiment (
  required_experiment_id  uuid PRIMARY KEY REFERENCES object_registry(object_id),
  open_question_id        uuid REFERENCES open_question(open_question_id),
  contradiction_id        uuid REFERENCES contradiction_record(contradiction_id),
  hypothesis              text NOT NULL,
  protocol                jsonb NOT NULL,
  acceptance_criteria     jsonb NOT NULL,
  implementation_ref      jsonb,
  result_object_ids       uuid[] NOT NULL DEFAULT '{}',
  status                  text NOT NULL DEFAULT 'PLANNED',
  CHECK (num_nonnulls(open_question_id, contradiction_id) >= 1)
);

-- ---------------------------------------------------------------------------
-- Canonical decisions and immutable supersession
-- ---------------------------------------------------------------------------

CREATE TABLE canonical_decision (
  canonical_decision_id   uuid PRIMARY KEY REFERENCES object_registry(object_id),
  decision_key            text NOT NULL,
  decision_version        integer NOT NULL CHECK (decision_version > 0),
  title                   text NOT NULL,
  decision_type           text NOT NULL,
  risk_tier               decision_risk_tier NOT NULL,
  resolution              decision_resolution NOT NULL,
  decision_statement      text NOT NULL,
  rationale               text NOT NULL,
  claim_ids               uuid[] NOT NULL DEFAULT '{}',
  evidence_link_ids       uuid[] NOT NULL DEFAULT '{}',
  alternatives            jsonb NOT NULL DEFAULT '[]'::jsonb,
  rejected_alternatives   jsonb NOT NULL DEFAULT '[]'::jsonb,
  assumptions             jsonb NOT NULL DEFAULT '[]'::jsonb,
  risks                   jsonb NOT NULL DEFAULT '[]'::jsonb,
  confidence              numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  acceptance_test         jsonb NOT NULL,
  revisit_trigger         jsonb NOT NULL,
  policy_decision_id      text NOT NULL,
  approved_by             jsonb NOT NULL,
  approved_at             timestamptz NOT NULL,
  signature_algorithm     text NOT NULL,
  signature               text NOT NULL,
  immutable_payload_hash  char(64) NOT NULL CHECK (immutable_payload_hash ~ '^[0-9a-f]{64}$'),
  UNIQUE (decision_key, decision_version),
  UNIQUE (immutable_payload_hash)
);

CREATE TABLE supersession_record (
  supersession_record_id  uuid PRIMARY KEY REFERENCES object_registry(object_id),
  superseded_object_id    uuid NOT NULL REFERENCES object_registry(object_id),
  superseding_object_id   uuid NOT NULL REFERENCES object_registry(object_id),
  reason                  text NOT NULL,
  effective_at            timestamptz NOT NULL,
  approved_by             jsonb NOT NULL,
  policy_decision_id      text NOT NULL,
  signature_algorithm     text NOT NULL,
  signature               text NOT NULL,
  CHECK (superseded_object_id <> superseding_object_id),
  UNIQUE (superseded_object_id, superseding_object_id)
);

CREATE VIEW current_canonical_decision AS
SELECT cd.*
FROM canonical_decision cd
WHERE cd.resolution = 'ACCEPTED'
  AND NOT EXISTS (
    SELECT 1
    FROM supersession_record sr
    WHERE sr.superseded_object_id = cd.canonical_decision_id
      AND sr.effective_at <= now()
  );

-- ---------------------------------------------------------------------------
-- Architecture and implementation mapping
-- ---------------------------------------------------------------------------

CREATE TABLE architecture_impact (
  architecture_impact_id  uuid PRIMARY KEY REFERENCES object_registry(object_id),
  canonical_decision_id   uuid NOT NULL REFERENCES canonical_decision(canonical_decision_id),
  impact_type             text NOT NULL CHECK (impact_type IN ('ADR', 'SCHEMA', 'API', 'SERVICE', 'REPOSITORY', 'POLICY', 'BACKLOG', 'TEST', 'DEPLOYMENT', 'DOCUMENTATION')),
  target_ref              jsonb NOT NULL,
  impact_summary          text NOT NULL,
  required_change         jsonb NOT NULL,
  status                  text NOT NULL DEFAULT 'PROPOSED',
  due_at                  timestamptz
);

CREATE TABLE implementation_link (
  implementation_link_id  uuid PRIMARY KEY REFERENCES object_registry(object_id),
  canonical_decision_id   uuid REFERENCES canonical_decision(canonical_decision_id),
  claim_id                uuid REFERENCES claim(claim_id),
  architecture_impact_id  uuid REFERENCES architecture_impact(architecture_impact_id),
  link_type               implementation_link_type NOT NULL,
  repository              text,
  repository_path         text,
  git_commit_sha          text,
  pull_request_ref        jsonb,
  ticket_ref              jsonb,
  test_ref                jsonb,
  deployment_ref          jsonb,
  runtime_evidence_ref    jsonb,
  observed_at             timestamptz,
  verification_status     claim_status NOT NULL DEFAULT 'PROPOSED',
  CHECK (num_nonnulls(canonical_decision_id, claim_id, architecture_impact_id) >= 1)
);

CREATE TABLE adr_reference (
  adr_reference_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  canonical_decision_id   uuid NOT NULL REFERENCES canonical_decision(canonical_decision_id),
  repository              text NOT NULL,
  path                    text NOT NULL,
  git_commit_sha          text,
  adr_number              text,
  adr_status              text NOT NULL,
  UNIQUE (repository, path, git_commit_sha)
);

CREATE TABLE backlog_reference (
  backlog_reference_id    uuid PRIMARY KEY REFERENCES object_registry(object_id),
  canonical_decision_id   uuid REFERENCES canonical_decision(canonical_decision_id),
  architecture_impact_id  uuid REFERENCES architecture_impact(architecture_impact_id),
  system                  text NOT NULL,
  project_key             text,
  ticket_key              text NOT NULL,
  ticket_url              text,
  ticket_status           text,
  owner                   jsonb,
  last_observed_at        timestamptz,
  UNIQUE (system, ticket_key)
);

-- ---------------------------------------------------------------------------
-- Professional Deep Research runs
-- ---------------------------------------------------------------------------

CREATE TABLE research_run (
  research_run_id         uuid PRIMARY KEY REFERENCES object_registry(object_id),
  task_id                 text NOT NULL,
  exact_prompt            text NOT NULL,
  prompt_hash             char(64) NOT NULL CHECK (prompt_hash ~ '^[0-9a-f]{64}$'),
  source_priority         jsonb NOT NULL,
  excluded_scope          jsonb NOT NULL DEFAULT '[]'::jsonb,
  model_provider          text NOT NULL,
  model_name              text NOT NULL,
  model_configuration     jsonb NOT NULL DEFAULT '{}'::jsonb,
  run_status              research_run_status NOT NULL,
  started_at              timestamptz,
  ended_at                timestamptz,
  raw_result_artifact_id  uuid REFERENCES artifact(artifact_id),
  completeness            numeric(4,3) CHECK (completeness BETWEEN 0 AND 1),
  reviewer_decision       decision_resolution,
  blind_group_key         text,
  UNIQUE (task_id, prompt_hash, model_provider, model_name, blind_group_key)
);

CREATE TABLE context_manifest (
  context_manifest_id     uuid PRIMARY KEY REFERENCES object_registry(object_id),
  research_run_id         uuid NOT NULL REFERENCES research_run(research_run_id),
  manifest_version        text NOT NULL,
  included_object_ids     uuid[] NOT NULL DEFAULT '{}',
  attached_version_ids    uuid[] NOT NULL DEFAULT '{}',
  exclusions              jsonb NOT NULL DEFAULT '[]'::jsonb,
  token_budget            integer,
  compilation_method      jsonb NOT NULL,
  UNIQUE (research_run_id, manifest_version)
);

CREATE TABLE source_ledger (
  source_ledger_id        uuid PRIMARY KEY REFERENCES object_registry(object_id),
  research_run_id         uuid NOT NULL REFERENCES research_run(research_run_id),
  source_uri              text,
  source_title            text,
  publisher               text,
  author                  jsonb,
  published_at            timestamptz,
  accessed_at             timestamptz NOT NULL,
  content_hash            char(64) CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  archived_artifact_id    uuid REFERENCES artifact(artifact_id),
  trust_class             trust_class NOT NULL,
  citation_locator        jsonb,
  source_status           text NOT NULL DEFAULT 'OBSERVED'
);

CREATE TABLE decision_delta (
  decision_delta_id       uuid PRIMARY KEY REFERENCES object_registry(object_id),
  research_run_id         uuid NOT NULL REFERENCES research_run(research_run_id),
  target_decision_key     text,
  delta_kind              text NOT NULL CHECK (delta_kind IN ('NEW', 'SUPPORT', 'CHALLENGE', 'SUPERSEDE', 'NO_CHANGE', 'OPEN_QUESTION')),
  prior_object_id         uuid REFERENCES object_registry(object_id),
  proposed_object_id      uuid REFERENCES object_registry(object_id),
  summary                 text NOT NULL,
  evidence_link_ids       uuid[] NOT NULL DEFAULT '{}',
  review_status           review_status NOT NULL DEFAULT 'OPEN'
);

-- ---------------------------------------------------------------------------
-- Human review workbench
-- ---------------------------------------------------------------------------

CREATE TABLE review_task (
  review_task_id          uuid PRIMARY KEY REFERENCES object_registry(object_id),
  queue_name              text NOT NULL,
  action_type             text NOT NULL,
  target_object_id        uuid NOT NULL REFERENCES object_registry(object_id),
  priority                integer NOT NULL CHECK (priority BETWEEN 0 AND 1000),
  risk_tier               decision_risk_tier NOT NULL,
  status                  review_status NOT NULL DEFAULT 'OPEN',
  assigned_to             jsonb,
  due_at                  timestamptz,
  context_bundle          jsonb NOT NULL,
  allowed_actions         text[] NOT NULL,
  claimed_at              timestamptz,
  resolved_at             timestamptz,
  resolution              jsonb
);

CREATE INDEX review_task_queue_idx ON review_task(queue_name, status, priority DESC, due_at NULLS LAST);

-- ---------------------------------------------------------------------------
-- Derived search layer and typed graph
-- ---------------------------------------------------------------------------

CREATE TABLE search_document (
  search_document_id      uuid PRIMARY KEY REFERENCES object_registry(object_id),
  source_object_id        uuid NOT NULL REFERENCES object_registry(object_id),
  source_version_id       uuid REFERENCES artifact_version(version_id),
  chunk_no                integer NOT NULL,
  text_content            text NOT NULL,
  title                   text,
  metadata                jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from              timestamptz,
  valid_until             timestamptz,
  canonical_only          boolean NOT NULL DEFAULT false,
  search_vector           tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(text_content, ''))
  ) STORED,
  UNIQUE (source_object_id, chunk_no)
);

CREATE INDEX search_document_fts_gin ON search_document USING gin(search_vector);
CREATE INDEX search_document_meta_gin ON search_document USING gin(metadata);

CREATE TABLE embedding_chunk (
  embedding_chunk_id      uuid PRIMARY KEY REFERENCES object_registry(object_id),
  search_document_id      uuid NOT NULL REFERENCES search_document(search_document_id) ON DELETE CASCADE,
  embedding_model         text NOT NULL,
  embedding_dimensions    integer NOT NULL,
  embedding               vector(1536),
  embedding_hash          char(64) NOT NULL CHECK (embedding_hash ~ '^[0-9a-f]{64}$'),
  generated_at            timestamptz NOT NULL,
  index_generation        text NOT NULL,
  UNIQUE (search_document_id, embedding_model, index_generation)
);

CREATE INDEX embedding_chunk_hnsw ON embedding_chunk USING hnsw (embedding vector_cosine_ops);

CREATE TABLE graph_edge (
  graph_edge_id           uuid PRIMARY KEY REFERENCES object_registry(object_id),
  from_object_id          uuid NOT NULL REFERENCES object_registry(object_id),
  edge_type               text NOT NULL,
  to_object_id            uuid NOT NULL REFERENCES object_registry(object_id),
  properties              jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from              timestamptz NOT NULL DEFAULT now(),
  valid_until             timestamptz,
  CHECK (from_object_id <> to_object_id),
  UNIQUE (from_object_id, edge_type, to_object_id, valid_from)
);

CREATE INDEX graph_edge_from_idx ON graph_edge(from_object_id, edge_type);
CREATE INDEX graph_edge_to_idx ON graph_edge(to_object_id, edge_type);

-- ---------------------------------------------------------------------------
-- Snapshots, append-only audit and resumable jobs
-- ---------------------------------------------------------------------------

CREATE TABLE canonical_snapshot (
  canonical_snapshot_id   uuid PRIMARY KEY REFERENCES object_registry(object_id),
  snapshot_key            text NOT NULL,
  prior_snapshot_id       uuid REFERENCES canonical_snapshot(canonical_snapshot_id),
  manifest                jsonb NOT NULL,
  merkle_root             char(64) NOT NULL CHECK (merkle_root ~ '^[0-9a-f]{64}$'),
  created_at              timestamptz NOT NULL,
  UNIQUE (snapshot_key)
);

CREATE TABLE event_ledger (
  event_id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id              uuid NOT NULL REFERENCES project(project_id),
  aggregate_type          text NOT NULL,
  aggregate_id            uuid NOT NULL,
  event_type              text NOT NULL,
  event_version           integer NOT NULL,
  actor                   jsonb NOT NULL,
  policy_decision_id      text,
  payload                 jsonb NOT NULL,
  payload_hash            char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  previous_event_hash     char(64) CHECK (previous_event_hash IS NULL OR previous_event_hash ~ '^[0-9a-f]{64}$'),
  event_hash              char(64) NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  signature_algorithm     text,
  signature               text,
  occurred_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (aggregate_type, aggregate_id, event_version),
  UNIQUE (event_hash)
);

CREATE INDEX event_ledger_aggregate_idx ON event_ledger(aggregate_type, aggregate_id, event_version);
CREATE INDEX event_ledger_time_idx ON event_ledger(project_id, occurred_at DESC);

CREATE TABLE job_queue (
  job_id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id              uuid NOT NULL REFERENCES project(project_id),
  job_type                text NOT NULL,
  idempotency_key         text NOT NULL,
  input_object_ids        uuid[] NOT NULL DEFAULT '{}',
  payload                 jsonb NOT NULL,
  status                  job_status NOT NULL DEFAULT 'QUEUED',
  priority                integer NOT NULL DEFAULT 100,
  attempts                integer NOT NULL DEFAULT 0,
  max_attempts            integer NOT NULL DEFAULT 5,
  available_at            timestamptz NOT NULL DEFAULT now(),
  locked_at               timestamptz,
  locked_by               text,
  last_error              jsonb,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, job_type, idempotency_key)
);

CREATE INDEX job_queue_claim_idx
  ON job_queue(status, priority DESC, available_at)
  WHERE status IN ('QUEUED', 'FAILED_RETRYABLE');

-- ---------------------------------------------------------------------------
-- Integrity guards: immutable raw/canonical/audit rows
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION forbid_update_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  RAISE EXCEPTION '% rows are immutable; append a new version/event/supersession record instead', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER artifact_immutable_guard
BEFORE UPDATE OR DELETE ON artifact
FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

CREATE TRIGGER canonical_decision_immutable_guard
BEFORE UPDATE OR DELETE ON canonical_decision
FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

CREATE TRIGGER supersession_record_immutable_guard
BEFORE UPDATE OR DELETE ON supersession_record
FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

CREATE TRIGGER event_ledger_immutable_guard
BEFORE UPDATE OR DELETE ON event_ledger
FOR EACH ROW EXECUTE FUNCTION forbid_update_delete();

-- ---------------------------------------------------------------------------
-- Coverage views used by the operator workbench
-- ---------------------------------------------------------------------------

CREATE VIEW accepted_decisions_without_implementation AS
SELECT cd.canonical_decision_id, cd.decision_key, cd.decision_version, cd.title
FROM current_canonical_decision cd
WHERE NOT EXISTS (
  SELECT 1
  FROM implementation_link il
  WHERE il.canonical_decision_id = cd.canonical_decision_id
    AND il.link_type IN ('IMPLEMENTS', 'PARTIALLY_IMPLEMENTS')
);

CREATE VIEW implemented_without_approved_decision AS
SELECT il.*
FROM implementation_link il
WHERE il.link_type IN ('IMPLEMENTS', 'PARTIALLY_IMPLEMENTS', 'DEPLOYS')
  AND il.canonical_decision_id IS NULL;

CREATE VIEW unresolved_high_risk_conflicts AS
SELECT *
FROM contradiction_record
WHERE severity IN ('HIGH', 'CRITICAL')
  AND resolution_state NOT IN ('RESOLVED', 'SUPERSEDED', 'REJECTED');

CREATE VIEW stale_knowledge_candidates AS
SELECT c.claim_id, c.normalized_assertion, c.status, el.valid_until, el.freshness_score
FROM claim c
LEFT JOIN evidence_link el ON el.claim_id = c.claim_id
WHERE c.status IN ('SUPPORTED', 'VERIFIED')
  AND (
    el.valid_until < now()
    OR el.freshness_score < 0.35
  );

-- ---------------------------------------------------------------------------
-- Example worker claim query (documentation only)
-- ---------------------------------------------------------------------------
-- WITH next_job AS (
--   SELECT job_id
--   FROM job_queue
--   WHERE status IN ('QUEUED', 'FAILED_RETRYABLE')
--     AND available_at <= now()
--   ORDER BY priority DESC, available_at
--   FOR UPDATE SKIP LOCKED
--   LIMIT 1
-- )
-- UPDATE job_queue j
-- SET status = 'RUNNING', locked_at = now(), locked_by = :worker_id,
--     attempts = attempts + 1, updated_at = now()
-- FROM next_job
-- WHERE j.job_id = next_job.job_id
-- RETURNING j.*;

COMMIT;
