# MAWorld — security handoff

Дата: **2026-07-22**

## Зафиксированный baseline

- **LIVE OFF / BUILD_FREEZE BLOCKED / production HOLD**
- root **54/54, 1086**; active **20/21, 411, external PostgreSQL RLS SKIP=1**
- runner **22/22**; release status **14/14**; single-source **10/10**
- Tier-2 **42 PASS / 0 FAIL / 5 SKIP**
- Rust authority v3 **109 PASS / 0 FAIL / 1 ignored**, fmt/Clippy PASS; `kf-intake` 70,
  `kf-parser` 17, `kf-store-pg` 9 default, trading risk 13
- guarded disposable PostgreSQL 16 authority v3 **1/1 PASS, 37.00s**; domain
  `dddddddd-dddd-4ddd-8ddd-dddddddddddd`, grants=7, consumed=3, blobs/occurrences/versions=3/3/3;
  disposable container удалён
- Python OSV **44/0**; RustSec **169 dependencies / 0 vulnerabilities, 1166 advisories loaded**
- supply **3 profiles/71 entries**, images **3/3 digests**, Compose config PASS
- `Cargo.lock` SHA-256 `714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171`

Не повышать статус по unit-тестам, credential, env flag, endpoint availability или historical docs.

## Уже закрыто локально

- строгий positive-evidence contract root/active runners;
- fail-closed MCP bridge tombstone;
- RiskService checked integer math и adversarial extremes;
- exact Rust toolchain/workspace/lock/CI/RustSec gate;
- bounded/verified CAS, fail-before-replay, ledger locks/stale-writer rejection;
- bounded parser/binary routing;
- strict build-pinned Ed25519/JCS authority v3 с signed `authority_domain_id` и durable local nonce consume;
- `ConsumedIngestAuthority → CAS publish → StoredIngestAuthority`; borrowed registrar proof
  rehashes exact CAS bytes immediately before SQL;
- one-shot empty-volume migration chain `001→002→003→004`; grant binds session role OID, runtime
  caller supplies only `grant_id`, public outcome hides blob/created flags;
- signed-root child containment, one-sided missing marker/ledger fail-closed и strict directory sync;
  coordinated marker+ledger deletion/rollback остаётся HOLD;
- exact PG ACL/function allowlist, client/server timeouts и PG16 membership/owner/RLS admission на
  каждой physical connection; raw pool removal и exact idempotency/lineage;
- guarded destructive authority-v3 acceptance прошла локально; production lifecycle всё ещё HOLD;
- stale READY/PASSED docs и operational live commands.

## Следующая очередь

### P0

1. Целевой Linux/runsc без пяти SKIP и с signed host/rootfs/policy evidence.
2. Process-isolated secrets broker/KMS/HSM + shared transactional replay store.
3. External custody/rotation, trusted clock, monotonic replay anchor и attested build provenance.
4. Повтор current Rust/PG evidence в clean external CI на immutable release artifact.
5. PostgreSQL TLS/credential confidentiality; one-shot `004` existing-volume/crash/restore acceptance;
   clone quarantine с domain+credential rotation.

### P1

6. Signed PostgreSQL schema/policy/function attestation и deployment drift monitoring.
7. Tenant/keyed dedup либо timing/lock/error non-interference proof (direct created/blob outcome скрыт).
8. Trusted signed provenance для risk observations и independent order execution gate.
9. Stripe/venue acceptance с reconciliation и signed evidence; descriptor-safe CAS finalize/recovery.
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
