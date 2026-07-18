# MAWORLD KNOWLEDGE FOUNDRY — ARCHITECTURE CLOSURE v1.1

**TASK_ID:** `KNOWLEDGE_FOUNDRY_ARCHITECTURE_CLOSURE_V1_1`  
**Status:** architecture baseline finalized; empirical calibration still required  
**Verdict:** `NARROW AND BUILD`  
**Supersedes:** unqualified claims that the v1 SQL/API bundle is already production-ready

## 0. EXECUTIVE CONCLUSION

The initial research path was correct: official documentation and primary specifications were used to define the storage, retrieval, provenance, security, connector and evaluation layers. The resulting v1 architecture correctly rejected a RAG-only design and established the essential control loop:

`RAW → PROVENANCE → CLAIM → EVIDENCE → CONFLICT → REVIEW → CANONICAL DECISION → IMPLEMENTATION → VERIFICATION`.

The audit, however, finds that **the conceptual architecture is stronger than the current reference DDL**. The system can be built now, but four items must be corrected before the SQL is treated as an implementation contract:

1. separate globally deduplicated raw bytes from project/source occurrences;
2. separate immutable facts/events from mutable workflow projections;
3. replace array-based critical relationships with junction tables;
4. make security and cryptographic invariants executable rather than descriptive.

A second category cannot be settled by more desk research alone. Parser choice, duplicate thresholds, claim atomicity, contradiction precision, review queue load and model/provider routing require a benchmark on the real MAWorld seed corpus.

The final architecture is therefore:

- **build the narrow intake-to-decision vertical slice now**;
- **do not migrate the full archive**;
- **do not freeze parser/model/dedup thresholds before empirical tests**;
- **treat the current v1 DDL as a reference draft, not a migration-ready schema**;
- **run one targeted Deep Research gap-closure study plus a local benchmark pack**.

---

## 1. WHAT THE v1 ARCHITECTURE GOT RIGHT

### 1.1 Correct problem framing

Knowledge Foundry is a project truth and evidence control plane, not a generic document manager, vector database or LifeOS memory layer.

### 1.2 Correct authority split

- immutable raw bytes: content-addressed storage;
- authoritative metadata, workflows and decisions: PostgreSQL;
- code, ADRs, schemas, policies and tests: Git;
- mutation authorization: ContinuityOS;
- semantic and full-text indexes: derived and rebuildable;
- private agent memory: LifeOS, outside project canon.

### 1.3 Correct promotion boundary

Models may propose claims, evidence links, contradictions and summaries. They may not promote anything into canonical state.

### 1.4 Correct incremental strategy

The owner does not pre-sort the corpus. New material enters an Inbox and the historical archive is processed by priority.

### 1.5 Correct operational narrowing

PostgreSQL plus Git plus a raw store is sufficient for the MVP. Qdrant, OpenSearch, graph databases, DataHub, OpenMetadata, lakeFS and Temporal are deferred until measured triggers exist.

---

## 2. BUILD-BLOCKING CORRECTIONS

## 2.1 Raw bytes and project artifacts must be different entities

### Problem

The v1 schema models `artifact` as both a globally deduplicated byte object and a project-scoped object registered in `object_registry`. A global unique constraint on `(content_hash, byte_size)` conflicts with project-scoped registry identities when the same bytes appear in multiple projects.

### Final model

```text
RawBlob
  blob_id
  sha256
  byte_size
  storage_uri
  storage_version_id
  media_type_detected
  immutable/recoverability fields

ArtifactOccurrence
  occurrence_id
  project_id
  source_system_id
  source_native_id
  observed_path_or_uri
  permissions snapshot
  observed metadata

ArtifactVersion
  version_id
  occurrence_id
  blob_id
  source_revision_key
  parent_version_id
  timestamps
  tombstone/partial flags

LogicalDocument
  logical_document_id
  project_id
  preferred_version_id
  identity rationale
```

One `RawBlob` may be referenced by many source occurrences and many projects. Access is granted through the occurrence/project relation, never through global blob identity alone.

### Acceptance test

Upload the same PDF into two projects. Only one byte blob is stored, but two independently governed occurrences and versions are created. A user authorized for project A cannot retrieve the blob through project B metadata.

---

## 2.2 Immutable records and mutable projections must be separated

### Problem

The v1 `object_registry` requires a content hash for stateful objects such as `ReviewTask`, `IngestionRun` and `JobQueue`, while their status is expected to change. That produces either stale hashes or an implicit overwrite model.

