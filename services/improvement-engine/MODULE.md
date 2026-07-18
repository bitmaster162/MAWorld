# improvement-engine

Целевая роль: оркестрация цикла `SENSE → PROPOSE → BUILD → EVALUATE → GATE → CANARY → PROMOTE/ROLLBACK`.

Локальный срез содержит `contracts/improvement/ImprovementProposal.yaml`, SQL-артефакты и проектные материалы. GEPA для промптов, reflection hooks для skills и DGM-style патчи относятся к целевым фазам развития, а не к принятому production runtime.

Поле `improvement_loop_state.improvement_loop_enabled` с default `FALSE` задаёт fail-closed намерение в доступном контуре. Оно само по себе не доказывает, что все внешние процессы подчиняются kill switch.

Статус: **Production HOLD**. Автономное улучшение, canary/promotion и внешние эффекты не приняты; loop должен оставаться выключенным, LIVE — OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
