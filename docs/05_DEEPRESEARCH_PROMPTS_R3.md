# Deep Research промпты — раунд 3 (ContinuityOS + brain интеграция)

Контекст: спайк контрольного хребта **пройден** (`spikes/control_spine_v0/RESULT.md`) — реальный ContinuityOS `preflight()` + hash-chain `Ledger` + DBOS recovery + bwrap-песочница. Теперь два трека интеграции реального кода из `C:\PROJECTS` в MAWorld.

Оба промпта следуют дисциплине disclosure-pack (файлы `CONTINUITYOS_DEEP_RESEARCH_*`): каждое утверждение о ContinuityOS помечать `VERIFIED_CURRENT / OBSERVED_CURRENT / TESTED_LOCAL / HISTORICAL_IMPLEMENTATION / PROPOSAL / RESEARCH_ONLY / PRODUCT_HYPOTHESIS / SUPERSEDED / CONFLICTED / UNKNOWN`. Не превращать PROPOSAL/HISTORICAL в current implementation.

## Что уже проверено (TESTED_LOCAL, база для обоих промптов)

- `continuityos/gate/`: `preflight(ActionSpec, policy, ledger, context) -> {decision, reasons, ...}`. Решения `ALLOW/WARN/HOLD/DENY/REQUIRE_CONFIRMATION/DRY_RUN_ONLY`. `rm -rf /` → DENY, `npm test` → ALLOW. **TESTED_LOCAL.**
- `continuityos/gate/ledger.py`: `Ledger` — hash-chain SQLite (WAL), `.append()/.verify()/.export()`. Цепочка верифицируется. **TESTED_LOCAL.**
- OSS `README.md` (VERIFIED_CURRENT, прямая цитата): *"ContinuityOS does NOT intercept raw shell/MCP/tool calls by merely being installed; mandatory broker enforcement remains future work."* + *"ContinuityBench v0 is a 30-case hand-labeled regression corpus, not a security-boundary certification."*
- `gate_hook.py`: мост Hermes → gate, гейтит только `{terminal, execute_code}`. **OBSERVED_CURRENT.**
- `continuity_os/mind/` — когнитивное ядро (CTHA: `ctha.py`, `attention.py`, `authority.py`, active inference, GWT-шина). `MIND_ARCHITECTURE.md`: *"MIND — разум самого Continuity OS; пишет только в mind/runtime/; канон и 01_RUNTIME — только чтение"*, gate «Default-DENY». Статус зрелости — **PROPOSAL/RESEARCH_ONLY** (по их же дисклеймеру про экспериментальные примитивы).
- 32 теста в OSS-пакете. `BRAIN.md` в trunk — помечен `LEGACY PROMPT REFERENCE — NON-AUTHORITATIVE` (SUPERSEDED, не путать с mind/).

---

## ПРОМПТ №1 — Gemini Deep Research: ContinuityOS как обязательный брокер MAWorld

