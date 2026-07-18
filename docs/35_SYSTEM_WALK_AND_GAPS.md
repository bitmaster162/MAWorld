# System-by-system прогон + чего не хватает + следующий ход (2026-07-16)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


## Что не хватало (честно) и что закрыл этим раундом
Главный пробел с самого первого GPT-аудита: **модули проходят изолированно, но не было единого e2e-
прогона через все системы**. Плюс research 2026 показал ещё две дыры: **fault-injection/chaos на
governance-путях** и **error-budget → автономия**. Всё три закрыто.

### 1. System walk — единый spine-проход (L3 integration)
`libs/maworld_core/system_walk.py` (12/12). Один intent течёт через ВСЕ 10 core-систем в композиции:
`global_cycle → input_guard → policy_engine → risk → trading_safety → action_authority → control_plane →
effect_registry → evidence_engine → article12`. Прогон:
- **healthy intent → ACCEPTED**, эconst проходит все системы, эффект **ровно 1 раз**, proposal-only.
- **все deny-пути → SAFE_HALT до эффекта** (0 fires): injection→input_guard, risk 2.5%→policy/risk,
  below-min qty→trading_safety, no owner confirm→action_authority.
- Каждая система даёт per-system verdict (реальная таблица «система за системой»).

### 2. Chaos / fault-injection (ReliabilityBench-стиль, 2026)
Инъекции в границах: **crash mid-effect → безопасная деградация, без двойного эффекта** (registry
держит/reconcile); **chaos на input_guard → SAFE_HALT (fail-closed)**. Governance-пути проверены под
сбоем — ровно то, что research называет главным для агентного chaos.

### 3. Error budget → автономия (SRE-for-agents)
`libs/maworld_core/error_budget.py`: чистый 30д → AUTONOMOUS; горение → ALERT→THROTTLE→FREEZE→
**CIRCUIT_BREAK** (завязано на `agent_containment` global-kill/terminate). Reliability = не только
uptime, а качество решений + safe-halt + знать когда остановиться.

## Полный статус: 35/35 suites, 336 adversarial-проверок
Единым `tests/run_all.py` (тот же, что в CI). Плюс system-walk доказывает КОМПОЗИЦИЮ, не только юниты.

## Чего ещё не хватает (остаток, честно — это деплой/прод, не переписывание)
1. Прогон на **реальном боксе** (не песочница): нужен ресурс (docs/33 — old144 или чистый VPS).
2. **Cedar symcc + cvc5** (реальное SMT-доказательство инвариантов политик) — апгрейд Z3-трека.
3. **SPIRE на VPS** (эфемерные X.509 SVID вместо статических ключей) — конфиги готовы (docs/34→27).
4. **Rust-консолидация** (risk-service/kf-store вне единого libs).
5. **Live-ключи/эффекты** — за поштучной отмашкой; live OFF.

## Следующий сильный ход
**Собрать всё в консолидированный ревью-пакет под Codex Sol 5.6 Ultra** (как ты и планировал: GPT o1 →
Codex → деплой). Пакет = единый `libs/maworld_core` (single source) + `tests/` (336 проверок, 35 сьютов
+ system-walk) + docs 1–35 + два пройденных раунда независимого Challenger'а (GPT+Gemini DR, все
рефутации закрыты). Это самопроверяемый артефакт: любой ревьюер запускает `tests/run_all.py` и получает
35/35 за одну команду. После Codex-прохода — ресурс под деплой (old144/чистый VPS) и docs/27 runbook.

## Источники (research)
- Chaos/e2e: https://cordum.io/blog/ai-agent-chaos-engineering-playbook · https://arxiv.org/pdf/2601.06112 (ReliabilityBench) · https://atlan.com/know/how-to-test-ai-agent-harness/
- SRE/error-budget: https://zylos.ai/research/2026-03-22-sre-ai-agent-systems-observability-incident-response/ · https://www.digitalapplied.com/blog/agentic-workflow-incident-response-playbook-2026
