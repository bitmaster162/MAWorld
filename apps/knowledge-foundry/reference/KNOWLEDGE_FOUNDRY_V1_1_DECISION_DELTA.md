# Knowledge Foundry v1 → v1.1 Decision Delta

| Area | v1 | v1.1 final position |
|---|---|---|
| Raw artifact identity | `Artifact` mixes bytes and project scope | global `RawBlob` + project/source `ArtifactOccurrence` + `ArtifactVersion` |
| Object registry | content hash required for mutable objects | immutable payload revisions/events separated from mutable projections |
| Critical edges | several UUID arrays | normalized junction tables |
| Signatures | algorithm/signature fields without byte contract | RFC 8785 canonical JSON + SHA-256 + external signer/checkpoints |
| Security | policy described | PostgreSQL RLS and provider routing as executable independent gates |
| Embeddings | arbitrary dimension field + `vector(1536)` | one explicit `EmbeddingProfile` in MVP; new generation for model changes |
| Parsing | Docling-first | format-aware parser router; winner selected by corpus benchmark |
| Provenance | custom ledger | W3C PROV-compatible Entity/Activity/Agent mapping, relational implementation |
| Runtime traces | domain-specific only | stable run IDs plus OTel/OpenLineage-compatible derived exports |
| Raw store Phase 0 | object storage emphasized | local no-overwrite CAS + off-host backup; S3 adapter when trigger fires |
| Readiness claim | build-ready reference | architecture-ready, DDL patch and corpus calibration still required |
| Verdict | NARROW AND BUILD | NARROW AND BUILD, with P0 schema corrections before seed ingestion |
