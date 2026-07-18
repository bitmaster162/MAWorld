# MAWorld Canonical Synthesis v1.4
## Control Spine Research Adjudication and DR-2 Task-Compliance Audit

**Date:** 2026-07-15  
**Parent:** `MAWorld_Canonical_Synthesis_v1.3_Rust_Intake_Delta.md`  
**New source:** `ContinuityOS Control Spine и Competitive Primitives Delta Study.docx`  
**System verdict:** **HARDEN AND BUILD**  
**Report verdict:** **STRONG SUPPORTING RESEARCH / PARTIAL DR-2 COMPLETION**

---

# 1. Task-Compliance Verdict

The new report is technically useful and source-conscious, but it is not a
complete answer to `CONTROL_SPINE_MANDATORY_BROKER_V3`.

## What it completed well

- workflow-runtime comparison;
- agent-harness comparison;
- MCP 2025-11-25 audit;
- forward-compatible treatment of unverified 2026 claims;
- observability/eval options;
- cost-policy hypotheses;
- secrets/identity narrowing;
- gVisor/E2B/Modal sandbox tiers;
- BranchLedger and ExternalEffectRegistry requirements;
- a production-shaped falsification workflow.

## What it did not complete

- actual ContinuityOS repository reality matrix;
- actual Rust intake source verification;
- independent build/test reproduction;
- PostgreSQL/sqlx migration review;
- RLS isolation tests;
- CTHA/mind repository inspection;
- Proposal Bridge specification and negative tests;
- CanonPromoter closure;
- direct `add_canon()` remediation;
- mandatory-broker bypass matrix;
- filesystem/Git/DB/secret adapter boundaries in file-level detail;
- actual DBOS spike verification;
- a complete `CODEX_HANDOFF`;
- file-by-file patch plan against the real repository.

Canonical classification:

```text
As general Control Spine research:
STRONG PASS

As DR-2 V3 implementation closure:
PARTIAL PASS

As replacement for repository audit and Codex handoff:
REJECT
```

The report should be attached to the next Claude/Codex pass as supporting
evidence, not treated as the final DR-2 closure.

---

# 2. Decisions Confirmed by the New Report

## 2.1 Authority Must Stay Outside Agent Frameworks — ACCEPT

The report independently confirms that:

- OpenAI handoffs;
- Claude agent loops;
- Google ADK delegation;
- Microsoft workflow transitions

are orchestration/runtime primitives, not signed delegated-authority systems.

Canonical rule remains:

```text
Framework control transfer
!=
ContinuityOS authority transfer
```

All tool permission continues to derive from:

- DelegationGrant;
- CapabilityToken;
- ActionSpec;
- ContinuityOS policy decision.

## 2.2 Thin Custom Harness — ACCEPT

Use:

```text
ProviderAdapter
FrameworkAdapter
```

under an MAWorld-owned harness.

Provider SDKs may offer:

- nested agents;
- subagents;
- handoffs;
- sessions;
- tool convenience.

They may not own:

- authoritative task state;
- authority;
- memory promotion;
- policy;
- approval;
- external-effect truth.

## 2.3 MCP Stable/Draft Split — ACCEPT

The new report confirms the currently line-verified published baseline as
`2025-11-25` and treats the alleged `2026-07-28` revision as unresolved.

Canonical implementation:

```text
MCPAdapterV2025Stable
MCPAdapterVDraft
→ CanonicalMCPRequest
→ ContinuityOS
```

Current stable work proceeds now.

No current session, version, auth, or transport logic is deleted for an
unratified future draft.

## 2.4 MCP Authorization Resolver — ACCEPT

Add a deterministic `MCPAuthorizationResolver` responsible for:

- issuer metadata;
- Protected Resource Metadata;
- requested and granted scopes;
- audience/resource binding;
- token expiry;
- token-passthrough rejection;
- incremental-scope HOLD;
- tool descriptor hash;
- server fingerprint.

