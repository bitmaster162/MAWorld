# Research Addendum R2 — 15 июля 2026 (раунд 2)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Это архив исследовательских выводов, а не текущая
> архитектурная истина, security-вердикт, разрешение на деплой или инструкция к исполнению. Старые
> статусы, оценки готовности, команды и численные результаты ниже не являются действующими гейтами.
> Актуальные источники: [полный security-аудит](44_SECURITY_HARDENING_2026-07-16.md),
> [текущий deploy-gate](../DEPLOY.md) и [Rust security HOLD](../apps/knowledge-foundry/RUST_SECURITY_HOLD.md).
> **LIVE остаётся OFF.**

Сведение трёх новых отчётов (D5-D7) + собственное исследование Claude по самоулучшению.

## Часть 1. Что решили отчёты раунда 2

### D5 — Trading Cell (Gemini, ответ на промпт №1)

| Задача | Вердикт | Conf |
|---|---|---|
| Движок | **ADOPT NautilusTrader v2** (Rust core, 128-bit fixed-point, PyO3; RiskEngine — точка врезки ContinuityOS; единственный риск — писать кастомные NATS/SBE DataClient/ExecutionClient) | 0.95 |
| Биржи | **ADOPT Hyperliquid** (перпы, cloid, Таиланд не заблокирован, testnet) + **ADAPT Binance TH** (спот THB, newClientOrderId). **REJECT OKX/Bybit** (заблокированы SEC TH), Bitkub (жёсткие user-id лимиты), IBKR (подписки на данные) | 0.98 |
| Маркет-дата | **ADOPT ArcticDB** (битемпоральность, `read(as_of=...)`, LMDB, serverless) для Research Plane + **Nautilus ParquetDataCatalog** для бэктест-ядра | 1.00 |
| Look-ahead bias | **ADAPT Look-Ahead-Bench**: запрет online-tools у аналитиков, принудительный `as_of`, Entity Embedding Neutralization (анонимизация тикеров), walk-forward, метрика Alpha Decay (15-22 п.п. падения out-of-sample — фиктивная доходность in-sample реальна) | 0.98 |
| LLM-аналитика | **ADAPT TradingAgents** (роли + Bull/Bear дебаты + structured outputs + SQLite decision log), **REJECT** LLM-роли Portfolio Manager/Risk → детерминированный Synthesizer → SignalProposal через NATS/SBE | 1.00 |
| Сверка | **ADOPT** Nautilus reconciliation (`refresh_account_state()`, `is_duplicate_fill()`, `generate_missing_orders` с тегом RECONCILIATION) + UUIDv7 ClientOrderId везде | 0.99 |
| Промоция | **ADAPT** Nautilus Nodes + свой **PromotionRouter**: SHADOW = перехват в OrderEmulator; CANARY = принудительное масштабирование quantity | 0.95 |

Контракты: SignalProposal, OrderIntent, ReconciliationReport, VenueAdapter → `contracts/trading/`.
MVP: Hyperliquid **Testnet** paper, Nautilus v2 на Linux VPS, стресс `kill -9` c ордерами in-flight, ноль дублей.

### D6 — Control Spine (GPT, ответ на промпт №2)

| Задача | Вердикт | Conf |
|---|---|---|
| Workflow runtime | **ADAPT DBOS + Postgres** сейчас (workflow ID = idempotency key, resume с последнего шага, exactly-once транзакции); Branch Ledger/Effect Registry — свой слой сверху; **Temporal = migration target** | 0.88 |
| Agent harness | **ADOPT тонкий свой harness** + LiteLLM/OpenRouter-роутинг; провайдерские SDK только как адаптеры (OpenAI — режим `Agent.as_tool()`, не handoff с полной историей); ADK — UNRESOLVED, MS Agent Framework — референс, не граница | 0.90 |
| MCP 2026-07-28 | Нормативный текст НЕ добыт (SOURCE CLAIM 0.45!) → **ADAPT защитно**: version-gating, default HOLD на неизвестные MCP-* заголовки, audience/scope binding в ActionSpec, reconciliation async-задач | 0.72 |
| Observability | **ADOPT OTel + self-hosted Langfuse**; свой TraceBridge-адаптер (semconv GenAI ещё движется — не биндить аудит к сырым именам); Phoenix — путь расширения evals | 0.91 |
| Cost | Оркестратор → OpenAI напрямую, супервизор → Anthropic напрямую; OpenRouter только PUBLIC/INTERNAL с `data_collection:deny` + `zdr:true`; кэш промптов (OpenAI cached $0.5/M; Anthropic reads 0.1x) + Batch (−50%). Диапазоны: light $60-180, medium $250-900, heavy $1200-4000/мес (HYPOTHESIS 0.63) | 0.84 |
| Secrets | **ADOPT Infisical** (runtime) + SOPS+age (bootstrap); identity = внутренние подписанные делегации + короткоживущие ключи по роли/классу данных; Vault/SPIFFE — потом. Telegram: webhook `secret_token` + nonce + expiry на одобрения | 0.90 |
| Sandbox | Tier2 = **локальный gVisor/rootless OCI ADOPT**; Tier3 = Firecracker только при проверенном KVM, иначе **E2B ADAPT**; Tier4 = **Modal GPU ADOPT**; **Daytona HOLD** (нет официальных доков изоляции). Стоимость ~$2.76-3.97/1000 исполнений (60с) | 0.87 |

