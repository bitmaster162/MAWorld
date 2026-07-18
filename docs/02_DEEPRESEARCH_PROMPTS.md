# Deep Research промпты — раунд 2 (июль 2026)

Два непересекающихся трека. №1 → Gemini Deep Research (Trading Cell). №2 → GPT Deep Research (Agent Runtime & Ops). Копируй блок целиком, включая контекст. Ответы вернутся на русском (язык задан внутри).

---

## ПРОМПТ №1 — Gemini Deep Research: Trading Cell Concretization

```
ROLE: You are a principal trading-systems architect performing a source-backed, build-ready study. Verify every claim against official docs, repos, and primary sources with URLs. Mark each claim: VERIFIED FACT / SOURCE CLAIM / INFERENCE / HYPOTHESIS / UNRESOLVED. Confidence 0.00-1.00 per verdict. OUTPUT LANGUAGE: Russian, keep technical terms in English.

CONTEXT (decided architecture — do NOT relitigate):
- Single-owner multi-agent operating environment, three planes: Research/Intelligence (LLMs), Deterministic Trading Plane (no LLMs, no vector DBs, no provider tools on hot path), Control/Observation (policy gateway "ContinuityOS", approvals via Telegram, append-only audit).
- LLMs never own authoritative state. All side effects pass a deterministic preflight gate (ALLOW/WARN/HOLD/DENY).
- Hot-path decisions already made: direct in-process calls for order admission; atomic kill-switch register read directly by admission path; custom lock-free MPMC queues REJECTED; float64 banned in money fields (fixed-point only); NATS JetStream for off-hot-path durable messaging; SBE for binary serialization outside the core; JSON banned in the trading plane.
- Risk limits owned by deterministic RiskService: max drawdown 10% hard stop, ≤20 trades/day, 3 consecutive losses → 1h pause, ≤1% risk per trade. Kill-switches: stale data >100ms, reconciliation mismatch, strategy heartbeat loss (reduce-only mode).
- Strategy promotion ladder: RESEARCH → BACKTEST → FORWARD_TEST → PAPER → SHADOW → CANARY → RESTRICTED_LIVE → PAUSED → RETIRED.
- Deployment: single owner, Thailand region; estate = Windows + WSL + Linux VPS; no HFT colocation; latency target is "low", not "ultra-low" (sub-ms on one host is enough, microsecond-class not required).
- Every LLM-generated trading signal is untrusted input requiring deterministic validation before OrderIntent.

RESEARCH TASKS:
1. BUILD VS ADOPT — core engine. Compare building our custom deterministic trading microservices vs adopting NautilusTrader (nautilustrader.io, nautechsystems/nautilus_trader) as the Trading Cell foundation. Evaluate: determinism guarantees, event-driven replay, backtest-live parity, Rust core + Python control plane fit, extension points for our ContinuityOS preflight gate and kill-switch register, state ownership compatibility (can our RiskService remain authoritative?), operational burden for one owner. Also assess hftbacktest, Freqtrade, Hummingbot, QuantConnect LEAN as alternatives. Verdict per option: ADOPT / ADAPT / REJECT + integration risk list.
2. VENUE AND CONNECTIVITY. For a Thailand-based individual (non-institutional): which crypto venues (Binance, Bybit, OKX, Bitkub, Hyperliquid, others) offer the best combination of: API quality (REST+WS, order idempotency via clientOrderId, rate limits), testnet/paper environments, reconciliation endpoints (fills, balances), legal accessibility from Thailand, fees. If tradfi brokers with API (Interactive Brokers etc.) are viable from Thailand, cover briefly. Output: venue comparison matrix + recommended primary/secondary venue.
3. MARKET DATA LAYER. Ingestion and storage for ticks/candles/order book: evaluate QuestDB, ArcticDB, TimescaleDB, ClickHouse, Parquet+DuckDB for a single-node estate. Criteria: write throughput, point-in-time correctness for backtests, storage cost, ops burden. Recommend one primary.
4. BACKTEST INTEGRITY FOR LLM SIGNALS. How to prevent look-ahead bias when LLM-agents (analyst crews in the Research Plane) contribute signals: point-in-time data discipline, prompt/data snapshotting, walk-forward protocol, references to Look-Ahead-Bench and similar. Define a deterministic validation contract between Research Plane signal proposals and Trading Plane admission.
5. LLM ANALYST LAYER (off hot path). Evaluate TauricResearch/TradingAgents and ContestTrade patterns as donors for our analyst/bull-bear/risk-debate roles: what to reuse (role prompts, debate structure), what to reject (any direct order authority). Map their roles onto our adjudication protocol (primary → challenger → synthesizer → deterministic verifier).
6. RECONCILIATION AND RECOVERY. Best-practice patterns for position/balance reconciliation against venue APIs, duplicate-order prevention (idempotency keys + venue clientOrderId), crash recovery of the trading cell without replaying external side effects. Cite real implementations.
7. PROMOTION TOOLING. Concrete tooling for each ladder stage: backtest harness, forward-test infra, paper trading via venue testnets, shadow mode (compute intents, don't send), canary sizing. What does NautilusTrader (or chosen engine) give for free vs what we build?

OUTPUT FORMAT:
- 01_EVIDENCE_AUDIT: claims table (claim / source / official evidence / verified status / correction / confidence).
- 02_VERDICTS: per task, ADOPT/ADAPT/REJECT/HOLD + confidence + revisit trigger.
- 03_ARCHITECTURE_DELTA: only new/changed components vs the context above; Mermaid diagrams for signal-to-order flow and reconciliation.
- 04_CONTRACTS: YAML logical contracts for SignalProposal, OrderIntent, ReconciliationReport, VenueAdapter interface.
- 05_BACKLOG: table (title / component / rationale / dependencies / acceptance criteria / security test / benchmark).
- 06_MVP_DECISION: what enters first trading MVP (paper only), smallest falsification spike.
- Sources with URLs for every verdict. No marketing claims without primary-source verification.
```

