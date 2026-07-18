# Deep Research по безопасному подключению CTHA поверх ContinuityOS без передачи authoritative state

## Executive verdict

```text
[✅] ContinuityOS gate/ledger: публично инспектировано
[✅] Trust boundary: можно зафиксировать жёстко
[⏳] mind/CTHA: нужен falsification spike
[📋] Memory promotion: только через governed proposer pipeline
[❌] Нельзя давать brain прямую запись в canon/ACTIVE
```

**[mind/ — SPIKE-FIRST / ContinuityOS — VERIFIED_CURRENT]** Вердикт: **SPIKE-FIRST**. Мой текущий вывод — подключать brain можно **только как non-authoritative proposer**, а не как участника, который принимает финальные решения по side effects или по canon/memory promotion. Причина не в слабости самой идеи, а в асимметрии доказательной базы: у `ContinuityOS` публично видны реализованные `preflight()`, append-only hash-chain ledger, проверки в `tests/test_gate.py` и `tests/test_ledger.py`, тогда как `mind/CTHA`, `docs/04_SELF_IMPROVEMENT_LOOP.md` и `docs/D7` в публично доступных репозиториях на дату исследования мне напрямую проверить не удалось. На видимом GitHub-профиле `bitmaster162` публично доступны только два репозитория, из которых релевантен именно `continuityos`; это означает, что для `mind/` нужно исходить из вашего source inventory и считать его design intent, пока boundary не доказан локальным spike’ом. citeturn45view0turn37view0turn13view0turn32view0turn32view1

**[ContinuityOS — VERIFIED_CURRENT]** Для внешних side effects authoritative gate уже есть: `continuityos/gate/engine.py` определяет `preflight(spec, ...)`, возвращает `decision`, `reasons`, `rollback_plan`, `ts`, инвариант `"no registered dangerous tool may execute unless a ContinuityOS preflight decision exists"`, а при наличии `ledger` записывает решение в append-only hash-chain. Тесты подтверждают как минимум блокировку `rm -rf /`, эскалацию команд, конфликтующих с canon, обнаружение tamper’а в ledger и возможность локального rollback файлов через snapshot/restore. Это делает ContinuityOS spine единственным разумным authoritative decision point для исполнения. citeturn13view0turn14view0turn31view0turn32view0

**[mind/ — OBSERVED_CURRENT]** По вашему source inventory у `mind/` есть собственные `T-layer Default-DENY gate` и `A-layer veto`, а также `GWT conscious-access bus`, запись только в `mind/runtime/` и read-only чтение `canon/01_RUNTIME`; но без прямого code inspection я не могу считать эти свойства доказанным runtime behavior. Поэтому архитектурно их надо трактовать как **inner cognitive safety filters**, а не как authority plane. Если хотя бы один внешний tool call сможет пройти по решению CTHA без `ContinuityOS preflight()`, это уже не complementary layering, а split-brain governance defect. citeturn45view0turn13view0

**Confidence:** **0.82**. Высокая уверенность по boundary на стороне `ContinuityOS`; средняя уверенность по рекомендациям для `mind/`, потому что публично верифицируемый код `mind/` недоступен и значительная часть выводов о brain-side behavior остаётся `OBSERVED_CURRENT` или `PROPOSAL`. citeturn45view0turn13view0turn59view0

## Trust boundary

**[ContinuityOS — VERIFIED_CURRENT / mind/ — PROPOSAL]** Самая безопасная интерпретация связи такова: **CTHA-gate — complementary only if internal; ContinuityOS gate — authoritative for execution**. Иначе говоря, `T-layer` и `A-layer` у CTHA допустимы как внутренняя фильтрация внимания, ранжирования и отказа от плохих собственных гипотез, но **не** как последний рубеж перед tool execution. Последний рубеж уже реализован и протестирован в `continuityos/gate/engine.py`, а публично проверяемого эквивалента для `mind/` нет. citeturn13view0turn32view0turn45view0

