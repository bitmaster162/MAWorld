# MAWorld — полный security hardening audit

> **DATED SNAPSHOT / SUPERSEDED FOR CURRENT STATUS.** Этот отчёт сохраняет evidence на
> 2026-07-16. Текущий continuation и изменившиеся counts: [45_SECURITY_CONTINUATION_2026-07-18.md](45_SECURITY_CONTINUATION_2026-07-18.md).
> Вердикт не повышен: **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD**.

Дата среза: **2026-07-16**

## Вердикт

**Проверенный локальный Python-контур зелёный. Production остаётся на HOLD.**

- LIVE: **OFF**
- BUILD_FREEZE: **BLOCKED**
- root adversarial suites: **52/52, 1046 assertions**
- active app/service entrypoints: **20/21 green, 411 checks, 1 explicit PostgreSQL SKIP**
- canonical single-source: **10/10**
- Tier-2 на Windows: **42 PASS, 0 FAIL, 5 SKIP**

Локальный PASS не разрешает реальные платежи, торговлю, внешнюю запись, загрузку production-ключей или deployment. Один active PostgreSQL SKIP и пять Tier-2 SKIP — это отсутствующее внешнее доказательство, а не пройденные DB/isolation gates.

## Проверенное evidence

| Контур | Результат | Что это доказывает |
|---|---:|---|
| Root adversarial runner | 52/52, 1046 | локальные Python-инварианты и regression-тесты |
| Active app/service runner | 20/21 green, 411, SKIP=1 | найденные entrypoints; выделенная PostgreSQL acceptance отсутствует |
| Single-source | 10/10 | критические Python-примитивы импортируются из `libs/maworld_core` |
| Tier-2 acceptance | 42/0/5 | fail-closed конфигурация; Linux runtime и внешняя assurance не приняты |
| Clean-copy root | 52/52, 1046 | результат воспроизводится без project bytecode cache |
| Clean-copy active | 19/21 green, 406, 2 explicit SKIP | отсутствуют выделенная PostgreSQL DB и sibling-проекты |
| Python/JSON/TOML/YAML parse | 287 / 5 / 6 / 23, failures=0 | синтаксис и форматы читаются |
| Docker Compose config | PASS | compose разворачивается в конфигурацию с обязательными dummy env |
| Supply-chain pins | 3 profiles / 71 hashed entries; images 3/3 digests | wheel-only exact locks и immutable compose refs присутствуют |
| OSV all-marker batch | 44 package/version pairs, findings=0 | проверены также lock-ветки других Python/OS markers |
| `pip check` | PASS | установленное Python-окружение не имеет broken requirements |
| High-confidence secret scan | 0 файлов | типовые реальные credential/private-key patterns не найдены |
| Reparse points | 0 | локальное дерево не содержит найденных symlink/reparse aliases |

`pip-audit 2.10.1` с OSV завершился без известных уязвимостей для применимых веток всех трёх lock-профилей. Дополнительно `tools/audit_python_locks_osv.py` без вычисления environment markers проверил все 44 уникальные package/version пары, включая альтернативные `numpy` и non-Windows `uvloop`; findings=0 на момент среза. Это не означает отсутствие неизвестных или ещё не опубликованных уязвимостей.

Lock resolution выявил несовместимые прежние direct pins: `nautilus_trader==1.202.0` требует `msgspec<0.19.0` и exact `fsspec==2023.6.0`; pins приведены к `msgspec==0.18.6` / `fsspec==2023.6.0`. Оба проверены OSV без findings, но старый Nautilus constraint остаётся maintenance risk и требует отдельного upgrade/compatibility решения.

Проверенные immutable compose refs: `pgvector/pgvector:pg16@sha256:1d533553fefe4f12e5d80c7b80622ba0c382abb5758856f52983d8789179f0fb`, `minio/minio:RELEASE.2024-10-13T13-34-11Z@sha256:9535594ad4122b7a78c6632788a989b96d9199b483d3bd71a5ceae73a922cdfa`, `nats:2.10.22-alpine@sha256:73b0ba5fec5518c5f698597c58d2a3350a2b5ccae43e84c308f8d2da1242deca`. Digest pin не заменяет signature/SBOM verification.