---

## ПРОМПТ №2 — GPT Deep Research: Agent Runtime, Governance & Ops

```
ROLE: You are a principal platform architect performing a source-backed, build-ready study. Verify every claim against official docs, specs, and repos with URLs. Mark each claim: VERIFIED FACT / SOURCE CLAIM / INFERENCE / HYPOTHESIS / UNRESOLVED. Confidence 0.00-1.00 per verdict. OUTPUT LANGUAGE: Russian, keep technical terms in English.

CONTEXT (decided architecture — do NOT relitigate):
- Single-owner multi-agent OS, three planes (Intelligence / Deterministic Trading / Control). LLMs plan and critique; deterministic services own workflow state, policy, budgets, approvals, audit, kill-switches.
- Policy gateway "ContinuityOS": SQLite-backed (WAL), gate_hook.py preflight intercepts every side-effecting tool call → ALLOW/WARN/HOLD/DENY; append-only audit ledger; canonical memory in SQLite, vector index derived (never source of truth).
- Adopted primitives (contracts already designed): Immutable Workflow Branching & Replay (Checkpoint Store, Branch Ledger, External Effect Registry with idempotency + reversibility classes; replay never re-fires side effects); Capability-Scoped Artifact Handoffs (HandoffEnvelope with artifact pointers + structured summary by default, capability/policy resolved separately from delegation); Governed Memory (PROPOSED→VALIDATED→APPROVED→ACTIVE lifecycle, no agent self-promotion); Risk-Tiered Sandboxing (Tier0 none / Tier1 WASM / Tier2 gVisor-rootless OCI / Tier3 microVM after feasibility / Tier4 dedicated worker).
- Model bindings: GPT-5.6 Sol = semantic orchestrator; Claude Fable 5 = strategic supervisor; Grok 4.5 = independent challenger (PUBLIC/INTERNAL data only, X/Web output treated as untrusted data); GLM 5.2, Nemotron 3 Ultra = executors/background. Data classes PUBLIC→CREDENTIAL route providers; FINANCIAL_SENSITIVE only to zero-data-retention providers.
- Estate: Windows + WSL + Linux VPS, single owner, Telegram as human control channel, Thailand region.

RESEARCH TASKS:
1. WORKFLOW RUNTIME CHOICE. Our Branch Ledger / Checkpoint Store / External Effect Registry need a durable execution substrate. Compare: (a) Temporal self-hosted, (b) DBOS (Postgres-embedded library), (c) Restate, (d) LangGraph checkpointers + Postgres, (e) custom ledger on NATS JetStream + Postgres. Criteria: fit to our contracts (immutable branching, fork-from-checkpoint, replay that never re-executes external effects), single-owner ops burden, Windows/WSL dev + Linux VPS prod, failure recovery, licensing/cost. Verdict + migration triggers.
2. AGENT HARNESS. Our roles are multi-provider by design. Compare Claude Agent SDK, OpenAI Agents SDK/AgentKit, LangGraph (incl. deepagents), Microsoft Agent Framework, Google ADK, and a thin custom harness over raw APIs + LiteLLM/OpenRouter routing. Which harness (or combination) best hosts our HandoffEnvelope semantics without smuggling authority? Resolve previously-PARTIAL verifications: Google ADK agent-transfer semantics and Microsoft Agent Framework workflow transitions — from official docs/repos at line level.
3. MCP 2026-07-28 SPEC REVISION. The new MCP spec (stateless protocol, OAuth 2.1 resource servers, audience-bound tokens, incremental scope consent, new MCP-* HTTP headers, async tasks, deprecation lifecycle) changes our threat model. Audit our ContinuityOS gate design against it: what old mitigations (session guards, token-passthrough bans) become native, what new risks appear (desync via MCP headers, header data leakage, async-task state confusion), what must change in gate_hook.py preflight and ActionSpec schema. Produce a concrete migration checklist.
4. OBSERVABILITY & EVALS (currently missing from our architecture). Design the layer: OpenTelemetry GenAI semantic conventions (current status/stability), self-hosted Langfuse vs Arize Phoenix vs LangSmith for traces+costs, structured audit correlation (correlation_id/causation_id/trace_id already in our envelopes). Plus agent evaluation: regression eval harness for role prompts (orchestrator/challenger/synthesizer), golden-set adjudication tests, drift detection for model upgrades. Recommend a minimal single-owner stack.
5. COST ENGINEERING. Token budget enforcement exists as a service concept; design the routing policy: prompt caching (per provider, incl. Anthropic/OpenAI current mechanics and prices), batch APIs for background work (Nemotron/GLM), OpenRouter vs direct API tradeoffs, per-role model fallback chains, budget circuit breakers (P0/P1 reserve already defined). Provide expected monthly cost bands for: 1 orchestrator + 1 supervisor + 1 challenger + 2 executors under light/medium/heavy usage.
6. SECRETS & IDENTITY. For a single-owner estate: secrets management (local vault options: HashiCorp Vault vs Infisical vs SOPS+age vs OS keychains), per-agent service identity, scoping API keys per role/data-class, Telegram bot hardening (approval spoofing prevention, replay protection).
7. SANDBOX PROVIDER DECISION. Finalize the Tier map with providers: local gVisor/rootless OCI vs Daytona (Tier2), local Firecracker vs E2B (Tier3), Modal for GPU (Tier4). Feasibility on our estate (Windows/WSL nested-virt constraints, Linux VPS KVM availability), egress-deny enforcement per provider, cost per 1000 executions. Verdict per tier.

OUTPUT FORMAT:
- 01_EVIDENCE_AUDIT: claims table (claim / source / official evidence / verified status / correction / confidence).
- 02_VERDICTS: per task ADOPT/ADAPT/REJECT/HOLD + confidence + revisit trigger.
- 03_ARCHITECTURE_DELTA: only new/changed components; Mermaid for the observability pipeline and the revised MCP-era gate flow.
- 04_CONTRACTS: YAML deltas only (e.g., ActionSpec changes for MCP 2026, TraceContext, EvalRecord, BudgetPolicy).
- 05_BACKLOG: table (title / component / rationale / dependencies / acceptance criteria / security test / benchmark).
- 06_MVP_DECISION: minimal runtime+observability stack for first vertical slice (Telegram → API Gateway → orchestrator plan → ContinuityOS preflight → deterministic verification → audit trace), smallest falsification spike.
- Sources with URLs for every verdict. Official docs over blogs; no vendor marketing without primary verification.
```

---

## Почему такое разделение

- №1 закрывает открытые вопросы мастер-дока: 1 (NautilusTrader), 7 частично (венью для Money Forge-платежей не трогаем — это Stripe, отдельно).
- №2 закрывает: 2 (runtime), 3 (MCP-ревизия), 4 (observability), 5 (ADK/MS AF PARTIALs), 6 (частично — retention в задаче 5/6).
- Оба промпта фиксируют принятые решения в CONTEXT, чтобы DR не пересматривал архитектуру, а конкретизировал её.
- После получения обоих ответов: сводим дельты в 00_MASTER v1.1 → собираем каркас в MAWorld → раскладываем твои существующие модули по слотам каркаса.
