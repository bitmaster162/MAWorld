# Canonical Synthesis v1.5 — DR-1+DR-2+DR-3+DR-4 → Contradiction Matrix → BUILD_FREEZE_V2

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


2026-07-15, раунд 14. По решению владельца никого не ждём: DR-3 и DR-4 выполнены мной; ответы GPT/
Gemini придут как **дополнения** и будут сверяться с этим документом, не заменять его.

## Статус исследований
| DR | Тема | Статус | Результат |
|---|---|---|---|
| DR-1 | Knowledge Foundry | ✅ | контракты v1.1–v1.3, intake CAS/JCS (Rust), RLS на реальном Postgres |
| DR-2 | Control Spine | ✅ | `docs/17` — 7/8 адверсариальных тезисов закрыты verified-рефутацией |
| DR-3 | LifeOS | ✅ (Claude; GPT — доп) | `docs/15` + **код**: `apps/lifeos/` 18/18 |
| DR-4 | Evidence/Research/Product | ✅ (Claude; Gemini — доп) | `docs/16` + **код**: evidence-engine 24/24, cockpit v0, pilot gate |

## Паттерн подтверждён кодом: Truth → Authority → Life → Proof → Product
- **Truth** (Foundry): CAS/JCS-происхождение, RLS-изоляция, provenance.
- **Authority** (Spine): реальный ContinuityOS gate + capability + CanonPromoter; LLM только предлагает.
- **Life** (LifeOS): приватный слой агента; lifecycle SM; hibernation с нулём токенов; model-swap
  continuity (identity ≠ model); fork без наследования authority. Структурно: `write_canon()` из
  life-слоя невозможен; Skill/Desire/Trust ≠ Permission (18/18).
- **Proof** (Evidence Engine): Audit ≠ Evidence ≠ Acceptance; агент не принимает свою работу; каждый
  провал → RegressionFixture (24/24). Слои composятся: LifeOS continuity-claim принят Evidence Engine.
- **Product** (Money Forge + Cockpit): vanity ≠ acceptance; pilot gate 5→≥3×$199; Cockpit v0 читает
  РЕАЛЬНЫЙ universe-манифест (13 систем) + self-audit + evidence; сам authority не держит.

## Final Contradiction Matrix
| # | Противоречие | Стороны | Разрешение | Статус |
|---|---|---|---|---|
| C1 | «Мандатная песочница» vs runsc не запущен | DEPLOY.md vs среда | fail-closed внедрён (без песочницы = ОТКАЗ исполнять); runsc = VPS-шаг с готовым OCI-бандлом | **ACT (деплой)** |
| C2 | «Nautilus ADOPT» vs «не импортирован» | MODULE_MAP vs devil M5 | СНЯТО: реальный 1.202.0 BacktestEngine прогнан, риск-гейт врезан | ✅ закрыто |
| C3 | dev-доказательства vs «прод» | self-audit vs VPS | компоненты реальные (Binance testnet, Stripe HMAC, Postgres, Nautilus); остаток = деплой, не переписывание | принято, зафиксировано |
| C4 | manifest `truthStatus` vs наши доказательства | Universe Hub vs MAWorld | manifest: Inner Circle/Forge `contradicted`, ContinuityOS `halted` — но M3 доказал реальный verifier; Cockpit v1 должен ОБНОВЛЯТЬ manifest из Evidence Engine, не вручную | **тикет T4** |
| C5 | Letta-паттерн памяти vs Governed Memory | внешний референс vs наш канон | агент сам пишет только в ПРИВАТНУЮ память; промоция в истину — только governed (доказано 18/18 + 24/24) | ✅ канонизировано |
| C6 | «агент сказал готово» vs приёмка | старые пайплайны vs Evidence Engine | acceptance только через детерминированную верификацию; self-claim отвергается тестом | ✅ канонизировано |

## BUILD_FREEZE_V2 — ГЕЙТ ЗАКРЫТ (RETRACTED, 2026-07-15 после GPT DR-2 аудита)
> **СТАТУС: BLOCKED.** GPT-аудит дал verified-рефутации нескольких "CLOSED" (confused-deputy в M6,
> Evidence RCE/self-attest, at-most-once, payment-proof). См. `docs/19_GPT_AUDIT_RESPONSE.md`. Механизмы
> блокеров 1/2/3/7 починены и adversarially протестированы на модульном уровне (8/8, 9/9, 18/18), но
> системная интеграция не доказана, а блокеры 4/5/6 открыты. **Freeze не разрешён**, live-эффекты OFF,
> пока не закрыты: rewire m6/money_forge, торговые единицы, RLS-scoped-tx, CanonPromoter SoD, CI/lockfiles.

## (изначально предполагалось) BUILD_FREEZE_V2 — гейт
Вход разрешён: ядро всех пяти узлов существует и протестировано (Foundry/Spine/LifeOS/Evidence/Forge),
7/8 адверсариальных тезисов закрыто. **Freeze-объём:** контракты `CANONICAL_CONTRACTS_v1.md` + схемы
Evidence (Claim/Verification/Acceptance/Fixture) + LifeOS инварианты (25) + pilot-правило 5→3.
Изменения после freeze — только через ImprovementProposal + EvalRegistry + human approval.

## Первые тикеты (Codex handoff)
| T | Задача | Готовая база | Приёмка (Evidence Engine claim) |
|---|---|---|---|
| T1 | VPS: установить runsc, прогнать tier2_acceptance на gVisor | OCI-бандл + 16/16 тест | `code_tests_pass` на VPS, механизм=runsc |
| T2 | VPS: DBOS → managed Postgres, systemd-юниты | dbos-postgres-m8 stages | `workflow_recovered` fire_count=1 на проде |
| T3 | Testnet-ключи (не дамми) → `/order/test` 200 + SHADOW-режим | e2e_m2 9/9 | `commit_made` + testnet 200 в trade-evidence |
| T4 | Cockpit v1: manifest ← Evidence Engine (авто-`truthStatus`), панель Delegations/Holds/Costs | cockpit v0 + manifest | `file_created` manifest-diff + человек подтвердил |
| T5 | Langfuse self-host + OTel спаны из m6_e2e (trace_id ↔ claim_id) | вердикт docs/16 | cost-per-verified-outcome виден по одному прогону |
| T6 | Pilot wedge: ContinuityOS policy-and-evidence boundary — лендинг+онбординг 5 пилотов | M3 Stripe + pilot_gate | `product_success` только payment/renewal |
| T7 | LifeOS: подключить lifecycle к control-plane (Telegram статусы), hibernation по расписанию | apps/lifeos 18/18 | `continuity_preserved` после ночного цикла |

## После исторически предполагавшегося freeze
Trading Cell = отдельный **domain implementation track**. Историческое утверждение о готовности
testnet/live отозвано: ключи и решение владельца сами по себе не разрешают запуск. Новых широких исследований не запускаем; GPT DR-3 /
Gemini DR-4 при поступлении проходят через dialectic-adjudicator как evidence, не как новые основания.

Текущий override этого исторического passport: **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD**.
