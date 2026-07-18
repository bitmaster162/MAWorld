# Pre-DR-4 — собственное исследование (Evidence / Observability / Money Forge / Cockpit)

Раунд 13, 2026-07-15. Пока GPT DR-3 (LifeOS) идёт, готовлю почву под DR-4, чтобы Evidence Engine
уже понимал, ЧТО проверять, а Operator Cockpit — что показывать. Всё привязано к нашим доказанным
примитивам (анти-задвоение).

## 0. Ключевая находка: Universe Hub manifest = прототип Operator Cockpit
`:8120/manifest` уже отдаёт РЕАЛЬНЫЙ реестр из 13 систем (Control Center, ContinuityOS, MIND, Reflex,
PFI/Brain, Trading/Arena, Sim-OS, Forge/x402, Inner Circle, BitEvo, Knowledge Lab, Executor Network,
Physical AI Factory) с полями `status`, `truthStatus` (claimed/evidenced/verified/**contradicted**),
`executionMode` (halted/read_only/approval_required/…), `modules`, и маршрутами `/evidence`,
`/conflicts`, `/work-orders`, `/timeline`. Это буквально словарь Evidence Engine + скелет Cockpit из
DR-4 — **строить Cockpit с нуля не нужно**, он садится на этот manifest как источник.

## 1. Observability — вердикт (после реального сравнения, как требует план)
- **Langfuse — основной** trace/eval/annotation-слой: лицензия **MIT (OSI)** — критично для суверенной
  single-owner системы (Phoenix = ELv2, не-OSI); ядро на **Postgres** (совпадает с нашим DBOS/Postgres
  стеком после M8); нативный **cost & token tracking по 100+ моделям** = прямой источник метрики
  «**cost per verified outcome**»; audit logs + annotation queues под human-review.
- **Phoenix — вторичный**, для eval/эксперимента (LLM-as-judge над трейсами) — берём при необходимости.
- **Провод — OTel + OpenInference**: эмитим спаны в стандарте, чтобы не залочиться (портируемо между
  Langfuse/Phoenix). В 2026 базовые `gen_ai.*` client-атрибуты (system, request.model, token counts)
  **стабильны**; agent/framework-спаны ещё Development → включаем явным
  `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`.
- Наш `contracts/CANONICAL_CONTRACTS_v1.md #18 TraceContext` + `services/eval-registry` уже совместимы —
  Langfuse/Phoenix это BACKEND под них, не замена.

## 2. Evidence Engine — ВНЕДРЁН (core), не только исследован
`services/evidence-engine/` (24/24). Формализует `Audit≠Evidence≠Acceptance` и поток
`Claim→EvidenceRequirement→Collection→VerificationResult→AcceptanceDecision→RegressionFixture`.
Реальные детерминированные верификаторы:
- file → recompute sha256 / substring; commit → `git cat-file` + `git show --name-only` diff;
  tests → реальный exit-code; workflow → effect fired **ровно 1** (тот же инвариант, что M8);
  memory → promotion state ACTIVE + human approval; continuity → model-swap test.
- **Инвариант доказан тестами:** агент НЕ принимает свою работу — `accept()` требует VERIFIED от
  верификатора; self-claim «готово» без доказательства → reject. Подделанный sha / фейковый commit /
  дубль-эффект / непромоутнутая память → reject.
- **Money Forge инвариант:** vanity (views/likes/model_interest/artifacts) НИКОГДА не acceptance —
  только payment/renewal/signed_pilot/retained_usage. Pilot gate: **5 пилотов → ≥3 платят $199 → SCALE**,
  иначе HOLD (закодировано, протестировано).
- **Failure→asset:** каждый провал → `RegressionFixture` (failure_class + repro) для CI.

## 3. Money Forge — контракты (готовы к DR-4)
Цикл DISCOVER→SCORE→RESEARCH→VALIDATE→PROTOTYPE→DISTRIBUTION→PAYMENT→RETENTION→SCALE/ITERATE/KILL
уже гейтится `apps/money-forge/money_forge_gate.py` (11/11: соц-внимание ≠ валидация) + реальный
Stripe verifier (M3). Evidence Engine добавляет ACCEPTANCE-слой: продукт «успешен» только по
payment/renewal. Первый wedge (из DR-4): **ContinuityOS как policy-and-evidence boundary для coding/
operational агентов** — и у нас это уже РАБОТАЕТ (gate DENY на реальном ContinuityOS + Evidence Engine).

## 4. Frontier Research Lab — маппинг на существующее
Роли (Director/Primary-Source/Parallel/Challenger/Methods/Citation/Experiment/Replication/Contradiction/
Synthesis) ложатся на: наш `mind/dialectic` (Challenger + Contradiction Registry — уже реальный),
`eval-registry` (Experiment/Replication фикстуры), Knowledge Foundry (Primary-Source + Citation +
provenance). Research object (Question/Hypothesis/Method/Evidence/Counterevidence/Sources/Confidence/
OpenQuestions) = запись, которую Evidence Engine может верифицировать (reproducible, не «красивый отчёт»).

## 5. Риск-флаги для ответа DR-4 (что проверить у GPT/при синтезе)
1. Cockpit не должен вводить свой authority — он READ-модель поверх spine + manifest; любое действие из
   Cockpit идёт через ContinuityOS gate + capability, не напрямую.
2. Evidence Engine не должен сам исполнять/чинить — он ПРОВЕРЯЕТ; ремонт = отдельный gated action.
3. «cost per verified outcome» требует связать Langfuse-трейс с AcceptanceDecision — заложить общий
   trace_id/claim_id в спан (иначе метрика не сходится).
4. Pilot gate — деньги реальные: НИКОГДА не исполняем платёж за пользователя; только верифицируем
   пришедший Stripe-вебхук (M3 уже так).

## Источники (web, 2026-07-15)
- Phoenix vs Langfuse: https://www.morphllm.com/comparisons/arize-phoenix-vs-langfuse · https://langfuse.com/faq/all/best-phoenix-arize-alternatives · https://latitude.so/blog/best-ai-agent-observability-tools-2026-comparison
- OTel GenAI semconv статус: https://techbytes.app/posts/opentelemetry-genai-agent-semconv-cheat-sheet-2026/ · https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