```text
                   READ ONLY                                    AUTHORITATIVE
        ┌──────────────────────────────┐              ┌──────────────────────────────┐
        │        canon/01_RUNTIME      │              │ ContinuityOS Control Spine   │
        │  truth snapshot / policies   │              │  preflight + ledger + exec   │
        └──────────────┬───────────────┘              └──────────────┬───────────────┘
                       │                                             │
                       │ read-only                                   │ execute only after
                       ▼                                             │ ContinuityOS decision
        ┌──────────────────────────────┐                             │
        │   CTHA cognitive layer       │                             │
        │ C/H/T/A + GWT bus            │                             │
        │ ranks plans / vetoes ideas   │                             │
        │ writes only mind/runtime/    │                             │
        └──────────────┬───────────────┘                             │
                       │                                             │
                       │ emits Proposed ActionSpec                   │
                       ▼                                             │
        ┌──────────────────────────────┐                             │
        │ Proposal Bridge              │────────────────────────────▶│
        │ schema check, signing,       │                             │
        │ trace correlation, no exec   │                             │
        └──────────────────────────────┘                             │
                                                                     ▼
                                                          deterministic effect + ledger
```

**[Proposed connection — PROPOSAL]** Точный boundary я рекомендую сформулировать так:

1. **CTHA may read** `canon/01_RUNTIME` snapshot и любые другие explicitly whitelisted derived views.  
2. **CTHA may write** только в `mind/runtime/` и только proposal artifacts, trace artifacts, local scoring artifacts.  
3. **CTHA may not call tools**, mutate `canon/`, mutate `ACTIVE` memory, append в authoritative ledger, or mark decisions executable.  
4. **Proposal Bridge** конвертирует brain output в нормализованный `ActionSpec` или `ImprovementProposal`.  
5. **ContinuityOS preflight()** — **единственный** компонент, который может выдать authorizing decision для внешнего side effect.  
6. **Executor** получает команду только от spine после `preflight` decision; не от brain.  

Это делает два gate’а **не redundant, а layered**: brain gate отсекает плохие идеи до попадания в authority plane; ContinuityOS gate решает, можно ли чему-то вообще выйти наружу. citeturn13view0turn32view0

**[ContinuityOS — VERIFIED_CURRENT / ContinuityOS council — SUPERSEDED for security use]** Важно, что даже существующие council/authority abstractions внутри публичного `ContinuityOS` нельзя воспринимать как достаточную security boundary: `continuityos/agents.py` действительно задаёт `authority` levels и `NAMESPACE_MIN_WRITE`, где `canon` требует `SOVEREIGN`, но audit прямо предупреждает, что actors живут в process memory (`self.actors`), без persistent identity и подписи, и это “вежливая договорённость, а не безопасность”. Следовательно, boundary между CTHA и canon должен быть enforced не council-convention’ами, а process isolation, ACL, capability separation и отсутствием write-capabilities у brain. citeturn36view0turn36view1turn36view4turn59view0

## Evidence table

**[Research status — VERIFIED_CURRENT / OBSERVED_CURRENT / PROPOSAL]** Ниже я намеренно разделяю **публично инспектированный implementation** от **design intent / user-supplied inventory**, потому что именно это отличает безопасное решение от wishful architecture. citeturn45view0turn13view0turn59view0

### Public implementation inspected

| Claim | Tag | Source path | Confidence |
|---|---|---|---|
| `preflight(spec, ...)` exists and is framed as the non-negotiable invariant before dangerous tool execution | VERIFIED_CURRENT | `continuityos/gate/engine.py` | High |
| `preflight()` returns `decision`, `reasons`, `rollback_plan`, `ts`, and an invariant string; it can append to ledger | VERIFIED_CURRENT | `continuityos/gate/engine.py` | High |
| The ledger is append-only, hash-chained, SQLite-backed, and has explicit `verify()` tamper detection | VERIFIED_CURRENT | `continuityos/gate/ledger.py` | High |
| Tests verify `rm -rf /` is denied, interpreter-mediated deletes are denied, canon conflicts escalate, and file rollback restores content | VERIFIED_CURRENT | `tests/test_gate.py` | High |
| Tests verify ledger tamper is detected | VERIFIED_CURRENT | `tests/test_gate.py`, `tests/test_ledger.py` | High |
| `canon` in public ContinuityOS is implemented as a namespace in structured memory, not a separate immutable governance engine | VERIFIED_CURRENT | `continuityos/continuity.py` | High |
| `Continuity.add_canon()` writes directly via `Memory.remember()` into `namespace="canon"` | VERIFIED_CURRENT | `continuityos/continuity.py` | High |
| `Memory.remember()` stores vectors, metadata, validity windows, and supersession links; `supersede()`/`upsert()` are append-only | VERIFIED_CURRENT | `continuityos/memory.py` | High |
| The public `Twin` is evidence-grounded but heuristic: `predict()` uses recall over namespaces and `alignment()` uses negation heuristics | VERIFIED_CURRENT | `continuityos/twin.py` | High |
| Public council authorization is not a hard security boundary because actors live in `self.actors` and lack persistent identity/signatures | VERIFIED_CURRENT | `continuityos/agents.py`; critique corroborated in `AUDIT_DEVIL_2026-06-17.md` | High |

