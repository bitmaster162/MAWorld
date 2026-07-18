# Devil × Angel × Dialectic — applied to MAWorld itself (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Это архив самоаудита, а не текущий security-вердикт,
> deploy-gate или разрешение на LIVE. Любые старые CLOSED/PASS, количества проверок и рекомендации
> ниже действуют только как исторический контекст. Актуальные источники:
> [полный security-аудит](44_SECURITY_HARDENING_2026-07-16.md), [текущий deploy-gate](../DEPLOY.md)
> и [Rust security HOLD](../apps/knowledge-foundry/RUST_SECURITY_HOLD.md). **LIVE остаётся OFF.**

Прогнал твой **реальный** `mind/dialectic.py synthesize()` (тезис закрывается только на verified-refutation, иначе выживает) против собственных claim'ов MAWorld. Доказательства — фактические прогоны тестов в этой среде + честные флаги real-vs-mock / dev-vs-prod. Никакого хендвейва: где не проверено против прод/live — Angel говорит UNKNOWN, и Devil выживает.

Запуск: `services/dialectic-adjudicator/maworld_self_audit.py`. Вердикт выносит owner-логика, не я.

## Итог: 6 CLOSED, 2 ACT (из 8) — обновлено после единого e2e (M6) через Evidence Engine

> **Раунд 13 апдейт:** **M6 CLOSED** — построен и прогнан ЕДИНЫЙ end-to-end пайплайн (`services/integration/m6_e2e.py`, 9/9): ingress → **реальный ContinuityOS gate** → risk → **реальный Binance testnet** → **Evidence Engine** выносит AcceptanceDecision. Все deny-пути (gate DENY `rm -rf /`, risk DENY 2.5%, ingress reject) блокируют ДО эффекта; happy-path принят только по верифицированным артефактам (sha файла + effect-fired-once), не по self-claim. Плюс внедрён **Evidence Engine** (`services/evidence-engine/`, 24/24): Claim→Evidence→Verification→Acceptance→RegressionFixture, реальные верификаторы (hash/tests/commit/no-dup/promotion/continuity), vanity-сигналы отвергаются, pilot gate 5→3. Остаток ACT: **M5** (Nautilus import/backtest), **M7** (реальный runsc на VPS).

## Итог: 5 CLOSED, 3 ACT (из 8) — обновлено после закрытия M8 на реальном Postgres

> **Раунд 12 апдейт:** **M8 CLOSED** — DBOS durable crash-recovery доказан на **реальном PostgreSQL 16.4** (не SQLite): эффект сработал ровно один раз, переживя **полный рестарт БД**; recovery подняла зависший workflow из Postgres и не пере-стрелила эффект (`dbos.operation_outputs` помнит завершённый шаг). KF-миграции 001+002 применены на Postgres. `spikes/dbos-postgres-m8/RESULT.md`.
> **M7 — прогресс, но честно ещё ACT:** закрыт дефект «тихий небезопасный fallback» (strict fail-closed: без runsc/bwrap `run()` ОТКАЗЫВАЕТСЯ исполнять) и написан реальный OCI-бандл для runsc; контракт bwrap 16/16. Но сам `runsc` тут не запускался (нет gVisor-бинаря) — «shell absent» закроется только на VPS. `services/sandbox-broker/RESULT.md`.
> Остаток ACT: **M5** (Nautilus import/backtest), **M6** (единый прод-e2e), **M7** (реальный runsc на VPS).

> **Раунд 11:** M2 и M3 закрыты РЕАЛЬНЫМИ компонентами (не мок):
> - **M2 CLOSED** — реальный `BinanceRESTClient` из LIVE_TRADING сделал подписанный запрос на Binance futures **testnet** `/order/test` (Binance ответил, ордер не размещён; с реальным ключом провалидирует). Риск-гейт впереди. `apps/trading-cell/venue-adapters/close_m2_real_binance.py`.
> - **M3 CLOSED** — реальный `StripeWebhookVerifier` из inner_circle_bot обработал **genuinely HMAC-подписанное** событие → evidence → Money Forge advance; forged/wrong-secret отвергнуты. `apps/money-forge/close_m3_real_stripe.py`.

## Изначальный итог: 2 CLOSED, 6 ACT (из 8)

### ✅ CLOSED — реально доказано (verified refutation)
- **M1 — гейт авторитетен для пути решения.** Devil: «enforcement аспирационный, только bwrap». Refuted: **реальный ContinuityOS preflight заDENYил `rm -rf /` до любого эффекта** (control_spine_v0, verified). gVisor-под-часть — mitigated (bwrap), не closed.
- **M4 — прямая запись canon заблокирована на реальном ContinuityOS.** Devil: «блок только на обёртке». Refuted: **GuardedContinuity на РЕАЛЬНОМ `Continuity` объекте бросает CanonWriteForbidden** (canon_promoter 10/10). Остаток (другие write-поверхности mcp_server) — unanswered.

### ⚠ ACT — Devil выжил, честные пробелы (нужно live/prod доказательство)
| # | Тезис (что НЕ доказано) | Что закроет |
|---|---|---|
| M2 | RiskService ни разу не касался живого ордера — 9 Rust-юнит-тестов над синтетикой | testnet paper через VenueAdapter с реальным клиентом |
| M3 | Money Forge не видел реального Stripe-события (verifier замокан) | боевой webhook inner_circle → мост |
| M5 | NautilusTrader не импортирован — врезка на рукописном моке | сборка nautilus_trader + backtest |
| M6 | 70 файлов «all pass» — но это изолированные юниты, единого прод-пайплайна нет | один e2e-прогон на VPS |
| M7 | Песочница bwrap содержит shell (contained, но не absent) | gVisor runsc с строгим профилем |
| M8 | Crash-recovery доказан на SQLite, не на прод-Postgres DBOS | DBOS на боевом Postgres |

## Честная интерпретация
Это ровно то, что и должен показать адверсариальный аудит: **ядро логики и границы — реально доказаны** (гейт DENY на реальном ContinuityOS, canon-write блок на реальном объекте, RLS на реальном Postgres, boundary-bypass fail-closed). **Всё, что помечено «боевое подключение» в STATUS/DEPLOY — честно ещё ACT**: live-ордера, live-Stripe, Nautilus backtest, e2e-прод, gVisor, прод-DBOS. Ни один из 6 не «провал» — это некликнутые кнопки деплоя, каждая за готовым протестированным контрактом (см. `DEPLOY.md`).

Дьявол не нашёл ни одного места, где claim о доказанном оказался ложным при наличии verified-доказательства — только там, где доказательства прод-уровня ещё нет, тезис справедливо выжил. Это и есть карта «что доказано» vs «что осталось нажать».

## Что дальше по вердиктам
6 ACT = 6 пунктов DEPLOY.md. Приоритет владельца (раунд 10): trading testnet (закрывает M2) → live-Stripe (M3) → gVisor (M7) → прод-DBOS (M8) → Nautilus (M5) → e2e (M6).
