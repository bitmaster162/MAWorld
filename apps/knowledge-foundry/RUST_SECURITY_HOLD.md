# Knowledge Foundry / Rust security HOLD

Дата среза: **2026-07-18**

Статус: **HOLD / не production-ready · LIVE OFF · BUILD_FREEZE BLOCKED**.

Этот файл отделяет локально подтверждённые исправления от ещё отсутствующей runtime- и
production-acceptance. Ни один Rust `PASS` не разрешает persistence, сеть, торговлю или deployment.

## Локально закрыто

- Добавлены workspace, exact `rust-toolchain.toml` **1.97.1** и locked `Cargo.lock`; проверяемой
  VCS provenance в текущей папке нет.
- Digest-pinned Linux gate выполняет `cargo fmt --check`, `cargo test --workspace --locked` и
  `cargo clippy ... -D warnings`: **72 PASS, 0 FAIL, 1 explicit ignored PostgreSQL acceptance**.
- Pinned RustSec/cargo-audit проверил **169 dependencies, 0 findings**. Неиспользуемые
  `sqlx-mysql`, `sqlx-sqlite` и уязвимый `rsa` удалены переходом на прямые exact
  `sqlx-core=0.8.6` / `sqlx-postgres=0.8.6`.
- RiskService считает drawdown в `i128`, отклоняет invalid config/equity, future tick и
  непроверенный heartbeat-reduce claim; sizing использует checked `Result` без narrowing wrap.
- JSONL replay сначала строго проверяет `seq`, `prev_hash`, `hash`, kind, payload и ссылки,
  строит временную projection и только затем публикует состояние.
- Sidecar file lock сериализует writers; stale writer отклоняется. Ledger/event размеры bounded,
  partial line и fork-chain отклоняются.
- CAS проверяет SHA-256 identifier, regular/non-symlink path, размер, уже существующий blob,
  результат publish и recovery; одинаковая длина больше не заменяет проверку hash.
- Parser ограничивает вход 8 MiB, не использует lossy UTF-8, отправляет binary magic/NUL/invalid
  UTF-8 в `SandboxRequired`, строго проверяет ledger и не вызывает rich parser in-process.
- Offline и PostgreSQL idempotency используют один ключ
  `(project_id, source_system_id, source_native_id)`; retry возвращает реальный version ID.
- `kf ingest` не имеет unsigned/default/demo пути. Build-time pin фиксирует exact bytes внешнего
  trust registry до JSON parse; strict Ed25519/JCS mandate связывает issuer/key, actor, project,
  canonical root, content hash/size, source identity, audience/action, TTL и nonce с key policy.
- Nonce `(issuer,key_id,nonce)` consume-ится под exclusive lock в bounded canonical hash-chain JSONL
  до CAS/meta effect; CAS после consume повторно хэширует bytes и не публикует несовпавший content.
- Signed store root теперь открывает только direct non-symlink `cas`/`meta` children; CAS проверяет
  оба hash-prefix компонента до создания, а их создание и blob publish используют strict directory
  fsync. Dangling ledger symlink, односторонне исчезнувший initialized state и ошибка durability
  fail-closed. Durable scoped intake намеренно отключён на Windows и требует pinned Linux runtime.
- Raw `PostgresMetaStore::pool()` удалён. Каждая новая physical runtime connection отклоняет
  privilege drift: exact PG16 membership options, чужие memberships, DB/schema/relation ownership,
  CREATE, PUBLIC/direct/column/sequence ACL, relation allowlist/grant option и ENABLE+FORCE RLS.
  Каждый закрытый MetaStore method начинает transaction, делает `SET LOCAL ROLE kf_runtime` и bound
  transaction-local `set_config` project scope.
- Migration `003_atomic_intake.sql` даёт runtime только narrow `SECURITY DEFINER` atomic
  blob+occurrence+version operation, отзывает direct identity INSERT и фиксирует same-occurrence
  linear lineage. Compose монтирует ordered chain `001 → 002 → 003`.
- Migration code требует dedicated superuser и атомарно должен сбрасывать runtime table/sequence ACL,
  database/schema CREATE, ownership и восстанавливать ENABLE+FORCE RLS. Destructive Python
  и ignored Rust guard code запрещает DSN overrides и на каждой admin connection должен сверять actual DB,
  loopback primary, unchanged superuser и отсутствие любых других DB кроме built-in templates/
  `postgres`; отдельное confirmation требуется для reset глобальных roles. Всё это подтверждено
  static/unit; PostgreSQL acceptance не запускалась.

