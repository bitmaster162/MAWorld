# Конкуренты MAWorld + что забираем (2026-07-15, веб-ресёрч)

## Категории и игроки
| Категория | Игроки | Чем сильны |
|---|---|---|
| **Agent governance / control-plane** | **Arthur** (для агентов с дня 1: discover→enforce→evaluate→evidence), **Fiddler** («AI Control Plane for Enterprise Agents», ре-позиция янв-2026), **PlainID** (PBAC для агентов, 2 крупнейших банка США), **TrueFoundry** | full-lifecycle governance, 18+ runtime-guardrails (PII, prompt-injection, jailbreak, tool-call), centralized policy |
| **Durable execution** | **Temporal** ($300M Series D, $5B, OpenAI/Block в проде, 9.1T экзекуций), **DBOS** (Postgres-is-enough, Databricks Lakebase), **Restate**, **Inngest** ($21M A), Hatchet | resume-after-crash примитив, exactly-once |
| **Agent identity (NHI)** | **SPIFFE/SPIRE** (ephemeral X.509 SVID, без long-lived секретов), AIP/aiAuthZ (arxiv-протоколы делегирования) | ворклоад-идентичность, NHI 17:1 к людям |
| **Policy engines** | **OPA** (CNCF graduated, Rego, sub-ms), **Cedar** (AWS, SMT-solver — provably correct, 42-60× быстрее Rego) | policy-as-code, fine-grained runtime-решение |
| **Threat framework** | **OWASP Top 10 for Agentic Apps 2026** (dec-2025, NIST/MS/NVIDIA), Lakera/Promptfoo/DeepTeam (red-team) | prompt-injection, tool-misuse, memory-poisoning |

## Рыночный попутный ветер
**EU AI Act — полное принуждение с 2 авг 2026:** требует **lineage-backed auditability + human oversight**
для high-risk AI. Плюс «82% предприятий уже имеют агентов, о которых security не знает». Это **ровно наш
wedge** — детерминированный контроль + verified evidence + human-in-loop. Есть даже arxiv «A Deterministic
Control Plane for LLM Coding Agents» = наша категория, валидирована академически.

## Что ЗАБИРАЕМ (и куда в MAWorld)
1. **Arthur full-lifecycle (discover→enforce→evaluate→evidence).** У нас есть enforce (action_authority/gate),
   evaluate (EvalRegistry/improvement-engine), evidence (Evidence Engine). **ПРОБЕЛ: discover** — реестр/
   обнаружение агентов. → строим `agent_registry` (discover-стадия).
2. **Cedar/OPA policy-as-code.** Наш capability/gate — per-action; добавляем слой **policy-engine**
   (детерминированные allow/deny с условиями), Cedar-стиль (провабельно-корректный — совпадает с нашим
   «deterministic + verified»). → строим `policy_engine`.
3. **SPIFFE/NHI ephemeral identity.** Наши capability — уже подписанные короткоживущие токены; выравниваем
   к SVID-модели: каждый агент = NHI с ephemeral workload identity, без long-lived секретов. → расширяем
   `capability` до workload-identity (ephemeral, expiry-bound — уже есть expiry).
4. **OWASP agentic defenses.** tool-misuse → уже action_authority (hash-bound); human-approval для
   goal-changing → control_plane; PII → DLP. **ПРОБЕЛЫ: prompt-injection guard + memory-poisoning defense
   (trust-scored retrieval + provenance).** → строим `input_guard` + `memory_provenance`.
5. **DBOS «Postgres-is-enough».** Наш выбор DBOS валидирован трендом; Temporal как escalation (у нас уже
   DurableRuntimeAdapter). Забирать нечего — мы уже там.

## Наши дифференциаторы (чего у них нет)
- **Sovereign single-owner** (не enterprise-SaaS) — ниша: один владелец, весь стек его.
- **Evidence Engine: «агент не принимает свою работу»** (engine-signed acceptance) — уникально; у
  конкурентов post-hoc monitoring, а не proof-of-correctness.
- **Deterministic spine + verified refutation** (dialectic) — не «наблюдаем», а «доказываем».
- **Фрактал/global-cycle мировоззрение** зашито в код.
- **Money Forge**: продукт «успешен» только по подписанному payment-proving событию (не vanity).

## Вывод
Категория подтверждена и растёт под EU AI Act. Мы уже сильны в enforce/evaluate/evidence/durable. Забираем
5 вещей: **policy-as-code (Cedar-стиль), discover-реестр, SPIFFE-выравнивание идентичности, prompt-injection
guard, memory-poisoning defense.** Первые самые ценные — строю ниже.
