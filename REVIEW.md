# MAWorld — security review snapshot

Дата: **2026-07-18**

## Итог

**Проверенные локальные Python/Rust gates зелёные; production не разрешён.**

- LIVE **OFF** · BUILD_FREEZE **BLOCKED** · production **HOLD**
- Python root **54/54 / 1086**, active **20/21 / 411 / SKIP=1**
- Rust **72 PASS / 0 FAIL / 1 ignored PostgreSQL acceptance**, fmt/Clippy PASS
- Python OSV **44/0**, RustSec **169 dependencies / 0 findings**
- Tier-2 **42 PASS / 0 FAIL / 5 SKIP**

## Подтверждено

- root и active runners требуют положительное terminal evidence; exit-zero/zero-check больше не PASS;
- MCP bridge без актуального authority API — fail-closed tombstone;
- critical Python boundaries остаются proposal-first и используют fixed verifier/policy;
- RiskService overflow/narrowing/future-tick/invalid-equity paths закрыты checked integer math;
- CAS, JSONL replay и parser bounded, проверяют hash/chain/sequence/type и блокируют stale writers;
- Rust intake принимает только strict Ed25519/JCS mandate, сверяет exact build-pinned registry bytes,
  связывает actor/project/root/content/source/nonce/TTL/audience и consume-ит nonce до side effect;
- `kf-store-pg` выдаёт только атомарный blob+occurrence+version API, ставит transaction-local role и
  project scope, а runtime лишён прямых INSERT в identity tables;
- signed-root child/hash-prefix symlink escapes, one-sided missing replay/meta state, directory fsync,
  hidden `SESSION_USER`, unsafe PG memberships/ownership и stale runtime ACLs теперь fail-closed;
- exact Rust 1.97.1 workspace/lock собирается и lint/test проходит в digest-pinned Linux container;
- лишние SQLx drivers и `rsa` advisory удалены из lock прямыми PostgreSQL dependencies;
- destructive DB guard code отклоняет remote/generic/не-disposable target; реальный DB test не запускался;
- Python locks, compose image digests, pinned CI actions и Rust audit pins статически проверяются;
- historical READY/PASSED docs маркированы, а старые live/key-loading команды удалены.

## Почему HOLD

1. Tier-2 всё ещё имеет 5 SKIP без целевого Linux/runsc и external assurance.
2. Нет process-isolated KMS/HSM/secrets custody и shared multi-replica replay store.
3. Локальный signed mandate зависит от доверия release binary, registry location, host clock/filesystem;
   external custody/rotation, shared replay и immutable build provenance не приняты.
4. Atomic PostgreSQL/RLS boundary не прошёл dedicated disposable-DB migration, pool-reuse,
   concurrency, rollback/crash и cross-project acceptance; authority→project scope и signed
   schema/policy/function attestation не доказаны end-to-end.
5. Global dedup различает existing/new hash и metadata conflict; без обязательного verified
   proof-of-content либо tenant/keyed dedup это cross-project membership oracle.
6. Risk `reconciled`/`heartbeat_ok` ещё не имеют trusted signed provenance.
7. Нет реальных Stripe/venue/PostgreSQL acceptance и recovery evidence.
8. NATS/MinIO — localhost dev config без production auth/TLS/least privilege.
9. Нет immutable internal mirror, signed SBOM/artifacts/images, external CI attestation и Git provenance.

## Воспроизведение

```powershell
python tests/run_all.py
python tests/run_active_entrypoints.py
python libs/maworld_core/check_single_source.py
python services/sandbox-broker/tier2_acceptance.py
powershell -File tools/verify_rust.ps1
```

Полный evidence и условия допуска: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
