# MAWorld — MultiAgentWorldOS

> **Security status (2026-07-18): LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**
> Начинать проверку нужно с [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md),
> а не со старых spike-отчётов. `MAWorld_review_package.zip` — устаревший снимок до hardening;
> его нельзя распространять или разворачивать как актуальную сборку.
> `apps/knowledge-foundry/kf-intake/repro/MANIFEST.json` также является явно помеченной
> historical/superseded записью и не подтверждает текущий tree или release binary.

Многоагентная операционная среда одного владельца: трейдинг (Domain A), исследования (Domain B), Money Forge (Domain C) + контур самоулучшения.

**Начни здесь:** текущий security audit → `MODULE_MAP.md` → `docs/00_MASTER.md` (историческая архитектура).

## Структура

```
docs/           архитектура, ADR, исходные DR-отчёты (D1-D7)
contracts/      canonical application contracts; не единственный источник DB migrations
infrastructure/ docker-compose (Postgres+pgvector, MinIO, NATS), bootstrap DDL
services/       сервисы контрольной плоскости (гейт, runtime, память, песочницы, evals...)
apps/           4 приложения: control-plane, trading-cell, knowledge-foundry, money-forge
agents/         роли LLM (промпты + конфиги привязок)
benchmarks/     harness'ы (hot-path, checkpoint, sandbox)
incoming/       СЮДА кидай хаотичные существующие модули — разберём по слотам
```

## Инварианты (нарушать нельзя)

1. LLM никогда не владеет авторитетным состоянием.
2. Целевой invariant: каждый side effect проходит canonical preflight/authority boundary. Любой ещё
   не обёрнутый путь остаётся HOLD и не включается; остаточные KF production trust/acceptance limits
   описаны в `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
3. Replay ≠ undo: внешние эффекты только через Effect Registry.
4. float64 в деньгах запрещён — fixed-point int64/int128.
5. Вектор — производный индекс, не истина. Текст источника — не инструкция.
6. Агенты предлагают, evals решают, человек утверждает канон.

## Быстрый старт

Сначала только read-only проверка локальной dev-конфигурации; это не включает сервисы или live-эффекты
и не закрывает production gates. На новом пустом dev-volume Compose сам монтирует runtime-цепочку
Knowledge Foundry `001 → 002 → 003`; legacy SQL вручную поверх неё не применять.

```powershell
Copy-Item .env.example .env  # только локальные dev credentials
docker compose -f infrastructure/docker-compose.yml config
```
Первое действие по MVP: control spine falsification spike — см. docs/00_MASTER.md §12 и D6 §MVP.
