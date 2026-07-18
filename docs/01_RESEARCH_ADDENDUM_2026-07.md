# Research Addendum — проверка Claude, 15 июля 2026

Собственное исследование поверх 4 отчётов: что подтвердилось, что устарело, что отсутствовало.

## 1. NautilusTrader — главный вызов решению "строить Trading Cell с нуля"

Production-grade Rust-native движок: детерминированная event-driven архитектура, research-to-live parity (стратегия из бэктеста идёт в лайв без изменений кода), наносекундные симуляции с моделями fill/fee/latency/order-book, Python как control plane. Активная разработка (релизы июнь 2026).
**Влияние:** D1 предписывает кастомные детерминированные микросервисы (NATS/SBE). NautilusTrader уже реализует ~70% Trading Cell, включая промоцию бэктест→лайв, которую мы оценивали в 10-15 дней исследований. Решение build-vs-adopt — вопрос №1 для DR-промпта №1. D3 уже ссылался на его архитектуру как референс.

## 2. Durable execution: Temporal больше не безальтернативен

- **DBOS** — библиотека внутри приложения, состояние в вашем Postgres, ~7 строк интеграции, минимальный ops-след. Для одного владельца — сильный кандидат.
- **Restate** — durable runtime, HTTP-native, воркфлоу = HTTP-хендлеры, проще в эксплуатации чем Temporal.
- **Temporal** — зрелый, но требует отдельного кластера и переархитектуры.
Консенсус 2026: "начинай с DBOS, возвращайся к Temporal когда упрёшься".
**Влияние:** наш Branch Ledger + Checkpoint Store (D2) может лечь поверх DBOS/Postgres вместо кастомного слоя или тяжёлого Temporal. → DR-промпт №2.

## 3. TradingAgents (TauricResearch) — готовые multi-agent торговые роли

Open-source фреймворк: 4 аналитика (fundamentals/sentiment/news/technical), bull/bear-исследователи, трейдер, риск-менеджер, портфельный менеджер; структурированные дебаты; LangGraph; v0.2.0 — мультипровайдерность (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x, GLM, OpenRouter, Ollama). Это точно наш паттерн Research Plane для Domain A — кандидат на донорство модулей/промптов. Смежное: ContestTrade (internal contest mechanism), Look-Ahead-Bench (бенчмарк look-ahead bias в point-in-time LLM — важно для честных бэктестов LLM-сигналов).

## 4. Агентные SDK 2026 — карта

- **Claude Agent SDK** (переименован из Claude Code SDK): готовый цикл, "дай агенту компьютер", глубочайшая MCP-интеграция (200+ серверов). Минус: только Claude.
- **OpenAI Agents SDK/AgentKit**: handoffs как ядро; добавлены sandboxed execution environments. Минус: только OpenAI.
- **LangGraph**: графы, чекпоинты, time-travel-отладка в Studio, мультипровайдерность.
**Влияние:** наши роли мультипровайдерны by design ⇒ либо LangGraph как harness, либо тонкий свой слой поверх raw API + наши контракты (HandoffEnvelope уже спроектирован). → DR-промпт №2.

## 5. Letta — статус PARTIAL закрыт

Официальные доки доступны: memory blocks (human/persona/custom), shared blocks между агентами (общий read/write workspace), **MemFS** — git-backed файловая система памяти (markdown + история версий + разрешение конфликтов). Иерархия: main context / recall / archival.
**Влияние:** подтверждает наш выбор — брать tiering, но promotion lifecycle оставлять свой (Letta-агенты сами правят память — у нас запрещено). Git-backed память рифмуется с нашим Agent Registry в Git.

## 6. Сандбоксы — статус PARTIAL закрыт

- **E2B**: Firecracker microVM, ~150 мс cold start, отдельное ядро на сессию → наш Tier 3 managed-вариант.
- **Daytona**: hardened OCI/Docker, ~27-90 мс, session-based, persistent processes → Tier 2 managed-вариант.
- **Modal**: GPU-workloads. Цены E2B/Daytona ~паритет (~$0.05/vCPU-час).
**Влияние:** тир-модель D2/D3 подтверждается рынком; адаптеры маппятся 1:1 (Tier2=Daytona/gVisor local, Tier3=E2B/Firecracker local, GPU=Modal/Tier4).