## 2.5 Async MCP Task Registry — ACCEPT

Add `AsyncTaskRegistry`.

Required binding:

```text
external_task_id
+ action_spec_id
+ delegation_grant_id
+ trace_id
+ workflow_id
```

No orphan polling.

Task creation is not task completion.

## 2.6 gVisor Tier 2 — ACCEPT AS SPIKE TARGET

The report further supports:

```text
Linux VPS
+ rootless OCI
+ gVisor
+ read-only rootfs
+ egress deny
+ no host socket
```

as the first production-shaped sandbox target.

It remains `REQUIRES BYPASS TESTS`, not a zero-risk claim.

## 2.7 E2B and Modal — ADAPT

- E2B: Tier 3 managed candidate while local KVM is unresolved.
- Modal: Tier 4 GPU candidate.
- Daytona: HOLD until isolation guarantees are proven.
- Firecracker: HOLD until actual `/dev/kvm` feasibility is proven.

## 2.8 SOPS + age MVP — ACCEPT

The new report aligns with Canon v1.3:

```text
SOPS + age
+ OS keychain bootstrap
+ short-lived adapter-scoped credentials
```

No dedicated Vault/Infisical control plane in the first slice.

---

# 3. Runtime Conflict: Temporal vs DBOS

The new report recommends:

```text
Temporal first
DBOS second
```

Earlier source-backed reports and the Claude implementation narrative recommend:

```text
DBOS first
Temporal migration target
```

This cannot be resolved by report count.

## 3.1 Evidence Comparison

### Temporal advantages

- mature event-history model;
- replay and reset surfaces;
- signals, timers, cancellation;
- stronger operational workflow tooling;
- multi-service/multi-language scaling path.

### Temporal costs

- separate always-on control service;
- deterministic workflow discipline;
- additional operational surface;
- custom BranchLedger still required;
- custom ExternalEffectRegistry still required.

### DBOS advantages

- Postgres-centered;
- lower single-owner operations burden;
- Python/TypeScript embedding;
- strong fit with current Knowledge Foundry PostgreSQL direction;
- a local recovery spike is reported to exist.

### DBOS unknowns

- the claimed spike is not yet independently reproduced;
- immutable branch semantics remain custom;
- external-effect reconciliation remains custom;
- long-horizon operational tooling is less proven in the attached package.

## 3.2 Canonical Runtime Decision

Do not switch the current build to Temporal solely because of this report.

Canonical rule:

```text
DurableRuntimeAdapter
├── DBOS implementation candidate
└── Temporal implementation candidate
```

Execution order:

1. Independently verify the reported DBOS spike.
2. Run the same `ExternalEffectRegistry` acceptance test.
3. Measure glue-code and operational burden.
4. Use Temporal only when the DBOS candidate fails the gate or exceeds the
   defined complexity threshold.

## 3.3 Runtime Selection Gate

Select DBOS when all are true:

- recovery test passes;
- no duplicate effect;
- human HOLD resumes correctly;
- branch/effect contracts remain runtime-independent;
- one-owner operations remain simple;
- custom glue remains bounded.

Escalate to Temporal when one is true:

- DBOS evidence cannot be reproduced;
- multi-language workers are immediately required;
- workflow signals/timers dominate the product;
- custom recovery/branch glue exceeds the workflow business logic;
- operator inspection and reset tooling becomes a critical requirement;
- availability requires a mature distributed workflow cluster.

Current canonical status:

```text
DBOS: FIRST SPIKE
Temporal: PRE-APPROVED FALLBACK / MIGRATION TARGET
```

The new report’s `TemporalRuntimeAdapter` becomes the generic
`DurableRuntimeAdapter`, not an immediate frozen implementation.

---

# 4. Observability Conflict: Phoenix vs Langfuse

The new report recommends Phoenix because its self-hosting path was verified in
that research pass.

Earlier research verified both Phoenix and Langfuse and preferred Langfuse for
trace/cost UI.

