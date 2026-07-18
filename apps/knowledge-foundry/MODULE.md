# knowledge-foundry
Целевая роль: управляемое authoritative состояние проекта. Ingestion (Local Folder + Git коннекторы, идемпотентные) → MinIO raw → sandbox-парсинг → FEVER-claims → PROV-O provenance → противоречия → Human Workbench → CanonicalDecision → ADR/Implementation map.
Runtime-схемы: `apps/knowledge-foundry/schema/001+002+003`; `infrastructure/sql/001` — legacy.
Монорепо-структура и 20 тикетов: D7 §17,21. 7-дневный план: D7 §22.
Целевые инварианты: сырьё иммутабельно; текст ≠ инструкция; дубликаты кластеризуются; вектор производный; канонизация — явный акт владельца. Пока все они не доказаны на runtime boundary, модуль остаётся HOLD.

Статус безопасности: **HOLD**. Локально закрыты bounded CAS/parser, fail-before-replay, stale-writer
locking, build-pinned signed authority, atomic transaction-scoped PostgreSQL API, exact Rust
toolchain/lock и dependency audit. Не приняты external key custody/rotation, trusted build/clock/host,
shared replay, end-to-end authority→project-scope wiring и dedicated loopback `maworld_rls_test_*`
acceptance; signed schema/policy/function attestation и dedup privacy также отсутствуют. Durable
scoped intake отключён на Windows и проверен только в digest-pinned Linux; DB test явно ignored/SKIP.
Условия: `RUST_SECURITY_HOLD.md`.
