# ADR-индекс
> **Исторический decision log.** `PASSED`/`CLOSED` ниже описывает отдельный старый прогон или принятое design-решение, а не текущую production acceptance. При конфликте действуют `STATUS.md`, `docs/44_SECURITY_HARDENING_2026-07-16.md`, `DEPLOY.md` и module-level HOLD.

Сводная таблица: docs/00_MASTER.md §13. Новые ADR раунда 2:
| ID | Решение | Источник |
|---|---|---|
| ADR-R2-01 | Historical target = NautilusTrader «v2»; current lock = `nautilus_trader==1.202.0`, Rust-core acceptance не выполнена | D5 T1 / current lock |
| ADR-R2-02 | Venues: Hyperliquid primary + Binance TH secondary | D5 T2 |
| ADR-R2-03 | Market data: ArcticDB + ParquetDataCatalog | D5 T3 |
| ADR-R2-04 | Anti-look-ahead: as_of + анонимизация + walk-forward | D5 T4 |
| ADR-R2-05 | Workflow runtime: DBOS+Postgres, Temporal = migration target | D6 T1 |
| ADR-R2-06 | Harness: thin custom + LiteLLM/OpenRouter; SDK = адаптеры | D6 T2 |
| ADR-R2-07 | MCP-era gate: default HOLD на неизвестные версии/заголовки | D6 T3 |
| ADR-R2-08 | Observability: OTel + self-hosted Langfuse + TraceBridge | D6 T4 |
| ADR-R2-09 | Secrets: Infisical + SOPS+age; Telegram nonce-approvals | D6 T6 |
| ADR-R2-10 | Sandbox: Tier2 gVisor default; Daytona HOLD; Modal GPU | D6 T7 |
| ADR-R2-11 | Knowledge Foundry: Postgres+pgvector+MinIO, single-DB | D7 |
| ADR-R2-12 | Self-improvement loop: agents propose / evals decide / human canon; kill-switch fail-closed | docs/04 |

## Раунд 3 (после 4 документов: 2 DR, Broker Integration, Canonical Synthesis v1.1)

| ID | Решение | Источник |
|---|---|---|
| **ADR-R3-01 (CORRECTION)** | MCP-гейт строится под **2025-11-25** (последняя финализированная спека). **2026-07-28 — Release Candidate**, НЕ финал → version-gate в HOLD, не фризить поведение. Отменяет ошибочную запись раунда 2 «2026-07-28 финал». | DR (D6-r2), офиц. changelog, Synthesis §6.4 |
| ADR-R3-02 | Enforcement: ContinuityOS — **HARDEN-FIRST**. Гейт сегодня opt-in/обходим. Прод: gVisor + egress-deny namespace + veth-to-proxy. Демо fail-closed в `spikes/control_spine_v1`. LD_PRELOAD/eBPF отвергнуты (обходимы). | Broker Integration Research |
| ADR-R3-03 | CTHA/mind = **SPIKE-FIRST, proposer-only**. Brain не владеет authoritative state; пишет только proposals; ContinuityOS preflight — единственный authority-plane. Council-роли ≠ security (нет persistent identity/подписи). | DR (D6-r3 CTHA) |
| ADR-R3-04 | Три системы отдельно владеемы: Knowledge Foundry (истина проекта) / ContinuityOS Control Spine (authority) / Trading Cell (детерминизм). LifeOS — приватная память, вне канона. | Canonical Synthesis v1.1 |
| ADR-R3-05 | ActionSpec v1.2: добавлен `mcp` блок (protocol_version, session_id_hash, origin, oauth.audience, task.state) + TraceContext/EvalRecord/BudgetPolicy. | DR (D6-r2 contracts) |

## Раунд 4 (после GPT Synthesis v1.3 — ревью Rust intake)

| ID | Решение | Источник |
|---|---|---|
| ADR-R4-01 | Language boundary уточнён: авторитет от владения сервисом/политики/контрактов, НЕ от языка. Rust — для integrity-critical; Postgres — авторитетное состояние; Rust-сервис = контролируемый писатель/валидатор. | v1.3 §2 |
| ADR-R4-02 | CAS no-overwrite портируем: hard_link или create_new+copy (не зависит от hard links). | v1.3 §4 |
| ADR-R4-03 | **CURRENT LOCAL STATUS:** каждый Rust store call ставит `SET LOCAL ROLE` и bound transaction-local project scope; dedicated DB acceptance остаётся SKIP | v1.3 §7 / `RUST_SECURITY_HOLD.md` |
| ADR-R4-04 | **HOLD:** raw pool удалён и scoped atomic API/runtime-role/raw_blob boundary реализованы локально; end-to-end authority wiring и dedicated RLS acceptance остаются | v1.3 §6 / `RUST_SECURITY_HOLD.md` |
| ADR-R4-05 | MCP normalizer врезан в workflow: решение шага = stricter(mcp, policy); DENY/HOLD до side effect. | control_spine_v2 |