## Canonical resolution

Do not couple MAWorld to either product.

Use:

```text
Internal TraceContext
→ OTel Collector
→ ObservabilityBackend
```

MVP backend decision:

```text
Phoenix first
```

Reason:

- narrower tracing/eval footprint;
- source-verified self-hosting in the new report;
- useful regression/evaluation capabilities;
- lower risk of building a broad observability platform before the core works.

Langfuse status:

```text
HOLD / ALTERNATE BACKEND
```

Adopt Langfuse later when:

- prompt-management UI;
- cost lens;
- sessions/agent-graph UI;
- broader operator workflows

provide measurable value beyond Phoenix.

Immutable audit remains separate from both.

---

# 5. New Canonical Components

The following components from the report are accepted into the architectural
backlog.

## 5.1 MCPAuthorizationResolver

Deterministic service.

Inputs:

- protocol version;
- server fingerprint;
- issuer;
- resource metadata;
- requested scopes;
- granted scopes;
- audience;
- token expiry;
- tool descriptor.

Outputs:

- verified auth context;
- HOLD for scope escalation;
- DENY for issuer/audience mismatch;
- normalized fields for ActionSpec.

## 5.2 AsyncTaskRegistry

Owns external asynchronous task correlation and status.

States:

```text
CREATED
→ RUNNING
→ INPUT_REQUIRED
→ RESULT_READY
→ RESULT_FETCHED
→ VERIFIED
→ COMPLETED / FAILED / EXPIRED / CANCELLED
```

## 5.3 BudgetRouter

Runs before model invocation.

Owns:

- role-level budget;
- provider lane;
- cache policy;
- batch eligibility;
- fallback;
- P0/P1 reserves;
- stale-price HOLD;
- actual cost observation.

Dollar ranges in the report remain `HYPOTHESIS`, not canonical budgets.

## 5.4 EvalRegistry

Owns:

- golden datasets;
- regression fixtures;
- prompt versions;
- model-binding versions;
- evaluator mode;
- drift verdict;
- evidence references.

## 5.5 Tiered Runner Adapters

- `Tier2LinuxRunner`
- `Tier3RemoteRunner`
- `Tier4GpuRunner`

All outputs require verification before promotion.

---

# 6. Updated MCP Canon

## Stable baseline

Target current stable MCP `2025-11-25` behavior:

- Streamable HTTP;
- protocol version;
- session semantics where applicable;
- Protected Resource Metadata;
- incremental scopes;
- resource/audience binding;
- token-passthrough prohibition;
- experimental tasks.

## Forward compatibility

Store future claims as data:

```yaml
protocol_revision_verified: "2025-11-25"
protocol_revision_claimed: "2026-07-28"
claim_status: "UNRESOLVED"
```

Do not embed unverified future claims into core policy logic.

## Additional accepted controls

- `tool_descriptor_hash`;
- `server_fingerprint`;
- header allowlist;
- session ID separate from authority ID;
- scope escalation creates HOLD/approval;
- async tasks preserve original authority lineage.

---

# 7. Updated First Control-Spine Spikes

The report proposes:

```text
git_commit_with_hold_and_recovery
```

This is a strong second-stage spike.

## Spike A — Boundary-Proven File Action

Required first because it is smaller and isolates the authority boundary.

```text
Foundry CanonicalDecision
→ CTHA proposal
→ Proposal Bridge
→ ActionSpec
→ DBOS candidate
→ ContinuityOS
→ gVisor temp-directory write
→ byte verification
→ audit/trace
→ crash/recovery
```

## Spike B — Git Commit with Push HOLD

After Spike A passes:

1. Owner requests “prepare patch and commit”.
2. Orchestrator plans.
3. Delegation permits:
   - repository read;
   - working-tree write;
   - test;
   - commit.
