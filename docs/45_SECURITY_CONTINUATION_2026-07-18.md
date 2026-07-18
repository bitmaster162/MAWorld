# MAWorld — security continuation audit

Дата среза: **2026-07-18**

## Вердикт

**Локальные Python и Rust контуры зелёные в проверенном объёме. Production остаётся HOLD.**

- LIVE: **OFF**
- BUILD_FREEZE: **BLOCKED**
- production: **HOLD**

Локальный PASS не разрешает реальные платежи, торговлю, внешние provider-вызовы, загрузку
production-секретов или deployment.

## Текущее evidence

| Контур | Результат | Ограничение |
|---|---:|---|
| Root adversarial runner | **54/54 suites, 1086 assertions** | локальные Python-инварианты |
| Active entrypoints | **20/21 green, 411 checks, 1 SKIP** | dedicated PostgreSQL/RLS DB отсутствует |
| Runner integrity | **22/22** | zero/malformed/late/forged evidence отклоняется |
| Release status | **14/14** | historical/live docs не повышают статус |
| Single source | **10/10** | critical Python primitives из `libs/maworld_core` |
| Tier-2 Windows | **42 PASS / 0 FAIL / 5 SKIP** | Linux/runsc и external assurance не приняты; Rust scoped intake на Windows отключён |
| Formats | **291 Python / 5 JSON / 8 TOML / 24 YAML, 0 failures** | syntax/structure only |
| Python supply chain | **3 profiles / 71 hashed wheel-only entries** | release signing ещё отсутствует |
| Supply-chain contract | **15/15** | static/reproducibility contract only |
| Python OSV | **44 package/version pairs / 0 findings** | срез на дату аудита |
| Compose images | **3/3 exact SHA-256 digests** | signatures/SBOM ещё отсутствуют |
| Rust workspace | **72 PASS / 0 FAIL / 1 explicit ignored DB acceptance** | DB acceptance не выполнена |
| Rust fmt / Clippy | **PASS / PASS (`-D warnings`)** | digest-pinned Linux container |
| RustSec | **169 dependencies / 0 findings** | pinned cargo-audit + advisory DB commit |
| Prior clean-copy snapshot | **SUPERSEDED** | предшествует authority/PG `003`; не evidence текущего дерева |
| `pip check`, Compose config | **PASS / PASS** | локальная среда |
| Secret / reparse scans | **0 files / 0 points** | high-confidence patterns/local tree |

Rust `Cargo.lock` SHA-256:
`F3A0CDB915548DD554BD612263B688B5E284569B72A9E79B13F8A9ECE6ED7980`.

Rust gate использует exact `rust:1.97.1-bookworm` linux/amd64 image digest
`sha256:389c1ae98c20fbcadca68a685482749267cec3c90893ae4671c5a37cc894c416`.
RustSec gate использует cargo-audit `0.22.2` с проверкой asset SHA-256 и advisory DB commit
`b5fc89b8be99e96f79194d8a6f11e9b4143b99f0`.

## Что закрыто в continuation

### Evidence runners

- Новый MCP bridge, который давал `PASS=0 FAIL=0`, заменён fail-closed tombstone и 8 тестами.
- Root runner требует ровно один положительный terminal TALLY, запрещает zero/FAIL/duplicate/late
  evidence и ставит timeout каждому suite.
- Active runner принимает только terminal TALLY, exact `ALL PASS (N/N)` / compatible seam summary
  или единственный explicit SKIP. `exit 0` с нулём проверок теперь FAIL.

### Rust reproducibility и supply chain

- Добавлены root workspace, exact toolchain `1.97.1`, `Cargo.lock`, local Docker gate и отдельный CI job.
- `sqlx` umbrella dependency удалена. Прямые `sqlx-core/sqlx-postgres` сократили lock и удалили
  `sqlx-mysql`, `sqlx-sqlite` и `rsa 0.9.10` / RUSTSEC-2023-0071 из lock, а не скрыли advisory ignore.
- CI и локальный gate выполняют locked tests, fmt, Clippy и checksum/commit-pinned RustSec audit.

### RiskService

- Устранены `i64` overflow и `u32` narrowing wrap в drawdown.
- Invalid equity/config, tick из будущего, zero-risk и непредставимый sizing fail-closed.
- Непроверенный `reduce_only` больше не обходит heartbeat loss; RiskService остаётся proposal-only.

### Knowledge Foundry local authority/storage/PostgreSQL

- Unsigned/default/demo ingest удалён. Обычная verification build намеренно собирается без registry
  pin и не способна выполнять ingest.
- Production-shaped path читает exact build-pinned trust-registry bytes до parse, проверяет strict
  Ed25519 signature над domain-separated JCS claims и key policy. Claims связывают issuer/key, actor,
  project, canonical existing store root, content hash/size, source identity, nonce, TTL,
  audience/action.
- `(issuer,key_id,nonce)` consume-ится до CAS/meta effect в bounded canonical hash-chain ledger под
  exclusive lock; restart/concurrency/replay/tamper/noncanonical/partial cases fail-closed.
- CAS после consume повторно открывает и хэширует source; bytes, отличные от signed digest/size, не
  публикуются. Crash после consume может сжечь mandate и требует новый — это availability limit.
- Direct `cas`/`meta` children и оба CAS hash-prefix компонента проверяются до создания; child/
  dangling-ledger symlink, односторонняя потеря initialized replay/meta state и ошибка directory
  durability sync теперь fail-closed. Durable scoped intake на Windows отключён и требует Linux.
- CAS проверяет hash format, размер, regular/non-symlink input, existing destination content,
  post-publish bytes и bounded recovery; одинаковый размер не считается доказательством hash.
