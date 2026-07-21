# MAWorld — security continuation audit

Дата среза: **2026-07-22**

## Вердикт

**Локальные Python, Rust и guarded PostgreSQL контуры зелёные в проверенном объёме. Production остаётся HOLD.**

- LIVE: **OFF**
- BUILD_FREEZE: **BLOCKED**
- production: **HOLD**

Локальный PASS не разрешает реальные платежи, торговлю, внешние provider-вызовы, загрузку
production-секретов или deployment.

Полный `VERIFY.ps1` завершён с exit 0. Отдельный guarded disposable PostgreSQL 16 authority-v3
acceptance также прошёл; этот destructive test остаётся ignored в canonical workspace suite.

## Текущее evidence

| Контур | Результат | Ограничение |
|---|---:|---|
| Root adversarial runner | **54/54 suites, 1086 assertions** | локальные Python-инварианты |
| Active entrypoints | **20/21 green, 411 checks, 1 SKIP** | external PostgreSQL RLS acceptance явно SKIP |
| Runner integrity | **22/22** | zero/malformed/late/forged evidence отклоняется |
| Release status | **14/14** | historical/live docs не повышают статус |
| Single source | **10/10** | critical Python primitives из `libs/maworld_core` |
| Tier-2 Windows | **42 PASS / 0 FAIL / 5 SKIP** | Linux/runsc и external assurance не приняты; Rust scoped intake на Windows отключён |
| Python supply chain | **3 profiles / 71 hashed wheel-only entries** | release signing ещё отсутствует |
| Supply-chain contract | **15/15** | static/reproducibility contract only |
| Python OSV | **44 package/version pairs / 0 findings** | срез на дату аудита |
| Compose images | **3/3 exact SHA-256 digests** | signatures/SBOM ещё отсутствуют |
| Rust workspace authority v3 | **109 PASS / 0 FAIL / 1 ignored** | ignored = destructive live PG acceptance |
| PostgreSQL 16 authority/RLS v3 | **1/1 PASS, 37.00s** | explicit guarded disposable run; production lifecycle не принят |
| Rust fmt / Clippy | **PASS / PASS (`-D warnings`)** | digest-pinned Linux container |
| RustSec / current `Cargo.lock` | **169 dependencies / 0 vulnerabilities** | 1166 advisories loaded |
| Prior clean-copy snapshot | **SUPERSEDED** | предшествует authority/PG `003+004`; не evidence текущего дерева |
| `pip check`, Compose config | **prior PASS / current PASS** | Compose current tree подтверждён отдельно |

Rust `Cargo.lock` SHA-256:
`714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171`.

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
- Current workspace breakdown: `kf-intake` 27 library + 43 binary = 70, `kf-parser` 17,
  `kf-store-pg` 9 default, trading risk 13; итого 109 PASS и 1 ignored live-DB test.

### RiskService

- Устранены `i64` overflow и `u32` narrowing wrap в drawdown.
- Invalid equity/config, tick из будущего, zero-risk и непредставимый sizing fail-closed.
- Непроверенный `reduce_only` больше не обходит heartbeat loss; RiskService остаётся proposal-only.

### Knowledge Foundry local authority/storage/PostgreSQL

- Unsigned/default/demo ingest удалён. Обычная verification build намеренно собирается без registry
  pin и не способна выполнять ingest.
- Production-shaped path читает exact build-pinned trust-registry bytes до parse и проверяет strict
  Ed25519 signature над domain-separated JCS claims v3. Claims и key policy связывают issuer/key,
  actor, canonical `authority_domain_id`, project/grant UUID, database session user, canonical
  existing store root, content hash/size, source identity, nonce, TTL, audience/action.
- `(issuer,key_id,nonce)` consume-ится до CAS/meta effect в bounded canonical hash-chain ledger под
  exclusive lock; restart/concurrency/replay/tamper/noncanonical/partial cases fail-closed.
- `ConsumedIngestAuthority` нельзя clone/deserialize. CAS consume-ит его, durable публикует exact
  bytes и только затем возвращает `StoredIngestAuthority`. Registrar принимает stored proof по
  ссылке для exact retry и непосредственно перед SQL повторно потоково хэширует CAS bytes/size в
  bounded blocking pool. Crash после consume может сжечь mandate — это availability limit.
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
- PostgreSQL raw pool удалён; destructive DB test explicit ignored по умолчанию и защищён loopback +
  `maworld_rls_test_*` + exact confirmations.
- Registrar регистрирует exact signed scope только из borrowed `StoredIngestAuthority`. PostgreSQL
  сверяет provisioned singleton domain, разрешает signed session user и сохраняет фактический role
  OID; recreated same-name login не наследует authority. Public Rust runtime caller передаёт только
  `grant_id`; configured domain принадлежит admitted store, а project/source/content и generated
  occurrence/version IDs caller не задаёт. Arbitrary project GUC не формирует authority.
