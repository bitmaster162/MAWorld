# Карта модулей — слоты и статус

> **Текущий security-вердикт (2026-07-18): LIVE OFF / BUILD_FREEZE BLOCKED.**
> Эта таблица содержит исторические результаты отдельных spike-прогонов и не является production acceptance.
> Актуальный проверяемый срез: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).

Первая таблица показывает зрелость **полного service slot**, а не наличие отдельных библиотек/спайков. Поэтому `EMPTY`/`WIP` здесь может сосуществовать с локально проверенным узким компонентом в исторических таблицах ниже; такой component PASS не повышает весь сервис до runtime-ready.

Статусы: `EMPTY` (полного сервиса нет) · `CANDIDATE` (есть хаотичный модуль в incoming/, надо адаптировать) · `WIP` · `DONE`.
Когда закидываешь свой модуль в `incoming/` — впиши его сюда в колонку "Кандидат из incoming".

| Слот | Что должен делать | Контракты | Статус | Кандидат из incoming |
|---|---|---|---|---|
| services/continuityos-gateway | gate_hook.py preflight, ActionSpec, MCP normalizer, egress broker | control/ActionSpec | **WIP — MCP norm + enforcement demoed** | ContinuityOS v0.9.0; control_spine_v0+v1 (preflight+Ledger+MCP+broker TESTED_LOCAL) |
| services/workflow-runtime | DBOS-адаптер, Checkpoint Store, Branch Ledger, Effect Registry | workflow/* | EMPTY | |
| services/handoff-gateway | HandoffEnvelope валидация, Capability Resolver | handoff/* | EMPTY | |
| services/memory-governor | promotion lifecycle PROPOSED→ACTIVE, слои Pinned/Working/Archival | memory/* | EMPTY | hermes_memory.db логика? |
| services/sandbox-broker | tier-роутинг: WASM/gVisor/Firecracker/E2B/Modal адаптеры | sandbox/* | EMPTY | |
| services/secrets-broker | Infisical-клиент, ключи по роли/классу данных | — | EMPTY | |
| services/budget-enforcer | квоты, P0/P1 резервы, кэш/batch-политики, fallback-цепочки | control/BudgetPolicy | EMPTY | QuotaGateway псевдокод D1 |
| services/trace-bridge | OTel-спаны + внутренний TraceContext → Langfuse | control/TraceContext | EMPTY | |
| services/eval-registry | golden sets, регрессии, drift-вердикты | control/EvalRecord | EMPTY | |
| services/improvement-engine | Improvement Loop: SENSE→...→PROMOTE, GEPA-раннер | improvement/* | EMPTY | |
| apps/control-plane | API Gateway, Telegram (secret_token+nonce), Approvals | — | EMPTY | Hermes/OpenClaw? |
| apps/trading-cell | `nautilus_trader==1.202.0`, proposal-only RiskService, kill-switch, NATS/SBE клиенты, PromotionRouter, venue adapters | trading/* | **WIP / LIVE OFF — local Rust math green; trusted observation/execution provenance pending** | BitEvo модули? |
| apps/knowledge-foundry | intake (Rust) + Postgres MetaStore + RLS | schema/001+002+003, kf-intake, kf-store-pg | **SECURITY HOLD — local API/static boundary implemented; authority→scope, schema attestation, dedup privacy и real-DB acceptance pending** | см. `apps/knowledge-foundry/RUST_SECURITY_HOLD.md` |
| apps/money-forge | пайплайн DISCOVER→...→SCALE, Stripe-вебхуки | — | EMPTY | |
| agents/orchestrator | GPT-5.6 Sol промпты/конфиг | — | EMPTY | |
| agents/supervisor | Fable 5 промпты/конфиг | — | EMPTY | |
| agents/challenger | Grok 4.5, только PUBLIC/INTERNAL | — | EMPTY | |
| agents/executors | Codex/GLM/Nemotron конфиги | — | EMPTY | |
| agents/improvement-proposer | рефлексия над трейсами, ImprovementProposal | improvement/* | EMPTY | |
| benchmarks | hot-path (direct vs channel vs SPSC), checkpoint, sandbox cold/warm | — | EMPTY | Gemini lock-free код → ТОЛЬКО как анти-пример |

## Спайки

| Спайк | Что доказывает | Статус |
|---|---|---|
| spikes/control_spine_v0 | Telegram→gate→sandbox→kill-9→recovery без дублей; реальный ContinuityOS preflight+Ledger | **PASSED** (см. RESULT.md) |
| apps/knowledge-foundry/kf-intake | RawBlob CAS + Occurrence/Version + JCS + идемпотентность; Rust | **LOCAL PASS 35 tests in digest-pinned Linux / SECURITY HOLD — Windows scoped intake disabled; external custody/build/host trust pending** |
| spikes/control_spine_v1 | MCP 2025-11-25 normalizer (11/11) + мандаторный egress-брокер (fail-closed) | **PASSED** |
| spikes/control_spine_v2 | MCP normalizer врезан в DBOS-workflow (stricter(mcp,policy)) | **PASSED** |
| apps/knowledge-foundry/schema (RLS) | destructive acceptance для выделенной loopback test DB | **CURRENT ACCEPTANCE SKIP — внешний PostgreSQL не предоставлен; historical result не production evidence** |
| apps/knowledge-foundry/kf-store-pg | Rust sqlx PostgresMetaStore | **LOCAL PASS 7 / 1 ignored DB acceptance — scoped atomic API implemented; real DB proof pending** |
| spikes/control_spine_v3 | AsyncTaskRegistry (orphan-poll ban + full state machine 11/11) + signed DelegationGrant/one-time CapabilityToken (12/12) + DurableRuntimeAdapter | **PASSED** |
| apps/knowledge-foundry/kf-parser | bounded parser router + strict locked KF event ledger | **LOCAL PASS 17 tests / external sandbox execution pending** |
| spikes/control_spine_v4 | Boundary-proven spike: Proposal Bridge + CTHA boundary + bypass matrix (DR2 0x09/0x0A/0x12) | **PASSED** |
| services/canon-promoter | CanonPromoter (DR2 0x0B): единственный путь в canon; GuardedContinuity блокирует прямой add_canon | **PASSED (10/10)** |
| services/workflow-runtime (ExternalEffectRegistry) | reversibility + reconciliation + compensation (DR2 0x0C) | **PASSED (7/7)** |
| spikes/spike_b_git | git commit под capability, push=HOLD, recovery без дубля коммита (v1.4 §7) | **PASSED (7/7)** |
| services/side-effect-adapters | единый SideEffectAdapter (Filesystem/Network) + AdapterRegistry (DR2 0x0D) | **PASSED (9/9)** |
| services/budget-enforcer (BudgetRouter) + services/eval-registry | budget lanes/reserves/stale-HOLD + golden/regression gate (v1.4 §5.3/5.4) | **PASSED (9/9)** |
| apps/trading-cell/risk-service | детерминированный proposal-only RiskService (Rust): checked fixed-point, kill-switches, conviction ignored | **LOCAL PASS 13 tests / HOLD — trusted observation + execution provenance pending** |
| apps/money-forge | pipeline gate: соц-внимание ≠ валидация; PAYMENT/RETENTION только verified (Domain C) | **PASSED (11/11)** |
| apps/money-forge/inner_circle_bridge | мост к inner_circle_bot StripeWebhookVerifier → verified evidence | **PASSED (8/8)** |
| apps/trading-cell/venue-adapters | Binance/Hyperliquid/Bitunix unified adapter, идемпотентный submit | **PASSED (8/8)** |
| apps/trading-cell/venue-adapters/e2e_m2 | Исторический testnet-spike; текущий risk API proposal-only, live transport не принят | **HISTORICAL; не production evidence** |
| apps/trading-cell/nautilus-adapter | NautilusTrader adopt-spike, RiskEngine врезка | **PASSED (6/6)** |
| services/sandbox-broker/tier2_runner | pinned-FD runsc-only runner без fallback; rootfs требует read-only mount; local flags не являются attestation | **42 PASS / 0 FAIL / 5 SKIP; Linux runtime/external assurance pending** |
| spikes/dbos-postgres-m8 | DBOS durable crash-recovery на **реальном Postgres 16.4**: no-duplicate effect через полный рестарт БД; KF-миграции применены (M8) | **PASSED** |
| contracts/CANONICAL_CONTRACTS_v1.md | 24 контракта в одном наборе (DR2 0x13) | DONE |
| services/dialectic-adjudicator | legacy external integration tombstoned; dialectic не входит в authority-цепь | **BLOCKED / proposal-only** |
| services/integration/wiring | seam-проверка: реальные клиенты (Binance/Stripe/dialectic/gate/ledger) совместимы с адаптерами | **PASSED (5/5)** |
| services/integration/m6_e2e | Исторический integration spike; внешние клиенты сейчас проверяются только как seam/contract | **HISTORICAL; runtime acceptance pending** |
| services/evidence-engine | **Evidence Engine (DR-4 core)**: Claim→Evidence→Verification→Acceptance→RegressionFixture; агент не принимает свою работу; vanity≠acceptance; pilot gate 5→3 | **PASSED (24/24)** |
| INTEGRATION_MAP.md | карта: реальный проект → слот MAWorld (анти-задвоение) | DONE |
| DEPLOY.md | боевой деплой-план (gVisor/DBOS-прод/биржи/Nautilus/Stripe) | DONE |

## Раунд 15-16 (пост-GPT-аудит: фиксы + консолидация + hardening)

| Слот | Что доказывает | Статус |
|---|---|---|
| libs/maworld_core | ЕДИНЫЙ источник security-примитивов (effect-registry/action-authority/evidence/mcp/trading/canon/secrets/dlp); shims в services/apps | **PASSED (single-source 10/10)** |
| services/evidence-engine (v2) | no-shell + HMAC-signed результаты; агент не принимает свою работу | **PASSED (18/18 adversarial)** |
| services/workflow-runtime/hardened_effect_registry | атомарный exactly-once, 20-thread concurrency + crash-window reconcile | **PASSED (9/9)** |
| services/action-authority | canonical ActionSpec+hash; confused-deputy заблокирован; REQUIRE_CONFIRMATION | **PASSED (8/8)** |
| apps/trading-cell/venue-adapters/trading_safety | fixed-point→lot/tick; обязательный RiskDecision; live OFF | **PASSED (12/12)** |
| services/canon-promoter/canon_sod | separation-of-duties (отдельный ключ, durable nonce, атомарно) | **PASSED (7/7)** |
| services/mcp-auth | RFC 8707 audience-bound токен, fail-closed, без passthrough | **PASSED (8/8)** |
| services/secrets-broker | секреты по роли/классу; агент получает reference, не plaintext; DLP-redaction | **PASSED (12/12)** |
| services/integration/m6_e2e_v2 | rewire на hardened-модули: hash-bound gate + exactly-once + units + signed acceptance | **PASSED (5/5)** |
| apps/money-forge/money_forge_v2 | двигает пайплайн только по подписанному payment-proving событию | **PASSED (4/4)** |
| apps/knowledge-foundry/schema/test_rls_acceptance.py | destructive RLS acceptance только для явно подтверждённой выделенной loopback DB `maworld_rls_test_*` | **SAFE GUARD PASS; DB ACCEPTANCE SKIP** |
| tests/run_all.py + .github/workflows/ci.yml + pyproject.toml | единый adversarial-раннер + CI + SHA-256 Python locks + digest-pinned images | **LOCAL SUPPLY-CHAIN CHECK PASS; production signatures/SBOM pending** |
| apps/control-plane (control_plane) | human-in-loop: owner identity (Telegram secret_token+nonce) привязана к точному ActionSpec hash; approval для A не исполнит B | **PASSED (7/7)** |
| libs/maworld_core/capability | подписанные capability-токены (bare string ≠ capability) + realpath-allowlist (prefix/traversal bypass закрыт) | **PASSED (11/11)** |
| apps/lifeos + services/side-effect-adapters | hardened: LifeOS требует подписанную capability; SideEffectAdapter — realpath containment вместо prefix | **PASSED (integration 8/8)** |
| libs/maworld_core/global_cycle | **МИРОВОЗЗРЕНИЕ-инвариант**: цикл начинается от GLOBAL и каскадит (top-down) + фрактал (каждый узел = отражение целого) | **PASSED (9/9)** |
| services/trace-bridge | OTel/OpenInference спаны от GLOBAL вниз; trace_id↔claim_id; cost-per-verified-outcome; Langfuse-экспортер | **PASSED (9/9)** |
| agents/runner | orchestrator/challenger как proposal-only (CTHA boundary — нет execute/gate/ledger/capability); цикл от GLOBAL; challenger=dialectic | **PASSED (9/9)** |
| libs/maworld_core/budget_router | durable spend, negative-reject, абсолютный потолок P0 | **PASSED (9/9)** |
| libs/maworld_core/sandbox_limits | RLIMIT CPU/RAM, output-cap, unique container id | **PASSED (5/5)** |
| libs/maworld_core/improvement_engine | bounded self-improvement (SENSE→GATE→CANARY), regression BLOCK, forbidden-classes, kill-switch | **PASSED (8/8)** |
| libs/maworld_core/policy_engine | policy-as-code (Cedar/OPA-стиль), default-deny, FORBID>PERMIT — забрали у конкурентов | **PASSED (6/6)** |
| libs/maworld_core/input_guard | prompt-injection/goal-hijack защита (OWASP Agentic) | **PASSED (7/7)** |
| libs/maworld_core/memory_provenance | memory-poisoning защита: provenance+trust-scored retrieval (OWASP) | **PASSED (8/8)** |
| libs/maworld_core/agent_registry | discover-стадия (Arthur) + NHI/SPIFFE ephemeral identity; shadow-агенты блок | **PASSED (registry+custody 11/11)** |
| libs/maworld_core/key_custody | раздача доменов ключей; gate-держатель НЕ подписывает approval (нет self-approval) | **PASSED (11/11)** |
| libs/maworld_core/pfi_bridge + apps/pfi-intake | PFI проходит untrusted-input pipeline и остаётся PROPOSED | **fixture-only; real corpus unavailable** |
| libs/maworld_core/pfi_autopull + scheduled task | bounded intake из явно заданного root; direct write отключён | **fixture-only; live automation не принята** |
| libs/maworld_core/multimodal_guard | Ghostcommit-защита: образы/AGENTS.md untrusted, агент не читает .env | **PASSED (в digest 15/15)** |
| libs/maworld_core/signed_oracle | Bonzo-защита: price-update только signed+multi-source+deviation-limit | **PASSED (в digest 15/15)** |
| libs/maworld_core/vulnerability_claim | GOLD EAGLE: proof→affected→risk→owner→fix; без proof/owner=HOLD | **PASSED (в digest 15/15)** |
| tests/test_owasp_redteam.py | OWASP Top-10 for Agentic Apps 2026 red-team корпус в CI | **PASSED (12/12)** |
| libs/maworld_core/article12_export | **из НАШЕГО PFI** (EU AI Act Art.12 ×4): bi-temporal hash-chained compliance-лог | **PASSED (12/12)** |
| libs/maworld_core/agent_containment | **из НАШЕГО PFI** («can't terminate agent»): terminate/quarantine/global-kill NHI | **PASSED (12/12)** |
| libs/maworld_core/cedar_align | policy_engine валидирован против РЕАЛЬНОГО Cedar (cedarpy): default-deny+forbid-overrides совпадают | **PASSED (10/10)** |
| libs/maworld_core/spiffe_identity | SPIFFE/SPIRE SVID-модель (ephemeral, без long-lived секретов) поверх NHI | **PASSED (в cedar+spiffe 10/10)** |
| apps/operator-cockpit/cockpit_v2 | offline renderer; входные данные помечаются UNVERIFIED/PROPOSED | **offline only; network server disabled** |
| libs/maworld_core/article12_export (enhanced) | EU AI Act Art.12: bi-temporal hash-chain + retention 183/730 + 3 цели Art.12(2) | **PASSED (research 16/16)** |
| libs/maworld_core/remote_attestation | TEE attestation-gated secret release (SEV-SNP/TDX модель); defense-in-depth против TEE.Fail | **PASSED (research 16/16)** |
| libs/maworld_core/agent_mandate | AP2/A2A: подписанные Intent+Cart мандаты; действие только внутри intent (cap+action) | **PASSED (research 16/16)** |
| libs/maworld_core/trading_stack_bridge | **связка реального проекта**: trading-stack 5-типовой контракт (SignalReport→GateDecision→ApprovalDecision→ExecutionIntent→ExecutionEvent) → spine, proposal-only + Article-12 лог | **PASSED (9/9)** |
| docs/33_FLEET_RESOURCES_AND_CONNECTIONS | инвентарь 3 машин + карта проекты→MAWorld + вывод по ресурсам деплоя | DONE |
| libs/maworld_core/bitevo_bridge | proposal path с capability/policy/gate binding; исполнение требует изолированного sandbox boundary | **local contract passed; production sandbox pending** |
| libs/maworld_core/reflex_bridge | **связка reflex OODA**: arbiter objective → improvement-engine (regression/forbidden/kill-switch); op→gated proposal; никогда не исполняет | **PASSED (7/7)** |
| libs/maworld_core/sap_bridge | **связка SAP Loop B**: promotion только machine_verified + separate-key approval (canon_sod); делегирование = подписанная capability | **PASSED (в sap+dtaap 8/8)** |
| libs/maworld_core/dtaap_z3_bridge | Z3 проверяет только restricted Boolean IR; equivalence с полной Cedar/PolicyEngine semantics не доказана | **local model passed; compiler/equivalence pending** |
| libs/maworld_core/gpts_moa_bridge | **связка GPT-S:CORE**: MoA-консенсус Q≥порог + S-Score (честность) + Anti-Self (сговор) → challenger; verified-only | **PASSED (в gpts+memir 10/10)** |
| libs/maworld_core/sovereign_memir_bridge | **связка sovereign-core**: MemIR typed + SSGM → memory_provenance; self-promote в истину запрещён | **PASSED (в gpts+memir 10/10)** |
| libs/maworld_core/compound_attestation | **GPT-DR fix**: цепочка verifier-signed AttestationResults (не raw quotes); splice/scope/TEE.Fail закрыты | **PASSED (batch2 11/11)** |
| libs/maworld_core/optimistic_verification | **GPT-DR fix**: irreversible не optimistic; hold-or-compensate; PRODUCT_SUCCESS только finalized | **PASSED (batch1 14/14)** |
| libs/maworld_core/agent_mandate_v2 | **GPT-DR fix**: AP2 payee+cart_hash+idempotency; replay/cart/payee substitution закрыты | **PASSED (batch1 14/14)** |
| libs/maworld_core/bitemporal_memory | **Gemini-DR fix**: valid_time+transaction_time (Zep-стиль); supersede не перезапись; ASI06 | **PASSED (batch2 11/11)** |
| article12_export.validate_retention | **Gemini-DR fix**: Art.26(6) блок <183д (штраф €35M/7%) + field-checklist | **PASSED (batch1 14/14)** |
| libs/maworld_core/system_walk | **СИСТЕМА ПО СИСТЕМЕ**: единый e2e spine-проход intent через все 10 core-систем в композиции; deny→safe-halt; chaos fault-injection | **PASSED (12/12)** |
| libs/maworld_core/error_budget | SRE: reliability→автономия; горение→ALERT/THROTTLE/FREEZE/CIRCUIT_BREAK (→agent_containment) | **PASSED (в system-walk 12/12)** |
| tests/run_all.py (historical checkpoint) | adversarial-suite + system-walk на том срезе | **HISTORICAL 35/35, 336; не current baseline — см. STATUS.md** |

## Реальные модули в C:/PROJECTS (для разбора)

| Путь | Что | Куда в MAWorld |
|---|---|---|
| continuityos/ (v0.9.0 OSS) | gate/preflight+Ledger, mcp_server, memory, continuity | services/continuityos-gateway (подключён в спайке) |
| continuity_os/mind/ | CTHA когнитивное ядро (brain) | agents/ + memory-governor (промпт R3 №2, после спайка границы) |
| continuity_os/ (trunk 774M) | канон, trading, fleet, BIN | разбирать по слотам через incoming/ |
| LIVE_TRADING/ (6G) | testnet bot btcusdt_binance_futures_v7 | apps/trading-cell (после Nautilus-адаптации) |