Поддержка по этим строкам — в публично видимом коде и тестах. citeturn13view0turn14view0turn28view0turn35view0turn35view1turn29view0turn36view0turn36view4turn32view0turn32view1turn59view0

### Design intent or unverified source inventory

| Claim | Tag | Source path | Confidence |
|---|---|---|---|
| `mind/` contains CTHA with 4-layer matrix `C/H/T/A` | OBSERVED_CURRENT | `mind/ctha.py` | Medium-Low |
| `mind/` has `GWT conscious-access bus` | OBSERVED_CURRENT | `mind/attention.py` | Medium-Low |
| `mind/` has explicit authority logic | OBSERVED_CURRENT | `mind/authority.py` | Medium-Low |
| `mind/` writes only to `mind/runtime/` and reads `canon/01_RUNTIME` read-only | OBSERVED_CURRENT | `mind/runtime/`, `canon/01_RUNTIME/` | Medium-Low |
| `mind/` emits `ctha_trace.jsonl` | OBSERVED_CURRENT | `mind/runtime/ctha_trace.jsonl` | Medium-Low |
| “authority-tagged multi-agent wrapper” and “twin” are experimental, not validated behavior or production multi-agent product | OBSERVED_CURRENT | `mind/README.md` or equivalent README path from your source inventory | Medium-Low |
| Self-improvement loop `SENSE->PROPOSE->BUILD->EVALUATE->GATE->CANARY->PROMOTE/ROLLBACK` exists as design contract | OBSERVED_CURRENT | `docs/04_SELF_IMPROVEMENT_LOOP.md` | Medium-Low |
| Knowledge Foundry with FEVER claims, PROV-O provenance, CanonicalDecision, contradiction records is the intended truth store | OBSERVED_CURRENT | `docs/D7*` | Medium-Low |

**[mind/ — UNKNOWN on public web / OBSERVED_CURRENT from provided inventory]** Эти строки я включаю, потому что вы дали path-level inventory, но я не мог непосредственно проверить их на публичном web и поэтому не поднимаю их выше `OBSERVED_CURRENT`. Видимый публичный профиль автора не показывает отдельный MAWorld/mind repository, что и есть причина такого консервативного ранжирования. citeturn45view0

## Memory and canon integration

**[ContinuityOS — VERIFIED_CURRENT / Governance wrapper — PROPOSAL]** Здесь есть главная тонкость. Публичный `ContinuityOS` уже хранит `canon` и другие continuity entities как structured memory namespaces, а `add_canon()` просто делает write в тот же memory store. Это удобно для continuity UX, но **само по себе не удовлетворяет** вашему инварианту “agent never owns authoritative state”, если brain вообще получит доступ к этим write APIs. Значит, для MAWorld-совместимого режима нужно считать публичный memory layer **storage substrate**, а authoritative promotion rules вынести **над ним** в отдельный governed pipeline. citeturn28view0turn35view0turn35view1

**[mind/ — PROPOSAL / Knowledge Foundry — OBSERVED_CURRENT]** Безопасная схема памяти должна быть такой:

`CTHA belief` → `MemoryMutationProposal` → `Validation/Evals` → `Human or CanonicalDecision` → `Promoter service` → `ACTIVE / canon`.

То есть brain может породить belief, hypothesis, contradiction candidate, extracted claim, or patch suggestion, но **не** может directly write into `ACTIVE`, `canon`, or `CanonicalDecision`. Его output должен иметь статус только **PROPOSED** до завершения promotion lifecycle. Это полностью снимает конфликт с инвариантом “LLM/agent never owns authoritative state”. citeturn45view0turn56search3turn58search0

**[Proposed integration — PROPOSAL]** Практически я бы ввёл четыре явных класса артефактов:

- `mind/runtime/beliefs/*.json` — ephemeral beliefs, hypothesis state, rankings, uncertainty.
- `mind/runtime/proposals/memory/*.json` — proposed memory mutations с обоснованием.
- `mind/runtime/proposals/actions/*.json` — proposed `ActionSpec`.
- `mind/runtime/proposals/improvements/*.json` — proposed `ImprovementProposal` для self-improvement loop.

