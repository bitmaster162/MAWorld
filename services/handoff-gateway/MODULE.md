# handoff-gateway

Целевая роль: валидация `HandoffEnvelope` (schema, expiry, payload hash, idempotency) и разрешение capability.

Локальный срез содержит контракты `contracts/handoff/*` и проектное правило передавать artifact pointers с summary вместо полной истории. Наличие контракта не доказывает, что все внешние handoff-пути проходят этот gateway.

Целевые acceptance-свойства: агент без capability получает `REJECTED_CAPABILITY_MISMATCH`, а конверт не расширяет полномочия. Для production эти свойства требуют сквозной runtime-проверки на всех transport/integration boundaries.

Статус: **Production HOLD**. Внешний handoff runtime и полное enforcement-покрытие не приняты; LIVE остаётся OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