## 7. A2A 1.0 — stable

Linux Foundation, 150+ организаций, SDK на 5 языках, v1.0: multi-protocol, multi-tenancy, обновлённые security flows. Подтверждён вердикт D2: A2A = внешняя federation-граница (если понадобится интеграция с чужими агентами), не внутренняя handoff-семантика.

## 8. ⚠ MCP 2026-07-28 — протокол стал stateless; ревизия ContinuityOS gate обязательна

Release candidate финализируется 28.07.2026: протокол stateless; MCP-серверы = OAuth 2.0 resource servers (OAuth 2.1, PKCE, audience-bound tokens); incremental scope consent (минимальный доступ на операцию); новые HTTP-заголовки (MCP-Method и др. — риск desync-атак и утечек через заголовки); async tasks; формальный lifecycle/deprecation (12 мес.).
**Влияние:** D1 писался под старую спеку. Хорошее: audience-bound tokens + incremental scopes нативно закрывают token passthrough и частично confused deputy. Плохое: stateless-модель переносит границы безопасности на разработчика — наш gate_hook.py и ActionSpec надо перепроверить под новые заголовки/async tasks. → DR-промпт №2, приоритет.

## 9. Наблюдаемость и evals — дыра во всех 4 отчётах

Индустрия сошлась на **OpenTelemetry GenAI semantic conventions** (gen_ai.* атрибуты: промпты, модели, токены, tool/agent calls; статус experimental, но default transport 2026). Open-source бекенды: **Langfuse** (OTLP endpoint), Arize Phoenix; Datadog/New Relic/Dynatrace поддерживают семконв нативно. Отдельная тема — регрессионные evals агентов.
**Влияние:** в каркас с первого дня: OTel-инструментирование всех агентных вызовов + self-hosted Langfuse. Дешевле заложить сейчас, чем прикручивать потом. → DR-промпт №2.

## Сводка влияния на мастер-док

| Находка | Действие |
|---|---|
| NautilusTrader | build-vs-adopt в DR №1; не начинать кастомный trading-код до ответа |
| DBOS/Restate | кандидаты на Workflow Runtime в DR №2 |
| TradingAgents | донор ролей/промптов Research Plane |
| Letta, E2B/Daytona | PARTIAL→VERIFIED; тир-карта подтверждена |
| A2A 1.0 | остаётся external-boundary, ничего не меняем |
| MCP 2026-07-28 | ревизия gate_hook/ActionSpec — в MVP backlog |
| OTel GenAI + Langfuse | новый обязательный элемент каркаса |

## Источники

- https://github.com/nautechsystems/nautilus_trader · https://nautilustrader.io/docs/latest/concepts/overview/
- https://www.tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution · https://www.restate.dev/vs/temporal · https://www.zenml.io/blog/temporal-alternatives
- https://github.com/tauricresearch/tradingagents · https://arxiv.org/pdf/2508.00554 (ContestTrade) · https://arxiv.org/pdf/2601.13770 (Look-Ahead-Bench)
- https://qubittool.com/blog/ai-agent-framework-comparison-2026 · https://www.morphllm.com/ai-agent-framework · https://docs.langchain.com/oss/python/deepagents/comparison
- https://docs.letta.com/letta-agent/memory · https://docs.letta.com/tutorials/shared-memory-blocks/
- https://baeseokjae.github.io/posts/e2b-vs-daytona-vs-blaxel-2026/ · https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes
- https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ · https://www.akamai.com/blog/security-research/new-mcp-specification-security-teams-must-prepare · https://stacktr.ee/blog/mcp-2026-spec-changes
- https://zylos.ai/research/2026-02-28-opentelemetry-ai-agent-observability · https://langfuse.com/integrations/native/opentelemetry · https://signoz.io/comparisons/llm-observability-tools/
