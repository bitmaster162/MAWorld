# Knowledge Foundry схемы
Полные DDL: infrastructure/sql/001_knowledge_foundry.sql
24 сущности (D7): SourceSystem, Artifact, ArtifactVersion, DuplicateCluster, IngestionRun,
DataClassification, ExtractionRecord, ProvenanceRecord, SourceLedger, Claim, EvidenceLink,
ContradictionRecord, OpenQuestion, CanonicalDecision, SupersessionRecord, ArchitectureImpact,
ImplementationLink, ADRReference, BacklogReference, ResearchRun, ContextManifest, DecisionDelta,
ReviewTask, AccessPolicy.
Статусы Claim: PROPOSED, SUPPORTED, VERIFIED, DISPUTED, CONTRADICTED, STALE, SUPERSEDED, UNVERIFIABLE, REJECTED.
Канонизация: RAW→PARSED→INDEXED→CLAIMS_EXTRACTED→REVIEW_REQUIRED→ACCEPTED_AS_EVIDENCE→CANDIDATE_CANON→CANONICAL→(SUPERSEDED|STALE|QUARANTINED).
