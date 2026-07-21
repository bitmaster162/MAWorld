# knowledge-foundry
Целевая роль: управляемое authoritative состояние проекта. Ingestion (Local Folder + Git коннекторы, идемпотентные) → MinIO raw → sandbox-парсинг → FEVER-claims → PROV-O provenance → противоречия → Human Workbench → CanonicalDecision → ADR/Implementation map.
Runtime-схемы: `apps/knowledge-foundry/schema/001+002+003+004`; `infrastructure/sql/001` — legacy.
Монорепо-структура и 20 тикетов: D7 §17,21. 7-дневный план: D7 §22.
Целевые инварианты: сырьё иммутабельно; текст ≠ инструкция; дубликаты кластеризуются; вектор производный; канонизация — явный акт владельца. Пока все они не доказаны на runtime boundary, модуль остаётся HOLD.

Статус безопасности: **HOLD**. В текущем authority-v3 дизайне signed `authority_domain_id` связывает
mandate с конкретным DB security domain. Opaque `ConsumedIngestAuthority` может быть превращён в
registrar-proof только после durable CAS publish; registrar принимает этот proof по ссылке и ещё раз
потоково проверяет CAS перед SQL. Grant фиксирует runtime role OID, а runtime caller передаёт только
`grant_id`; project/source/content извлекаются server-side. Наружный outcome не раскрывает blob ID и
`*_created` flags; функции и client transactions имеют bounded lock/statement timeout и exact ACL
allowlist.

Migration `004` — one-shot и в текущем runbook поддерживается только для нового пустого volume;
current locked workspace gate прошёл **109/0/1 ignored**, fmt/Clippy PASS; guarded PostgreSQL 16
authority-v3 acceptance прошла **1/1 за 37.00s** на disposable domain
`dddddddd-dddd-4ddd-8ddd-dddddddddddd`, после чего container удалён. Не приняты
external key/registrar credential custody, PostgreSQL TLS/credential confidentiality, trusted
build/clock/host, external monotonic anchor против local replay rollback, clone quarantine с domain
и credential rotation, existing-volume/backup/crash/restore lifecycle, signed schema attestation,
timing non-interference и descriptor-based CAS boundary против hostile pathname replacement.
Условия: `RUST_SECURITY_HOLD.md`.