Новые компоненты: DurableRuntimeAdapter, ProviderHarness, MCPPreflightAdapter, TraceBridge, EvalRegistry, BudgetEnforcer, SecretsBroker. Контракты: ActionSpec-delta, TraceContext, EvalRecord, BudgetPolicy → `contracts/control/`.

### D7 — Knowledge Foundry (Gemini)

Система знаний для хаотичного корпуса MAWorld. **NARROW AND BUILD.**
- Хранение: **PostgreSQL единая БД** (pgvector HNSW + FTS + Recursive CTE для графов) — Qdrant/Weaviate/Elastic отклонены; **MinIO** для иммутабельных сырых блобов; концепты lakeFS для версионирования.
- Модель: Artifact (SHA-256) → ArtifactVersion/DuplicateCluster → ExtractionRecord (парсинг в microVM-песочнице) → **Claim** (FEVER-стиль, атомарные, exact_source_excerpt) → EvidenceLink (SUPPORTS/REFUTES) → ContradictionRecord → **CanonicalDecision** (явный подписанный акт владельца) → ADR/ImplementationLink → Runtime Evidence (обратная связь).
- Provenance: W3C PROV-O (Entity/Activity/Agent), trust по источникам (PRIMARY_CODE / INDEPENDENT_RESEARCH / UNVERIFIED_IMPORT / VENDOR_CLAIM).
- ResearchRun + ContextManifest: слепые независимые прогоны с хешами входов; расхождение моделей → DecisionConflict.
- Инварианты: текст источника ≠ инструкция; вектор — производный индекс; дубликаты кластеризуются, не удаляются; противоречия — сигнал, не ошибка; код vs документация — решает владелец.
- Границы: Knowledge Foundry (истина) / LifeOS Memory (приватная память агентов, read-only доступ к канону) / ContinuityOS (политики) / Workflow Runtime (джобы) / Evidence Engine (верификация) / Git (код).
- 24 схемы, 31 failure-тест, 20 тикетов, 7-дневный план, 30/60/90 roadmap.

### Совместимость D5/D6/D7 — конфликты

1. **Sandbox для парсинга**: D7 требует microVM для парсеров; D6 говорит Tier3 microVM только после KVM-спайка. Решение: парсинг Tier2 (gVisor) в MVP, microVM после спайка — риск парсинга ниже произвольного кода.
2. **SBE на SignalProposal** (D5) vs "JSON в Intelligence Plane" (D1): SignalProposal пересекает границу плоскостей → SBE оправдан на транспорте NATS, JSON-представление остаётся в аудите. Не конфликт.
3. **Postgres теперь обязателен** (DBOS + Knowledge Foundry) — SQLite остаётся только у ContinuityOS (политики/память). Двух-БД модель зафиксирована.

## Часть 2. Собственное исследование — самоулучшение (требование раунда 2)

Задача владельца: «коробка сама должна уметь себя улучшать с помощью агентов». Проверенные механизмы:

1. **Darwin Gödel Machine** (Sakana AI, arXiv 2505.22954): агент итеративно переписывает собственный код, каждое изменение **эмпирически валидируется на бенчмарках**, ведётся архив вариантов (эволюционное дерево, не единственная линия). Ключевой урок: самоулучшение = поиск с эмпирическим фитнесом, не "доказуемая" самомодификация.
2. **AlphaEvolve** (DeepMind): эволюция решений против автоматических evaluator'ов — паттерн "generate → evaluate → select" для улучшения конкретных алгоритмов/модулей.
3. **GEPA** (ICLR 2026, gepa-ai/gepa, DSPy): рефлексивная эволюция промптов по execution traces — читает трейсы, диагностирует провалы на естественном языке, держит Парето-фронт кандидатов. До +20% против RL при 35× меньшем числе прогонов. Уже в проде (Decagon, Nous Hermes self-evolution). **Прямо ложится на наш EvalRegistry + Langfuse traces.**
4. **Self-improving skills** (паттерн Claude Agent Skills 2026): агент курирует собственные skill-файлы — reflection hook после исполнения, learnings-файл, промоция проверенных паттернов из «предложений» в «правила». Ложится на наш Governed Memory promotion lifecycle.
5. **MAS-PromptBench** (arXiv 2606.23664): оптимизация промптов в мультиагентных системах помогает не всегда — нужен eval-gate до принятия.

**Вывод:** все четыре механизма сводятся к одному контуру: *телеметрия → предложение → песочница → детерминированная оценка → gate → канареечное внедрение → промоция/откат*. У нас уже есть все примитивы для его безопасной реализации (Branching, EvalRegistry, Sandbox tiers, Effect Registry, ContinuityOS, Knowledge Foundry canonization). Дизайн контура: `04_SELF_IMPROVEMENT_LOOP.md`.

## Источники (собственное исследование)

- https://arxiv.org/abs/2505.22954 (Darwin Gödel Machine) · https://aipapersacademy.com/darwin-godel-machine/
- https://github.com/gepa-ai/gepa · https://gepa-ai.github.io/gepa/ · https://decagon.ai/blog/optimizing-gepa-for-production
- https://the-agent-report.com/2026/06/hermes-agent-self-evolution-dspy-gepa-june2026/
- https://arxiv.org/pdf/2606.23664 (MAS-PromptBench)
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview · https://github.com/anthropics/skills
- https://arxiv.org/pdf/2602.05848 (DARWIN: Dynamic Agentically Rewriting Self-Improving Network)
