# Knowledge Foundry — историческая записка о Rust vs Python (SUPERSEDED)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует раннее языковое предложение,
> но не определяет текущую authority boundary и не доказывает безопасность Knowledge Foundry.
> Не использовать его как разрешение на реализацию, миграцию, деплой или LIVE. Актуальные источники:
> [полный security-аудит](44_SECURITY_HARDENING_2026-07-16.md), [текущий deploy-gate](../DEPLOY.md)
> и [Rust security HOLD](../apps/knowledge-foundry/RUST_SECURITY_HOLD.md). **LIVE остаётся OFF.**

Архивная оценка пакета GPT (v1 + v1.1 closure) и прежнее языковое предложение от 2026-07-15.
Слова `verdict`, `канон`, `прод` и `acceptance` ниже описывают состояние этой записки на тот момент,
а не действующий статус проекта.

## Что прислал GPT — статус

На момент записки пакет содержал 25-секционную архитектуру, 42 таблицы DDL, OpenAPI 3.1
(25 операций) и validation_report. Его исторический вердикт был **NARROW AND BUILD**, но это не
текущий build/deploy-gate. Тогда было оговорено:
- архитектурные принципы предлагались как рабочая гипотеза, требующая новой проверки;
- **v1 DDL — черновик, не migration-ready**: нужны 4 P0-правки до посева;
- **пороги (парсер/дедуп/модели) нельзя фиксировать теорией** — нужен бенчмарк на реальном корпусе MAWorld;
- первое действие: intake-срез `POST /v1/projects/{id}/intake/uploads` — один Markdown, дедуп, no-overwrite CAS, точное восстановление байт.

4 обязательные P0-правки схемы (согласен со всеми):
1. RawBlob (глобальный дедуп байт) ≠ ArtifactOccurrence (проектный доступ) ≠ ArtifactVersion — разнести.
2. Иммутабельные факты/события ≠ мутабельные проекции (очередь ревью, курсоры) — не вешать content_hash на статусные строки.
3. Критичные связи — junction-таблицы, не UUID-массивы.
4. Крипто-инварианты исполняемые: RFC 8785 JCS + SHA-256, RLS Postgres, EmbeddingProfile явный.

## Историческое языковое предложение (не действующий вердикт)

> **Действующее уточнение:** authority исходит из политики, credentials, транзакций и проверяемых
> контрактов — **не из языка реализации**. Rust и Python могут реализовывать детерминированные задачи,
> но ни один из них не получает право мутации без того же авторизованного policy-пути. PostgreSQL
> хранит транзакционное состояние, однако и доступ к нему требует отдельно доказанных RLS и ролей.

GPT предлагал «Python service and worker». Эта записка предлагала Rust-first реализацию критичных
путей, но выбор языка сам по себе не создаёт авторитет и не закрывает security boundary.

Intake/CAS/идентичность/хеширование/RLS требуют точных транзакционных и policy-инвариантов. Rust может
уменьшать некоторые классы ошибок памяти и моделирования состояний, но не делает мутацию невозможной,
не заменяет RLS/credentials/подписанную authority и не доказывает корректность SQL, replay или CLI.
Текущий аудит выявил незакрытые Rust/Postgres authority gaps; см. `RUST_SECURITY_HOLD.md`.

Следующая таблица — **не нормативная историческая декомпозиция**, а не разрешённая реализация:

