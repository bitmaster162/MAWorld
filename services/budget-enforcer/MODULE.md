# budget-enforcer
Роль: исполняемая политика затрат. contracts/control/BudgetPolicy.yaml.
Правила (D6): оркестратор→OpenAI direct, супервизор→Anthropic direct (+prompt cache), OpenRouter только PUBLIC/INTERNAL (deny data_collection, zdr), Batch для фоновых (−50%), P0/P1 резерв неприкосновенен, circuit breakers. Диапазоны: $60-180/$250-900/$1200-4000 мес.
Кандидат из наследия: QuotaGateway (D1 §08 Go-псевдокод).
