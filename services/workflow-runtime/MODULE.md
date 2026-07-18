# workflow-runtime

Целевая роль: durable-исполнение с Checkpoint Store, Branch Ledger, External Effect Registry и Branch Comparator поверх выбранного workflow/PostgreSQL-субстрата.

Локальный срез содержит контракты `contracts/workflow/*` и описание `WorkflowBranchingService`. DBOS+Postgres, gRPC-сервис и сквозной внешний runtime не считаются принятыми только на основании этих контрактов.

Целевой инвариант: replay не должен повторно исполнять внешний эффект. Acceptance-критерий — восстановление после `kill -9` в середине выполнения без дубля эффекта — требует отдельного runtime-прогона и сейчас не является подтверждённым production evidence.

Статус: **Production HOLD**. Durable runtime и внешние эффекты не приняты; LIVE остаётся OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
