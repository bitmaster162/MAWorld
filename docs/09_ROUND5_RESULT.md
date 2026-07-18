# Round 5 — Implementation Result (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Вход: новый отчёт «ContinuityOS Control Spine и Competitive Primitives Delta Study» (Gemini) + v1.3 (уже обработан). Изучил, проверил, внёс. Три новых прогона зелёные против реального софта.

## Что подтвердил отчёт (валидация прошлых решений)
- **MCP 2025-11-25 — последняя финализированная** ревизия; **2026-07-28 не найдена** в официальном repo → UNRESOLVED/HYPOTHESIS. Это ровно моя коррекция раунда 3. ✓
- Tier2 gVisor, thin custom harness, «authority не из agent-SDK» — совпадает с уже принятым.
- MCP `tasks` (experimental, «call-now fetch-later», polling endpoints tasks/get|result) — подтверждён веб-поиском.

## A. MCP AsyncTaskRegistry + Capability tokens — `control_spine_v3` 12/12 PASS
Реализовал главные новые концепты отчёта (05_BACKLOG + secrets acceptance):

**AsyncTaskRegistry** (`async_task_registry.py`) — бан orphan-polling MCP-задач: задача при создании привязана к `(action_spec_id, delegation_grant_id, trace_id, task_external_id)`; любой poll/result с несовпадающей привязкой → DENY. Закрывает «async-task state confusion»: deferred result после pause/resume не может переполучить authority.

**Signed DelegationGrant + one-time CapabilityToken** (`capability.py`) — authority вынесена из transport-session в подписанный короткоживущий grant; токен одноразовый и привязан к одному `action_spec_id`. Доказано: expired grant → reject; token reuse → reject; cross-project → block; **capability enlargement невозможен** (token capabilities ⊆ grant). Это acceptance-тест отчёта §06 (secrets/identity).

## B. KF Parser Router (build-seq E+F) — `kf-parser` PASSED (Rust)
```
00_MASTER.md   NativeMarkdown  blocks=4  [1-1 heading1][2-2 paragraph][4-4 heading2][5-6 paragraph]
notes.txt      NativeText      blocks=3
report.pdf     SandboxRequired blocks=0  (НЕ парсится in-process)
KF event chain (E): ok=true events=9
PARSER ROUTER PASSED
```
- **F (parser router, closure §2.7):** format-aware маршрутизация — детерминированные native-парсеры для MD/TXT/source с **точными line-локаторами** (для exact_source_excerpt у Claim); rich/binary (pdf/docx) → **SandboxRequired**, не парсятся в процессе (Tier2 gVisor в проде, sandbox-broker владеет исполнением).
- **E (intake → KF events):** identity-события `raw_blob.observed` / `occurrence.created` / `extraction.created` идут в hash-chained KF-леджер (тот же паттерн, что kf-intake). Цепочка верифицируется.

## Расхождения с прошлым синтезом — как решено
| Тема | Новый отчёт | Мой статус | Решение |
|---|---|---|---|
| Workflow runtime | **Temporal-first** (DBOS = «ADAPT-second, lower-confidence») | **DBOS проверен** спайком (crash-recovery без дублей) | Оставляю DBOS для рабочего спайка (доказан, легче для одного владельца — это и есть revisit-триггер отчёта); **Temporal — задокументированная migration-цель** (ADR-R2-05). Отчёт усиливает Temporal как target, не отменяет DBOS-MVP. |
| Observability | **Phoenix** (self-host line-verified; Langfuse не line-verified в этом проходе) | Langfuse (self-host был verified в D6) | Оба валидны и self-hostable. Фиксирую: **TraceContext — свой стабильный schema**, маппинг в OTel; бэкенд (Phoenix|Langfuse) — заменяемая деталь, выбор после первых 20-30 runs. |
| MCP 2026-07-28 | UNRESOLVED | уже исправлено (RC, не финал) | Согласовано. protocol_revision хранить как **данные, не код-константы** (checklist #7). |

## Cost bands (из отчёта, INFERENCE)
Light $120-220 / Medium $550-900 / Heavy $2.2k-3.5k в месяц (5 ролей, surrogate-mix OpenAI+Anthropic, official rates; без sandbox/OpenRouter/vector/GPU). Не финансовый прогноз — для приоритизации.

## Запуск
```
cd spikes/control_spine_v3 && python3 test_authority.py          # 12/12
cd apps/knowledge-foundry/kf-parser && cargo run -- demo          # PARSER ROUTER PASSED
```

## Остаток build-sequence
Сделано: A(intake)→B(migration)→C(sqlx MetaStore)→D(RLS)→E(intake→KF events)→F(parser router). Дальше: G (claim-extraction proposal worker, Python, только PROPOSED), H (human canonicalization), I (ContinuityOS controlled action path — соединить kf-parser extraction → gate). Плюс из отчёта: `MCPAuthorizationResolver` (кэш issuer/scopes/audience), вынести egress-broker на gVisor, `git_commit_with_hold_and_recovery` спайк (DelegationGrant на commit, push=HOLD) — capability-примитивы уже готовы (A).