## Раунд 5 (после отчёта Control Spine + Competitive Primitives)

| ID | Решение | Источник |
|---|---|---|
| ADR-R5-01 | MCP async `tasks`: AsyncTaskRegistry банит orphan-polling — poll/result привязан к (action_spec_id, delegation_grant_id, trace_id, task_external_id). | отчёт 05_BACKLOG |
| ADR-R5-02 | Authority вне transport-session: подписанный короткоживущий DelegationGrant + одноразовый CapabilityToken, привязанный к action_spec_id. Enlargement невозможен. | отчёт 06 secrets |
| ADR-R5-03 | KF parser router: native для MD/TXT/source с локаторами; rich/binary → SandboxRequired (Tier2 gVisor). Не парсить rich in-process. | closure §2.7 + отчёт Tier2 |
| ADR-R5-04 | protocol_revision/deprecation хранить как данные, не код-константы (пока 2026-07-28 не line-verifiable). | отчёт MCP checklist #7 |
| ADR-R5-05 (divergence) | Runtime: отчёт склоняет к Temporal-first; DBOS остаётся проверенным MVP, Temporal = migration target (ADR-R2-05). Observability: Phoenix\|Langfuse — заменяемый бэкенд за стабильным TraceContext. | отчёт vs Synthesis v1.1 |

## Раунд 6 (после v1.4 Adjudication + DR2 Mandatory Broker V3)

| ID | Решение | Источник |
|---|---|---|
| ADR-R6-01 | **DurableRuntimeAdapter** канонизирует runtime-конфликт: DBOS = FIRST SPIKE (проходит runtime-gate §3.3), Temporal = PRE-APPROVED FALLBACK. Не фризить Temporal «по числу отчётов». | v1.4 §3 |
| ADR-R6-02 | Observability развязана от продукта: TraceContext → OTel → ObservabilityBackend; Phoenix = первый бэкенд, не постоянная архитектура. | v1.4 §4 |
| ADR-R6-03 | **Proposal Bridge** (DR2 0x09): недоверенный proposal → strip authority-маркеров → свежий ActionSpec; никогда не исполняет и не промотит canon. Доказано 9/9 негативных. | DR2 0x09 |
| ADR-R6-04 | **CTHA boundary** (DR2 0x0A): brain в рестриктной песочнице не может мутировать canon/ACTIVE/сеть/DB/секреты — структурно. bypass-матрица fail-closed. | DR2 0x0A |
| ADR-R6-05 | **AsyncTaskRegistry** полный state machine + orphan-poll ban (нельзя перескочить verify/переоткрыть terminal). | v1.4 §5.2 |
| ADR-R6-06 | Boundary-proven spike (DR2 0x12) — keystone интеграции; DR-2 остаётся OPEN до CanonPromoter + формального ExternalEffectRegistry + Spike B. | DR2 0x12 / §10 |

## Раунд 7 (закрытие keystone DR-2)

| ID | Решение | Источник |
|---|---|---|
| ADR-R7-01 | **CanonPromoter** — единственный путь в canon; Foundry CanonicalDecision авторитетна, ContinuityOS canon = производный view; прямой add_canon структурно запрещён (GuardedContinuity). Доказано 10/10 на реальном ContinuityOS. | DR2 0x0B |
| ADR-R7-02 | **ExternalEffectRegistry**: reversibility class + reconciliation (CONFIRMED/ABSENT/AMBIGUOUS→HOLD) + compensation (IRREVERSIBLE→HOLD). Replay никогда не пере-стреливает. 7/7. | DR2 0x0C |
| ADR-R7-03 | **Spike B**: git commit под capability (grant без git.push), push=HOLD; commit = IRREVERSIBLE effect, recovery сверяется с git log → нет дубля. 7/7. | v1.4 §7 |
| ADR-R7-04 | DR-2 keystone закрыт (boundary + CanonPromoter + effect-registry + Spike B доказаны). Осталось: side-effect адаптеры, MCPAuthorizationResolver-сервис, BudgetRouter, EvalRegistry, консолидация контрактов, gVisor на VPS. | DR2 §10 |

## Раунд 8 (остаток DR-2 + Trading Cell + Money Forge)

| ID | Решение | Источник |
|---|---|---|
| ADR-R8-01 | Единый SideEffectAdapter-контракт: capability+idempotency+evidence+rollback+timeout+audit; ни один эффект без redeemed capability. 9/9. | DR2 0x0D |
| ADR-R8-02 | BudgetRouter: sensitive→direct lane, P0/P1 резерв защищён, stale-price→HOLD non-critical; EvalRegistry: регрессия→BLOCK. 9/9. | v1.4 §5.3/5.4 |
| ADR-R8-03 | **SUPERSEDED:** Trading Cell RiskService — детерминированный proposal-only фильтр, не authority; arithmetic/provenance и текущая Rust acceptance на HOLD | D5 / current `apps/trading-cell/MODULE.md` |
| ADR-R8-04 | **Money Forge gate**: соц-внимание/AI-сентимент ≠ валидация; пересечение PAYMENT_TEST требует verified payment (Stripe), RETENTION — verified retention, SCALE — оба. 11/11. | Domain C |
| ADR-R8-05 | **SUPERSEDED:** LLM остаётся proposal-only; локальные domain gates сами не являются execution/payment authority | Synthesis §7,10 / current security audit |