## Остаётся HOLD

### P0 — production trust для локальной authority

- Build-time registry pin защищает только при доверенном release binary. Текущая папка без `.git`,
  signed ref/build attestation и immutable artifact provenance не доказывает, какой pin попал в binary.
- Registry location, host filesystem и system clock остаются локально доверенными. Нет принятой
  external KMS/HSM custody, rotation/revocation, trusted clock и process/descriptor isolation.
- Replay ledger локальный и single-host: filesystem writer может пересчитать всю hash-chain; нет
  shared transactional consume для replicas и внешнего tail anchor. Initialized deletion теперь
  fail-closed только при односторонней потере state; согласованный rollback/truncation либо совместное
  удаление ledger+markers локальным writer всё ещё неотличимы.
  Bounded 64 MiB ledger без rotation — отдельный availability limit.
- Crash после nonce consume, но до завершения CAS/meta effect, сжигает mandate и требует новый. Это
  fail-closed по безопасности, но production recovery/availability protocol ещё не принят.

### P0 — PostgreSQL / RLS

1. Signed authority ещё не соединена end-to-end с `IngestObservation.project_id`: database GUC —
   scope claim, не authentication. Отдельно полученный runtime credential пока может выбрать project.
2. Нет destructive acceptance на отдельном disposable loopback cluster/DB `maworld_rls_test_*`; SQL compiler/static
   tests не доказывают, что migration, grants, FORCE RLS и function реально исполняются PostgreSQL.
3. Не приняты реальные pool-reuse, rollback/crash, concurrent lineage/global dedup, cross-project
   read/write/probing и existing-volume migration/backup/restore сценарии. Ignored Rust test
   использует superuser + `SET LOCAL ROLE`, а не реальный NOINHERIT login через `connect_runtime`.
4. Production login grants, TLS, credential issuance/rotation, object-store ACL и deployment drift
   не проверены. Чужие Docker DB и существующие volumes намеренно не использовались.
5. Global dedup всё ещё возвращает различимый `blob_created`/metadata-conflict result. Пока verified
   mandate не является обязательным proof-of-content, это cross-project hash-membership oracle.
6. Admission проверяет ACL/ownership/RLS flags, но не является signed attestation exact `pg_policy`,
   function body/owner/ACL и всего schema state. Нужны versioned schema digest, trusted migration
   plane и post-deploy drift monitoring.

### P0/P1 — provenance и durability

- `reconciled` и `heartbeat_ok` в RiskService остаются caller observations без trusted signed source.
  Функция proposal-only и не исполняет order, но production eligibility требует проверенной provenance.
- Локальная hash-chain обнаруживает случайную/частичную порчу, но writer с доступом к файлам может
  пересчитать цепочку. Нужны signed events/external anchor и защищённая service identity.
- Cooperative file lock и pathname checks имеют check/use race против concurrent hostile root writer;
  они не заменяют descriptor-based `openat`/handle sandbox либо object store.
- `SandboxRequired` — только решение router; реальный pinned gVisor execution относится к отдельному
  Tier-2 gate и сейчас имеет SKIP.
- GitHub workflow добавлен, но нет принятой внешней CI attestation, signed release provenance,
  полного license gate и независимого review.

## Условия снятия HOLD

1. Local signed authority выпускается из attested release build и использует external custody,
   rotation/revocation, trusted clock/host isolation и shared transactional replay/recovery.
2. End-to-end authority→project scope доказан, а уже реализованный atomic PostgreSQL ingest проходит
   dedicated migration/RLS/pool-reuse/concurrency/crash/recovery acceptance без raw connection escape.
3. Risk observations приходят из фиксированного доверенного verifier/ledger, а execution boundary
   независимо доказывает position-reducing semantics.
4. Tier-2 проходит на целевом Linux/runsc без FAIL и SKIP.
5. Clean external CI повторяет locked build/test/lint/RustSec/license gates и выпускает подписанные
   SBOM, artifacts и provenance из проверяемого VCS ref.
6. Независимый reviewer повторяет critical tests на release artifact.

До выполнения всех пунктов исторические demo/logs не повышают этот контур выше **HOLD**.