`MAWorld_review_package.zip` отдельно проверен: 220 entries, path traversal не найден, high-confidence credential patterns не найдены, SHA-256 `C82891ED46774A52436D3F42AF8FDC42BEF29C7101B34344518426977B87C3E1`. Архив содержит старый pre-hardening snapshot и **не должен распространяться или деплоиться как актуальная сборка**.

## Объём и ограничения метода

Проверены active Python boundaries, app/service test entrypoints, legacy shims/tombstones, effect/payment/trading/canon paths, secrets dispatch, PFI intake, evidence I/O, database bootstrap, CI configuration, dependency metadata, Tier-2 runner и исторические claims, способные вводить в заблуждение.

Использованы adversarial tests, ручной trust-boundary review, отдельный повторный static review, AST/format parsing, secret-pattern scan, dependency audit, compose validation и прогон из чистой временной копии.

Не выполнялись реальные Stripe settlement, venue order execution, production PostgreSQL migration/recovery, Linux gVisor runsc, внешний KMS/HSM, настоящий PFI corpus, независимый timestamp service и production CI attestation. На машине отсутствуют `cargo` и `rustc`.

Каталог не содержит `.git`. Поэтому commit provenance, diff attribution, signed commits/tags и проверяемая история изменений недоступны.

## Закрытые классы проблем

- caller booleans, callbacks, keys и transport objects больше не считаются authority на проверенных critical boundaries;
- trading conversion использует строгий signed-i64 ABI, валидный `InstrumentSpec` и floor-to-step без увеличения quantity/price;
- `safe_submit` остаётся proposal-only и не вызывает venue, registry или reconcile;
- AP2 проверяет merchant nonce, exact intent/cart lineage, `payment_identifier`, signed `allowed_action`, bounded canonical cart и не выполняет charge;
- PFI HMAC покрывает полный memory envelope, включая confidence, sources, domain и authoritative;
- oracle replay хранится атомарно и переживает verifier/store restart;
- secrets capability consumption атомарно, переживает broker restart и блокирует повтор на второй connection при общем durable store;
- owner webhook nonce хранится durable; effect registry race закрыт compare-and-set переходами;
- secrets/OpenRouter capability привязан к operation, method и logical endpoint; произвольный URL/header/body dispatch невозможен;
- evidence file reads используют no-follow/fd checks; Git verification запрещает gitfile, alternates, includes, grafts и подмену executable;
- Tier-2 не имеет PATH lookup/fallback, backend validation и exec используют один pinned FD, rootfs требует descriptor pin и read-only host mount;
- Tier-2 больше не выдаёт одиночный TCP probe или запись в `/etc` за доказательство полной изоляции;
- database bootstrap статически включает RLS/FORCE RLS и ограничивает runtime role; compose ports привязаны к localhost; Rust runtime совместимость с этими правами **не принята**;
- CI actions закреплены immutable commit SHA, permissions минимальны, credentials checkout не сохраняются;
- Python locks имеют SHA-256 hashes, CI использует `--require-hashes`/wheel-only install и all-marker OSV gate; 3 compose images закреплены digest;
- destructive RLS acceptance требует exact confirmation, loopback host и DB prefix `maworld_rls_test_`; без них entrypoint явно SKIP;
- concurrent fresh-open SQLite/WAL race в Canon SoD закрыта bounded `SQLITE_BUSY` retry; test barrier/join больше не может зависнуть;
- известные high-risk runbook/ADR/spike claims помечены historical/superseded; raw source/reference directories явно объявлены untrusted research input.

Финальный независимый static review после исправлений не нашёл новых high-confidence P0/P1 в active Python-коде. Это утверждение относится только к проверенному локальному срезу и не заменяет runtime acceptance.

## Остаточные production-блокеры