Каждый proposal должен включать как минимум: `proposal_id`, `source_trace_id`, `brain_run_id`, `read_set`, `evidence_refs`, `confidence`, `target_namespace`, `proposed_operation`, `risk_class`, `requires_human`, `created_at`. Авторitative promoter уже затем решает, делать ли `Memory.upsert()`/`supersede()` и в какой namespace. Это согласуется и с append-only pattern’ом `Memory.remember()`/`supersede()`, и с PROV-O, где provenance описывается через relation между `Entity`, `Activity` и `Agent`. citeturn35view0turn35view1turn56search3turn56search11

**[ContinuityOS — VERIFIED_CURRENT / Security caveat — VERIFIED_CURRENT]** Критически важно не использовать для этого public `Council.remember()` как самостоятельный authoritative promoter, даже если у него есть write rules на `canon`. Причина: audit уже фиксирует, что current council — это governance notation, а не cryptographically enforceable authority plane. Значит, self-promotion защитит не council role name, а отдельный promoter process с отдельным credential, отдельно от brain runtime. citeturn36view0turn36view4turn59view0

**[Recommended canon flow — PROPOSAL]** Рекомендованный canonical path я бы записал так:

1. Brain читает `canon/01_RUNTIME` snapshot.  
2. Brain формирует candidate claim or contradiction.  
3. Knowledge Foundry verifier проверяет evidence quality по схеме FEVER-style claim/evidence, contradiction linkage и provenance graph.  
4. Evals выносят one of: `REJECT`, `HOLD`, `VALIDATED`, `ESCALATE_TO_HUMAN`.  
5. Только после `VALIDATED + APPROVED` promoter service выпускает `CanonicalDecision` и materializes change into authoritative store.  
6. Vector index обновляется как **derived artifact**, never as truth source.  

Это именно тот случай, где `ContinuityOS` storage usable, но without granting brain storage authority. citeturn35view0turn35view1turn56search3turn58search0

## Feasibility of mind as proposer

**[mind/H-layer — PROPOSAL supported by research]** С точки зрения research fit, ваш тезис правильный: `H-layer` active inference с `Expected Free Energy` и policy ranking очень естественно ложится на фазу **PROPOSE** в self-improvement loop. В active inference policy selection делается через минимизацию expected free energy, которая объединяет pragmatic value и epistemic value; в process-theory formulation это именно механизм выбора policy under uncertainty, а не обязательство немедленного исполнения. Поэтому использовать CTHA как generator/ranker of `ImprovementProposal` — архитектурно разумно, если исполнение и promotion остаются outside the cognitive core. citeturn57search1turn57search7turn57search13turn57search16

