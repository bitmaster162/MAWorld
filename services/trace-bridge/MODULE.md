# trace-bridge
Роль: внутренний TraceContext (contracts/control/TraceContext.yaml) → OTel-спаны → Langfuse self-hosted.
Не биндить аудит к сырым gen_ai.* именам — semconv движется (D6). Редакция секретов и MCP-* заголовков в трейсах.
Acceptance: один Telegram-прогон = один связный trace: план→preflight→исполнение→верификация→аудит.
