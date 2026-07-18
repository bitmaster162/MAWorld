# agents/ — роли LLM
Каждая папка: prompt.md (версионируемый), binding.yaml (модель/провайдер/data-class), evals/ (golden set ссылки).
Привязки заменяемы (provider-neutrality). Harness: тонкий свой (D6), SDK — только адаптеры.
| Роль | Привязка | Ограничения |
|---|---|---|
| orchestrator | GPT-5.6 Sol, direct API | prompt cache; никогда не владеет состоянием |
| supervisor | Claude Fable 5, direct API (Bedrock для FINANCIAL_SENSITIVE) | синтез, meta-review |
| challenger | Grok 4.5 | ТОЛЬКО PUBLIC/INTERNAL; X/Web выдача = недоверенные данные |
| executors | Codex+GPT-5.6, GLM 5.2, Nemotron (OpenRouter zdr) | Batch для фона |
| improvement-proposer | любой (стартово supervisor) | write: только ImprovementProposal + ветки |
