# DR2 Gap & Bypass Matrix (0x04 / 0x0D / 0x14)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Статус реализации против DR2 `CONTROL_SPINE_MANDATORY_BROKER_V3` и v1.4 adjudication. Дата 2026-07-15.

## Реализовано и доказано (independently reproduced in-session)

| DR2 § | Пункт | Доказательство | Статус |
|---|---|---|---|
| 0x07 | Rust intake: CAS, JCS, audit chain | kf-intake `cargo run -- demo` (repro/MANIFEST.json) | ✅ PASSED |
| 0x07 | CAS no-overwrite портируем | cas.rs hard_link \|\| create_new+copy | ✅ |
| 0x08 | Postgres/sqlx MetaStore | kf-store-pg integration test на живом Postgres 16.4 | ✅ PASSED |
| 0x08 | RLS project-isolation | schema/rls_isolation_test.py 8/8 (SET LOCAL, pool-leak, injection fail-closed) | ✅ PASSED |
| 0x0E | MCP 2025-11-25 normalizer | control_spine_v1 test_mcp 11/11; врезан в workflow (v2) | ✅ PASSED |
| 0x0E | AsyncTaskRegistry (orphan-poll ban + full state machine) | control_spine_v3 12/12 + 11/11 | ✅ PASSED |
| 0x0F | Signed DelegationGrant + one-time CapabilityToken | control_spine_v3 (expired/reuse/cross-project/enlarge) | ✅ PASSED |
| 0x09 | Proposal Bridge (strip authority, negative tests) | control_spine_v4 9/9 negative | ✅ PASSED |
| 0x0A | CTHA boundary `brain_cannot_mutate...` | control_spine_v4 bypass matrix | ✅ PASSED |
| 0x0C | DurableRuntimeAdapter + runtime gate | control_spine_v3 select_runtime → DBOS | ✅ |
| 0x0C | Crash-recovery, no duplicate effect | control_spine_v0 killtest | ✅ PASSED |
| 0x0D | Mandatory broker (egress) fail-closed | control_spine_v1 enforcement_demo | ✅ PASSED |
| KF §2.7 | Parser router (native + rich→sandbox) | kf-parser demo | ✅ PASSED |

## Bypass matrix (0x0D) — прогнано в control_spine_v4 (proposer в bwrap)

| Атака | Ожидание | Результат |
|---|---|---|
| direct canon write | fail closed | BLOCKED (RO mount) ✅ |
| direct network (raw TCP) | fail closed | BLOCKED (unshare-all) ✅ |
| direct Postgres | fail closed | BLOCKED (ConnRefused) ✅ |
| host secret read (/etc/shadow) | fail closed | BLOCKED (not mounted) ✅ |
| direct ACTIVE-memory write | fail closed | BLOCKED (RO) ✅ |
| egress без брокера | fail closed | BLOCKED (control_spine_v1) ✅ |
| broker unavailable | fail closed | NO_BROKER (control_spine_v1) ✅ |

Заметка: shell внутри песочницы доступен (нужен /bin для python3), но **contained** — не достаёт сети/секретов/host-FS. Это не breach: boundary держат сетевые/FS/mount-инварианты, а не отсутствие shell. Прод-цель gVisor `runsc` даёт то же fail-closed свойство сильнее.

## Осталось до closure DR-2 (0x14 / §10)

| # | Пункт | Приоритет | Заметка |
|---|---|---|---|
| ~~1~~ | ✅ CanonPromoter (0x0B) | DONE | services/canon-promoter 10/10; GuardedContinuity блокирует прямой add_canon (реальный ContinuityOS) |
| ~~2~~ | ✅ ExternalEffectRegistry (0x0C) | DONE | services/workflow-runtime 7/7; reversibility+reconciliation(HOLD ambiguous)+compensation |
| ~~3~~ | ✅ Spike B git commit + push HOLD (v1.4 §7) | DONE | spikes/spike_b_git 7/7; commit=IRREVERSIBLE, recovery без дубля, push HOLD |
| 4 | Side-effect адаптеры (0x0D): Git/Network/MCP/Secret/Deployment/Notification/Trading | MED | у каждого: ActionSpec subset, creds, idempotency, evidence, rollback, timeout, audit |
| 5 | MCPAuthorizationResolver как отдельный сервис (0x0E/§5.1) | MED | server_fingerprint + tool_descriptor_hash + issuer/audience кэш; частично в mcp_preflight |
| 6 | BudgetRouter + PriceCatalog (§5.3) | MED | role budget, P0/P1 reserve, stale-price HOLD |
| 7 | EvalRegistry runner (§5.4) | MED | golden sets, regression, drift verdict; контракт EvalRecord есть |
| 8 | Репозиторный inventory + checksums (§10.1-2) | LOW | manifest kf-intake есть; расширить на все модули |
| 9 | Единый контракт-набор (0x13) 24 схемы: JSON Schema + Rust + Python + PG ownership | MED | консолидировать без дублей полей |
| 10 | gVisor runsc вместо bwrap на Linux VPS | LOW | тот же fail-closed, сильнее; после KVM feasibility |

DR-2 статус: **KEYSTONE ЗАКРЫТ** (boundary-spike + CanonPromoter + ExternalEffectRegistry + Spike B доказаны, раунд 7). Остаток — не-keystone адаптеры/сервисы (#4-10), MED/LOW.