| Компонент | Язык | Почему |
|---|---|---|
| **Intake Gateway** (preflight, hash, limits) | **Rust** | стриминговый SHA-256, лимиты, zero-copy; горячий путь приёма |
| **RawBlob CAS** (no-overwrite, byte recovery) | **Rust** | байт-точность, атомарные fs-операции, восстановление по хешу |
| **Identity** (RawBlob/Occurrence/Version/LogicalDocument) | **Rust** | P0-модель v1.1, тип-энфорсед разделение байт/доступа |
| **Canonical hashing** (RFC 8785 JCS + SHA-256) | **Rust** | KD-07: воспроизводимые байты, `serde_json_canonicalizer` |
| **Event Ledger** (append-only, hash-chain, checkpoints) | **Rust** | тот же класс, что ContinuityOS Ledger; целостность |
| **CanonicalDecision / Supersession** | **Rust** | иммутабельные подписанные записи |
| **Postgres access** (RLS, junction-таблицы, FTS) | **Rust (sqlx)** | compile-time проверка запросов, async, pgvector |
| **`kf` CLI + API** (axum) | **Rust** | один бинарь, контракт OpenAPI |
| — граница — | | |
| **Claim/Contradiction extraction** (LLM-предложения) | **Python** | model/IO-bound, ML-экосистема; только ПРЕДЛАГАЕТ |
| **Parser Router оркестрация** | **Python** | вызывает песочные инструменты; бенчмарк-драйвен |
| **Eval harness** (gold sets, метрики §6.2) | **Python** | датасеты, sklearn-метрики |
| **Sandboxed parser workers** | **любой (subprocess/контейнер)** | изолированы, язык не важен; rootless, no-net |
| **Operator Workbench UI** | **TS/React** | веб-дашборд (D7) |

Authority определяется политикой, credentials, транзакцией и проверяемым контрактом, а не языком.
Компилируемый путь без вызова LLM сам по себе не гарантирует ни допустимость мутации, ни RLS-изоляцию,
ни целостность replay. Любая промоция должна быть отдельно доказана действующими acceptance-тестами.

## Rust-стек (историческое исследование)

- **sqlx** (не Diesel): async-native, compile-time проверка сырого SQL, pgvector поддержан. Diesel — синхронный ORM, для нашего сервиса async важнее; сырой SQL ближе к RLS/junction-контролю. Источник: diesel.rs/compare, dev.to/yellow_coder.
- **serde_json_canonicalizer** — RFC 8785 JCS (serde_jcs заброшен, отличается от RFC). Для KD-07.
- **sha2** — стриминговый SHA-256 (спека требует именно SHA-256, не BLAKE3).
- **axum** + **tokio** — API-слой.
- CAS — свой ~80 строк (no-overwrite, tmp+rename, verify-on-read); контроль важнее готового casq (он на BLAKE3).

## Что переделываем из присланного

| Артефакт GPT | Действие |
|---|---|
| `knowledge_foundry_schema.sql` (v1, 42 табл.) | **Переделать** под v1.1 P0: RawBlob/Occurrence/Version split, события/проекции, junction-таблицы, RLS FORCE, EmbeddingProfile. → `apps/knowledge-foundry/schema/` |
| `knowledge_foundry_openapi.yaml` (25 опер.) | **Оставить как контракт**, реализовывать по срезам начиная с intake upload |
| Архитектура v1 + closure v1.1 | Исторический design input; **не текущий канон** |
| «Python service/worker» | Исторически предлагалось заменить критичные пути на Rust; **не authority-решение** |

## Какой срез предлагалось строить первым (исторически)

Intake-срез как рабочий Rust-код + доказательство acceptance-теста:
- `kf ingest <file> --project <p>` → RawBlob + Occurrence + Version, дедуп, no-overwrite, точное восстановление, идемпотентность.
- Acceptance: тот же файл дважды под разными именами → **один** RawBlob, **две** Occurrence, нет перезаписи байт, восстановление по хешу совпадает, повторный запуск идемпотентен.
- Плюс JCS-хеш демонстрация для CanonicalDecision (KD-07).

В записке предполагался трейт `MetaStore`: SQLite для offline-прогона и Postgres/sqlx как будущий
вариант. Это не доказательство drop-in совместимости и не production acceptance.

## Источники
- https://diesel.rs/compare_diesel.html · https://dev.to/yellow_coder/diesel-vs-sqlx-in-raw-and-orm-modes-4bgd · https://github.com/pgvector/pgvector-rust
- https://docs.rs/serde_json_canonicalizer/ · https://www.rfc-editor.org/info/rfc8785/
- https://crates.io/crates/casq (BLAKE3 CAS ref) · https://docs.rs/sha256/