### Final model

Use three categories:

1. **Immutable entities:** raw blobs, extraction outputs, claims, evidence assertions, canonical decisions, supersession records, signed snapshots.
2. **Append-only domain events:** state transitions and mutation audit.
3. **Mutable projections:** review queue, current job lease, current connector cursor, current preferred version, current status views.

`content_hash` belongs to an immutable payload revision, not to a mutable row merely because it is a domain object.

### Acceptance test

Changing a review task from `OPEN` to `APPROVED` appends a transition event and updates a projection. It does not mutate the immutable decision payload or invalidate its stored hash.

---

## 2.3 Critical graph relationships must not live in UUID arrays

### Problem

Arrays such as `claim_ids`, `evidence_link_ids`, `affected_decision_ids`, `parent_object_ids` and `included_object_ids` weaken referential integrity, cascade behavior, indexing and impact queries.

### Final model

Use junction tables for all relationships that participate in authority, lineage, review or implementation coverage:

- `decision_claim`;
- `decision_evidence`;
- `provenance_parent`;
- `context_manifest_item`;
- `contradiction_decision`;
- `experiment_result`;
- `snapshot_member`.

JSON and arrays remain acceptable only for non-authoritative annotations and display bundles.

### Acceptance test

Deleting or superseding a referenced projection cannot leave an unresolvable UUID inside a core decision payload. Every critical edge is queryable and constraint-checked.

---

## 2.4 Hashing and signatures require a canonical serialization contract

### Problem

The v1 schema stores hashes and signatures but does not define the exact byte representation that is hashed or signed. Different JSON serializers can produce different bytes for the same logical object.

### Final model

- canonical JSON: RFC 8785 JSON Canonicalization Scheme;
- payload digest: SHA-256 over canonical bytes;
- attestation envelope: DSSE/in-toto-compatible statement where useful;
- signing: external signer or `cosign sign-blob` bundle for snapshots/public CI artifacts;
- private corpus: no mandatory publication to a public transparency log;
- event ledger: per-project sequence plus previous-event hash;
- periodic signed checkpoint: Merkle root over canonical decisions/events, copied off-host.

### Acceptance test

Two independent implementations serialize the same decision, obtain identical canonical bytes and SHA-256, and verify the same detached signature bundle.

---

## 2.5 Row-level security must be executable from day one

### Problem

The report describes project and data-class filtering, but the DDL does not define actual PostgreSQL Row-Level Security policies.

### Final model

- every project-scoped authoritative table carries `project_id` directly or through a mandatory constrained parent;
- RLS enabled and forced on project-scoped tables;
- session context contains actor, project scopes and maximum data class;
- blob retrieval first resolves an authorized occurrence;
- service roles cannot bypass RLS except a separately audited maintenance role;
- provider routing repeats authorization and data-class checks independently of search.

### Acceptance test

A query executed with project A scope cannot return project B metadata, search chunks, embeddings or a raw blob URL, including through joins and recursive graph traversal.

---

## 2.6 Embedding dimensions and model lineage must be explicit

### Problem

The v1 schema declares an arbitrary `embedding_dimensions` field while the actual column is `vector(1536)`. This is inconsistent and locks the schema to one model.

### Final model

For the MVP, select exactly one embedding profile and encode it explicitly:

```text
EmbeddingProfile(profile_id, provider, model, revision, dimensions,
                 normalization, data_class_policy, created_at)
EmbeddingChunk(search_document_id, profile_id, embedding, generation_id)
```

If multiple dimensions are later needed, use profile-specific tables/partitions or expression/partial indexes. Do not pretend one HNSW index supports arbitrary dimensions.

### Acceptance test

The semantic index can be dropped and recreated from `SearchDocument` and an `EmbeddingProfile`. Changing the model creates a new generation; it never silently overwrites old vectors.

---

## 2.7 Parser choice must be routed by format and benchmark, not declared globally

### Problem

“Docling-first” is plausible but not yet proven on MAWorld files. Official documentation establishes format support, not extraction quality on the actual corpus.

### Final parser router

- Markdown/TXT/source code/CSV: deterministic native parsers;
- DOCX/XLSX/PPTX: native OOXML extraction plus a layout-rich candidate when required;
- PDF with text layer: native text/layout candidate first;
- scanned PDF/images: OCR pipeline;
- unknown/broad formats: Apache Tika for detection/metadata and isolated fallback;
- Docling and Unstructured: benchmark candidates, not authority;
- all rich parsing: rootless disposable sandbox, no network, strict CPU/RAM/time/output limits.