```
You are conducting evidence-driven Deep Research on integrating ContinuityOS as the
MANDATORY control-plane broker of a multi-agent operating environment (MAWorld).
OUTPUT LANGUAGE: Russian, technical terms in English. Label every ContinuityOS claim
with an evidence tag (VERIFIED_CURRENT / OBSERVED_CURRENT / TESTED_LOCAL /
HISTORICAL_IMPLEMENTATION / PROPOSAL / RESEARCH_ONLY / SUPERSEDED / CONFLICTED / UNKNOWN).
Do NOT convert proposals or historical claims into current implementation facts.

VERIFIED CONTEXT (do not relitigate — these are decided or tested):
- ContinuityOS v0.9.0, local-first, stdlib-core, single SQLite file, Apache-2.0.
  gate.preflight(ActionSpec) -> ALLOW/WARN/HOLD/DENY/REQUIRE_CONFIRMATION/DRY_RUN_ONLY.
  Hash-chain tamper-evident Ledger with verify(). [TESTED_LOCAL in our spike]
- KNOWN LIMITATION [VERIFIED_CURRENT, official README]: "ContinuityOS does NOT intercept
  raw shell/MCP/tool calls by merely being installed; mandatory broker enforcement remains
  future work." Enforcement today is opt-in via `continuity run` or an installed host hook
  (gate_hook.py, which gates only {terminal, execute_code} from Hermes).
- Our control-spine spike PASSED: Telegram(secret_token+nonce) -> gate preflight -> external
  effect (idempotent, fires once) -> bwrap sandbox verify -> hash-chain audit; killed with
  os._exit(137) mid-run, DBOS recovered the workflow with NO duplicate side effect.
- Decided stack (prior rounds): DBOS+Postgres durable runtime; Tier2 gVisor/rootless-OCI
  sandbox; Infisical secrets; OTel+Langfuse observability; NautilusTrader trading cell.
- Estate: single owner, Windows + WSL + Linux VPS, Thailand region.

RESEARCH TASKS:
1. MANDATORY ENFORCEMENT. The #1 gap: today the gate is bypassable (opt-in). Research
   concrete, OS-level ways to make EVERY side-effecting call (shell, file-write, network,
   MCP tool, provider-hosted tool) physically route through preflight() on our estate:
   Linux seccomp/eBPF syscall interception, LD_PRELOAD shims, a mandatory MCP broker proxy,
   Windows equivalents (WSL vs native), agent-sandbox egress-only-through-broker. For each:
   feasibility on Windows/WSL/Linux-VPS, bypass surface, performance overhead, failure mode
   (must be fail-closed). Rank by robustness vs single-owner ops cost. Cite primary docs.
2. GATE UNDER MCP 2026-07-28. The new MCP spec (stateless, OAuth2.1 resource servers,
   audience-bound tokens, incremental scope, MCP-* headers, async tasks) changes the broker.
   Map exactly what MCPPreflightAdapter must add to ActionSpec (we drafted contracts/control/
   ActionSpec.yaml). Header desync/leak risks, async-task reconciliation to original authz,
   default-HOLD on unknown protocol version. Produce a migration checklist.
3. LEDGER AT SCALE. ContinuityBench v0 is 30 hand-labeled cases (NOT a security cert). Design
   the path from that to a trustworthy audit: append-only guarantees under concurrent DBOS
   workers, WAL on Linux (not on network shares), external anchoring (periodic hash to append-
   only store), retention, and a regression corpus 10x larger. What breaks the hash-chain?
4. SANDBOX PRODUCTIONIZATION. Our spike used bubblewrap; prod target is gVisor/rootless-OCI.
   Concrete: gVisor runsc on the Linux VPS, KVM feasibility for Tier3 Firecracker, egress-deny
   enforcement per tier, how the Sandbox Broker maps to E2B/Modal fallbacks. Boot/teardown
   benchmarks and cost/1000 exec.
5. DBOS PRODUCTION. We proved DBOS recovery on SQLite. Migrate to Postgres: schema, executor
   identity, multi-process recovery, how Branch Ledger / External Effect Registry sit on top
   of DBOS workflow IDs. Windows-dev + Linux-VPS-prod concerns.

OUTPUT:
1. Executive verdict: how close is ContinuityOS to being a real mandatory broker (not opt-in)?
   INTEGRATE-AS-IS / HARDEN-FIRST / REPLACE-LAYER. Confidence.
2. Enforcement architecture (the exact mechanism to make bypass impossible on our estate).
3. Evidence table (claim / evidence tag / source path or URL / confidence).
4. MCP-2026 gate migration checklist.
5. Ledger-trust and sandbox-prod designs with benchmarks.
6. Risk register + falsification tests.
7. 30/60/90-day plan. One concrete next decision.
Cite exact file paths for ContinuityOS claims. Official docs over prose. No production-readiness
assumptions without TESTED_LOCAL evidence.
```

---

## ПРОМПТ №2 — GPT Deep Research: mind/ (CTHA brain) как когнитивный слой над хребтом

