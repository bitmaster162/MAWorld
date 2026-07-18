# DR (self-run) — findings applied to MAWorld, 2026-07-15

I ran my own docs/20 prompts as web research and applied the results. Where research validated a fix I
say so; where it demanded a NEW fix I built + tested it.

## 1. Exactly-once / idempotency — VALIDATES the hardened effect registry
Finding: **"exactly-once delivery is mathematically impossible"** — real systems do **effectively-once =
at-least-once + idempotent processing** (idempotent-consumer / inbox: atomically record the message id in
the same transaction as the business op; discard duplicates). This is exactly what
`hardened_effect_registry` does: atomic single-winner claim on the idempotency key + status ladder +
crash-window reconcile. Applied: keep the atomic-claim design; the "transactional outbox" is the right
shape for the future event bus (business write + outbox row in one tx, poller publishes). Idempotency
key stays client-generated (UUIDv7) and is stored with the result. Proven: 9/9 incl. 20-thread concurrency.

## 2. RLS under connection pooling — VALIDATES the scoped-transaction fix
Finding: the #1 rule is **replace every session `SET` with `SET LOCAL` inside an open transaction**;
session GUCs leak across tenants on a pooled backend; `SET LOCAL` outside a tx → **0 rows** (fail-closed);
RLS is incompatible with **statement** pooling and needs **transaction** pooling at most. Our fix matches
exactly: `BEGIN; SET LOCAL app.project_ids=…; query; COMMIT` on a **non-superuser, NOBYPASSRLS** role.
Proven 7/7 on real Postgres (isolation holds, INSERT works, cross-tenant WITH CHECK blocks, no-scope→0,
admin bypasses = why runtime must not be admin). Applied note: **pgbouncer must be transaction-pooling**,
never statement-pooling; documented for deploy.

## 3. MCP authorization — NEW fix built (`services/mcp-auth`, 8/8)
Finding (MCP Authorization spec + RFC 8707): the server, as an OAuth2.1 resource server, **MUST validate
the token audience** is THIS server, reject non-audience-bound tokens (**401**), validate issuer/expiry/
scope, and **MUST NOT pass the token upstream**. Audience-binding is the spec's own **confused-deputy
mitigation**. Our old preflight trusted caller metadata and failed **open** on an empty origin allowlist.
Built `mcp_token_validator`: audience==this-server (RFC 8707), trusted issuer, expiry, required scope,
**fail-closed** empty allowlist, signature check, no passthrough. Adversarial 8/8 (wrong-aud/iss/expired/
scope/origin/forged all rejected).

## 4. Trading unit safety — research-consistent
Decimal/lot/tick conversion + mandatory RiskDecision + live-off matches "dry-run testing modes +
human-in-the-loop for high-impact actions." Proven 12/12.

## What this round changed at the mechanism level (all adversarially tested)
evidence-engine v2 18/18 · effect-registry 9/9 · action-authority 8/8 · trading-safety 12/12 ·
canon-SoD 7/7 · m6 e2e v2 5/5 · money-forge v2 4/4 · mcp-auth 8/8 · RLS scoped 7/7 · cockpit v1 7/7.

## Sources
- Idempotency/outbox: https://backendbytes.com/articles/idempotency-patterns-distributed-systems/ · https://oneuptime.com/blog/post/2026-01-30-exactly-once-delivery/view · https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
- RLS + pooling: https://multi-tenant-saas.com/tenant-aware-data-routing-query-scoping/connection-pooling-in-multi-tenant-systems/pgbouncer-transaction-pooling-for-multi-tenant-saas/ · https://planetscale.com/blog/rls-sounds-great-until-it-isnt
- MCP auth / RFC 8707: https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization · https://nhimg.org/community/workload-identity-management-forum/rfc-8707-and-mcp-authorization-are-your-tokens-audience-bound/
