# memory-governor

Целевая роль: Governed Memory со слоями Pinned Core / Working / Archival и lifecycle `PROPOSED → VALIDATED → APPROVED → ACTIVE → SUPERSEDED`.

Локальный срез содержит контракты `contracts/memory/*` и проектные правила для изоляции retrieval. Запрет кросс-проектного retrieval является целевой политикой; его полное enforcement-покрытие во внешнем runtime не доказано.

SQLite/Postgres рассматриваются как возможный канон, а FastEmbed vector index — как производное представление. Production durability, tenant isolation, rebuild и recovery для этого контура не приняты.

Статус: **Production HOLD**. Внешний memory runtime и сквозная изоляция не приняты; LIVE остаётся OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