### Acceptance test

The same benchmark corpus is processed by candidate pipelines. Default routing is selected by measured structure fidelity, locator accuracy, table fidelity, failure rate, latency and cost.

---

## 2.8 Provenance should map to an established conceptual model

### Final model

Use a minimal W3C PROV-compatible vocabulary:

- `Entity`: raw blob, source version, extraction output, claim, decision, test result;
- `Activity`: ingestion, extraction, claim generation, review, canonicalization, verification;
- `Agent`: owner, connector, parser, model, reviewer, CI system;
- relations: `wasGeneratedBy`, `used`, `wasDerivedFrom`, `wasAssociatedWith`, `actedOnBehalfOf`.

This is a mapping contract, not a requirement to deploy RDF or a graph database.

### Acceptance test

Export one research run and one canonical decision as a self-contained provenance bundle whose inputs, activities, agents and outputs can be reconstructed without querying model logs.

---

## 2.9 Workflow and observability records must be correlated

### Final model

Every ingestion/extraction/research/verification execution receives:

- stable `run_id`;
- job definition/version;
- input object IDs and hashes;
- output object IDs and hashes;
- start/end/failure events;
- trace ID and span IDs;
- code/container digest;
- retry attempt and idempotency key.

OpenTelemetry/OpenLineage-compatible exports may be emitted, but the Foundry database remains authoritative for Foundry domain state.

### Acceptance test

From a failed claim extraction, the owner can navigate to the exact input version, parser/model/prompt version, worker image digest, logs, retry event and successful replacement output.

---

## 2.10 Phase 0 should not require a self-hosted object-storage service

### Final decision

For a single-owner Phase 0:

- PostgreSQL;
- local filesystem content-addressed blob store with no-overwrite semantics;
- encrypted off-host backup;
- Git;
- one API/worker process;
- one web review interface.

Move to S3-compatible versioning/Object Lock when one of these triggers fires:

- multiple machines/workers need shared object access;
- legal/WORM retention is required;
- corpus size or availability makes local storage operationally unsafe;
- restore testing shows the local approach misses RPO/RTO.

This removes MinIO as an MVP dependency without weakening the logical storage contract.

---

## 3. FINAL REFERENCE ARCHITECTURE

```text
Sources
  ↓
Intake Gateway
  ↓
Local-only preflight: stream hash, file magic, size/archive limits,
malware/secret scan, initial data class
  ↓
Immutable RawBlob CAS
  ↓
ArtifactOccurrence + ArtifactVersion + Provenance Activity
  ↓
Sandboxed Parser Router
  ↓
Versioned Extraction Representation + exact locators
  ↓
Deterministic identity/dedup/version candidates
  ↓
Atomic Claim Proposals + Evidence Links
  ↓
Contradiction/Open Question/Required Experiment
  ↓
Human Review Workbench
  ↓ ContinuityOS capability decision
Immutable CanonicalDecision / Supersession Event
  ↓
ADR / Schema / API / Ticket / Commit / Test / Deployment / Runtime Evidence
  ↓
Coverage and Drift Views
```

### Authoritative stores

| Concern | Authority |
|---|---|
| raw bytes | RawBlob CAS |
| source observation/version | PostgreSQL |
| claims, evidence, conflicts | PostgreSQL immutable revisions + events |
| current workflow state | PostgreSQL projections |
| canonical decisions | signed immutable decision records |
| code/ADR/schema/test/deploy definitions | Git |
| runtime evidence | immutable captured evidence plus linked observability system |
| semantic/lexical index | derived PostgreSQL indexes, rebuildable |
| private agent memory | LifeOS, never project authority |

---

## 4. FINAL MVP STACK

### Required

- PostgreSQL 18 or a supported PostgreSQL 17 deployment;
- Python service and worker;
- filesystem CAS for Phase 0, S3-compatible adapter contract;
- Git;
- PostgreSQL FTS/GIN and `pg_trgm`;
- optional single-profile pgvector generation;
- sandboxed parser containers;
- minimal web workbench;
- ContinuityOS authorization adapter with a local fail-closed stub for development.

### Deferred

- Qdrant;
- OpenSearch;
- graph database;
- Temporal;
- DataHub/OpenMetadata;
- lakeFS;
- Kubernetes;
- autonomous canonicalization;
- all connectors beyond Manual Drop, Local Folder and Git.