## Раунд 9 (интеграция бирж/Stripe/Nautilus/gVisor + консолидация)

| ID | Решение | Источник |
|---|---|---|
| ADR-R9-01 | Unified VenueAdapter имеет local contract tests; external client injection, submit и reconcile остаются отдельной runtime acceptance, LIVE OFF | владелец / current audit |
| ADR-R9-02 | `inner_circle_bot` Stripe verifier совместим на seam/contract уровне; settlement/fulfillment и runtime evidence не приняты | inner_circle_bot / current audit |
| ADR-R9-03 | Current pin `nautilus_trader==1.202.0`; bridge — local seam only, research→live parity и Rust-core build не доказаны | D5 / current lock |
| ADR-R9-04 | Tier2 sandbox: gVisor `runsc` на Linux VPS (spec), bwrap fallback тот же контракт (egress-deny доказан). | v1.4 §5.5 |
| ADR-R9-05 | 24 контракта консолидированы в `contracts/CANONICAL_CONTRACTS_v1.md` (BaseObject, junction-таблицы, fixed-point, jcs/sbe/json profiles). | DR2 0x13 |

## Раунд 10 (Devil×Angel×Dialectic + анти-задвоение реальных проектов)

| ID | Решение | Источник |
|---|---|---|
| ADR-R10-01 | **SUPERSEDED:** external dialectic import hard-disabled; допустим только будущий изолированный proposal adapter, не live authority | mind/dialectic.py / current tombstone |
| ADR-R10-02 | Existing projects — integration candidates; RiskService proposal-only и runtime integration остаются HOLD | владелец / `INTEGRATION_MAP.md` |
| ADR-R10-03 | Проверена только seam/contract compatibility; это не external runtime acceptance и не разрешение на injection/live effects | services/integration / current audit |
| ADR-R10-04 | Boneyard формализован в DEPLOY.md: gVisor(runsc)/DBOS-прод-Postgres/боевые биржи/Nautilus/live-Stripe — пошагово, каждый за готовым тестируемым контрактом. | DEPLOY.md |

## Раунд 11 (закрытие ACT реальными компонентами + LifeOS research)

| ID | Решение | Источник |
|---|---|---|
| ADR-R11-01 | **HISTORICAL seam probe:** `/order/test` не размещал ордер и не закрывает venue lifecycle/reconcile/runtime gate; LIVE OFF | self-audit M2 |
| ADR-R11-02 | **HISTORICAL seam probe:** signed Stripe fixture не закрывает settlement/fulfillment/recovery acceptance | self-audit M3 |
| ADR-R11-03 | Self-audit обновлён: 4 CLOSED / 4 ACT (осталось Nautilus, e2e, gVisor, прод-DBOS). Дьявол не нашёл ложных claim'ов о доказанном. | 14_DIALECTIC_SELF_AUDIT |
| ADR-R11-04 | LifeOS = приватный слой агента ПОВЕРХ spine; ~10/25 инвариантов уже доказаны (CTHA boundary, capability, Governed Memory, self-improvement loop). Self-promotion памяти в истину запрещён (vs Letta). Новое: lifecycle SM, hibernation zero-token, temporal self, fork/merge. | LifeOS V3 + research |

## Раунд 12 (закрытие M8 на Postgres + hardening M7)

| ID | Решение | Источник |
|---|---|---|
| ADR-R12-01 | **HISTORICAL crash probe:** старый disposable Postgres run не закрывает current KF RLS/authority, versioned migration или production recovery acceptance | spikes/dbos-postgres-m8 |
| ADR-R12-02 | **SUPERSEDED:** current Tier-2 — pinned-FD runsc-only без fallback; Windows result 42 PASS / 0 FAIL / 5 SKIP, Linux/external assurance pending | services/sandbox-broker / STATUS.md |
| ADR-R12-03 | Self-audit: 5 CLOSED / 3 ACT (осталось M5 Nautilus, M6 e2e, M7 runsc-на-VPS). Дьявол по-прежнему не нашёл ложных claim'ов о доказанном. | 14_DIALECTIC_SELF_AUDIT |
| ADR-R12-04 | Дашборды владельца 8110/8120 недоступны (TCP принимает, HTTP молчит — бэкенд/allowlist). Не блокируем сборку; ждём проверки владельцем. | сессия |