- JSONL replay валидирует полный chain/sequence/kind/payload/references до публикации projections.
- Sidecar locks и disk-tail comparison блокируют concurrent stale writer/fork.
- Ledger/event/input размеры bounded; partial terminal line, oversized line, binary magic, NUL,
  invalid UTF-8 и symlink/non-regular input fail-closed.
- Idempotency key согласован с SQL schema; retry возвращает реальный version ID и parent lineage.
- PostgreSQL raw pool удалён; DB test теперь explicit ignored и защищён loopback +
  `maworld_rls_test_*` + exact confirmation.
- `kf-store-pg` выставляет `SET LOCAL ROLE kf_runtime` и bound transaction-local project context в
  каждом method; pool/connection/transaction наружу не выдаются.
- Migration `003_atomic_intake.sql` реализует narrow RLS-subject `SECURITY DEFINER` operation:
  global blob dedup + stable occurrence + version/parent lineage в одной transaction. Runtime direct
  INSERT в три identity table отозван; Compose монтирует ordered chain `001 → 002 → 003`.
- Migration/admission code сбрасывает runtime table/sequence ACL, запрещает database/schema CREATE
  и ownership и восстанавливает ENABLE+FORCE RLS. Каждая новая physical connection должна проверять
  `SESSION_USER`, exact PG16 membership options, ownership, PUBLIC/direct/column/sequence ACL,
  relation allowlist/grant option и scoped-table RLS flags. Это подтверждено static/unit, но не real DB.
- Destructive Python и ignored Rust guard code отвергает DSN overrides и на каждой admin connection до
  effect должен сверять actual database, loopback primary, unchanged superuser и отсутствие любых других
  DB, включая `ALLOW_CONNECTIONS false` и custom templates; разрешены только built-in templates,
  `postgres` и current test DB. Отдельное confirmation требуется для reset cluster roles; сам
  destructive PostgreSQL run не выполнялся.

### Документация

- Опасные historical `PASSED/PROVEN/READY` отчёты получили uniform
  `HISTORICAL / SUPERSEDED / NON-OPERATIVE` banner.
- Операционные `--live` и key-loading команды удалены из старых Arena/Hermes runbooks.
- Наличие credential, env flag или owner statement явно не считается authority.

## Что не выполнялось

- Не запускалась destructive PostgreSQL acceptance: на машине нет отдельного disposable loopback
  cluster/DB `maworld_rls_test_*`. Остановленные/чужие Docker PostgreSQL containers и volumes не
  использовались.
- Не выполнялись реальные Stripe settlement, venue orders, external provider spending или LIVE calls.
- Не загружались production credentials.
- Не выполнялась Linux/runsc acceptance и независимая external assurance.
- Предыдущая clean-copy проверка предшествует последним authority/PG изменениям и помечена
  superseded; за current evidence она не выдаётся.
- Migration `003`, grants, RLS policies и concurrent lineage не исполнялись на реальном PostgreSQL:
  compiler/static SQL tests не заменяют dedicated disposable-DB acceptance.
- Ignored Rust DB test использует superuser pool с `SET LOCAL ROLE`; он ещё не доказывает реальный
  NOINHERIT service login, PG16 membership grant и `connect_runtime` path.

## Остаточные production-блокеры

| Приоритет | Блокер | Условие закрытия |
|---|---|---|
| P0 | Local authority не имеет production trust bootstrap | attested release binary/build pin, external custody/rotation/revocation, trusted clock/host и shared replay/recovery |
| P0 | Authority→PostgreSQL scope не доказан end-to-end | только verified signed claim формирует `project_id`; runtime credential/GUC сам по себе не authority |
| P0 | Atomic PG/RLS boundary не прошёл real-DB acceptance | disposable DB migration, grants/FORCE RLS, pool reuse, cross-project probing, concurrency, rollback/crash, backup/restore |
| P0 | Tier-2 имеет 5 SKIP | целевой pinned Linux/runsc, signed host/rootfs/policy evidence, controlled egress/write tests |
| P0 | External secrets custody отсутствует | process-isolated broker/KMS/HSM, rotation/revocation, shared transactional replay store |
| P1 | Risk observations не имеют trusted provenance | fixed verifier/signed observation ledger + independent execution/reduction proof |
| P1 | Нет реальных external effect acceptances | isolated Stripe/venue/PostgreSQL tests с reconciliation/recovery и signed evidence |
| P1 | Release supply provenance отсутствует | immutable mirror, signed SBOM/images/artifacts, release scan и external CI attestation |
| P1 | NATS/MinIO остаются dev-only | mTLS/auth, least privilege, secret manager и network policy |
| P1 | Global blob dedup различает existing/new hash | обязательный verified proof-of-content либо tenant/keyed dedup и неразличимые outcomes |
| P1 | Нет signed attestation exact PostgreSQL policy/function/schema state | versioned schema digest, trusted migration plane, exact policy/function owner+ACL proof и drift monitoring |
| P1 | Local ledger/path boundary не защищает от hostile root writer | external monotonic replay tail + descriptor-based `openat`/handle boundary либо isolated object store |
| P1 | Нет проверяемой VCS provenance | нормальный Git history, signed refs/timestamps; текущая папка не содержит `.git` |

## Воспроизведение

```powershell
python tests/run_all.py
python tests/run_active_entrypoints.py
python libs/maworld_core/check_single_source.py
python tools/check_supply_chain.py
python tools/audit_python_locks_osv.py
python services/sandbox-broker/tier2_acceptance.py
powershell -File tools/verify_rust.ps1
```

Итоговое правило неизменно: статус можно пересматривать только после одновременного закрытия всех
P0/P1, повторного аудита release artifact и независимого review. До этого:
**HOLD / LIVE OFF / BUILD_FREEZE BLOCKED**.