### Optional derived systems

Choose at most one of Langfuse or Phoenix after the first model-assisted extraction benchmark. Neither stores canonical truth.

---

## 5. CORRECTED DECISION REGISTER

## KD-01 — Build a control plane, not a RAG product

**Decision:** Canonical truth is controlled by explicit events and review; retrieval only proposes context.  
**Evidence:** PostgreSQL supports transactional authoritative state and FTS; semantic indexes are derived.  
**Assumptions:** single owner, incomplete corpus.  
**Alternatives:** vector-first RAG; document platform.  
**Rejected Alternatives:** cannot provide explicit supersession, claim-level evidence or implementation coverage.  
**Risks:** review backlog.  
**Confidence:** `0.99`.  
**Acceptance Test:** deletion of all vectors does not alter any decision or evidence status.  
**Revisit Trigger:** none; this is a core invariant.

## KD-02 — Global RawBlob plus project-scoped occurrences

**Decision:** deduplicate bytes globally while governing access and lineage through project/source occurrences.  
**Evidence:** content addressing identifies byte equality; source-native IDs identify observations and histories.  
**Assumptions:** exact duplicate bytes can appear across sources/projects.  
**Alternatives:** project-local duplicate bytes; one artifact row per file.  
**Rejected Alternatives:** waste storage or conflate byte identity with provenance.  
**Risks:** blob access-control bugs.  
**Confidence:** `0.98`.  
**Acceptance Test:** cross-project duplicate test in §2.1.  
**Revisit Trigger:** regulatory requirement forbids cross-project physical deduplication.

## KD-03 — Events plus projections

**Decision:** immutable payloads/events; mutable operational projections.  
**Evidence:** statusful queues and connector cursors are not immutable knowledge objects.  
**Assumptions:** current-state queries require efficient projections.  
**Alternatives:** mutable rows only; full event sourcing for every field.  
**Rejected Alternatives:** mutable-only weakens audit; universal event sourcing adds unnecessary complexity.  
**Risks:** projection drift.  
**Confidence:** `0.96`.  
**Acceptance Test:** rebuild selected projections from events and immutable records.  
**Revisit Trigger:** projection rebuild becomes too expensive or events lack required information.

## KD-04 — PostgreSQL remains the sole Foundry authority

**Decision:** PostgreSQL owns domain state, RLS, events, graph edges and FTS.  
**Evidence:** current PostgreSQL supports RLS, GIN and text search; pgvector supports exact and approximate vector search.  
**Assumptions:** initial corpus is moderate and one-owner operations dominate.  
**Alternatives:** SQLite-only; OpenSearch/Qdrant/graph DB.  
**Rejected Alternatives:** additional stateful services without measured need.  
**Risks:** vector/filter scaling.  
**Confidence:** `0.94`.  
**Acceptance Test:** all MVP queries and policy filters pass with one database.  
**Revisit Trigger:** measured scale/latency thresholds, not projected growth.

## KD-05 — Parser router selected by benchmark

**Decision:** native parsers for simple formats; isolated candidate pipelines for rich documents; no universal parser declaration before corpus tests.  
**Evidence:** Docling, Unstructured and Tika have broad but materially different capabilities and security boundaries.  
**Assumptions:** the corpus includes mixed Russian/English PDFs, Office files, code and exports.  
**Alternatives:** Docling-only; cloud document intelligence only.  
**Rejected Alternatives:** format brittleness, privacy and lock-in.  
**Risks:** benchmark and routing complexity.  
**Confidence:** `0.96`.  
**Acceptance Test:** benchmark gate in §6.2.  
**Revisit Trigger:** one pipeline wins all material format families with stable quality and cost.

## KD-06 — W3C PROV mapping without RDF infrastructure

**Decision:** use Entity/Activity/Agent semantics in relational tables and export bundles.  
**Evidence:** W3C PROV provides interoperable provenance concepts.  
**Assumptions:** graph database/RDF are unnecessary for MVP.  
**Alternatives:** ad hoc JSON only; full triple store.  
**Rejected Alternatives:** ad hoc semantics drift; triple store is premature.  
**Risks:** incomplete mapping.  
**Confidence:** `0.91`.  
**Acceptance Test:** provenance export round-trip.  
**Revisit Trigger:** external interoperability requires native PROV-O/RDF queries.

## KD-07 — Canonical payloads use JCS and signed checkpoints