- Migration `003_atomic_intake.sql` реализует narrow RLS-subject `SECURITY DEFINER` operation:
  global blob dedup + stable occurrence + version/parent lineage в одной transaction. Runtime direct
  INSERT в три identity table отозван. Migration `004_authority_grants.sql` добавляет registrar-owned
  grant table, global replay uniqueness и runtime wrapper, который server-side выводит exact scope и
  атомарно consume-ит grant. Наружный outcome содержит occurrence/version/parent IDs, но не global
  blob ID и не внутренние `*_created` flags. Compose монтирует ordered chain
  `001 → 002 → 003 → 004` только для нового пустого volume; `004` one-shot и не является
  existing-volume upgrade procedure.
- Migration/admission code сбрасывает runtime table/sequence ACL, запрещает database/schema CREATE
  и ownership и восстанавливает ENABLE+FORCE RLS. Каждая новая physical connection должна проверять
  `SESSION_USER`, exact PG16 membership options, ownership, PUBLIC/direct/column/sequence ACL,
  relation allowlist/grant option и scoped-table RLS flags. Runtime/registrar transactions и SQL
  functions имеют 5s lock timeout и 30s statement timeout; raw pool/connection наружу не выдаются.
- Destructive Python и ignored Rust guard code отвергает DSN overrides и на каждой admin connection до
  effect должен сверять actual database, loopback primary, unchanged superuser и отсутствие любых других
  DB, включая `ALLOW_CONNECTIONS false` и custom templates; разрешены только built-in templates,
  `postgres` и current test DB. Отдельное confirmation требуется для reset cluster roles.
- Guarded acceptance на чистой disposable PostgreSQL 16 DB с actual NOINHERIT runtime/registrar
  logins прошла **1/1 за 37.00s**. Domain
  `dddddddd-dddd-4ddd-8ddd-dddddddddddd`; final rows: grants=7, consumed=3, raw_blob=3,
  occurrences=3, versions=3. Проверены domain/OID substitution, retry/concurrency, pool reuse и
  denial paths; disposable container после evidence удалён.

### Документация

- Опасные historical `PASSED/PROVEN/READY` отчёты получили uniform
  `HISTORICAL / SUPERSEDED / NON-OPERATIVE` banner.
- Операционные `--live` и key-loading команды удалены из старых Arena/Hermes runbooks.
- Наличие credential, env flag или owner statement явно не считается authority.

## Что не выполнялось

- Не выполнялись реальные Stripe settlement, venue orders, external provider spending или LIVE calls.
- Не загружались production credentials.
- Не выполнялась Linux/runsc acceptance и независимая external assurance.
- Предыдущая clean-copy проверка предшествует последним authority/PG изменениям и помечена
  superseded; за current evidence она не выдаётся.
- Не выполнялись one-shot `004` existing-volume upgrade, partial-migration recovery, backup/restore,
  forced process/DB crash recovery или clone quarantine/domain+credential rotation.
- PostgreSQL TLS/`verify-full`/channel-binding и confidentiality runtime/registrar credentials кодом
  admission не enforced; production transport/custody не приняты.
- Не приняты external KMS/HSM key custody, registrar credential custody, trusted clock, signed build
  provenance, external monotonic ledger anchor или descriptor-based pathname boundary.

## Остаточные production-блокеры

| Приоритет | Блокер | Условие закрытия |
|---|---|---|
| P0 | Local authority не имеет production trust bootstrap | attested release binary/build pin, external key + registrar credential custody/rotation/revocation, trusted clock/host и recovery |
| P0 | Local replay допускает coordinated rollback до DB registration | external monotonic tail/shared transactional anchor; recovery для local consume→DB registration gap |
| P0 | PostgreSQL transport/credential confidentiality не enforced | TLS verify-full/channel binding policy, isolated secret custody and rotation evidence |
| P0 | One-shot `004` не имеет existing-volume lifecycle | upgrade/partial-failure/backup/restore/forced-crash acceptance на production-like copy |
| P0 | Clone наследует domain/grants/credentials | quarantine, revoke outstanding grants, rotate `authority_domain_id` + runtime/registrar credentials + issuer policy |
| P0 | Tier-2 имеет 5 SKIP | целевой pinned Linux/runsc, signed host/rootfs/policy evidence, controlled egress/write tests |
| P1 | Risk observations не имеют trusted provenance | fixed verifier/signed observation ledger + independent execution/reduction proof |
| P1 | Нет реальных external effect acceptances | isolated Stripe/venue tests с reconciliation/recovery и signed evidence |
| P1 | Release supply provenance отсутствует | immutable mirror, signed SBOM/images/artifacts, release scan и external CI attestation |
| P1 | NATS/MinIO остаются dev-only | mTLS/auth, least privilege, secret manager и network policy |
| P1 | Global dedup direct outcomes скрыты, но timing/lock/error channel не исследован | tenant/keyed dedup либо adversarial non-interference acceptance |
| P1 | Нет signed attestation exact PostgreSQL policy/function/schema state | versioned schema digest, trusted migration plane, exact policy/function owner+ACL proof и drift monitoring |
| P1 | Local ledger/path boundary не защищает от hostile root writer | external monotonic replay tail + descriptor-based `openat`/handle boundary либо isolated object store; CAS→DB finalize/reconcile |
| P1 | Нет external VCS/release provenance | signed refs/timestamps, external CI attestation и immutable release artifact; local baseline commit недостаточен |

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