```
You are conducting evidence-driven Deep Research on connecting the ContinuityOS "mind"
cognitive core (CTHA) as a cognitive layer ON TOP OF an already-working control spine,
WITHOUT letting it own authoritative state. OUTPUT LANGUAGE: Russian, technical terms in
English. Label every claim about mind/ or ContinuityOS with an evidence tag (VERIFIED_CURRENT
/ OBSERVED_CURRENT / TESTED_LOCAL / PROPOSAL / RESEARCH_ONLY / SUPERSEDED / CONFLICTED /
UNKNOWN). The mind/ module is largely PROPOSAL/RESEARCH_ONLY by its own disclaimers — treat it
as design intent, not proven behavior, unless code/tests prove otherwise.

VERIFIED CONTEXT (decided/tested — do not relitigate):
- The control spine is REAL and TESTED_LOCAL: ContinuityOS gate.preflight (ALLOW/WARN/HOLD/
  DENY) + hash-chain Ledger + DBOS durable recovery + sandboxed execution. Side effects fire
  once, crash-recovery does not duplicate them.
- INVARIANTS (non-negotiable, from MAWorld master): LLM/agent never owns authoritative state;
  every side effect passes ContinuityOS preflight; replay != undo; vector index is derived, not
  truth; agents PROPOSE, evals DECIDE, human APPROVES canon.
- mind/ facts [OBSERVED_CURRENT from source]: CTHA 4-layer decision matrix (C cognitive /
  H high-level active-inference / T tactical Default-DENY gate / A active reflex/veto), GWT
  conscious-access bus, writes ONLY to mind/runtime/, reads canon/01_RUNTIME read-only,
  files ctha.py/attention.py/authority.py. Maturity: PROPOSAL — the OSS README explicitly says
  the authority-tagged multi-agent wrapper and twin are experiments, "not evidence of a
  validated behavioral twin or production multi-agent product."
- Adopted self-improvement loop design (docs/04_SELF_IMPROVEMENT_LOOP.md): SENSE->PROPOSE->
  BUILD->EVALUATE->GATE->CANARY->PROMOTE/ROLLBACK; GEPA for prompts, DGM-style for code;
  kill-switch fail-closed.
- Knowledge Foundry (docs/D7): FEVER-claims, PROV-O provenance, CanonicalDecision, contradiction
  records — the truth store the brain must respect.

RESEARCH TASKS:
1. AUTHORITY BOUNDARY: CTHA gate vs ContinuityOS gate. mind/ has its own "T-layer Default-DENY
   gate" and "A-layer veto". ContinuityOS has preflight(). Are these redundant, complementary,
   or CONFLICTED? Define exactly which gate is authoritative for external side effects (must be
   ContinuityOS preflight — the tested spine) and how CTHA's internal deliberation feeds a
   PROPOSED ActionSpec into it without ever bypassing it. Draw the trust boundary.
2. MEMORY INTEGRATION. mind/ writes to mind/runtime/; MAWorld has Governed Memory
   (PROPOSED->VALIDATED->APPROVED->ACTIVE) and Knowledge Foundry (canonical truth). Map how the
   brain's beliefs become PROPOSED memory mutations that flow through the promotion lifecycle
   and CanonicalDecision — never self-promoting to ACTIVE/canon. Resolve any CONFLICT with the
   invariant "agent never owns authoritative state."
3. ACTIVE INFERENCE AS PROPOSER. CTHA's H-layer (active inference, EFE, plan ranking) is a
   natural fit for the self-improvement loop's PROPOSE step. Assess feasibility of using CTHA to
   generate ImprovementProposals (contracts/improvement/) that are then gated by evals + human.
   What in mind/ is real code vs aspiration? Which parts need a falsification spike before trust?
4. OBSERVABILITY. CTHA writes ctha_trace.jsonl. Map this onto our TraceBridge/OTel/Langfuse and
   TraceContext so brain deliberation is auditable end-to-end and correlates with the hash-chain
   ledger. What identity/trace fields must CTHA emit?
5. MINIMAL SAFE CONNECTION. Design the smallest spike that connects mind/ to the proven spine:
   brain proposes -> ContinuityOS preflight -> (allowed) deterministic action -> audit, with the
   brain able to READ canon but PROVABLY unable to mutate authoritative state or bypass the gate.
   Include the falsification test (e.g., brain tries to write canon directly -> must be denied).

OUTPUT:
1. Executive verdict: CONNECT-NOW / SPIKE-FIRST / DEFER for the brain. Confidence.
2. Trust-boundary diagram: CTHA deliberation vs ContinuityOS authority.
3. Evidence table (claim / tag / source path / confidence) separating real code from PROPOSAL.
4. Memory + canon integration design (how beliefs reach canon safely).
5. mind/-as-proposer feasibility for the self-improvement loop.
6. Minimal safe-connection spike + its falsification test.
7. Risk register (top risk: brain bypassing the gate or self-promoting beliefs to truth).
8. 30/60/90 plan. One concrete next decision.
Cite exact file paths. Separate real implementation from design intent. Assume NO autonomous
authority for the brain until a spike proves the boundary holds.
```

---

## Ответ на твой вопрос: подключаем ContinuityOS первым?

**Да, и это уже сделано в спайке.** ContinuityOS — единственная точка, через которую проходят side effects; спайк импортирует твой реальный `preflight()` и `Ledger` и держит на них границу (DENY реально блокирует `rm -rf /` до эффекта, аудит — твой hash-chain). Это и есть «подключён первым».

**Про brain (`mind/`, CTHA) — вторым, и через спайк.** По его же `MIND_ARCHITECTURE.md` он «пишет только в mind/runtime, канон только читает» — то есть он потребитель хребта, а не сам хребет. Плюс OSS-README прямо помечает mind-слой как эксперимент, не как проверенный продукт. Поэтому промпт №2 требует сначала falsification-спайк границы (мозг предлагает → preflight решает → мозг не может мутировать канон), и только потом доверие. `BRAIN.md` в trunk не путать — он помечен LEGACY/NON-AUTHORITATIVE; настоящий мозг это `mind/`.

**Ключевая находка для обоих:** твой же README честно говорит — *"mandatory broker enforcement remains future work"*. Сейчас гейт **обходим** (opt-in через `continuity run`/hook). Это задача №1 промпта №1: сделать его физически обязательным (seccomp/eBPF/broker-proxy), иначе весь инвариант «всё через гейт» держится на честном слове.
