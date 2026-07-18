# continuityos-gateway

Целевая роль: Policy Enforcement Point для preflight-решений ALLOW/WARN/HOLD/DENY перед side effect.

Локальный срез содержит контракт `contracts/control/ActionSpec.yaml` и компоненты preflight-адаптера. Утверждение «каждый side effect обязательно проходит этот gateway» является целевым инвариантом архитектуры, а не доказанным свойством всех внешних путей выполнения.

Целевые свойства: allowlist заголовков, audience binding, reconciliation асинхронных задач и default HOLD для неизвестного. Политики, append-only аудит и семантическая память описаны как проектный контур; их production durability и полнота покрытия не приняты.

Зависимости и внешние runtime-интеграции, включая secrets broker и trace bridge, требуют отдельной acceptance-проверки. Исторические материалы D1/D6 и псевдокод — исследовательские входы, не runtime evidence.

Статус: **Production HOLD**. Сквозное enforcement всех эффектов и внешний runtime не приняты; LIVE остаётся OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
