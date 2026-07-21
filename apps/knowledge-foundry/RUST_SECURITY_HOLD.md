# Knowledge Foundry / Rust security HOLD

Дата среза: **2026-07-22**

Статус: **HOLD / не production-ready · LIVE OFF · BUILD_FREEZE BLOCKED**.

Этот файл отделяет локально подтверждённые fail-closed границы от production acceptance. Полный
`VERIFY.ps1` завершён с exit 0; authority-v3 Rust/SQL evidence приведено ниже. Локальный PASS,
ignored test или credential всё равно не разрешают persistence, сеть, торговлю или deployment.

## Локально закрыто и перепроверено

- Workspace использует exact `rust-toolchain.toml` **1.97.1** и locked `Cargo.lock`. Локальный Git
  baseline существует, но unsigned commit не является external VCS/release provenance.
- Canonical digest-pinned gate: **109 PASS / 0 FAIL / 1 ignored**; `kf-intake` 27 library + 43
  binary = 70, `kf-parser` 17, `kf-store-pg` 9 default tests, trading risk 13. `cargo fmt --check`
  PASS, Clippy `-D warnings` PASS. Pinned RustSec загрузил 1166 advisories и проверил **169 crate
  dependencies: 0 vulnerabilities**. `Cargo.lock` SHA-256:
  `714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171`.
- Parser, CAS и JSONL replay остаются bounded и fail-closed: строгая chain/sequence/payload
  проверка предшествует projection, partial/forked ledger отвергается, writers сериализуются
  sidecar lock, а durable scoped filesystem intake отключён на Windows.
- `kf ingest` не имеет unsigned/default/demo пути. Build-time registry digest проверяется до JSON
  parse. Strict Ed25519/JCS authority v3 подписывает issuer/key, actor, canonical
  `authority_domain_id`, project/grant UUID, database session user, canonical root, content
  hash/size, source identity, audience/action, TTL и nonce; key policy ограничивает те же domains,
  projects, users и roots.
- Local replay key `(issuer,key_id,nonce)` consume-ится до side effects под exclusive lock.
  `ConsumedIngestAuthority` имеет private fields, не clone/serde и не может напрямую попасть в
  registrar.
- Путь к DB устроен как `ConsumedIngestAuthority → durable CAS publish → StoredIngestAuthority`.
  CAS consume-ит capability; registrar принимает `StoredIngestAuthority` по ссылке для exact retry,
  создаёт bounded blocking work item и непосредственно перед SQL заново открывает CAS, потоково
  проверяя signed SHA-256/size.
- PostgreSQL authority domain хранится отдельным singleton UUID без default. Registrar принимает
  только тот signed `authority_domain_id`, который совпадает с provisioned DB domain.
- При регистрации grant PostgreSQL разрешает signed `database_session_user`, сохраняет фактический
  role OID и exact scope. Runtime сверяет одновременно `SESSION_USER` и сохранённый OID; удаление и
  пересоздание одноимённой роли не сохраняет authority.
- Public Rust runtime API принимает только `grant_id`. Configured `authority_domain_id` принадлежит
  admitted store instance; project/source/content и occurrence/version IDs caller не задаёт.
  `kf_ingest_authorized` выводит scope из locked grant и генерирует IDs server-side.
- Runtime outcome содержит только occurrence/version/parent IDs. Global blob ID и внутренние
  `blob_created`/`occurrence_created`/`version_created` flags наружу не возвращаются.
- Raw pool/connection/transaction не выдаются. Runtime и registrar connections проверяют
  NOINHERIT membership, role attributes, role ownership, database/schema CREATE, relation/column/
  sequence/function ACL и точный function allowlist. Каждый transaction делает `SET LOCAL ROLE`
  (`kf_runtime` либо registrar role) и transaction-local 5s lock / 30s statement timeout; SQL
  functions закрепляют такие же timeout и fail-closed `search_path`/RLS настройки.
- Ordered clean bootstrap — `001 → 002 → 003 → 004`. Migration `004_authority_grants.sql`
  deliberately one-shot и отказывается от повторного применения. Текущий поддерживаемый сценарий —
  новый пустой volume; это не in-place upgrade contract.
- Отдельный guarded disposable PostgreSQL 16 authority-v3 acceptance прошёл **1/1 за 37.00s** с
  actual NOINHERIT runtime/registrar logins и domain
  `dddddddd-dddd-4ddd-8ddd-dddddddddddd`. Итоговые counts: grants=7, consumed=3, raw_blob=3,
  occurrences=3, versions=3. Проверены migrations `001–004`, domain/OID substitution,
  retries/concurrency, pool reuse и denial paths; disposable container после evidence удалён.

## Остаётся HOLD

### P0 — trust, replay и CAS

- Build-time registry pin имеет смысл только у attested release binary. Нет external KMS/HSM key
  custody, registrar credential custody, accepted rotation/revocation, trusted clock, signed build
  provenance и защищённой process identity.
