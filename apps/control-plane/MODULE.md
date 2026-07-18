# control-plane
Роль: API Gateway, Telegram-адаптер (webhook secret_token + nonce+expiry на одобрения, D6), Approval Service, Agent Registry (Git-версионируемый).
Вертикальный срез MVP: Telegram → API GW → оркестратор(план) → ContinuityOS preflight → детерминированная верификация → audit trace → cockpit.
Кандидат из наследия: Hermes/OpenClaw Telegram-бот.