**Decision:** canonicalize JSON before hashing; hash-chain project events; sign decisions/snapshots through an external signer.  
**Evidence:** RFC 8785 defines reproducible JSON canonicalization; Sigstore/in-toto provide attestation patterns.  
**Assumptions:** private decisions may require offline/self-managed signing.  
**Alternatives:** database-only signature fields; sign every mutable row.  
**Rejected Alternatives:** undefined signing bytes and high operational friction.  
**Risks:** key loss or signer compromise.  
**Confidence:** `0.93`.  
**Acceptance Test:** independent signature verification and checkpoint restore.  
**Revisit Trigger:** hardware/KMS or multi-owner signing requirements.

## KD-08 — RLS and provider routing are independent gates

**Decision:** enforce project/data-class policy in PostgreSQL and again at provider routing.  
**Evidence:** RLS restricts rows per role/user; indirect prompt injection and sensitive uploads require defense in depth.  
**Assumptions:** services use separate least-privilege roles.  
**Alternatives:** application filters only.  
**Rejected Alternatives:** one missed filter becomes cross-project leakage.  
**Risks:** policy complexity and accidental denial.  
**Confidence:** `0.98`.  
**Acceptance Test:** adversarial cross-project and provider-exfiltration suite.  
**Revisit Trigger:** external authorization service can provide formally equivalent enforcement.

## KD-09 — Model outputs are proposals and must be evaluated

**Decision:** claim extraction and contradiction detection run under versioned prompts/models and benchmark datasets.  
**Evidence:** experiment/dataset systems support repeatable comparisons; model confidence is not evidence.  
**Assumptions:** local gold labels can be produced for a small seed set.  
**Alternatives:** manual-only; automatic promotion.  
**Rejected Alternatives:** manual-only does not scale; auto-promotion violates governance.  
**Risks:** evaluator bias and review cost.  
**Confidence:** `0.98`.  
**Acceptance Test:** unsupported-claim and locator-validity metrics meet gates before production enablement.  
**Revisit Trigger:** only after long-term calibrated performance and an explicit governance change.

## KD-10 — Build only three connectors initially

**Decision:** Manual Drop, Local Folder and Git. Google Drive is next.  
**Evidence:** this covers seed corpus, future intake and implementation mapping; Drive and GitHub provide durable incremental mechanisms for later adapters.  
**Assumptions:** current seed files and repositories are locally accessible.  
**Alternatives:** all connectors at once.  
**Rejected Alternatives:** delays the core lifecycle and multiplies failure semantics.  
**Risks:** later sources expose identity gaps.  
**Confidence:** `0.97`.  
**Acceptance Test:** owner adds arbitrary future files without reorganizing the workspace.  
**Revisit Trigger:** source latency materially blocks active work.

---

## 6. WHAT STILL REQUIRES DEEP RESEARCH OR EXPERIMENTS

## 6.1 Researchable from primary sources

1. exact PostgreSQL 18/RLS/backup baseline and supported deployment path;
2. current pgvector filtering/index constraints and one-profile schema;
3. raw-store options and verified immutability/backup semantics;
4. current Docling/Unstructured/Tika capabilities and security guidance;
5. Google Drive revisions/export/change-token edge cases;
6. GitHub webhook reconciliation and rate-limit behavior;
7. Sigstore/in-toto/SLSA patterns appropriate for private project decisions;
8. Langfuse versus Phoenix as a derived evaluation system;
9. legal/privacy implications of routing each MAWorld data class to providers;
10. operational cost and maintenance burden for one owner.

## 6.2 Requires local empirical benchmark

### Parser benchmark

Corpus: 20–40 representative files across PDF, scanned PDF, DOCX, XLSX, PPTX, Markdown, source code, Telegram/model exports.

Metrics:

- text completeness;
- reading order;
- headings/list hierarchy;
- table cell fidelity;
- page/sheet/slide locator accuracy;
- image/diagram references;
- Russian/English OCR quality;
- deterministic repeatability;
- failure/timeout rate;
- CPU/RAM/runtime;
- output stability across versions.

### Artifact identity/dedup benchmark

Gold pairs:

- exact duplicate;
- renamed duplicate;
- old content with new timestamp;
- DOCX/Markdown derivative;
- minor edit;
- partial export;
- generated summary;
- merged document;
- unrelated but semantically similar document.

Metrics: precision/recall by relation type and reviewer disagreement.

### Claim/evidence benchmark

Gold set: at least 150 material atomic claims with exact locators and statuses.

