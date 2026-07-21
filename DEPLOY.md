# MAWorld — production deployment gate

Дата: **2026-07-22**

## Решение

**Production deployment заблокирован. LIVE=OFF, BUILD_FREEZE=BLOCKED.**

Этот файл не является инструкцией по включению реальных ключей, платежей, торговли или внешних
provider-вызовов. Credential, env flag и owner statement сами по себе не являются authority.

## Текущий локальный baseline

| Проверка | Результат | Статус |
|---|---:|---|
| Root adversarial | 54/54, 1086 | local PASS |
| Active entrypoints | 20/21, 411, SKIP=1 | external PostgreSQL RLS acceptance явно SKIP |
| Runner / release contracts | 22/22 · 14/14 | PASS |
| Single-source | 10/10 | PASS |
| Tier-2 Windows | 42/0/5 | production gate не пройден |
| Python supply | 71 hashed entries; OSV 44/0 | local PASS only |
| Rust workspace authority v3 | 109 PASS / 0 FAIL / 1 ignored; fmt/Clippy PASS | digest-pinned local evidence; scoped intake disabled on Windows |
| Guarded PostgreSQL 16 authority v3 | 1/1 PASS, 37.00s | disposable clean-volume evidence; production lifecycle не принят |
| RustSec / current Cargo.lock | 169 dependencies / 0 vulnerabilities | 1166 advisories loaded; pinned audit |
| Cargo.lock SHA-256 | `714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171` | current tree |
| Compose/images | config PASS; 3/3 digests | dev config only |

## Обязательные gates

### 1. Linux sandbox и assurance

- pinned gVisor/runsc и digest-bound read-only rootfs;
- signed attestation связывает backend, rootfs, policy, host, expiry и nonce;
- controlled TCP/UDP/IPv4/IPv6/DNS egress и host-write/namespace evidence;
- Tier-2 без FAIL и без SKIP.

### 2. Identity, secrets и idempotency

- ключи вне repository/application process;
- внешний KMS/HSM либо изолированный broker process;
- fixed trust roots, rotation/revocation/audit;
- shared transactional replay/idempotency store для replicas;
- защищённые service identities и durable paths.

### 3. Rust / Knowledge Foundry

В current tree реализованы exact toolchain/lock, bounded CAS/parser/replay и signed authority v3.
Signed `authority_domain_id` связывает mandate с DB domain; только цепочка
`ConsumedIngestAuthority → durable CAS → borrowed StoredIngestAuthority registrar proof` допускает
registration, причём CAS rehash выполняется перед SQL. Grant хранит runtime role OID, runtime caller
передаёт только `grant_id`, direct blob/created outcome скрыт, а ACL и lock/statement timeouts
ограничены. Current locked gate прошёл **109/0/1 ignored**, fmt/Clippy и RustSec зелёные; отдельный
guarded PostgreSQL run прошёл **1/1 за 37.00s**. Это локальный PASS, не production acceptance.

Для production всё ещё обязательны:

- attested release build с закреплённым registry digest и проверяемой VCS/build provenance;
- external key и registrar credential custody/rotation/revocation, trusted clock/host boundary и
  external monotonic replay anchor;
- повтор current Rust/RustSec и guarded PostgreSQL evidence в clean external CI на immutable
  release artifact;
- PostgreSQL TLS/`verify-full`/channel-binding и credential confidentiality enforcement;
- one-shot `004` existing-volume/partial-failure/backup/forced-crash/restore acceptance;
- clone quarantine, outstanding-grant revocation и coordinated rotation domain + credentials;
- signed schema/policy/function attestation и проверка deployment drift;
- tenant/keyed dedup либо adversarial timing/lock/error non-interference evidence;
- descriptor/handle или immutable object-store CAS boundary против hostile pathname replacement;
- production runtime/registrar role grants и deployment verification;
- trusted signed provenance для RiskService observations и независимый execution gate.

### 4. Supply chain

- immutable internal wheel/crate/container mirror;
- signed SBOM, images, artifacts и provenance;
- повторный scan именно release artifact;
- external CI attestation и нормальный Git repository с signed release refs;
- полный license/policy gate и независимый review.

### 5. External integrations и database

- Stripe settlement/fulfillment lineage в test environment;
- venue lifecycle, idempotency, kill switch и reconciliation;
- versioned migration existing PostgreSQL volume beyond one-shot `004` + backup/restore/clone recovery;
- NATS mTLS/auth, MinIO least privilege и network policy.

## Порядок допуска

1. Закрыть все P0/P1 в current security report.
2. Получить external runtime evidence и signed supply provenance.
3. Повторить полный аудит на immutable release artifact.
4. Независимо проверить critical boundaries и recovery.
5. Только затем владелец может отдельно пересмотреть LIVE/BUILD_FREEZE.

Текущий отчёт: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
