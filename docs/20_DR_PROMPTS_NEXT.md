# Deep Research prompts — next round (post-GPT-audit). Adversarial + reproducible.

Both prompts demand REPRODUCIBLE evidence (commands, file:line, pass/fail), not prose. They target the
OPEN blockers (#4 trading units, #5 RLS-under-pool, #6 separation-of-duties) and a mandated re-audit of
this round's fixes (evidence_engine v2, hardened_effect_registry, action_authority, cockpit v1).

---
## Prompt for GPT (o-series) — "Adversarial correctness of the fixes + open blockers"

You are the independent Challenger for MAWorld. Read-only. Do NOT trust prior status docs. Your job is
to FALSIFY, with reproducible evidence (file:line, exact command, observed vs expected).

1. RE-AUDIT this round's fixes — try to break each:
   - `services/evidence-engine/evidence_engine.py` (v2): can you still (a) achieve command execution via
     any claim field, (b) get `accept()` to return accepted for a result the engine did not sign, (c)
     make a workflow/payment/memory claim pass without the real re-derivation? Attack the HMAC handling,
     canonicalization, path allowlist, and timing.
   - `services/workflow-runtime/hardened_effect_registry.py`: prove or refute true at-most-once under
     (a) process kill between SENT and CONFIRMED, (b) two processes on two connections racing the claim,
     (c) SQLite vs the Postgres `INSERT ... ON CONFLICT DO NOTHING RETURNING` port. Is the reconcile
     contract sound, or can it double-fire or wrongly confirm?
   - `services/action-authority/action_authority.py`: can a decision for spec A ever authorize spec B?
     Attack canonicalization (unicode, key ordering, param types), replay of an old decision, and the
     confirmation-token binding. Is REQUIRE_CONFIRMATION truly non-executable without the human token?
2. OPEN blocker #4 (trading units): design the correct instrument-aware conversion (fixed-point 1e6 →
   Decimal → venue lot size / tick size) for Binance/Hyperliquid/Bitunix, the mandatory RiskDecision
   contract at submit, and a real (non-static) reconciliation. Provide a failing test that catches a
   wrong-units order, and the exact code to make live-safe. Live stays OFF until this passes.
3. OPEN blocker #6 (separation of duties): specify an approval protocol where the approver key is NOT
   held by the promoting process, approval signs the exact canonical candidate hash, nonces are durable,
   timestamps validated, and unlock is atomic. Give a threat model + reproducible test that a process
   cannot self-approve. (We already have the separate-key pattern in action_authority — extend it.)
4. Distributed-systems formalization: is a transactional outbox the right exactly-once pattern here?
   Compare against DBOS durable steps. Where must idempotency keys be cryptographically bound to payload?
Deliver: a falsification report (what broke, file:line, repro), corrected specs, and failing→passing
tests. Rank by exploitability.

---
## Prompt for Gemini (2.x Pro / Deep Research) — "Production-readiness, RLS-under-pool, MCP auth, reproducibility"

You are the independent production-readiness reviewer for MAWorld. Read-only, sourced, reproducible.

1. OPEN blocker #5 (Knowledge Foundry RLS): the Rust store must enforce per-request tenant isolation
   under a CONNECTION POOL. Research and specify the correct pattern: `BEGIN; SET LOCAL app.project_ids
   = ...; <query>; COMMIT` on a role that is NON-superuser and NON-owner (so it cannot bypass RLS), with
   the exact GRANTs (including INSERT, which the current role lacks) and `FORCE ROW LEVEL SECURITY`.
   Address pgbouncer/transaction-pooling interaction with SET LOCAL. Cite PostgreSQL docs. Provide a
   reproducible test proving: correct role isolates tenants; admin/owner bypass is DISALLOWED in prod;
   the service can actually INSERT. Unify the divergent compose schema.
2. MCP Authorization conformance: audit our MCP preflight against the current MCP Authorization spec —
   token audience/resource-server validation, issuer, expiry, scope, signature, and origin allowlist
   fail-CLOSED (not fail-open on empty). Cite the spec. Provide conformant validation code + tests.
3. Reproducibility & CI: specify the minimal but real setup — root pyproject + lockfile, Cargo.lock +
   workspace, pinned image digests (no `latest`), a single pytest/cargo-test suite replacing ad-hoc
   `sys.exit` scripts, pre-commit, and a CI that runs the adversarial suite (concurrency, crash-window,
   replay, unpaid-Stripe, RLS-bypass, sandbox-exhaustion). Cite Docker immutable-tag/digest docs.
4. Observability wiring: concrete Langfuse(self-host) + OTel/OpenInference plan so every run's trace_id
   binds to an Evidence `claim_id` → real "cost per verified outcome". Deliverable = runnable config.
5. De-duplication: list every copy of the security-critical modules (effect registry, gate bridge,
   sandbox) and propose the single-source-of-truth refactor so fix-once propagates.
Deliver: sourced findings, runnable configs/migrations, and reproducible tests. Flag anything where our
code contradicts an official spec with the citation.

---
## Rule
Both results return through `dialectic-adjudicator` as EVIDENCE (Devil/Angel/verified-refutation), not
as new authority. Nothing is marked CLOSED without a reproducible passing adversarial test. Live effects
stay OFF until blockers 4/5/6 pass. No BUILD_FREEZE until the full adversarial suite is green in CI.
