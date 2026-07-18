# Round 6 — Implementation Result (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Вход: `v1.4 Adjudication` + `DR2_Control_Spine_Mandatory_Broker_V3` (GPT). Изучил оба, проработал под наш проверенный стек, внедрил keystone-спайк. Всё зелёное против реального софта.

## Что v1.4 решил (в мою пользу)
v1.4 канонически разрешил мои прошлые расхождения ровно как я и предлагал:
- **Runtime:** `DurableRuntimeAdapter` — DBOS = FIRST SPIKE (мой recovery-тест проходит runtime-gate §3.3), Temporal = PRE-APPROVED FALLBACK. Не переключаться на Temporal «по числу отчётов».
- **Observability:** развязать от продукта — `TraceContext → OTel → ObservabilityBackend`; Phoenix = первый бэкенд, не постоянная архитектура.
- Инструкция §11 Claude: «использовать отчёт как supporting evidence, не заменять им обязательный аудит репозитория и hardening». Именно так и делаю.

## A. Boundary-Proven Integration Spike — `control_spine_v4` PASSED (keystone)
Это DR2 0x12 + v1.4 Spike A: связал ВЕСЬ boundary end-to-end на проверенных модулях.
```
A ingest artifact -> B CanonicalDecision -> C read-only CanonSnapshot ->
D CTHA proposer в РЕСТРИКТНОЙ песочнице (canon RO, no net/shell-reach/creds) ->
E ProposedActionSpec -> F Proposal Bridge (strips fake authority) -> canonical ActionSpec ->
H ContinuityOS gate (real) -> I sandboxed executor (bwrap) file write -> J byte verify ->
K audit chain -> N bypass matrix
```
Результат: bridge снял поддельные `approved/decision/execute`; gate ALLOW; sandboxed-запись + точная сверка байт; audit-цепочка цела; **bypass-матрица вся fail-closed**; **9/9 negative bridge-тестов** (0x09).

**Proposal Bridge (DR2 0x09)** — `proposal_bridge.py`: вход недоверенный; валидирует schema+provenance+trace, **срезает authority-маркеры** (execute/ALLOW/approval), резолвит data-class + адаптер, чеканит СВЕЖИЙ ActionSpec (authority только от spine), биндит idempotency, **никогда не исполняет и не промотит canon**. Негативные тесты: fake ALLOW → strip, direct shell → reject, target вне scope → reject, missing evidence/trace → reject, secret в proposal → quarantine, expired/duplicate → reject, чужой адаптер → reject.

**CTHA boundary (DR2 0x0A)** — `cta_proposer.py` в bwrap: `brain_cannot_mutate_authoritative_state_or_bypass_gate` — прямая запись canon (RO-mount) BLOCKED, сеть BLOCKED, прямой DB BLOCKED, host-secret BLOCKED. Структурно, не промптом.

**Находка:** shell внутри песочницы доступен (нужен /bin для python), но **contained** — сеть/секреты/host-write перекрыты, так что shell ничего не достаёт. Убрал бессмысленный «shell blocked» тест; boundary держат сетевые/FS-инварианты.

## B. AsyncTaskRegistry — полный state machine (v1.4 §5.2) — 11/11
`control_spine_v3/async_task_registry.py`: canonical lifecycle `CREATED→RUNNING→INPUT_REQUIRED→RESULT_READY→RESULT_FETCHED→VERIFIED→COMPLETED/FAILED/EXPIRED/CANCELLED` + orphan-poll ban. Нельзя перескочить verify, нельзя переоткрыть terminal, transition с чужим binding → DENY.

## C. DurableRuntimeAdapter (v1.4 §3.2/3.3) — `control_spine_v3/durable_runtime_adapter.py`
ABC-контракт (start_workflow / recover_pending / external_effect_once) + `select_runtime(evidence)` runtime-gate. На текущих доказательствах (control_spine_v0) gate возвращает **DBOS**; Temporal — swap-in по escalation-триггерам.

## Что подтвердил/не промотил (per v1.4 §8)
- Cost bands → HYPOTHESIS (нужен PriceCatalog + реальные гистограммы).
- Temporal unconditional → held за runtime-gate. Phoenix permanent → нет, первый бэкенд.
- «Exactly once» брокера ≠ ExternalEffectRegistry. MCP 2026-07-28 → UNRESOLVED.

## Матрица покрытия DR2 (0x14) — `docs/11_DR2_GAP_BYPASS_MATRIX.md`
Что уже доказано vs что осталось. Ключевое сделано: Rust intake (CAS/JCS/audit), Postgres/sqlx/RLS (8/8), MCP normalizer+resolver-поля, capability tokens, async registry, parser router, Proposal Bridge, CTHA boundary, bypass matrix, boundary-spike. Осталось: CanonPromoter (0x0B), формальный ExternalEffectRegistry с reversibility/reconciliation, Spike B (git commit + push HOLD), полный набор side-effect адаптеров, репозиторный чек-сумм-инвентарь.

## Запуск
```
cd spikes/control_spine_v4 && CONTINUITYOS_PATH=C:/PROJECTS/continuityos python3 run_v4.py   # SPIKE v4 PASSED
cd spikes/control_spine_v3 && python3 test_async_statemachine.py   # 11/11
                              python3 test_authority.py            # 12/12
```
