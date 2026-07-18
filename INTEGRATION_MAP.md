# MAWorld — Карта интеграции реальных проектов (анти-задвоение)

> **План интеграции, не acceptance evidence.** LIVE OFF / BUILD_FREEZE BLOCKED.
> Ни одна строка ниже не разрешает сеть, платёж или ордер. Текущий security-вердикт:
> [docs/44_SECURITY_HARDENING_2026-07-16.md](docs/44_SECURITY_HARDENING_2026-07-16.md).

Принцип владельца: **внедряем существующие проекты первым делом, чтобы не задвоить и начать использовать.** MAWorld-модули, где они дублируют готовое, становятся тонкой врезкой (gate/adapter), а не заменой. Ниже — что реально есть в `C:\PROJECTS` и куда оно встаёт.

## Каталог: реальный проект → слот MAWorld → роль

| Реальный проект (C:\PROJECTS) | Что это (живое) | Слот MAWorld | Как интегрируем (не дублируем) |
|---|---|---|---|
| **continuityos** (OSS v0.9.0) | gate/preflight + hash-chain Ledger | services/continuityos-gateway | ✅ УЖЕ используется в спайках (реальный preflight+Ledger) |
| **continuity_os/mind/dialectic.py** | Внешний Devil×Angel×Dialectic Synthesizer | services/dialectic-adjudicator | External import hard-disabled; возможен только будущий изолированный proposal adapter |
| **continuity_os/mind/** (ctha, gate, memory) | CTHA когнитивное ядро (brain) | agents/ proposer | Врезка через Proposal Bridge (proposer-only, доказано v4) |
| **inner_circle_bot** | Stripe verifier в отдельном проекте | apps/money-forge | Только seam/contract compatibility; runtime settlement acceptance не выполнен |
| **trading-edge** | Research→Paper→Live: CCXT WS + microstructure/regime features + **PromotionGate + PhaseGate (A→B→C)** + active-inference preflight | apps/trading-cell (промоция + фичи) | Только future integration: proposal-only RiskService остаётся HOLD; execution authority и runtime seam не приняты |
| **LIVE_TRADING/btcusdt_binance_futures_bot_v7** | Testnet Binance execution bot (BinanceRESTClient, ExecutionGateway, reconcile, backtest/walkforward) | apps/trading-cell/venue-adapters | **Инжектим его BinanceRESTClient в BinanceVenue** (execution/reconcile — его, идемпотентность/audit — наши) |
| **continuity_os/04_OUTPUTS/bitunix_*** | Bitunix public WS venue + gate hardening | apps/trading-cell/venue-adapters | Инжектим в BitunixVenue |
| **archiveos_api / archiveos_data** | Archive tooling (ingestion/harvest) | apps/knowledge-foundry (коннекторы) | Источник для KF ingestion-коннекторов (Local Folder/Git уже спроектированы) |
| **hermes_os** | Telegram/Hermes оболочка (в _ARCHIVE) | apps/control-plane (Telegram) | Источник паттернов Telegram-адаптера (secret_token+nonce доказаны) |

## Что НЕ дублируем (берём готовое)
- **Лестница промоции стратегий** — у trading-edge есть PhaseGate A→B→C + PromotionGate. Локальный Rust `RiskService` — только proposal-only фильтр на HOLD; его вывод не является execution authority. Integration/runtime acceptance ещё нет.
- **Binance execution + reconcile** — у LIVE_TRADING (BinanceRESTClient/ExecutionGateway/BootstrapSynchronizer). VenueAdapter.BinanceVenue оборачивает его, добавляя идемпотентность + audit через spine.
- **Stripe** — inner_circle_bot. Проверена только seam/contract compatibility; settlement/fulfillment и runtime bridge не приняты.
- **Devil×Angel×Dialectic** — внешний код не исполняется внутри authority-процесса; legacy path заблокирован.
- **Gate/Ledger** — continuityos OSS. Используется.

## Что наше (нет дублей — заполняем пробелы)
Локальные компоненты контрольного хребта (Proposal Bridge, CanonPromoter, ExternalEffectRegistry, capability tokens, MCP normalizer, broker, AsyncTaskRegistry), experimental Knowledge Foundry Rust intake/Postgres/RLS/parser, proposal-only RiskService, Money Forge gate, side-effect adapters и BudgetRouter/EvalRegistry. KF и Rust risk остаются HOLD; component tests не означают готовность полных сервисов.

## Порядок будущей изолированной приёмки
1. **Trading:** proposal-only `RiskService.evaluate_proposal()` → отдельный signed Action Authority → paper/testnet adapter. До этого venue transport отключён.
2. **Money Forge:** Stripe test webhook → fixed verifier → signed evidence → proposal-only gate. Settlement/fulfillment отдельно принимаются в sandbox.
3. **Dialectic:** `mind.dialectic` в расписании → findings → review/canon-candidate через CanonPromoter (человек утверждает).
4. **Knowledge Foundry:** archiveos как ingestion-источник.
5. **Инфра (деплой):** gVisor на VPS, DBOS→прод-Postgres, Nautilus backtest. См. `DEPLOY.md`.

Целевой инвариант: внешние проекты и модели дают только данные/предложения. Исполнение возможно
только после отдельного фиксированного verifier/authority boundary и production acceptance.