4. `git push` remains HOLD.
5. Work executes in Tier 2 Linux runner.
6. Runtime is killed at a controlled point.
7. Recovery does not create a duplicate commit.
8. Commit artifact, diff, tests, evidence, audit, and trace are produced.
9. Push still requires explicit approval.

This becomes the first realistic Codex workflow.

---

# 8. Report Claims Not Promoted

The following remain non-canonical:

## Cost bands

The report’s monthly ranges are planning hypotheses.

They depend on assumed:

- models;
- token volumes;
- output verbosity;
- cache rates;
- provider mix;
- sandbox use.

Canonical action:

- build PriceCatalog;
- ingest official rates;
- measure real token histograms;
- forecast after the first 100–1,000 runs.

## Temporal unconditional selection

Held behind runtime acceptance gate.

## Phoenix as permanent backend

Phoenix is first implementation, not permanent architecture.

## “Exactly once” broker semantics

NATS/transport deduplication does not replace ExternalEffectRegistry.

## Future MCP 2026 claims

Remain unresolved.

---

# 9. Updated Decision Ledger

## ACCEPT

- thin custom harness;
- provider/framework adapters;
- authority outside frameworks;
- current MCP stable migration;
- MCPAuthorizationResolver;
- AsyncTaskRegistry;
- internal TraceContext;
- OTel Collector;
- Phoenix first backend;
- EvalRegistry;
- BudgetRouter;
- SOPS+age;
- gVisor Tier 2;
- E2B Tier 3 candidate;
- Modal Tier 4;
- Git commit HOLD/recovery spike.

## ADAPT

- Temporal as runtime adapter candidate;
- DBOS as first reproducibility spike;
- OpenAI Agents as tools for bounded subwork;
- Claude/ADK/Microsoft patterns as execution conveniences;
- future MCP fields behind compatibility adapters;
- cost bands into measured PriceCatalog forecasts.

## HOLD

- final runtime selection;
- Langfuse;
- exact budget values;
- Firecracker;
- Daytona security boundary;
- Vault/Infisical;
- MCP revision above 2025-11-25;
- direct implementation from this report without repository audit.

## REJECT

- using agent-framework handoff as authority;
- LangGraph as Control-plane authority;
- custom NATS+Postgres workflow runtime for MVP;
- treating NATS dedupe as exactly-once external effects;
- selecting Temporal without comparing the existing DBOS artifact;
- presenting this report as full DR-2 V3 completion.

---

# 10. Missing Work Before DR-2 Closure

The next Claude/Codex pass must still produce:

1. repository inventory;
2. exact source checksums;
3. Rust bundle independent reproduction;
4. DDL/sqlx audit;
5. RLS tests;
6. direct ContinuityOS bypass matrix;
7. Proposal Bridge;
8. CTHA boundary proof;
9. CanonPromoter;
10. ExternalEffectRegistry implementation;
11. DBOS-vs-Temporal acceptance comparison;
12. file-level patch plan;
13. Codex handoff;
14. first integrated security tests.

Until then:

```text
DR-2 status = OPEN
```

---

# 11. Next Input Package for Claude

Attach:

1. `DR2_Control_Spine_Mandatory_Broker_V3.md`
2. `MAWorld_Canonical_Synthesis_v1.3_Rust_Intake_Delta.md`
3. this v1.4 adjudication
4. new Control Spine research report
5. actual ContinuityOS repository
6. actual Rust intake source bundle
7. actual DBOS spike artifacts, if present

Instruction to Claude:

```text
Use the new report as supporting evidence.
Do not replace the mandatory repository and implementation audit with its
Temporal/Phoenix recommendations.
```

---

# 12. Final Verdict

```text
New report quality: STRONG
Task compliance against DR-2 V3: PARTIAL
Architecture impact: MATERIAL
Build decision: HARDEN AND BUILD
DR-2 closure: NOT YET COMPLETE
```

The report improves the control-spine design, especially around current MCP,
framework authority separation, async tasks, and tiered execution. It does not
replace the implementation closure that must inspect and harden the real project.
