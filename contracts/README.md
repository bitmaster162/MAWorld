# contracts/ — единственный источник схем
Источник: D2 (primitives delta), D5 (trading), D6 (control spine), D7 (knowledge).
Правила: schema_version обязателен; major-изменение = новый namespace; policy_version/code_version/prompt_version/tool_versions/configuration_hash — промоушен-гейты.
Ошибки API: INVALID_ARGUMENT / FAILED_PRECONDITION / ALREADY_EXISTS / PERMISSION_DENIED / ABORTED / DEADLINE_EXCEEDED / HOLD (никогда не авторетраится в side effect).
Деньги: только fixed-point (int64 + scale). float64 запрещён (ADR-D6).
