# Round 8 — Implementation Result (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


«Гони по остатку и заводи trading-cell / Money Forge». Доделал остаток DR-2 non-keystone И завёл оба домена. Шесть модулей, все зелёные.

## Остаток DR-2

### Side-Effect Adapters (DR2 0x0D) — 9/9 — `services/side-effect-adapters/`
Единый контракт `SideEffectAdapter`: declared ActionSpec subset, required capability, reversibility class, идемпотентность (ExternalEffectRegistry), evidence, rollback/compensation, timeout, audit. Ни один эффект без redeemed capability + idempotency key. Реализованы Filesystem (sandboxed write, COMPENSATABLE rollback) и Network (broker-mediated, allowlist). AdapterRegistry маршрутизирует ActionSpec→адаптер. Тесты: неверная capability→DENIED, путь вне scope→HOLD, host вне allowlist→HOLD, replay→REPLAYED, rollback компенсирует.

### BudgetRouter + PriceCatalog + EvalRegistry (v1.4 §5.3/5.4) — 9/9 — `services/budget-enforcer/`, `services/eval-registry/`
- **BudgetRouter:** роль→lane (sensitive/direct-required → direct, никогда router); P0/P1 резерв защищён (низкий приоритет не ест резерв → DENY); stale-price → HOLD non-critical, P0 продолжает; batch только для фоновых P3+.
- **EvalRegistry:** golden set + baseline; регрессия детектируется → `BLOCK_REGRESSION`; без регрессии → PROMOTE. Это gate self-improvement-контура.

## Trading Cell (Domain A) — RiskService — 9/9 — `apps/trading-cell/risk-service/` (Rust)
**Детерминированный авторитетный контроллер на hot path.** Деньги — fixed-point `i64` (никакого f64). LLM SignalProposal — недоверенный вход: `conviction_score` **игнорируется** риск-математикой. Доказано в Rust:
- risk > 1% → DENY (conviction 99 не помогает)
- drawdown ≥ 10% → HARD STOP
- stale data > 100мс → kill-switch DENY
- reconciliation mismatch → DENY
- heartbeat loss → reduce-only (non-reduce → DENY)
- >20 сделок/день, 3 подряд лосса → DENY
- position_size — fixed-point, детерминированный

Это ядро D5/closure §9: LLM никогда не авторизует увеличение риска; авторитет — у скомпилированного детерминированного сервиса.

## Money Forge (Domain C) — pipeline gate — 11/11 — `apps/money-forge/`
Пайплайн DISCOVER→…→PAYMENT_TEST→RETENTION_TEST→SCALE с жёстким правилом: **соц-внимание / AI-сентимент ≠ валидация рынка**. Пересечение границы PAYMENT_TEST требует **детерминированного** экономического доказательства (verified Stripe webhook), не buzz. Доказано:
- ранние стадии прогрессируют на soft-сигналах
- buzz/ai не пересекают границу платежа → `SOCIAL_ATTENTION_IS_NOT_VALIDATION`
- unverified payment → DENY; verified → ADVANCE
- RETENTION нужен verified retention; SCALE — оба; без пропусков стадий; KILL всегда доступен

## Итог
DR-2 закрыт полностью (keystone раунд 7 + non-keystone раунд 8). Оба домена MAWorld заведены детерминированными авторитетными ядрами (Rust RiskService, Money Forge gate) — LLM остаётся вне hot path/валидации, только предлагает.

Осталось (крупное, инфраструктурное): консолидация 24 контрактов (0x13) в единый JSON-Schema+Rust+Python+PG набор; gVisor runsc на Linux VPS вместо bwrap; реальные адаптеры бирж (Hyperliquid/Binance TH) для trading-cell; Stripe-интеграция для Money Forge; NautilusTrader adoption spike.

## Запуск
```
python3 services/side-effect-adapters/test_adapters.py            # 9/9
python3 services/budget-enforcer/test_budget_eval.py              # 9/9
cd apps/trading-cell/risk-service && cargo test                   # 9/9
python3 apps/money-forge/test_money_forge.py                      # 11/11
```
