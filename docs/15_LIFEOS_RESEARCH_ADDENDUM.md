# LifeOS — независимое исследование (пока GPT DR работает), 2026-07-15

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Собственный проход по `FINAL_GPT_DEEP_RESEARCH_PROMPT_LIFEOS_V3.md`, чтобы (а) сверить будущий ответ GPT, (б) показать, что бОльшая часть LifeOS-инвариантов уже покрыта нашими доказанными примитивами, (в) выделить действительно новое.

## Что такое LifeOS в нашей архитектуре
LifeOS = **приватный слой агента**: идентичность, приватная/эпизодическая/рабочая/реляционная память, отношения, навыки, жизненный цикл, bounded evolution. Инварианты §0x05 (25 штук) прямо разделяют его с Control Spine и Knowledge Foundry: `LifeOS != Control Spine`, `LifeOS != Knowledge Foundry`, `Private Memory != Project Canon`, `Skill != Permission`, `Relationship Trust != CapabilityToken`, `Desire != Permission`.

## LifeOS → наши доказанные примитивы (анти-задвоение)
| LifeOS требует | У нас уже доказано | Статус |
|---|---|---|
| CTHA proposal-only (нет tool/canon/ledger/secret creds) | control_spine_v4: CTHA boundary, bypass matrix fail-closed | ✅ доказано |
| Proposal Bridge (strip authority, schema, trace-bind) | control_spine_v4: 9/9 negative | ✅ доказано |
| Приватная память ≠ canon; промоция управляемая | Governed Memory (memory-governor) PROPOSED→VALIDATED→APPROVED→ACTIVE; CanonPromoter 10/10 | ✅ доказано |
| Skill ≠ Permission; Desire ≠ Permission; Relationship Trust ≠ CapabilityToken | capability tokens (control_spine_v3): authority только от подписанного grant, не от навыка/желания/репутации | ✅ доказано |
| Bounded evolution (не бесконтрольная само-модификация) | self-improvement loop (docs/04): SENSE→PROPOSE→EVALUATE→GATE→CANARY, FORBIDDEN-классы, kill-switch fail-closed | ✅ спроектировано |
| Evolution proposals через gate | ImprovementProposal + EvalRegistry (regression→BLOCK) | ✅ доказано (9/9) |
| Lifecycle state machine (валидные переходы) | паттерн AsyncTaskRegistry (11/11): нельзя перескочить/переоткрыть terminal | ✅ паттерн есть |
| Hibernation/restore манифесты, Continuity Reports | checkpoint/branch + ExternalEffectRegistry (reconcile) | ✅ примитивы есть |
| `Social Consensus != Verified Truth` | Money Forge gate + dialectic (verified-only) | ✅ доказано |
| `Self-Preservation != Right to Resist Human Authority` | всё под ContinuityOS gate + human approval на canon | ✅ инвариант держится |

**Вывод:** ~10 из 25 инвариантов LifeOS уже реализованы и протестированы в нашем стеке. LifeOS не требует нового authority-слоя — он садится ПОВЕРХ доказанного spine как приватный слой агента.

## Что действительно НОВОЕ (нет у нас, ждём GPT + строим)
1. **Agent Lifecycle state machine** (SEED→BOOTSTRAPPING→ACTIVE→ENGAGED→REFLECTING→LEARNING→RESTING→HIBERNATING→RESTORING + DEGRADED/QUARANTINED/FORKING/MERGING/RETIRING/ARCHIVED/TERMINATED) с per-state политиками (model-call policy, memory behavior, Safe Mode).
2. **Hibernation с нулём токенов** — `Agent Existence != Continuous Token Consumption`: агент функционально персистентен без активных model-calls (состояние в БД, не в контексте). Это отличает от Letta, где агент «runs inside» рантайма.
3. **Temporal Self** (Historian / Present Executive / Future Simulator / Meta Observer) — 4 темпоральные роли.
4. **Fork/Merge идентичности** (`Fork != Reproduction`, `Copy != Proven Same Entity`) — генеалогия агентов.
5. **Memory Fabric 5 слоёв** формализованный (Core/Episodic/Working/Procedural-Skill/Relational) — у нас есть Governed Memory, но не 5-слойная приватная фабрика агента.

## Внешняя сверка (Letta/MemGPT 2026)
Letta (ex-MemGPT) = референс persistent-agent memory: Core/Recall/Archival, идентичность переживает рестарты, агент сам управляет памятью (RAM↔disk). **Ключевое расхождение с LifeOS/MAWorld:** у Letta агент САМ пишет в archival; у нас — `Private Memory != Project Canon` + промоция в авторитетное состояние ТОЛЬКО через governance (memory-governor + CanonPromoter). То есть Letta-паттерн памяти берём, но self-promotion в истину запрещён (наша коррекция Governed Memory Paging из раунда 1 — уже доказана).

## Риск-флаги для ответа GPT (что проверить)
- LifeOS lifecycle не должен вводить свой authority — переходы состояний (особенно FORKING/MERGING/evolution) обязаны идти через ContinuityOS gate + human approval, иначе `Evolution != Uncontrolled Self-Modification` нарушается.
- Hibernation-restore: восстановление состояния = replay из durable store, НЕ из model-context; External effects при restore не должны пере-стреливать (наш ExternalEffectRegistry).
- Relational trust / reputation: не должны маппиться в CapabilityToken (инвариант #25) — доказать структурно, как CTHA boundary.
- Fork: forked-агент получает НОВЫЙ WorkloadIdentity + новые capability-грани, не наследует авторитет родителя (как HandoffEnvelope не переносит authority).

## Порядок внедрения (когда придёт ответ GPT)
LifeOS садится в `apps/lifeos/` поверх spine: (1) Agent Identity Kernel + lifecycle state machine (наш паттерн), (2) Memory Fabric на memory-governor, (3) CTHA как proposer (control_spine_v4), (4) evolution через self-improvement loop + EvalRegistry, (5) fork/merge через capability + genealogy audit. Ничего из authority не дублируем.

## Источники
- Letta/MemGPT 2026: https://vectorize.io/articles/mem0-vs-letta · https://xelionlabs.com/blog/persistent-ai-agents-guide · https://mem0.ai/blog/state-of-ai-agent-memory-2026
- Наши доказанные: docs/04 (self-improvement), control_spine_v3/v4 (capability/CTHA/bridge), services/canon-promoter, services/memory-governor.
