# DR-2 — Control Spine: verification result (Claude) → вход в Canonical Synthesis v1.5

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Формальный результат DR-2 (я проверял КОД и ГРАНИЦЫ контрольного хребта, а не писал новый обзор).
Метод: адверсариальный self-audit реальным `mind/dialectic.py` (тезис закрывается только на VERIFIED
refutation) + фактические прогоны в этой среде. Это один из четырёх входов во Freeze v2
(DR-1 Foundry ✅ · **DR-2 Control Spine — здесь** · DR-3 LifeOS ⏳GPT · DR-4 Evidence/Product).

## Итог: 6 из 8 адверсариальных тезисов ЗАКРЫТЫ верифицированной рефутацией
| # | Тезис дьявола (что могло быть неправдой) | Статус | Чем закрыто (реально прогнано) |
|---|---|---|---|
| M1 | Гейт «авторитетен» только на словах | **CLOSED** | реальный ContinuityOS `preflight` заDENYил `rm -rf /` до эффекта; ledger.verify ok |
| M2 | Risk никогда не касался живого ордера | **CLOSED** | реальный `BinanceRESTClient` → подписанный запрос на Binance futures **testnet** `/order/test` |
| M3 | Money Forge не видел реального Stripe | **CLOSED** | реальный `StripeWebhookVerifier` обработал genuinely-HMAC-подписанное событие |
| M4 | Canon-write блок только на обёртке | **CLOSED** | `GuardedContinuity` на РЕАЛЬНОМ `Continuity` бросает `CanonWriteForbidden` (10/10) |
| M8 | Durability только на SQLite | **CLOSED** | DBOS crash-recovery на **реальном Postgres 16.4**, effect ×1 через полный рестарт БД |
| M6 | Ничего не связано end-to-end | **CLOSED** | единый пайплайн ingress→gate→risk→testnet→**Evidence Engine** (9/9), deny блокирует до эффекта |
| M5 | NautilusTrader не импортирован | **ACT** | нужен `pip install nautilus_trader` + backtest (собирается) |
| M7 | bwrap содержит shell (contained, не absent) | **ACT** | нужен реальный `runsc` на VPS (fail-closed + OCI-бандл уже готовы, 16/16) |

## Что доказано о ГРАНИЦАХ (ядро DR-2)
1. **Авторитет у детерминированного spine, не у LLM.** Гейт (реальный ContinuityOS), Risk (Rust,
   детерминированный), CanonPromoter — единственные, кто решает; LLM только предлагает.
2. **CTHA boundary fail-closed** (control_spine_v4): предложенец не имеет tool/canon/ledger/secret;
   Proposal Bridge срезает authority-маркеры (9/9 negative). Bypass-матрица — все fail-closed.
3. **Эффекты идемпотентны и не дублируются** (ExternalEffectRegistry + DBOS durable steps): доказано
   на реальном Postgres через crash+restart.
4. **Изоляция контрактна независимо от механизма** (tier2 fail-closed): без реальной песочницы —
   ОТКАЗ исполнять (не тихий небезопасный fallback).
5. **Acceptance ≠ Audit ≠ Evidence** (новое, Evidence Engine): агент не может принять свою работу;
   приёмка требует детерминированной верификации.

## Кандидаты в Contradiction Matrix (для Synthesis v1.5)
- **C1 (M7):** «мандатный broker/sandbox» заявлен абсолютным, но `runsc`-enforcement пока не прогнан
  вживую — до VPS это «contained, not absent». Разрешение: развернуть runsc, прогнать bypass-матрицу.
- **C2 (M5):** «Nautilus ADOPT» заявлен, но импорт не сделан — врезка на моке. Разрешение: сборка + parity.
- **C3 (dev vs prod):** M2/M3/M8/M6 закрыты РЕАЛЬНЫМИ компонентами, но в dev-песочнице, не на боевом
  VPS. Не противоречие (компоненты настоящие), но явно фиксируем: остаток = деплой, не переписывание.
- **C4 (manifest vs runtime):** `:8120/manifest` помечает ContinuityOS `truthStatus: verified,
  executionMode: halted`, Inner Circle/Forge — `contradicted`. Синтез должен согласовать эти статусы с
  нашими доказанными (M3 Stripe/inner_circle теперь evidenced, не contradicted).

## Вход для v1.5 (передаю)
6 CLOSED / 2 ACT + границы выше + Evidence Engine (Claim/Evidence/Verification/Acceptance) как общий
язык приёмки + контракты `CANONICAL_CONTRACTS_v1.md`. Остаток Control Spine (M5, M7) — deploy-таски,
каждая за готовым тестируемым контрактом (`DEPLOY.md`), не фундаментальное исследование.