| Приоритет | Блокер | Условие закрытия |
|---|---|---|
| P0 | Нет Linux/runsc runtime acceptance; 2 functional и 3 external-assurance проверки SKIP | реальный pinned runsc, digest-pinned rootfs, signed host/policy attestation, controlled multi-vector egress и host-write tests |
| P0 | Secrets broker и ключи остаются in-process/local | отдельный broker process, KMS/HSM/custody, rotation/revocation и общий transactional replay store для всех replicas |
| P0 | Rust Knowledge Foundry имеет прямые persistence/network paths без canonical signed authority; `kf-store-pg` не ставит scoped project context, raw pool обходит wrapper, runtime role не может выполнить current raw_blob ingest, JSONL replay применяет projection до chain verification | tenant-safe atomic DB API, SET LOCAL в одной транзакции, без raw pool escape, fail-before-replay, payload binding, nonce/TTL/durable consume и adversarial runtime acceptance |
| P0 | Rust toolchain и `Cargo.lock` отсутствуют | установить pinned toolchain, создать locks, build/test все 4 crates и выполнить dependency audit |
| P1 | Нет реальных Stripe, venue и PostgreSQL acceptance-прогонов | изолированные sandbox/test runs с signed evidence, reconciliation/recovery и idempotency |
| P1 | Existing PostgreSQL volume не применит новые init migrations автоматически | явная versioned migration, RLS/session acceptance и recovery test на копии production-like volume |
| P1 | Local hash-lock/digest pinning есть, но release artifacts/images не имеют подписанного SBOM/signatures и immutable internal mirror | internal wheelhouse/registry, signed SBOM/image/artifact provenance и повторный scan release artifact |
| P1 | NATS без auth/TLS, MinIO использует root credentials; compose годится только локально | mTLS/auth, least-privilege identities, secret manager и network policy |
| P1 | SQLite replay/canon/effect stores зависят от защиты каталогов ОС и не являются distributed transaction service | process identity + protected paths либо внешний transactional store |
| P1 | Нет подписанных CI/continuity attestations, независимого timestamp anchor и Git provenance | fixed issuers, expiry/replay, signed artifacts, RFC 3161/эквивалент и нормальный VCS history |
| P1 | `nautilus_trader==1.202.0` удерживает старые exact `fsspec`/`msgspec` constraints; Rust risk-service arithmetic/provenance не приняты | compatibility-tested Nautilus upgrade либо формально изолированный support plan; overflow/input-bound tests и trusted observation boundary |
| P1 | Checked-in review ZIP содержит устаревший код | пересобрать из принятого commit либо удалить/карантинировать по решению владельца |
| P2 | Z3 проверяет restricted Boolean IR, а не всю policy semantics | verified compiler/mapping и semantic-equivalence suite |
| P2 | Реальный PFI corpus отсутствует | immutable signed corpus и reproducible ingest/quarantine report |
| P2 | Art.50 маркировка основана на metadata | C2PA/SynthID-class устойчивое доказательство |

Дополнительное trust assumption: capability reference имеет смысл только при проверенном underlying grant. Сам reference не является authority. Локальные durable SQLite stores требуют защищённого абсолютного пути; для multi-host production нужен общий внешний store.

## Production decision gate

Статус можно пересматривать только когда одновременно выполнены все условия:

1. все локальные и active entrypoint checks зелёные;
2. Tier-2 завершён без FAIL и без SKIP на целевом Linux host;
3. external custody, Rust authority и supply-chain P0/P1 закрыты воспроизводимым evidence;
4. реальные Stripe/venue/PostgreSQL acceptances выполнены в изолированной среде;
5. CI/continuity artifacts и timestamps подписаны доверенными issuers;
6. проект имеет проверяемую VCS provenance;
7. независимый reviewer повторил critical tests;
8. владелец отдельно и явно изменил LIVE и BUILD_FREEZE.

До этого: **HOLD / LIVE OFF / BUILD_FREEZE BLOCKED**.

## Команды baseline

```powershell
powershell -File .\VERIFY.ps1
```

Либо по отдельности:

```text
python tests/run_all.py
python tests/run_active_entrypoints.py
python libs/maworld_core/check_single_source.py
python services/sandbox-broker/tier2_acceptance.py
```
