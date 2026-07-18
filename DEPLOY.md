# MAWorld — production deployment gate

Дата: **2026-07-18**

## Решение

**Production deployment заблокирован. LIVE=OFF, BUILD_FREEZE=BLOCKED.**

Этот файл не является инструкцией по включению реальных ключей, платежей, торговли или внешних
provider-вызовов. Credential, env flag и owner statement сами по себе не являются authority.

## Текущий локальный baseline

| Проверка | Результат | Статус |
|---|---:|---|
| Root adversarial | 54/54, 1086 | local PASS |
| Active entrypoints | 20/21, 411, SKIP=1 | dedicated PostgreSQL acceptance не выполнена |
| Runner / release contracts | 22/22 · 14/14 | PASS |
| Single-source | 10/10 | PASS |
| Tier-2 Windows | 42/0/5 | production gate не пройден |
| Formats | 291/5/8/24, failures=0 | syntax only |
| Python supply | 71 hashed entries; OSV 44/0 | local PASS only |
| Rust workspace | 72 PASS; 1 ignored DB acceptance; fmt/Clippy PASS | digest-pinned Linux local PASS only; scoped intake disabled on Windows |
| RustSec | 169 dependencies / 0 findings | pinned snapshot |
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

Локально уже есть exact toolchain/lock, locked build/test/lint/RustSec, bounded CAS/parser/replay,
build-pinned signed ingest mandate и одна tenant-scoped atomic PostgreSQL operation без raw pool
escape. Для production всё ещё обязательны:

- attested release build с закреплённым registry digest и проверяемой VCS/build provenance;
- external key custody/rotation/revocation, trusted clock/host boundary и shared transactional replay;
- end-to-end доказательство, что signed authority — единственный источник PostgreSQL project scope;
- signed schema/policy/function attestation и проверка deployment drift;
- обязательный verified proof-of-content либо tenant/keyed dedup с неразличимым outcome;
- dedicated disposable-cluster `maworld_rls_test_*` migration/RLS/pool-reuse/concurrency/crash/recovery acceptance;
- production runtime credentials/TLS/role grants и deployment verification;
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
- versioned migration existing PostgreSQL volume + backup/restore;
- NATS mTLS/auth, MinIO least privilege и network policy.

## Порядок допуска

1. Закрыть все P0/P1 в current security report.
2. Получить external runtime evidence и signed supply provenance.
3. Повторить полный аудит на immutable release artifact.
4. Независимо проверить critical boundaries и recovery.
5. Только затем владелец может отдельно пересмотреть LIVE/BUILD_FREEZE.

Текущий отчёт: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
