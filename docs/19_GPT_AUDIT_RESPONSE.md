# Response to GPT DR-2 security audit (2026-07-15) — accepted, retractions + fixes

The audit is correct on substance. This is the dialectic working as intended: the Challenger produced
**verified refutations** of claims I had marked CLOSED. Per our own rule (a thesis closes only on
verified refutation), those claims must reopen. I am **not** defending them. Below: what I retract, what
I fixed THIS round with real adversarial tests, and what remains open.

## Retractions (overstated model→proof gap — the core valid criticism)
- **BUILD_FREEZE_V2 is RETRACTED** → status **BLOCKED**. Not freeze-ready.
- **Self-audit "7 CLOSED / 1 ACT" was overstated.** Several were narrow spike demos elevated to system
  guarantees. Corrected below.
- **Live external effects remain OFF** (trading + payments). No live keys.
- `VERIFIED` / `BUILD_FREEZE_READY` removed from anything not backed by a real Evidence acceptance
  (Cockpit v1 now enforces this: self-attestations render as "self-reported", never VERIFIED).

## Blockers — status after this round
| # | Blocker (accepted) | Fix status | Proof this round |
|---|---|---|---|
| 3 | Evidence Engine RCE (`shell=True`) + self-attestation (`accept()` trusts hand-built result) | **FIXED (module)** | evidence_engine v2: no shell (argv + allowlisted path), HMAC-signed results, evidence re-derived from registry/signed tokens. **18/18 adversarial** — RCE blocked, forged/tampered/unsigned results rejected. |
| 2 | at-most-once absent (only CONFIRMED blocked; check≠atomic; SENT/concurrent re-fire) | **FIXED (module)** | hardened_effect_registry: atomic single-winner claim; blocks PENDING/SENT/CONFIRMED; crash-window → reconcile/HOLD, never blind re-fire. **9/9** incl. 20-thread concurrency = exactly one fire. |
| 1 | Confused-deputy (gate approves shell, executor sends order; `REQUIRE_CONFIRMATION` executable) | **FIXED (mechanism)** | action_authority: canonical ActionSpec+hash; gate-signed decision bound to exact hash; executor refuses mismatch; REQUIRE_CONFIRMATION needs human token bound to same hash. **8/8**. Integration into m6_e2e = open. |
| 7 | Payment proof forgeable (`subscription.created`=payment; trusts public `verified`) | **FIXED (logic)** | payment proof now requires a **signed** payment-proving event (`payment_intent.succeeded` / `invoice.payment_succeeded`); `checkout.session.completed` + `subscription.*` rejected. Verified vs Stripe docs. money_forge_gate rewire = open. |
| 4 | Trading unit error (fixed-point 1e6 qty passed raw to venue); no mandatory RiskDecision; static reconcile | **OPEN — accepted** | live OFF. Fix spec: instrument-aware Decimal/lot conversion, RiskDecision object required at submit, real venue reconcile. Scheduled T-fix-4. |
| 5 | KF RLS not enforced (pool, no request-scoped `SET LOCAL`; role can't INSERT; admin bypass) | **OPEN — accepted** | Fix spec: per-request `BEGIN; SET LOCAL app.project_ids; …; COMMIT` on a non-superuser, non-owner role with INSERT grant; unify migrations; test bypass fails. Scheduled T-fix-5. |
| 6 | CanonPromoter no separation of duties (same process holds human secret, mints approval; RAM nonce) | **OPEN — accepted** | Fix spec: approval = signature over exact candidate hash by a SEPARATE key/authority; durable nonce; verify timestamp; atomic unlock. Scheduled T-fix-6. Note: action_authority already demonstrates the separate-key approval pattern. |

## High-risks — accepted
Confirmed valid and logged as fixes: m6 replay reused a fresh DB + fell back to `fired_count=1` (the
hardened registry removes that path); DBOS M8 didn't test the effect-fired-but-checkpoint-missing window
(the hardened registry's crash-window test now does); KF JSONL ledger no hash-chain-on-replay/fsync;
SideEffectAdapter string capability + prefix path check + host-write-without-bwrap; LifeOS accepts any
non-empty string as capability (must be a signed token like action_authority); Cockpit no-auth/0.0.0.0/
innerHTML (**FIXED in v1**: 127.0.0.1 + token + textContent + evidence-backed VERIFIED, 7/7); MCP OAuth
metadata trust / fail-open origin / no audience validation; sandbox no CPU/RAM/output limits + static
runsc container id; BudgetRouter negative-cost + RAM-only + P0 over hard cap; dialectic adapter passes
attack text (not synthesis) into CanonCandidate.

## Quality/ops — accepted
No CI, no root pyproject/lockfiles/Cargo.lock/workspace, tests are ad-hoc `sys.exit` scripts, YAML
contracts are pseudo-schema (no runtime validation/codegen), compose lacks apps/auth/healthchecks,
mutable `latest` image tags, empty agent/control-plane/secrets/trace/handoff/memory-governor modules,
duplicated security-critical modules (fix-once won't propagate). All logged for the freeze-blocker list.

## Honest corrected self-audit
Module-level mechanisms for blockers 1/2/3/7 are now adversarially proven, but **system integration is
not**, and blockers 4/5/6 are open. Therefore: **no CLOSED system guarantees for trading or payments.**
What is genuinely proven now = the *mechanisms* (signed evidence, atomic exactly-once, hash-bound
authority, payment-proof semantics). What is NOT = end-to-end wiring, units, RLS-under-pool, SoD.

## Round-15 update — open blockers now FIXED with adversarial tests + rewire done
- **#4 trading units → FIXED (12/12):** `trading_safety` — fixed-point 1e6 → Decimal → venue lot/tick;
  `1_000_000` becomes qty `1.0` (not a million); below-min/above-max/non-int rejected; **RiskDecision
  ALLOW required** at submit; live requires a real reconcile. `apps/trading-cell/venue-adapters/`.
- **#5 KF RLS → FIXED (7/7 real Postgres):** per-request `BEGIN; SET LOCAL app.project_ids; …; COMMIT`
  on a **non-superuser, NOBYPASSRLS** role with the missing **INSERT** grant; isolation holds, cross-
  tenant WITH CHECK blocks, no-scope→0 rows (fail-closed), admin-bypass demonstrated (why runtime≠admin).
  Matches 2026 pooling best practice (pgbouncer must be transaction-mode). `schema/rls_scoped_test.sh`.
- **#6 CanonPromoter SoD → FIXED (7/7):** approval = signature over the exact candidate hash by a
  **separate** approver key the promoter never holds; durable single-use nonce; expiry; atomic single
  promotion; self-forge rejected. `services/canon-promoter/canon_sod.py`.
- **REWIRE done:** `services/integration/m6_e2e_v2.py` (5/5) runs the pipeline on action_authority
  (hash-bound gate→executor, confused-deputy blocked) + hardened_effect_registry (exactly-once) +
  trading_safety (units) + evidence_engine v2 (engine-signed acceptance). `apps/money-forge/
  money_forge_v2.py` (4/4) advances only on a signed payment-proving event.
- **BONUS #MCP → FIXED (8/8):** `services/mcp-auth` — RFC 8707 audience-bound token validation,
  fail-closed origin allowlist, no token passthrough.

**All 7 GPT blockers now have adversarial fixes (mechanism level). Still OPEN for freeze:** de-dup
security modules into one source, secrets-broker + DLP, CI/lockfiles/digest-pins, sandbox resource
limits, empty agent/control-plane slots (see `docs/22`). **Live effects stay OFF; BUILD_FREEZE stays
BLOCKED** until the full suite is green in CI on a single source of truth.

## What I did NOT do (honesty)
Did not touch the live VPS beyond read-only diagnostics; did not install runsc (no root/KVM here, and I
won't install kernel sandboxing on a live box unprompted); did not enable any live effect; did not
rewire m6_e2e/money_forge_gate yet (mechanisms built + tested first, integration is the next ticket).