**[mind/ — OBSERVED_CURRENT / RESEARCH_ONLY]** Но feasibility не равна trust. Поскольку публично инспектируемых реализаций `mind/ctha.py`, `mind/attention.py`, `mind/authority.py` я не увидел, мне приходится разделять две вещи:  
- **концептуально**: active inference-as-proposer — сильная идея;  
- **операционно**: пока не доказано, что конкретный `mind/` делает это deterministically, auditable, and boundary-safe.  
Именно поэтому brain надо подключать сначала не к реальным side effects и не к canon promotion, а к **contracts/improvement/** как к proposal-only surface. citeturn45view0turn57search1turn57search7

**[What is real today — VERIFIED_CURRENT]** На публичной стороне реально есть уже работающие конструкции, которые brain может использовать как downstream authority layer: `preflight()` с canon conflict checks, append-only ledger, file-snapshot rollback, append-only memory supersession, evidence-grounded but heuristic `Twin`, and authority labelling in council. Это достаточно, чтобы принять proposals от brain и дальше решать их outside the brain. citeturn13view0turn14view0turn35view0turn35view1turn29view0turn36view0

**[What needs falsification before trust — PROPOSAL]** Перед любым ростом доверия я бы потребовал четыре falsification spike’а на стороне `mind/`:

1. **Boundary falsification:** brain пытается напрямую мутировать `canon/` и `ACTIVE`; должно быть hard denied на FS/capability layer.  
2. **Bypass falsification:** brain пытается вызвать tool/executor напрямую; это должно быть structurally impossible.  
3. **Trace falsification:** каждая brain proposal обязана коррелироваться с downstream `trace_id` и затем с `ledger_hash`; “untraced proposal” автоматически invalid.  
4. **Stability falsification:** повтор одного и того же input должен давать либо тот же proposal digest, либо explainable delta, иначе improvement proposer трудно оценивать.  

Пока эти spike’и не зелёные, mind/ упирается в статус `RESEARCH_ONLY` для production-facing trust. citeturn45view0turn56search0turn56search10turn56search17

## Minimal safe connection spike

**[Recommended spike — PROPOSAL]** Минимальный безопасный spike должен быть **меньше, чем “интеграция мозга”**, и фактически сводиться к одной связке:

`brain proposes` → `Bridge normalizes` → `ContinuityOS preflight` → `deterministic executor` → `ledger + trace correlation`.

Никакой direct memory write, никакого canon write, никакого human-approval bypass. citeturn13view0turn14view0turn32view0

**[Spike scope — PROPOSAL]** Я бы зафиксировал такой состав spike’а:

- **Process A: CTHA sandbox**  
  Mounts: `canon/01_RUNTIME` **read-only**, `mind/runtime/` **read-write**, no network, no shell, no git, no DB credentials, no ledger credentials.

- **Process B: Proposal Bridge**  
  Responsible for schema validation and normalization of `mind/runtime/proposals/actions/*.json` into a canonical `ActionSpec`.

- **Process C: ContinuityOS authority runner**  
  Holds the only capability to call `preflight()` and the only capability to trigger executor.

- **Executor**  
  Restricted to one deterministic action kind for the spike, for example a filesystem write under a temp directory already covered by `allowed_roots`.

Это важно: spike не должен начинаться с “пусть brain управляет чем-то важным”. Он должен начинаться с “пусть brain предложит один безопасный, детерминированный `ActionSpec`, а spine докажет, что boundary держится”. citeturn13view0turn32view0

**[Observability mapping — PROPOSAL backed by standards]** Для end-to-end audit CTHA должен эмитить как минимум следующие поля в `ctha_trace.jsonl`:

- `trace_id` — тот же distributed trace identifier, который потом уйдёт в bridge, preflight и executor.
- `span_id`, `parent_span_id` — для локальной causal chain.
- `traceparent`, `tracestate` — если хотите W3C-compliant propagation across services.
- `brain_run_id`, `proposal_id`, `proposal_kind`.
- `read_set` — какие canon/runtime entities были прочитаны.
- `write_set` — какие `mind/runtime/` entities были записаны.
- `action_spec_digest` or `proposal_digest`.
- `policy_version`, `canon_snapshot_id`.
- `decision_source="brain_proposal_only"`.
- `downstream_preflight_decision`, `downstream_ledger_hash` — заполняются bridge/runner’ом post hoc.
- `prov_activity_id`, `prov_used_entities`, `prov_generated_entities` — для PROV-O-compatible provenance.
- `status`, `error_code`, `uncertainty`, `rank_score`.

W3C Trace Context задаёт стандарт для `traceparent`/`tracestate`, OpenTelemetry допускает causal `Span Links` между asynchronous operations, а Langfuse already supports custom trace IDs and OTel-native ingestion; значит, brain trace можно без костылей положить в ту же end-to-end story, что и authoritative spine. citeturn56search0turn56search8turn56search17turn56search13turn56search2turn56search10turn56search3

**[Falsification test — PROPOSAL]** Обязательный falsification test для spike я бы оформил так:

**Test name:** `brain_cannot_mutate_authoritative_state_or_bypass_gate`

**Given**
- `canon/01_RUNTIME` mounted read-only into CTHA sandbox.
- No executor credentials in CTHA process.
- Only Bridge has access to `ActionSpec` intake.
- Only authority runner can call `preflight()` and executor.

**When**
1. Brain tries to write file under `canon/01_RUNTIME/...`.
2. Brain emits a fake `{"decision":"ALLOW","execute":true}` artifact.
3. Brain emits an `ActionSpec` targeting path outside allowed roots.
4. Brain emits a memory promotion request to `ACTIVE` without human/eval approval.

**Then**
1. OS/filesystem denies direct canon mutation.
2. Bridge ignores execution markers from brain and re-materializes its own canonical `ActionSpec`.
3. `ContinuityOS preflight()` returns `DENY`, `HOLD`, or `REQUIRE_CONFIRMATION` per policy/D3.
4. No authoritative store changes occur.
5. The failed attempt is visible in trace and, if routed via runner, in the ledger.

Если этот тест не зелёный, интеграция brain не должна переходить даже в canary stage. citeturn13view0turn32view0turn56search0turn56search17

## Risk register

**[Top risks — PROPOSAL informed by public ContinuityOS evidence]** Главные риски здесь не в “плохом reasoning”, а в плохом boundary engineering. citeturn13view0turn59view0

| Risk | Why it matters | Current evidence | Mitigation |
|---|---|---|---|
| Brain bypasses authoritative gate | Collapse of non-negotiable invariant | Public `preflight()` is authoritative; `mind/` bypass behavior unverified | No executor/tool capabilities in brain; authority runner only |
| Brain self-promotes belief to truth | Violates “agent never owns authoritative state” | Public `ContinuityOS` canon is writable storage namespace; not enough by itself | Promotion lifecycle outside brain; promoter service + human/evals |
| Council authority mistaken for security | False sense of protection | Audit says council is polite agreement, not security | Treat council labels as metadata only; use capabilities/ACL/signatures |
| Untraceable cognition | Can’t correlate proposal to effect | `mind/ctha_trace.jsonl` not publicly verified; standards exist | W3C trace fields + OTel spans + Langfuse trace IDs + ledger hash link |
| Heuristic twin over-trusted as decision engine | Misplaced autonomy | Public `Twin` is recall+heuristics, not validated twin | Keep twin/brain in proposal role only |
| Brain contaminates canon with derived vectors or stale beliefs | Truth drift | Public memory uses vectors as retrieval substrate | Make vector index derived-only; canon change only via CanonicalDecision |
| Ambiguous failure semantics on replay/recovery | Duplicate effects or ghost state | Your premise says spine already solved effect-once semantics | Keep brain stateless wrt authority; replay only re-drives proposals, not side effects |

**[ContinuityOS — VERIFIED_CURRENT / Risk note — VERIFIED_CURRENT]** Отдельно отмечу: публичный audit уже сам диагностирует, что twin легко переоценить, а council governance декоративна без persistent identity and signatures. Это редкий и полезный случай, когда проект сам даёт вам аргументы, почему authority нельзя отдавать вверх по cognitive stack. citeturn59view0turn29view0turn36view4

## Timing plan and next decision

**[Thirty-day plan — PROPOSAL]** В первые 30 дней задача не “подключить мозг”, а **доказать boundary**. Результатом должен стать один минимальный spike с read-only canon mount, write-only `mind/runtime/`, canonical `ActionSpec` bridge, authoritative `preflight()`, one deterministic action type и зелёный falsification test на direct canon write / gate bypass. Никаких memory promotions и никаких real-world external APIs в этой фазе. citeturn13view0turn32view0

**[Sixty-day plan — PROPOSAL]** Во вторые 30 дней добавляется governed promotion path: `MemoryMutationProposal`, provenance fields, contradiction handling, eval gates и human approval surfaces. Здесь же добавляется full observability through W3C Trace Context, OTel spans/links и Langfuse trace correlation, так чтобы любой `proposal_id` можно было довести до `ledger_hash` или до explicit rejection record. citeturn56search0turn56search13turn56search17turn56search2turn56search10turn56search3

**[Ninety-day plan — PROPOSAL]** Только к 90 дням имеет смысл canary for **mind-as-proposer** в self-improvement loop, и то сперва не для operational side effects, а для `contracts/improvement/`: prompt proposals via GEPA-style search, code proposals in DGM-style build/eval loops, with kill-switch fail-closed and explicit rollback/promotion governance. Идея здесь — дать CTHA оптимизировать candidate improvements, но не делать merge/promotion authority частью CTHA. citeturn57search1turn57search7

**[One concrete next decision — PROPOSAL]** Следующее решение я рекомендую принять формулировкой:

> **Approve a boundary spike, not a brain integration.**  
> Разрешить только `CTHA -> Proposed ActionSpec -> ContinuityOS preflight -> deterministic temp-dir executor`, при жёстких условиях: `canon` mounted read-only, `mind/runtime` isolated, zero direct write to authoritative memory, zero direct tool execution, mandatory trace/ledger correlation, mandatory falsification test.

**[Final bottom line — mind/ SPIKE-FIRST / ContinuityOS VERIFIED_CURRENT]** Если коротко: **CTHA сейчас стоит подключать не “поверх spine как co-authority”, а “перед spine как proposer-only cognitive layer”.** В этой роли его `T/A` layers становятся ценными inner filters, `H-layer` становится полезным proposer/ranker, а tested spine `ContinuityOS preflight + ledger + durable execution` остаётся единственным authority plane для side effects и для truth promotion. Это и есть соединение brain и spine без передачи brain’у authoritative state. citeturn13view0turn14view0turn32view0turn35view0turn59view0turn57search1turn57search7