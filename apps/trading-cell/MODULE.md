# trading-cell (Domain A)
Закреплённый Python package: `nautilus_trader==1.202.0` (Rust/PyO3 internals не пересобирались на этом host). Любые старые ссылки на «v2» — historical architecture target, не установленная версия.
Свой код (только это): NATS/SBE DataClient+ExecutionClient; RiskService-гейт врезкой в Nautilus RiskEngine; Kill-Switch Atomic Register (contracts/trading/KillSwitchState.yaml); PromotionRouter (SHADOW→OrderEmulator, CANARY→масштабирование);
адаптеры: hyperliquid (primary, cloid) + binance_th (secondary, newClientOrderId), оба UUIDv7.
Данные: ArcticDB (as_of, Research Plane) + ParquetDataCatalog (бэктест). Анти-look-ahead: as_of enforced, тикеры анонимизированы, walk-forward, Alpha Decay метрика.
Лимиты (RiskService — детерминированный proposal-only фильтр, не authority): drawdown 10% HARD, ≤20 сделок/день, 3 лосса→пауза 1ч, ≤1%/сделку. Overflow/narrowing и invalid/future inputs локально закрыты 13 Rust-тестами. Его `reconciled`/`heartbeat` остаются caller observations без trusted provenance и не дают права на исполнение; поэтому runtime execution остаётся HOLD. LLM запрещены на hot path.
Целевой MVP (ещё не current runtime evidence): Hyperliquid TESTNET paper; стресс kill -9 с in-flight ордерами; независимо подтверждённая reconciliation.