Metrics:

- atomicity pass rate;
- exact excerpt validity;
- locator validity;
- unsupported claim rate;
- evidence-link precision;
- duplicate claim rate;
- cost/latency;
- reviewer correction time.

### Contradiction benchmark

Gold set: at least 50 pairs covering direct contradiction, incompatible ADRs, stale capability, schema drift, code/document mismatch and renamed concepts.

Target before automatic queue creation:

- high-severity contradiction precision ≥ 0.90;
- recall ≥ 0.75;
- false P0/P1 conflicts ≤ 5%;
- every result carries both source locators and a proposed verification method.

### Security lab

- prompt injection in PDF/DOCX/HTML;
- macros and external links;
- zip/XML bombs;
- path traversal;
- parser crash/hang;
- secret in text/image/metadata;
- forged citations;
- cross-project retrieval;
- provider-routing bypass;
- object-store and database interruption;
- event-chain tampering;
- malicious parser/container dependency.

## 6.3 Requires access to real MAWorld artifacts

- `00_MASTER.md`;
- `01_RESEARCH_ADDENDUM_2026-07.md`;
- D1–D4 reports;
- current Deep Research prompts;
- selected ContinuityOS ADR/schema/policy/code/test files;
- at least one known contradictory pair;
- at least one real implementation receipt or runtime-evidence bundle.

Without these files, thresholds and parser/model decisions remain hypotheses.

---

## 7. UPDATED SEVEN-DAY BUILD CUT

### Day 1

Implement `RawBlob`, `ArtifactOccurrence`, `ArtifactVersion`, streaming SHA-256, no-overwrite local CAS and byte-recovery verification.

### Day 2

Implement SourceSystem, IngestionRun events, idempotent Manual Drop and Local Folder reconciliation.

### Day 3

Implement preflight/quarantine, file magic, limits, secret scan interface and sandbox job envelope.

### Day 4

Implement deterministic native extraction for Markdown/TXT/source code plus versioned extraction records and locators.

### Day 5

Implement duplicate/version candidates, one simple claim proposal path and review task projection.

### Day 6

Implement immutable CanonicalDecision/Supersession, JCS hashing, ContinuityOS authorization stub and ADR/ticket link.

### Day 7

Implement Inbox, one contradiction view, changelog, RLS tests, interruption/retry tests and backup/restore drill.

**Explicit cut:** no Drive connector, no vector search, no rich-document model parser, no Langfuse/Phoenix, no historical migration during the first seven days.

---

## 8. FINAL VERDICT

`NARROW AND BUILD` remains correct, with a stricter interpretation:

- the **architecture principles are final enough to implement**;
- the **v1 reference DDL is not final enough to run unchanged**;
- the **tool/model thresholds cannot be finalized by web research alone**;
- the **next Deep Research run must close evidence gaps and design experiments, not produce another broad architecture report**.

## 9. FIRST CONCRETE ACTION

Implement and test one API operation:

```text
POST /v1/projects/{project_id}/intake/uploads
```

For one Markdown file it must return:

```json
{
  "blob_id": "...",
  "occurrence_id": "...",
  "version_id": "...",
  "sha256": "...",
  "byte_size": 123,
  "raw_recovery_verified": true,
  "state": "RAW"
}
```

The acceptance test uploads the same file twice under different names and proves:

1. one `RawBlob`;
2. two source observations when the upload contexts differ;
3. no byte overwrite;
4. exact recovery by hash;
5. idempotent retry after worker interruption;
6. no parser/model invocation before the raw record is durable.

---

## 10. PRIMARY SOURCES USED FOR THE CLOSURE

- PostgreSQL 18 documentation: Full Text Search, GIN, Row Security Policies and current releases.
- pgvector official repository and filtering/index documentation.
- Amazon S3 documentation: Object Lock, Versioning and checksum integrity.
- Docling official documentation: supported formats, OCR and pipeline options.
- Unstructured official documentation: partitioning formats and strategies.
- Apache Tika official security model and parser documentation.
- OWASP File Upload and LLM Prompt Injection cheat sheets.
- W3C PROV-DM and PROV-O specifications.
- RFC 8785 JSON Canonicalization Scheme.
- SLSA provenance, in-toto Attestation Framework and Sigstore/Cosign documentation.
- OpenTelemetry tracing/log correlation and OpenLineage run/object models.
- Google Drive Changes API and export API documentation.
- Langfuse and Phoenix dataset/experiment documentation.
