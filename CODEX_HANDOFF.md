# MAWorld — security handoff

Дата: **2026-07-18**

## Зафиксированный baseline

- **LIVE OFF / BUILD_FREEZE BLOCKED / production HOLD**
- root **54/54, 1086**; active **20/21, 411, PostgreSQL SKIP=1**
- runner **22/22**; release status **14/14**; single-source **10/10**
- Tier-2 **42 PASS / 0 FAIL / 5 SKIP**
- Rust **72 PASS / 0 FAIL / 1 ignored DB acceptance**, fmt/Clippy PASS в digest-pinned Linux;
  durable scoped intake на Windows отключён
- Python OSV **44/0**; RustSec **169 dependencies / 0 findings**
- formats **291/5/8/24**, supply **3 profiles/71 entries**, images **3/3 digests**

Не повышать статус по unit-тестам, credential, env flag, endpoint availability или historical docs.

## Уже закрыто локально

- строгий positive-evidence contract root/active runners;
- fail-closed MCP bridge tombstone;
- RiskService checked integer math и adversarial extremes;
- exact Rust toolchain/workspace/lock/CI/RustSec gate;
- bounded/verified CAS, fail-before-replay, ledger locks/stale-writer rejection;
- bounded parser/binary routing;
- strict build-pinned Ed25519/JCS ingest authority с durable local nonce consume;
- atomic scoped PG blob+occurrence+version API, runtime INSERT revocation и migration `003`;
- signed-root child containment, one-sided missing marker/ledger fail-closed и strict directory sync;
  coordinated marker+ledger deletion/rollback остаётся HOLD;
- exact PG ACL allowlist и код PG16 membership/owner/RLS admission на каждой physical connection;
  guarded destructive DSN/server/cluster proof пока подтверждён static/unit, не real DB;
- PG raw pool removal, exact idempotency/lineage и guarded ignored DB acceptance;
- stale READY/PASSED docs и operational live commands.

## Следующая очередь

### P0

1. Целевой Linux/runsc без пяти SKIP и с signed host/rootfs/policy evidence.
2. Process-isolated secrets broker/KMS/HSM + shared transactional replay store.
3. External custody/rotation/trusted clock/shared replay и attested build provenance для local authority.
4. End-to-end authority→project-scope wiring и production PostgreSQL credentials/TLS/role deployment.
5. Dedicated disposable PostgreSQL migration/RLS/pool/concurrency/crash/recovery acceptance.

### P1

6. Signed PostgreSQL schema/policy/function attestation и deployment drift monitoring.
7. Verified proof-of-content либо tenant/keyed dedup с неразличимым outcome.
8. Trusted signed provenance для risk observations и independent order execution gate.
9. Stripe/venue/PostgreSQL acceptance с reconciliation и signed evidence.
10. Immutable mirror + signed SBOM/images/artifacts + external CI/license/provenance gate.
11. NATS mTLS/auth, MinIO least privilege и network policy.
12. Нормальная VCS provenance, signed refs/timestamps и independent release review.

## Приёмка

```powershell
powershell -File .\VERIFY.ps1
```

Профильные boundary tests обязательны. Production gate требует одновременно: Tier-2 без SKIP,
закрытые P0/P1, external acceptances, signed supply/evidence и отдельное решение владельца.

Источник: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