- Local replay ledger single-host. Writer с filesystem-доступом может согласованно откатить или
  пересчитать marker+ledger; PostgreSQL uniqueness после registration не заменяет внешний
  monotonic tail anchor до registration.
- Crash между local nonce consume, CAS publish и DB registration может сжечь mandate или оставить
  CAS blob без grant. Это fail-safe для authority, но production reconciliation/recovery protocol
  не принят.
- Bounded `spawn_blocking` допускает не более двух CAS revalidation workers на процесс, но
  зависший filesystem I/O нельзя отменить. Два зависших чтения остановят все новые registrations;
  нужны storage-level deadlines/health isolation и принятый recovery path.
- Проверки non-symlink/canonical path и повторный CAS hash ловят многие подмены, но не атомизируют
  pathname с DB commit. Hostile writer может заменить/удалить путь после revalidation. Нужны
  descriptor-based `openat`/handle boundary, immutable object-store retention/custody либо
  transactional finalize/reconciler.

### P0 — PostgreSQL lifecycle и credentials

1. `004` принят только как one-shot clean empty-volume bootstrap. Existing-volume upgrade,
   partial migration, forced crash, backup/restore и rollback/forward recovery не приняты.
2. Rust admission проверяет DB roles/ACL, но не требует TLS, `verify-full`, channel binding или иной
   transport confidentiality. Production runtime/registrar credentials могут быть раскрыты без
   отдельного deployment enforcement и secret custody.
3. Registrar credential фактически является minting authority: PostgreSQL registration function
   доверяет полям, уже проверенным Rust registrar, и не перепроверяет Ed25519/registry pin. Нужны
   изоляция credential от иных callers, rotation, audit и attested verifier process.
4. PostgreSQL roles cluster-global, а admission/ACL audit относится к current database. Production
   требует dedicated cluster либо explicit revoke `PUBLIC CONNECT/TEMP`, строгий `pg_hba` allowlist
   и отдельные principals для каждой DB; одноимённая функция в соседней DB не принята этим тестом.
5. Snapshot/clone наследует `authority_domain_id`, grants и потенциально credentials. До допуска
   клона обязательны quarantine, очистка/revocation outstanding grants и coordinated rotation DB
   domain + runtime/registrar credentials + issuer policy; HA/DR identity semantics требуют
   отдельного принятого runbook.
6. Consumed grant возвращает тот же recovery outcome даже после последующих expiry/revoke. Это
   предотвращает повторную мутацию после ambiguous result, но делает confidentiality `grant_id` и
   bounded recovery policy частью security contract; отдельный recovery TTL/token ещё не принят.
7. Admission не является signed attestation точного `pg_policy`, function body/owner/ACL и всего
   schema state. Нужны versioned digest, trusted migration plane и drift monitoring.
8. Явные blob/created outcomes скрыты, но отсутствие timing/lock/error side-channel global dedup не
   доказано. Нужны tenant/keyed dedup либо отдельная non-interference acceptance.

### P2 — недостающие adversarial сценарии

- Два разных grants/sources с одинаковыми bytes должны доказать один global blob без scope leak.
- Повторный ingest того же source с новыми bytes должен доказать lineage и exact parent version.
- Immutable metadata conflict должен доказать полный transaction rollback.
- Нужны успешный project-B ingest, настоящий two-database clone/misroute test и CAS delete/corrupt
  именно после registration, но до consume.

### P0/P1 — остальной production контур

- `reconciled` и `heartbeat_ok` в RiskService остаются caller observations без trusted signed
  provenance; RiskService proposal-only и не исполняет order.
- `SandboxRequired` — routing decision, не исполненная изоляция. Tier-2 на целевом Linux/runsc всё
  ещё должен пройти без FAIL/SKIP с external signed assurance.
- Нет signed release/SBOM/artifact provenance, external CI attestation, полного license gate и
  независимого review.
- Stripe/venue external acceptances, production NATS mTLS/auth и MinIO least-privilege deployment
  остаются непринятыми.

## Условия снятия HOLD

1. Текущие локальные Rust/PG gates повторяются clean external CI на immutable release artifact с
   signed provenance; destructive DB acceptance не остаётся только локальным одноразовым evidence.
2. Authority выпускается из attested release build с external key/registrar credential custody,
   rotation/revocation, trusted clock/host isolation и external monotonic replay/recovery.
3. Приняты PostgreSQL TLS/credential policy, clone quarantine/domain rotation, existing-volume
   upgrade, backup/restore, forced crash/recovery и signed schema drift monitoring.
4. CAS использует descriptor/handle или immutable object-store boundary, а global dedup проходит
   timing/error/lock non-interference либо становится tenant/keyed.
5. Risk observations и execution boundary имеют независимую trusted provenance; Tier-2 проходит на
   target Linux/runsc без SKIP.
6. Clean external CI выпускает signed SBOM/artifacts/provenance из проверяемого VCS ref, после чего
   независимый reviewer повторяет critical tests на release artifact.

До выполнения всех пунктов: **HOLD / LIVE OFF / BUILD_FREEZE BLOCKED**.
