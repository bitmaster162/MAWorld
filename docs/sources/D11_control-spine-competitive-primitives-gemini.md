ContinuityOS Control Spine и Competitive Primitives Delta Study
===============================================================

Evidence Audit
--------------

**Artifact: 01\_EVIDENCE\_AUDIT**

  Claim                                                                                                                                                                                              Source system                Official evidence                                                                                                              Verified status   Correction                                                                                                                                                    Confidence
  -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- ---------------------------- ------------------------------------------------------------------------------------------------------------------------------ ----------------- ------------------------------------------------------------------------------------------------------------------------------------------------------------- ------------
  Temporal сохраняет durable `Event History` для каждого `Workflow Execution`, а `reset`/`show` доступны как официальные операции/CLI-поверхности.                                                   Temporal                     [\[1\]](https://docs.temporal.io/workflow-execution/event)                                                                     VERIFIED FACT     Для `immutable branching` этого недостаточно: `Branch Ledger` и `External Effect Registry` все равно нужны поверх Temporal.                                   0.91
  Temporal Server распространяется под MIT license.                                                                                                                                                  Temporal                     [\[2\]](https://raw.githubusercontent.com/temporalio/temporal/master/LICENSE)                                                  VERIFIED FACT     Лицензия не снимает ops‑cost; это отдельный риск.                                                                                                             0.98
  Restate документирует durable invocation model и `restart invocation as new`, где можно копировать часть progress из исходного journal.                                                            Restate                      [\[3\]](https://docs.restate.dev/llms.txt)                                                                                     VERIFIED FACT     Это близко к fork/restart, но не эквивалент вашему `immutable branch ledger` контракту.                                                                       0.83
  LangGraph документирует `Persistence`, `checkpoints` и `time travel`.                                                                                                                              LangGraph                    [\[4\]](https://docs.langchain.com/oss/python/langgraph/persistence)                                                           VERIFIED FACT     Это полезно для Intelligence plane, но не доказывает достаточность как Control-plane durable substrate.                                                       0.89
  NATS JetStream документирует deduplication через `Nats-Msg-Id` и "exactly once" публикацию/consumption primitives.                                                                                 NATS JetStream               [\[5\]](https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive)                                           VERIFIED FACT     Эти primitives не дают готовых `branch/fork/replay-without-side-effects` semantics.                                                                           0.90
  OpenAI Agents SDK различает `handoffs` и `agents as tools`: при `handoff` новый агент "takes over", при `agent-as-tool` центральный агент сохраняет контроль.                                      OpenAI Agents SDK            [\[6\]](https://openai.github.io/openai-agents-python/tools/)                                                                  VERIFIED FACT     Для ContinuityOS authority нельзя брать из native handoff semantics; authority должен решаться отдельно.                                                      0.94
  Claude Agent SDK работает как library "in your own process", имеет hooks, checkpointing/sessions и built-in tool execution.                                                                        Anthropic Claude Agent SDK   [\[7\]](https://docs.anthropic.com/en/docs/claude-code/sdk)                                                                    VERIFIED FACT     Это сильный execution harness, но не отдельный authority plane.                                                                                               0.92
  Google ADK поддерживает automatic delegation через `sub_agents`; root agent может автоматически transfer control к sub-agent, а collaborative modes описывают возврат контроля.                    Google ADK                   [\[8\]](https://adk.dev/tutorials/agent-team/)                                                                                 VERIFIED FACT     Это подтверждает `agent-transfer` semantics, но не подтверждает signed delegation grants или capability tokens.                                               0.95
  Microsoft Agent Framework документирует graph-based workflows с `executors`, `edges`, `checkpointing`, а также orchestration patterns `sequential`, `concurrent`, `hand-off`.                      Microsoft Agent Framework    [\[9\]](https://github.com/microsoft/agent-framework)                                                                          VERIFIED FACT     Это workflow transitions, а не policy-grade delegated authority.                                                                                              0.93
  В доступном официальном MCP repo/документации последняя опубликованная revision, которую удалось line‑verify в этом проходе, --- `2025-11-25`; `2026-07-28` в доступной структуре не обнаружена.   MCP                          [\[10\]](https://github.com/modelcontextprotocol/specification)                                                                UNRESOLVED        Любые утверждения о revision `2026-07-28` ниже помечены как HYPOTHESIS или forward-compatible delta, если они не подтверждены этой опубликованной revision.   0.86
  MCP revision `2025-11-25` официально добавляет OIDC discovery support, incremental scope consent через `WWW-Authenticate`, OAuth Client ID metadata documents и experimental `tasks`.              MCP                          [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)   VERIFIED FACT     Это уже требует изменений в `gate_hook.py` и `ActionSpec`, даже без 2026 revision.                                                                            0.96
  Официальная страница OpenTelemetry для `Generative AI semantic conventions` существует, но retrieved lines в этом проходе не подтвердили стабильность/статус conventions.                          OpenTelemetry                [\[12\]](https://opentelemetry.io/docs/specs/semconv/gen-ai/)                                                                  UNRESOLVED        Для MVP надо считать `GenAI semconv` evolving surface и version-pin instrumentation.                                                                          0.71
  Arize Phoenix имеет официальный self-hosting path c Docker и Kubernetes deployment options.                                                                                                        Arize Phoenix                [\[13\]](https://arize.com/docs/phoenix/self-hosting)                                                                          VERIFIED FACT     Это делает Phoenix пригодным для single-owner observability/evals MVP.                                                                                        0.88
  OpenAI pricing page публикует rates для input, cached input, output; `Batch API` не имеет отдельного surcharge --- токены биллятся по model rates.                                                 OpenAI API                   [\[14\]](https://platform.openai.com/docs/pricing)                                                                             VERIFIED FACT     Для cost modeling можно считать `batch` коэффициент маршрутизации, а не отдельный product fee.                                                                0.92
  Anthropic pricing page публикует `input`, `output`, `prompt caching write/read` rates.                                                                                                             Anthropic API                [\[15\]](https://www.anthropic.com/pricing)                                                                                    VERIFIED FACT     Это позволяет явным образом моделировать cache economics для supervisor роли.                                                                                 0.95
  Firecracker использует Linux KVM, требует hardware virtualization support и ориентирован на Linux host/guest.                                                                                      Firecracker                  [\[16\]](https://firecracker-microvm.github.io/)                                                                               VERIFIED FACT     На Windows/WSL это не production-safe default без отдельного Linux/KVM feasibility proof.                                                                     0.97
  gVisor --- userspace `application kernel` для container sandboxing.                                                                                                                                gVisor                       [\[17\]](https://gvisor.dev/docs/)                                                                                             VERIFIED FACT     Это валидный Tier2 candidate для Linux VPS.                                                                                                                   0.94
  E2B публично тарифицирует sandboxes по second of running sandbox, сверх plan fee.                                                                                                                  E2B                          [\[18\]](https://www.e2b.dev/pricing)                                                                                          VERIFIED FACT     В этом проходе не удалось line‑extract публичную точную per-second breakdown, поэтому `cost per 1000 executions` остается partially unresolved.               0.83
  Modal публикует per-second CPU pricing и per-second GPU pricing, включая A100/H100.                                                                                                                Modal                        [\[19\]](https://modal.com/pricing)                                                                                            VERIFIED FACT     Это делает Modal хорошим Tier4 candidate для GPU-only workloads, но не заменяет Tier2/Tier3.                                                                  0.94
  Daytona docs подтверждают hosted API surface "create a sandbox and run code", но retrieved docs не доказали конкретный isolation mechanism уровня gVisor/KVM/microVM.                              Daytona                      [\[20\]](https://www.daytona.io/docs)                                                                                          VERIFIED FACT     Daytona следует считать managed sandbox API, а не автоматически доказанную isolation primitive.                                                               0.80

Executive Summary and Verdicts
------------------------------

**Artifact: 02\_VERDICTS**

Исследование сводится к одному практическому выводу: для первого
production-worthy vertical slice ContinuityOS не нужен новый grand
runtime. Нужен узкий, проверяемый control spine:
`Temporal self-hosted + Postgres side registries`, `thin custom harness`
поверх provider APIs, `MCP-aware preflight`, `OTel + Phoenix`,
`Tier2 gVisor` и строго вынесенные `delegation/policy/effect` контракты.
Handoff и tool ecosystems уже зрелые, но authority boundary у них по
умолчанию не совпадает с вашими требованиями; именно поэтому право на
side effect должно оставаться в ContinuityOS, а не в agent SDK.
[\[21\]](https://docs.temporal.io/workflow-execution/event)

    ✅ Temporal as durable substrate
    ✅ thin custom harness + provider adapters
    ✅ OTel + Phoenix self-hosted
    ✅ Tier2 gVisor on Linux VPS
    ⏳ MCP 2026-07-28 exact text
    ⏳ Firecracker local feasibility on actual VPS/KVM
    ⏳ Vault/Infisical procurement pass
    ❌ LangGraph as Control-plane durable runtime
    ❌ custom NATS+Postgres runtime for MVP

  Task                        Verdict                                     Confidence   Revisit trigger
  --------------------------- ------------------------------------------- ------------ ------------------------------------------------------------------------------------------
  Workflow runtime choice     ADAPT                                       0.84         если Temporal ops‑burden окажется несоразмерным для single-owner deployment
  Agent harness               ADOPT THIN CUSTOM + ADAPT SDKs              0.87         если появится framework с first-class signed delegation/capability semantics
  MCP spec revision impact    ADAPT NOW, HOLD 2026‑specific assumptions   0.73         когда официальная revision `2026-07-28` станет line-verifiable
  Observability & evals       ADOPT                                       0.79         если Phoenix coverage окажется недостаточной для regression governance
  Cost engineering            ADAPT                                       0.62         когда будут зафиксированы реальные role-level token histograms за 2--4 недели
  Secrets & identity          NARROW MVP                                  0.58         когда появится второй operator, вторая среда prod, либо remote workers с secrets fan-out
  Sandbox provider decision   ADOPT Tier2 / HOLD Tier3 / ADOPT Tier4      0.74         после проверки KVM availability и реальных per-execution cost traces

**Workflow runtime choice**

**Decision:** `ADAPT` --- принять `Temporal self-hosted` как durable
execution substrate для Control plane, но не как готовую реализацию
`Branch Ledger / Checkpoint Store / External Effect Registry`. Эти
контракты остаются вашими собственными persistence components поверх
Postgres. `LangGraph + Postgres` не брать как primary control runtime;
`custom NATS JetStream + Postgres` отвергнуть для MVP; `Restate`
оставить как `HOLD`; `DBOS` оставить как lower-confidence
`ADAPT-second`.
[\[22\]](https://docs.temporal.io/workflow-execution/event)

**Evidence:** Temporal уже имеет durable event histories, replay model и
reset surface; это самый близкий production substrate под ваши
recovery/failure tests. Restate официально демонстрирует safe "restart
as new" c journal progress copy, что полезно, но все равно не заменяет
ваш immutable branch model. LangGraph дает checkpoints/time travel,
однако он лучше работает как orchestration/runtime inside agent
workflows, чем как отдельный owner для authoritative control state.
JetStream дает dedupe и limited "exactly once" primitives, но не дает
готовых semantics для fork/replay with side-effect suppression.
[\[22\]](https://docs.temporal.io/workflow-execution/event)

**Assumptions:** prod работает на Linux VPS; одна дополнительная
always-on control service допустима; replay side effects по-прежнему
запрещен и будет блокироваться вашим `External Effect Registry`.

**Alternatives:** `DBOS` выглядит концептуально близким single-DB path
для single-owner estate, но в этом проходе я не line-verified
first-class fit именно к вашим
`immutable branching / non-replay effects` контрактам, поэтому даю ему
только secondary status. `Restate` интересен, если важен service-native
durable call model и меньше orchestration surface.

**Risks:** Temporal приносит ops footprint и дисциплину deterministic
workflow code. Branching и effect ledger придется строить
самостоятельно, а не "включить флагом".

**Confidence:** 0.84.

**Acceptance Test:** запустить workflow "Telegram → approval → git
commit", убить semantic orchestrator во время tool phase, поднять worker
заново, восстановить state без повторного внешнего side effect, получить
тот же final artifact и immutable audit trace.

**Revisit Trigger:** если в течение 30 дней single-owner ops burden по
Temporal превышает \~1 инженерный день в месяц, либо glue-code под
branching/effect registry станет толще, чем ожидалось, нужно повторно
сравнить DBOS и Restate.

**Candidate matrix for task 1**

  Candidate                          Fit to contracts                                                                                                                                                              Ops burden    Estate fit                                              Verdict
  ---------------------------------- ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- ------------- ------------------------------------------------------- ---------------------------
  Temporal self-hosted               High for history/replay, medium for branching because custom layer still required. [\[1\]](https://docs.temporal.io/workflow-execution/event)                                 Medium        Good on Linux VPS, acceptable from WSL as dev target.   ADAPT
  DBOS                               Promising Postgres-centric path, but branch/effect fit not fully verified in this pass.                                                                                       Low--medium   Good hypothesis for estate.                             ADAPT-SECOND
  Restate                            Good durable invocation semantics; branching still custom. [\[3\]](https://docs.restate.dev/llms.txt)                                                                         Medium        Good on Linux VPS.                                      HOLD
  LangGraph + Postgres               Strong for harness persistence/time travel; wrong ownership boundary for authoritative control state. [\[23\]](https://docs.langchain.com/oss/python/langgraph/persistence)   Low           Good as harness.                                        REJECT as primary runtime
  NATS JetStream + Postgres custom   Maximum freedom, maximum implementation risk. [\[5\]](https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive)                                            High          Technically feasible, strategically wasteful now.       REJECT for MVP

**Agent harness**

**Decision:** `ADOPT` thin custom harness over raw provider APIs with
two adapter classes: `provider_adapter` and `framework_adapter`. Native
`handoffs`, `subagents`, `routing`, `workflow agents` можно использовать
только как execution conveniences. Authority, approvals, data-scope и
tool authorization обязаны жить в
`HandoffEnvelope + DelegationGrant + CapabilityToken`, а не в
framework-native transfer semantics.
[\[24\]](https://openai.github.io/openai-agents-python/tools/)

**Evidence:** OpenAI Agents SDK официально различает `handoffs` и
`agents as tools`; это полезно, потому что `agents as tools` лучше
совпадает с вашим требованием "не смугглить authority", тогда как native
handoff передает conversational control новому агенту. Claude Agent SDK
запускает agent loop в вашем процессе и дает hooks/permissions/sessions,
что хорошо для local control, но не создает formal delegated authority.
Google ADK официально подтверждает automatic delegation и mode-based
transfer/return control; Microsoft Agent Framework официально
подтверждает `sequential/concurrent/hand-off` workflows с checkpointing.
Ни один из этих документов не показывает first-class signed delegation
grant как authorization truth.
[\[25\]](https://openai.github.io/openai-agents-python/tools/)

**Assumptions:** multi-provider routing --- требование, а не
nice-to-have; `authority != conversation control`; data classes
PUBLIC→CREDENTIAL уже заданы.

**Alternatives:** OpenAI Agents SDK можно адаптировать как orchestration
SDK внутри orchestrator role. LangGraph/Deep Agents можно брать как
high-level harness для research/coding tasks, где authority
предварительно отрезан ContinuityOS. Microsoft Agent Framework и Google
ADK стоит держать как controlled experiment lanes, а не как
authorization host.

**Risks:** если позволить native handoff напрямую решать tool access,
произойдет смешение `task delegation` и `authority delegation`. Это
прямо противоречит вашим invariants.

**Confidence:** 0.87.

**Acceptance Test:** handoff инициирует downstream work без передачи
новых permissions; target agent видит только
`artifact pointers + structured summary`; попытка вызвать tool вне
`CapabilityToken` блокируется даже если framework считает delegation
валидной.

**Revisit Trigger:** когда появится framework, где `delegation grant`,
`capability scope`, `audit-grade provenance` и `tool approval` являются
first-class, line-verifiable constructs.

**MCP revision impact**

**Decision:** `ADAPT` gate\_hook.py сейчас, но делать это в двух слоях.
Слой А --- confirmed changes из официально опубликованной MCP revision
`2025-11-25`. Слой Б --- forward-compatible fields под user-asserted
`2026-07-28`, которые пока нужно считать `HYPOTHESIS/UNRESOLVED`, потому
что в доступной официальной структуре эта revision не была найдена.
[\[26\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification)

**Evidence:** Верифицировано, что MCP `2025-11-25` добавляет OIDC
discovery, incremental scope consent через `WWW-Authenticate`, OAuth
Client ID metadata documents и experimental `tasks`. Также в доступной
структуре repo/latest published revision --- `2025-11-25`; официально
line-verified `2026-07-28` отсутствует в этом проходе.
[\[27\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2025-11-25)

**Assumptions:** список "stateless protocol, audience-bound tokens,
MCP-\* headers, async tasks, deprecation lifecycle" из user brief в
части `async tasks` и auth discovery частично уже совпадает с
`2025-11-25`; остальные элементы пока нельзя считать verified spec
facts.

**Alternatives:** ждать `2026-07-28` нельзя; practical move --- внести
schema/gate deltas, которые усиливают безопасность даже если итоговая
wording revision окажется иной.

**Risks:** два класса риска особенно важны. Первый ---
`auth metadata desync`: `WWW-Authenticate` и `.well-known` могут
расходиться. Второй --- `async-task state confusion`: long-running MCP
task может потерять связь с original `ActionSpec` и approval context.
[\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)

**Confidence:** 0.73.

**Acceptance Test:** preflight отклоняет MCP call, если `audience`,
`scope`, `origin`, `tool_descriptor_hash` или `task lineage` не совпали
с `ActionSpec`; async task после pause/resume продолжает один и тот же
`trace_id/action_spec_id` без повторной выдачи authority.

**Revisit Trigger:** сразу после публикации официальной, line-verifiable
MCP revision выше `2025-11-25`.

**Concrete migration checklist**

1.  Вынести `MCPAuthorizationResolver` в отдельный deterministic
    component, который кэширует `issuer`, `resource metadata`,
    `requested scopes`, `granted scopes`, `audience`, `token expiry`.
    Основание --- уже verified OIDC/OAuth discovery and incremental
    consent surface.
    [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
2.  Добавить `AsyncTaskRegistry` и запретить "orphan polling": любой
    последующий poll обязан иметь тот же `action_spec_id`,
    `delegation_grant_id`, `trace_id`, `task_external_id`. Основание ---
    verified experimental `tasks`.
    [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
3.  Ввести strict header allowlist в `gate_hook.py`. Даже если future
    MCP revisions formalize `MCP-*` headers, gate должен логировать и
    policy-check каждое transport header field. Это forward-compatible
    security control; spec details выше `2025-11-25` пока `HYPOTHESIS`.
4.  Разделить `session_id` и `authority_id`. Даже если future protocol
    станет по сути stateless, authority не должен жить в transport
    session. Это design requirement, а не trust assumption.
5.  Для каждого MCP tool call сохранять `tool_descriptor_hash` и
    `server_fingerprint`; это снижает `metadata rug-pull` risk
    независимо от финальной revision wording.
6.  Любой incremental scope escalation оформлять как новый `Approval`
    или explicit policy `WARN/HOLD`, а не silent continuation. Основание
    --- verified incremental consent path.
    [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
7.  Все future `deprecation` and `protocol_revision` claims хранить как
    data, а не code constants, пока `2026-07-28` не подтверждена.

**Observability & evals**

**Decision:** `ADOPT` minimal self-hosted stack:
`OpenTelemetry SDKs + OTel Collector + Phoenix self-hosted + append-only audit correlation`.
Не пытаться в первом MVP одновременно поднимать Phoenix, Langfuse и
LangSmith. В этом проходе официальный self-hosting Phoenix подтвержден;
официальные self-hosting surfaces Langfuse/LangSmith в retrieved links
не были line-verified, поэтому они остаются `UNRESOLVED` для
source-backed MVP decision.
[\[28\]](https://arize.com/docs/phoenix/self-hosting)

**Evidence:** Phoenix документирует Docker/Kubernetes self-hosting. OTel
имеет официальный `Generative AI semantic conventions` surface, но
retrieved snippet не подтвердил статус стабильности; значит
instrumentation надо version-pin и считать evolving.
[\[29\]](https://arize.com/docs/phoenix/self-hosting)

**Assumptions:** один владелец, low-ops bias, приоритет --- correlation
и regression gates, а не максимальная feature richness.

**Alternatives:** если later потребуется richer prompt-management UI и
team workflows, можно провести отдельный verified buy-pass по
Langfuse/LangSmith.

**Risks:** слишком ранняя ставка на unstable semconv names сломает
dashboards. Решение --- собственный stable `TraceContext` schema внутри
ContinuityOS и маппинг его в OTel attrs.

**Confidence:** 0.79.

**Acceptance Test:** один end-to-end run должен породить связанный
`trace_id` через Telegram ingress, orchestrator span, preflight span,
tool span, evidence span и audit event; golden-set regression должен
фейлить rollout при drift on role prompts.

**Revisit Trigger:** если Phoenix не покрывает требования по cost lens /
eval adjudication после первых 20--30 recorded runs.

**Cost engineering**

**Decision:** `ADAPT`. Primary lane --- direct provider APIs для
orchestrator/supervisor. Secondary lane --- cheap direct models для
executor/challenger. Tertiary lane --- OpenRouter only for sparse
fallback SKUs, а не как default billing plane. Prompt-caching
использовать на orchestrator/supervisor. Batch --- разрешать только тем
lanes, где pricing и recovery semantics verified; для non-verified
providers default = `supports_batch: false`.
[\[30\]](https://platform.openai.com/docs/pricing)

**Evidence:** OpenAI pricing page line-verifies `input`, `cached input`,
`output` tariffs и отдельно говорит, что `Batch API` itself не priced
separately; Anthropic pricing line-verifies `input`, `output`,
`prompt caching write/read`.
[\[30\]](https://platform.openai.com/docs/pricing)

**Assumptions:** для cost bands я использую source-backed surrogate mix,
потому что pricing по всем вашим named models в этом проходе не была
одинаково line-verified. Модельный набор для расчета: orchestrator =
OpenAI `gpt-5.6-sol`, supervisor = Anthropic `Sonnet 5`, challenger =
Anthropic `Haiku 4.5`, executors = OpenAI `gpt-5.4-mini`. Это
`INFERENCE`, а не invoice forecast. Части workload, идущие через
OpenRouter или иные providers, в bands не включены.
[\[31\]](https://platform.openai.com/docs/pricing)

**Alternatives:** если вам важнее single bill, можно поднять OpenRouter
до secondary lane, но только после отдельной verified
pricing/reliability ревизии.

**Risks:** самая дорогая роль --- orchestrator output. Если
orchestration оставить verbose и без cache discipline, именно она
"съест" бюджет, а не executors.

**Confidence:** 0.62.

**Acceptance Test:** `BudgetPolicy` должен hard-stop low-priority
background work раньше, чем затронет `P0 reserve`; cache hit ratio для
orchestrator/supervisor --- не ниже 40% на повторяющихся prefix-heavy
tasks в течение первой недели.

**Revisit Trigger:** после 2--4 недель реальных token histograms и после
верификации фактических fallback/provider mixes.

**Expected monthly cost bands**

  Usage band   Assumption summary                                                                                      Expected band
  ------------ ------------------------------------------------------------------------------------------------------- --------------------------
  Light        \~11--13M uncached input, \~10--11M cached reads, \~3--3.5M output/month across 5 roles. `INFERENCE`.   **\$120--220 / month**
  Medium       \~54M uncached input, \~56M cached reads, \~15--16M output/month. `INFERENCE`.                          **\$550--900 / month**
  Heavy        \~210M uncached input, \~216M cached reads, \~62M output/month. `INFERENCE`.                            **\$2.2k--3.5k / month**

Эти bands опираются на official rates для OpenAI cached/non-cached token
billing и Anthropic prompt caching pricing, но не включают managed
sandboxes, OpenRouter premia, vector DB, hosted search, storage, or GPU
jobs. [\[30\]](https://platform.openai.com/docs/pricing)

**Secrets & identity**

**Decision:** `NARROW MVP`. Для first vertical slice не поднимать
отдельный secrets control plane класса Vault/Infisical. Вместо этого:
encrypted-at-rest static config, host-side OS keychain/env injection,
short-lived in-process `WorkloadIdentity`, signed `DelegationGrant`,
one-time `CapabilityToken`, separate `ArtifactSigningIdentity`. Это
архитектурная `INFERENCE/HYPOTHESIS` из single-owner estate;
vendor-level feature comparison в этом проходе не был полноценно
line-verified.

**Evidence:** source-backed часть здесь --- то, что authority нельзя
смешивать с tool delegation/handoffs: SDK ecosystems покрывают
routing/handoffs, но не дают вашего required delegated-authority proof
chain. [\[32\]](https://openai.github.io/openai-agents-python/tools/)

**Assumptions:** один владелец; небольшой estate; secrets rotations
контролируются вручную/через scripts; нет многопользовательской
self-service модели.

**Alternatives:** при появлении второго operator, постоянных remote
workers или multi-host secret fan-out, перейти к dedicated secret
manager.

**Risks:** main risk не в "слишком простом storage", а в путанице
идентичностей. Надо жестко различать `HumanIdentity`, `AgentIdentity`,
`ModelBinding`, `WorkloadIdentity`, `WorkerIdentity`,
`ToolAdapterIdentity`, `ProviderIdentity`, `ArtifactSigningIdentity`.

**Confidence:** 0.58.

**Acceptance Test:** replay Telegram approval message не может повторно
авторизовать action; expired `DelegationGrant` отвергается;
`CapabilityToken` привязан к `action_spec_id` и не переиспользуется;
cross-project delegation блокируется.

**Revisit Trigger:** второй human operator, второй production
environment, либо постоянные external workers.

**Sandbox provider decision**

**Decision:**\
`Tier2` --- `ADOPT` local Linux `rootless OCI + gVisor`;
`Daytona = HOLD` как managed developer convenience, не как verified
isolation primitive.\
`Tier3` --- `HOLD` local Firecracker до фактической проверки KVM на
Linux VPS; `ADAPT` E2B как remote untrusted-code option.\
`Tier4` --- `ADOPT` Modal для GPU workloads.
[\[33\]](https://gvisor.dev/docs/)

**Evidence:** gVisor --- userspace `application kernel`; это хорошо
соответствует вашему Tier2. Firecracker explicitly depends on Linux KVM
and hardware virtualization. E2B публично показывает per-second sandbox
billing, значит это operationally usable managed plane, но без fully
retrieved per-execution public breakdown в этом проходе. Modal дает
transparent per-second CPU/GPU pricing. Daytona docs подтверждают hosted
sandbox API, но retrieved docs не доказали isolation mechanism уровня
microVM. [\[33\]](https://gvisor.dev/docs/)

**Assumptions:** dev --- Windows+WSL; prod --- Linux VPS; live trading в
MVP нет; `egress deny` реализуется либо host firewall/namespace policy,
либо provider policy, но должна проверяться empirically.

**Alternatives:** если KVM подтвержден и firecracker automation проста,
Tier3 можно later перевести на local microVM. Если нет --- E2B закрывает
gap быстрее, но дороже.

**Risks:** главная ошибка --- считать Daytona/E2B/Firecracker "одним и
тем же sandbox". Это не одно и то же ни по isolation primitive, ни по
trust boundary, ни по cost surface.

**Confidence:** 0.74.

**Acceptance Test:** Tier2 runner не имеет host Docker socket, не
выходит в интернет без allowlist, не читает host secrets; Tier3 runner
уничтожается после task и не может быть случайно resumed; Tier4 GPU job
публикует provenance и signed artifact, но сам по себе не промоутит
output.

**Revisit Trigger:** подтверждение KVM on VPS, либо реальные workload
traces покажут, что Tier2 недостаточен для hostile repos.

**Illustrative cost-per-1000 executions**

  Provider / tier      Scenario                    Estimate
  -------------------- --------------------------- ------------------------------------------------------------------------------------------------------------------------------------------------
  Local gVisor Tier2   1000 × 30s × 1 core         host-amortized; marginal near-zero excluding host cost. `INFERENCE`.
  Modal CPU            1000 × 30s × 1 core         ≈ **\$1.18** plus memory. `INFERENCE` from per-second price. [\[34\]](https://modal.com/pricing)
  Modal A100           1000 × 60s × 1x A100 80GB   ≈ **\$41.64**. `INFERENCE` from per-second price. [\[35\]](https://modal.com/pricing)
  E2B Tier3            1000 executions             public exact number **UNRESOLVED** in this pass; pricing page confirms per-second billing plus plan fee. [\[18\]](https://www.e2b.dev/pricing)
  Daytona              1000 executions             **UNRESOLVED**; public pricing/isolation proof not line-verifiable in retrieved docs. [\[20\]](https://www.daytona.io/docs)

Architecture Delta
------------------

**Artifact: 03\_ARCHITECTURE\_DELTA**

Ниже указаны только новые или измененные компоненты. Базовая multi-agent
topology не повторяется.

  Component                    Type                      Why it is new/changed
  ---------------------------- ------------------------- ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  `TemporalRuntimeAdapter`     control service           Берет на себя durable timers, signals, retries, cancellation и crash recovery, но не владеет authority/policy/effects truth. [\[1\]](https://docs.temporal.io/workflow-execution/event)
  `BranchLedgerStore`          Postgres schema           Хранит `branch_id`, `parent_branch_id`, `fork_checkpoint_id`, hashes и promotion audit отдельно от runtime engine.
  `ExternalEffectRegistry`     Postgres schema + API     Единственная truth surface для idempotency, reconciliation, compensation и "do-not-replay" behavior.
  `MCPAuthorizationResolver`   deterministic component   Разрешает `issuer`, `resource metadata`, `scope escalation`, `audience` и token expiry до tool dispatch. Confirmed need exists from MCP auth changes. [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
  `AsyncTaskRegistry`          deterministic component   Нужен для MCP `tasks` и долгих remote operations. [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
  `OTelTraceBridge`            instrumentation layer     Маппит `trace_id/correlation_id/causation_id` в spans и связывает их с audit IDs.
  `PhoenixEvalRegistry`        eval service              Хранит golden set runs, regression fixtures, drift decisions. Phoenix self-hosting verified. [\[13\]](https://arize.com/docs/phoenix/self-hosting)
  `BudgetRouter`               deterministic service     Выбирает model lane, cache policy, fallback chain и circuit breakers до model invocation.
  `Tier2LinuxRunner`           execution adapter         Rootless OCI + gVisor; default sandbox for non-hostile code on Linux VPS. [\[17\]](https://gvisor.dev/docs/)
  `Tier3RemoteRunner`          execution adapter         E2B adapter для untrusted arbitrary code, пока local Firecracker не доказан на хосте. [\[36\]](https://www.e2b.dev/pricing)
  `Tier4GpuRunner`             execution adapter         Modal adapter для GPU-only jobs. [\[37\]](https://modal.com/pricing)

Ниже --- минимальная observability pipeline: audit ledger остается
authoritative "what happened", а observability/evals слой --- derived
telemetry plane для trace/debug/regression. OTel GenAI surface
существует официально, Phoenix официально self-hosted; значит связка
реалистична для MVP, но attribute naming нужно version-pin.
[\[38\]](https://opentelemetry.io/docs/specs/semconv/gen-ai/)

  ----------------------------------------------------------------------------------------------------------
  ![Rendered Mermaid diagram 1](media/rId45.png){width="5.833333333333333in" height="1.188270997375328in"}
  ----------------------------------------------------------------------------------------------------------

Ниже --- revised MCP-era gate flow. Здесь важна не transport session, а
deterministic preflight: policy смотрит на `ActionSpec`, auth metadata,
delegated authority и idempotency. Experimental MCP `tasks` уже
confirmed в `2025-11-25`; потому long-running MCP operations не должны
bypass audit/policy только потому, что они "уже стартовали".
[\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)

  -----------------------------------------------------------------------------------------------------------
  ![Rendered Mermaid diagram 2](media/rId48.png){width="5.833333333333333in" height="14.835390419947506in"}
  -----------------------------------------------------------------------------------------------------------

Contracts
---------

**Artifact: 04\_CONTRACTS**

Ниже только `YAML deltas`. Поля спроектированы так, чтобы покрыть уже
verified MCP `2025-11-25` auth/tasks changes и безопасно пережить future
spec revision, которая в этом проходе не была официально line-verified.
[\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)

    ActionSpec:
      mcp:
        enabled: true
        protocol_revision_verified: "2025-11-25"
        protocol_revision_claimed: "2026-07-28"
        claim_status: "UNRESOLVED"
        transport: "streamable_http|sse|stdio"
        server_id: ""
        server_fingerprint: ""
        tool_name: ""
        tool_descriptor_hash: ""
        request_origin: ""
        http_header_allowlist: []
        observed_headers: {}
        auth:
          issuer: ""
          protected_resource_metadata_uri: ""
          authorization_server_metadata_uri: ""
          audience: ""
          granted_scopes: []
          requested_scopes: []
          incremental_scope_requested: false
          token_expiry: ""
          token_binding: "delegation_grant_id"
        async_task:
          enabled: false
          external_task_id: ""
          task_state: "NONE|PENDING|RUNNING|COMPLETED|FAILED|EXPIRED"
          poll_uri: ""
          deferred_result_expected: false
          task_created_at: ""
          task_expires_at: ""
          parent_action_spec_id: ""
        state_binding:
          session_id: ""
          session_semantics: "NON_AUTHORITATIVE"
          continuation_key: ""
    TraceContext:
      trace_id: ""
      correlation_id: ""
      causation_id: ""
      span_id: ""
      parent_span_id: ""
      workflow_id: ""
      branch_id: ""
      checkpoint_id: ""
      task_id: ""
      action_spec_id: ""
      delegation_grant_id: ""
      capability_token_id: ""
      agent_id: ""
      workload_id: ""
      worker_id: ""
      model_binding_id: ""
      provider_id: ""
      tool_call_id: ""
      external_effect_id: ""
      evidence_id: ""
      artifact_id: ""
      policy_version: ""
      approval_id: ""
      data_class: "PUBLIC|INTERNAL|CONFIDENTIAL|CREDENTIAL|FINANCIAL_SENSITIVE"
      sampling_tier: "FULL|HEAD|TAIL|ERROR_ONLY"
    EvalRecord:
      eval_id: ""
      eval_suite: "golden_set|regression|drift|adjudication"
      run_id: ""
      trace_id: ""
      workflow_id: ""
      task_id: ""
      role: "orchestrator|supervisor|challenger|executor|synthesizer"
      prompt_version: ""
      prompt_hash: ""
      model_name: ""
      model_provider: ""
      model_version: ""
      dataset_id: ""
      fixture_id: ""
      input_artifact_ids: []
      expected_outcome_ref: ""
      actual_outcome_ref: ""
      judge_mode: "deterministic|human|independent_model"
      score:
        value: 0.0
        max: 1.0
      verdict: "PASS|FAIL|REGRESSION|DRIFT|UNDECIDED"
      failure_class: ""
      replayable: true
      created_at: ""
    BudgetPolicy:
      policy_id: ""
      policy_version: ""
      owner_id: ""
      reserves:
        p0_usd: 0
        p1_usd: 0
      monthly_caps:
        orchestrator_usd: 0
        supervisor_usd: 0
        challenger_usd: 0
        executors_usd: 0
        sandbox_usd: 0
      routing:
        primary_lane: ""
        secondary_lane: ""
        tertiary_lane: ""
        supports_batch: false
        supports_prompt_cache: true
        direct_provider_required: true
        openrouter_allowed_for: []
      breakers:
        hard_stop_threshold_pct: 100
        warn_threshold_pct: 70
        hold_threshold_pct: 85
        max_cost_per_run_usd: 0
        max_cost_per_task_usd: 0
      fallback:
        on_provider_error: "RETRY_SECONDARY|HOLD|FAIL_CLOSED"
        on_budget_exceeded: "DOWNGRADE|QUEUE|DENY"
      accounting:
        count_cached_input_separately: true
        include_sandbox_runtime: true
        include_eval_spend: true

Backlog
-------

**Artifact: 05\_BACKLOG**

  Title                                                Component                    Rationale                                                                                                                                                                                  Dependencies                                                     Acceptance criteria                                                                                             Security test                                                              Benchmark
  ---------------------------------------------------- ---------------------------- ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ ---------------------------------------------------------------- --------------------------------------------------------------------------------------------------------------- -------------------------------------------------------------------------- --------------------------------------
  Temporal runtime adapter with effect-safe replay     `TemporalRuntimeAdapter`     Durable recovery surface already verified; must be wrapped by ContinuityOS contracts. [\[1\]](https://docs.temporal.io/workflow-execution/event)                                           Postgres, audit ledger                                           crash in mid-tool does not duplicate side effect; replay resumes from checkpoint cursor                         duplicate external effect attempt is blocked by `ExternalEffectRegistry`   restart-to-recovery p95
  Branch ledger and checkpoint API                     `BranchLedgerStore`          Temporal does not natively satisfy your immutable branch contract.                                                                                                                         Postgres schema                                                  `CreateCheckpoint`, `ForkFromCheckpoint`, `ReplayFromCheckpoint`, `PromoteBranch` work with immutable history   superseded branch cannot delete history                                    checkpoint create latency p95
  External effect registry and reconciliation worker   `ExternalEffectRegistry`     Required to make replay safe across runtimes.                                                                                                                                              Branch ledger                                                    every side effect gets `effect_id`, idempotency state, reconciliation status                                    ambiguous reconciliation yields `HOLD`                                     reconcile loop throughput
  Thin custom harness with provider adapters           `AgentHarness`               SDK-native delegation is not an authority boundary. [\[32\]](https://openai.github.io/openai-agents-python/tools/)                                                                         LiteLLM-or-equivalent optional, model routing, HandoffEnvelope   framework handoff cannot enlarge capability scope                                                               inject unauthorized tool capability and verify block                       handoff serialization size
  MCP auth metadata resolver                           `MCPAuthorizationResolver`   Confirmed MCP auth changes require deterministic preflight. [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)   policy engine, token store                                       scope escalation always creates policy/audit event                                                              fake resource metadata / issuer mismatch denied                            resolver latency p95
  Async task watcher for MCP                           `AsyncTaskRegistry`          Confirmed experimental `tasks` add state confusion risk. [\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)      runtime adapter, audit                                           deferred result resumes with same `action_spec_id` and `trace_id`                                               orphan poll attempt denied                                                 poll loop fan-out
  OTel bridge and collector deployment                 `OTelTraceBridge`            Need span correlation independent from audit store.                                                                                                                                        OTel SDK/collector                                               every run has consistent `trace_id/correlation_id/causation_id`                                                 tampered span attrs do not modify immutable audit                          span export overhead
  Phoenix self-hosted eval registry                    `PhoenixEvalRegistry`        Official self-hosting is verified; minimal single-owner eval plane. [\[13\]](https://arize.com/docs/phoenix/self-hosting)                                                                  OTel collector, Postgres                                         golden set run stored with verdict and fixture linkage                                                          eval write path isolated from prod approval path                           eval ingest p95
  Budget router and circuit breakers                   `BudgetRouter`               Need role-aware routing before scale.                                                                                                                                                      pricing config, provider adapters                                breaker stops background work before P0 reserve depletion                                                       malicious prompt inflation capped                                          cost-estimation overhead
  Telegram approval signature and replay cache         `TelegramControlAdapter`     Approval spoofing/replay must fail closed.                                                                                                                                                 approval service, owner identity                                 approval callback valid once only; expires by ttl                                                               replay old callback and forged chat payload                                approval roundtrip p95
  Linux Tier2 runner with gVisor                       `Tier2LinuxRunner`           gVisor is verified userspace application kernel. [\[17\]](https://gvisor.dev/docs/)                                                                                                        Linux VPS, rootless OCI                                          read-only rootfs, no host socket, egress deny baseline                                                          attempt host secret read / network escape                                  cold-start and steady-state run time
  Firecracker feasibility spike                        `Tier3Feasibility`           Firecracker requires KVM; must not be assumed on estate. [\[16\]](https://firecracker-microvm.github.io/)                                                                                  Linux VPS access                                                 produce pass/fail artifact for KVM, jailer, snapshot, egress policy                                             verify no host metadata access                                             cold-start time and teardown
  E2B remote runner adapter                            `Tier3RemoteRunner`          Fastest path to external microVM-like isolation while Firecracker feasibility remains open. [\[18\]](https://www.e2b.dev/pricing)                                                          provider account, budget router                                  untrusted code executes with evidence capture and cleanup                                                       ensure no production credentials injected                                  cost per run sample
  Modal GPU adapter                                    `Tier4GpuRunner`             Transparent per-second GPU pricing and API fit for GPU-only jobs. [\[37\]](https://modal.com/pricing)                                                                                      budget router, artifact signing                                  GPU job emits provenance and signed output manifest                                                             output cannot auto-promote without verification                            p50/p95 GPU startup
  Regression drift gate for role prompts               `EvalGate`                   Model upgrades must not silently degrade orchestrator/supervisor/challenger prompts.                                                                                                       Phoenix, prompt registry                                         CI blocks on regression or drift verdict                                                                        adversarial prompt fixture included                                        adjudication latency

MVP Decision
------------

**Artifact: 06\_MVP\_DECISION**

Минимальный first vertical slice должен быть уже production-shaped, но
предельно узким:

**Runtime:** `Temporal self-hosted` как durable substrate, плюс
Postgres-backed `BranchLedgerStore` и `ExternalEffectRegistry`.
[\[1\]](https://docs.temporal.io/workflow-execution/event)\
**Harness:** thin custom harness; OpenAI/Anthropic SDK adapters только
как execution clients.
[\[39\]](https://openai.github.io/openai-agents-python/tools/)\
**Gate:** MCP-aware `gate_hook.py` с auth metadata resolution,
idempotency binding и approval hooks.
[\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)\
**Observability:** OTel → Collector → Phoenix, при authoritative
append-only audit отдельно.
[\[13\]](https://arize.com/docs/phoenix/self-hosting)\
**Sandbox:** Tier2 Linux `rootless OCI + gVisor`; Tier3 remote E2B
только для explicitly untrusted code; Firecracker не включать в MVP
checkpoint до feasibility proof. [\[40\]](https://gvisor.dev/docs/)\
**Secrets/identity:** narrow MVP: local encrypted config + short-lived
internal workload tokens; no live trading.\
**Commercial shape of this slice:** Telegram command as human control
ingress, but not the only source of proof; proof lives in audit,
evidence, approval, and reproducible trace.

**Minimal vertical slice**

`Telegram → API Gateway → orchestrator plan → ContinuityOS preflight → Temporal workflow state → Tier2 sandbox/tool call → deterministic verification → artifact + evidence + immutable audit + Phoenix trace.`

**Why this slice and not wider**

Потому что он уже проверяет все действительно load-bearing assumptions:
durable recovery, non-smuggled authority, preflight policy, effect-safe
replay, evidence verification, correlated traces и cost gating. Ничего
из этого не требует ни full LifeOS, ни live trading, ни large cockpit
surface. [\[41\]](https://docs.temporal.io/workflow-execution/event)

**Smallest falsification spike**

Начать сегодня нужно с одного spike:

`git_commit_with_hold_and_recovery`

Сценарий:

1.  Telegram owner отправляет команду "prepare patch and commit".
2.  Orchestrator строит plan, но не получает authority автоматически.
3.  ContinuityOS выдает `DelegationGrant` только на `read repo`,
    `write working tree`, `git commit`; `git push` остается `HOLD`.
4.  Исполнение идет в Tier2 Linux gVisor runner.
5.  В середине tool execution semantic orchestrator убивается.
6.  Temporal worker поднимается заново.
7.  Runtime восстанавливает state, не дублирует `git commit`, пишет
    artifact, evidence, audit trace и regression fixture.
8.  Phoenix показывает связанный trace; audit показывает who/what/why;
    `git push` все еще требует explicit approval.

Если этот spike не проходит, значит текущий runtime/gate/identity stack
нельзя считать production-ready, и нужно немедленно пересмотреть либо
Temporal glue layer, либо authority boundary, а не строить dashboard.
[\[42\]](https://docs.temporal.io/workflow-execution/event)

**Research limitations**

Три зоны остаются открытыми и не должны маскироваться под "решенные":
официальная MCP revision `2026-07-28` не была line-verified в доступной
spec tree; official self-hosted Langfuse/LangSmith surfaces не были
верифицированы в retrieved official pages этого прохода; публичные exact
per-execution cost figures для Daytona и E2B остались неполными. Поэтому
эти решения в отчете сознательно помечены как `UNRESOLVED`, `INFERENCE`
или `HYPOTHESIS`, а не искусственно "закрыты".
[\[43\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification)

**System Passport**

  Field      Value
  ---------- ------------------------------------------------------------------------------------------------
  Pattern    control-spine-first, authority-outside-agents
  Fidelity   source-backed where official line evidence exists; unresolved explicitly marked
  Entropy    medium; concentrated in MCP revision drift, secrets vendor choice, Tier3 cost/host feasibility
  Nodes      runtime, harness, MCP gate, observability, cost, identity, sandbox

[\[1\]](https://docs.temporal.io/workflow-execution/event)
[\[21\]](https://docs.temporal.io/workflow-execution/event)
[\[22\]](https://docs.temporal.io/workflow-execution/event)
[\[41\]](https://docs.temporal.io/workflow-execution/event)
[\[42\]](https://docs.temporal.io/workflow-execution/event)
https://docs.temporal.io/workflow-execution/event

<https://docs.temporal.io/workflow-execution/event>

[\[2\]](https://raw.githubusercontent.com/temporalio/temporal/master/LICENSE)
https://raw.githubusercontent.com/temporalio/temporal/master/LICENSE

<https://raw.githubusercontent.com/temporalio/temporal/master/LICENSE>

[\[3\]](https://docs.restate.dev/llms.txt)
https://docs.restate.dev/llms.txt

<https://docs.restate.dev/llms.txt>

[\[4\]](https://docs.langchain.com/oss/python/langgraph/persistence)
[\[23\]](https://docs.langchain.com/oss/python/langgraph/persistence)
https://docs.langchain.com/oss/python/langgraph/persistence

<https://docs.langchain.com/oss/python/langgraph/persistence>

[\[5\]](https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive)
https://docs.nats.io/using-nats/developer/develop\_jetstream/model\_deep\_dive

<https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive>

[\[6\]](https://openai.github.io/openai-agents-python/tools/)
[\[24\]](https://openai.github.io/openai-agents-python/tools/)
[\[25\]](https://openai.github.io/openai-agents-python/tools/)
[\[32\]](https://openai.github.io/openai-agents-python/tools/)
[\[39\]](https://openai.github.io/openai-agents-python/tools/)
https://openai.github.io/openai-agents-python/tools/

<https://openai.github.io/openai-agents-python/tools/>

[\[7\]](https://docs.anthropic.com/en/docs/claude-code/sdk)
https://docs.anthropic.com/en/docs/claude-code/sdk

<https://docs.anthropic.com/en/docs/claude-code/sdk>

[\[8\]](https://adk.dev/tutorials/agent-team/)
https://adk.dev/tutorials/agent-team/

<https://adk.dev/tutorials/agent-team/>

[\[9\]](https://github.com/microsoft/agent-framework)
https://github.com/microsoft/agent-framework

<https://github.com/microsoft/agent-framework>

[\[10\]](https://github.com/modelcontextprotocol/specification)
https://github.com/modelcontextprotocol/specification

<https://github.com/modelcontextprotocol/specification>

[\[11\]](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx)
https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx

<https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx>

[\[12\]](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
[\[38\]](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
https://opentelemetry.io/docs/specs/semconv/gen-ai/

<https://opentelemetry.io/docs/specs/semconv/gen-ai/>

[\[13\]](https://arize.com/docs/phoenix/self-hosting)
[\[28\]](https://arize.com/docs/phoenix/self-hosting)
[\[29\]](https://arize.com/docs/phoenix/self-hosting)
https://arize.com/docs/phoenix/self-hosting

<https://arize.com/docs/phoenix/self-hosting>

[\[14\]](https://platform.openai.com/docs/pricing)
[\[30\]](https://platform.openai.com/docs/pricing)
[\[31\]](https://platform.openai.com/docs/pricing)
https://platform.openai.com/docs/pricing

<https://platform.openai.com/docs/pricing>

[\[15\]](https://www.anthropic.com/pricing)
https://www.anthropic.com/pricing

<https://www.anthropic.com/pricing>

[\[16\]](https://firecracker-microvm.github.io/)
https://firecracker-microvm.github.io/

<https://firecracker-microvm.github.io/>

[\[17\]](https://gvisor.dev/docs/) [\[33\]](https://gvisor.dev/docs/)
[\[40\]](https://gvisor.dev/docs/) https://gvisor.dev/docs/

<https://gvisor.dev/docs/>

[\[18\]](https://www.e2b.dev/pricing)
[\[36\]](https://www.e2b.dev/pricing) https://www.e2b.dev/pricing

<https://www.e2b.dev/pricing>

[\[19\]](https://modal.com/pricing) [\[34\]](https://modal.com/pricing)
[\[35\]](https://modal.com/pricing) [\[37\]](https://modal.com/pricing)
https://modal.com/pricing

<https://modal.com/pricing>

[\[20\]](https://www.daytona.io/docs) https://www.daytona.io/docs

<https://www.daytona.io/docs>

[\[26\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification)
[\[43\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification)
https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification

<https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification>

[\[27\]](https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2025-11-25)
https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2025-11-25

<https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2025-11-25>
