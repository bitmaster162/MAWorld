# Deep Research промпты — что хочу от GPT и Gemini (2026-07-16)

Прицельно под то, что глубже моего веб-ресёрча. Оба возвращаются через `dialectic-adjudicator` как
EVIDENCE, не как authority. Ничего не CLOSED без воспроизводимого теста. Требование к обоим:
воспроизводимость (команды/схемы/цитаты/pass-fail), не проза.

---
## Промпт для GPT (o-series) — «Cryptographic verifiability + confidential compute для агентов»

Ты — независимый Challenger MAWorld. Контекст: у нас детерминированный spine + Evidence Engine (engine-
signed VerificationResults = "tool receipts"), secrets-broker с enclave-resolve, remote_attestation
(SEV-SNP/TDX модель, defense-in-depth против TEE.Fail), agent_mandate (AP2). Read-only, задача —
FALSIFY и углубить, с воспроизводимыми артефактами (file:line, схема, тест).

1. **Compound attestation для multi-hop agent chains.** Открытая проблема (arxiv 2605.03213): как
   связать attestation через цепочку агент→агент→tool так, чтобы каждый следующий hop проверял, что
   предыдущий исполнялся в подлинном TEE с ожидаемым кодом? Дай протокол (nonce-chaining? nested quotes?),
   threat-model (TEE.Fail forged quotes), и failing→passing тест поверх нашего `remote_attestation`.
2. **zkML vs tool-receipts — граница.** Для каких классов проверок (детерминированные side-effects: hash,
   commit, no-dup, payment) наши подписанные receipt'ы строго достаточны, а где нужен реальный ZK
   (недетерминированный inference)? Дай карту «receipt достаточно / нужен zk / нужен TEE», с оценкой
   стоимости и конкретными библиотеками 2026 (ezkl/Risc0/…).
3. **Optimistic verification fallback.** Спроектируй challenge-window поверх Evidence Engine: результат =
   provisional-accepted, но оспариваемый в окне T (fraud-proof). Как это сочетается с нашим
   `hardened_effect_registry` (эффект уже сработал)? Компенсация vs удержание. Тест.
4. **AP2/x402 боевой путь.** Как наш `agent_mandate` (Intent+Cart) маппится на реальный AP2 mandate-формат
   и x402 settlement, чтобы Money Forge мог принимать агентные платежи? Где риск (mandate replay,
   cart-substitution) и как закрыть. Приёмка через Evidence Engine `PRODUCT_SUCCESS`.
Верни: falsification-отчёт, corrected specs, failing→passing тесты, ранжирование по эксплуатируемости.

---
## Промпт для Gemini (2.x Pro / Deep Research) — «Compliance, memory 2026, formal policy, red-team корпус»

Ты — независимый production/compliance-ревьюер MAWorld. Sourced, воспроизводимо.

1. **EU AI Act Article 12 полный чек-лист под наш `article12_export`.** Мы делаем bi-temporal hash-chain,
   retention 183/730, 3 цели Art.12(2). Дай ПОЛЯ-по-полям для НАШЕГО класса (agent governance, не
   biometric): что именно логировать под Art.79(1)/72/26(5), формат, retention, и как это стыкуется с
   Art.13 (transparency) и Annex IV (tech docs). Цитаты статей. Дай failing→passing тест-набор полей и
   готовый compliance-export template.
2. **Agent memory 2026 (Letta/Mem0/Zep) под наш LifeOS + memory_provenance.** Мы: 5-слойная приватная
   память, governed promotion (не self-promote в истину), trust-scored retrieval + provenance против
   poisoning. Сверь с SOTA 2026: что взять (temporal knowledge graph? sleep-time compute?), что у нас
   уже сильнее, и где дыра. Runnable-миграция + тест на memory-poisoning корпусе.
3. **Формальная верификация политик (Cedar SMT).** Мы валидировали `policy_engine` против реального
   cedarpy (default-deny, forbid-overrides). Как использовать Cedar's SMT-solver, чтобы ДОКАЗАТЬ
   свойства (напр. «ни одна политика не разрешает live-эффект без human-confirm»)? Дай Cedar-схему +
   доказательство свойства + тест.
4. **OWASP Agentic Top-10 red-team корпус (расширение).** У нас 12/12 базовых. Дай ПОЛНЫЙ корпус атак
   (tool-misuse chains, jailbreak-варианты, memory-poisoning с задержкой, excessive-agency, multimodal
   Ghostcommit-варианты) как исполнимый набор для CI — с ожидаемым «blocked» по каждому.
5. **SPIRE реальный на VPS.** Пошагово: как поднять SPIRE server/agent, выдавать X.509 SVID нашим NHI
   (agent_registry), заменить статические ключи workload-identity. Приёмка: SVID ephemeral, ротация,
   attestation ноды.
Верни: sourced findings, runnable configs/migrations, failing→passing тесты, места где наш код
противоречит официальной спеке — с цитатой.

---
## Правило
Результаты → dialectic-adjudicator как evidence. Live-эффекты OFF до зелёного CI + отмашки. BUILD_FREEZE
снимается только когда весь adversarial-корпус (сейчас 27/27, 257 проверок) зелёный в CI на едином
источнике + закрыты deploy-шаги (docs/27).
