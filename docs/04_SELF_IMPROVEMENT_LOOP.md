# Контур самоулучшения MAWorld v1.0

Требование: коробка должна уметь улучшать сама себя с помощью агентов — не нарушая ни один инвариант (LLM не владеет состоянием; side effects через ContinuityOS; человек утверждает канон).

## Принцип

**Агенты предлагают. Детерминированные evals решают. ContinuityOS пропускает. Человек утверждает канон. Откат всегда возможен.**

Самоулучшение — это не "агент правит свой код в проде". Это эволюционный поиск (DGM/AlphaEvolve/GEPA-паттерн) поверх уже принятых примитивов:

| Механизм контура | Реализуется через (уже есть в архитектуре) |
|---|---|
| Наблюдение за собой | TraceBridge → Langfuse; Knowledge Foundry runtime evidence; ContradictionRecord |
| Фитнес-функция | EvalRegistry: golden sets, регрессионные фикстуры, adjudication-тесты; для трейдинга — бэктест/Alpha Decay |
| Вариация | Improvement Proposer агенты (GEPA-стиль рефлексии над трейсами провалов) |
| Изоляция эксперимента | Workflow Branching (fork ветки), Sandbox Tier1-2, SHADOW-режим PromotionRouter |
| Отбор | Детерминированный eval-gate: новый кандидат обязан побить текущего на golden set без регрессий |
| Внедрение | Канареечное: раскатка на N% задач; авто-откат по метрикам |
| Фиксация знания | CanonicalDecision в Knowledge Foundry + Governed Memory promotion (learnings → правила) |
| Архив вариантов | Улучшения не перезаписывают друг друга — DGM-стиль дерево в Branch Ledger; проигравшие ветки остаются для будущего скрещивания |

## Цикл (Improvement Loop)

```
[1] SENSE      Langfuse traces + EvalRegistry провалы + ContradictionRecords + бэклог владельца
[2] PROPOSE    Improvement Proposer (агент) формирует ImprovementProposal
               (diff промпта / новый skill / патч модуля / изменение конфига)
[3] BUILD      Кандидат собирается в Sandbox (Tier1-2), из артефактов, не из чата
[4] EVALUATE   EvalRegistry: golden set + регрессии + security-тесты + (для трейдинга) walk-forward бэктест
               Провал → архив ветки + learnings. Успех → [5]
[5] GATE       ContinuityOS preflight: класс риска цели определяет маршрут
[6] CANARY     SHADOW/CANARY внедрение (ветка, % трафика, лимиты)
[7] PROMOTE    Метрики держатся N прогонов → CanonicalDecision, ветка → PROMOTED
   / ROLLBACK  Деградация → мгновенный откат на родительскую ветку, learnings в Foundry
```

## Матрица целей самоулучшения (риск → gate)

| Цель | Риск | Механизм | Gate |
|---|---|---|---|
| Промпты ролей (orchestrator/challenger/...) | Низкий | GEPA-стиль рефлексивная эволюция по трейсам | eval-gate автоматом; человек — batch-ревью еженедельно |
| Skills / playbooks агентов | Низкий-средний | self-improving skills: reflection hook → learnings → промоция правил | eval-gate + Governed Memory lifecycle (PROPOSED→...→ACTIVE) |
| Код модулей (сервисы, адаптеры) | Высокий | DGM-стиль: патч в песочнице, полный тест-сьют + security-чеки + SBOM | eval + человек одобряет merge; деплой через обычный CI |
| Торговые стратегии | Высокий | стандартная лестница RESEARCH→...→CANARY (это уже самоулучшение) | RiskService + человек на PAPER→SHADOW и CANARY→LIVE |
| Конфиги маршрутизации моделей / бюджеты | Средний | BudgetEnforcer предлагает по статистике затрат | человек |
| Политики ContinuityOS, риск-лимиты, конституция агентов | **Запрещено агентам** | только предложение в бэклог | **только человек, криптоподпись CanonicalDecision** |
| Сам Improvement Loop (его промпты/evals) | Высокий | разрешено только через отдельную ветку + человек | человек, всегда |

## Жёсткие инварианты (нарушение = стоп контура)

1. Improvement Proposer **не имеет** write-доступа никуда, кроме создания ImprovementProposal и веток. Никаких прямых правок прод-промптов/кода/памяти.
2. Eval-gate детерминирован и версионируется; агент не может править golden set и судейские промпты в том же proposal, который по ним оценивается (анти-Гудхарт: разделение изменяемого и измеряющего).
3. Каждый promoted candidate несёт `policy_version/prompt_version/code_version/eval_run_id` — полный provenance в Knowledge Foundry.
4. Kill-switch контура: атомарный флаг `improvement_loop_enabled`; человек выключает одним действием; выключение fail-closed.
5. Бюджет контура — отдельный BudgetPolicy (P4/P5 приоритет): самоулучшение никогда не отъедает резерв P0/P1.
6. Rollback-путь обязан существовать до внедрения (reversibility class в Effect Registry; для IRREVERSIBLE целей самоулучшение запрещено).

## Контракт

`contracts/improvement/ImprovementProposal.yaml` — цель, тип (PROMPT/SKILL/CODE/CONFIG), diff-артефакт, гипотеза, ожидаемая метрика, eval-план, риск-класс, ветка, статусы: `PROPOSED → BUILT → EVALUATED → GATED → CANARY → PROMOTED | ROLLED_BACK | ARCHIVED`.

## Порядок включения (после MVP control spine)

1. Фаза A (пассивная): только SENSE — Langfuse + EvalRegistry собирают базовые метрики 2 недели. Без агентов.
2. Фаза B (промпты): GEPA-контур на одной роли (challenger) с ручным утверждением каждого промоушена.
3. Фаза C (skills): reflection hooks + learnings через Governed Memory.
4. Фаза D (код): DGM-стиль патчи на несущественных модулях (benchmarks, коннекторы) с полным CI-гейтом.
5. Фаза E: автопромоция низкорисковых улучшений (человек — только batch-ревью и kill-switch).

Источники: Darwin Gödel Machine (arXiv 2505.22954), GEPA (gepa-ai/gepa, ICLR 2026), AlphaEvolve, Agent Skills self-improvement pattern, MAS-PromptBench (2606.23664). Детали — `03_RESEARCH_ADDENDUM_R2.md`.
