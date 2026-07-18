# Финальные исследования → внедрено (2026-07-16)

Веб-ресёрч по всем открытым фронтам MAWorld; реализуемое внедрено реальными модулями (16/16), глубокое —
в DR-промптах (docs/32).

## 1. EU AI Act Article 12 (наш wedge, подтверждён нашим же PFI ×4)
Находки: automatic logging (система сама, не вручную), lifetime (deploy→decommission); цели Art.12(2):
(a) risk-ситуация/substantial modification (Art.79(1)), (b) post-market (Art.72), (c) operation (Art.26(5));
общим high-risk — поля по risk-assessment; **tamper-evident, retention ≥6 мес (24 мес для biometric/LE)**.
→ **Внедрено:** `article12_export` дополнен `retention_days` (183/730), `LOG_PURPOSES` (3 цели),
`classify_purpose` (DENY/high→risk_situation). Bi-temporal hash-chain уже был. Это буквально продуктовый
compliance-export к 2 авг 2026.

## 2. Confidential computing / TEE (для enclave-resolve secrets)
Находки: платформы SEV-SNP/TDX/H100-CC; **remote attestation** — верификатор подтверждает, что ожидаемый
код исполняется в подлинном TEE, ДО передачи секретов; **TEE.Fail 2026** — quote'ы подделываемы при утечке
ключей → TEE не единственный корень доверия.
→ **Внедрено:** `remote_attestation` — attestation-gated release: секрет отдаётся только при валидном quote
(ожидаемый measurement + свежий nonce) **И** прошедшем capability-слое (defense-in-depth против TEE.Fail).
Wrong-code/replay/stale/forged — отвергнуты.

## 3. Verifiable inference (наш Evidence Engine = «tool receipts», не ZK)
Находки: вопрос 2026 — «можно ли доказать КАК получен вывод, кто отвечает, держится ли он»; ZKML тяжёл
(×орды величин); **TEE-attested inference** — практичный путь; **«Tool Receipts, Not ZK Proofs»** (arxiv) —
практичные подписанные receipt'ы вместо ZK. → Это ровно наш **Evidence Engine** (engine-signed
VerificationResults = tool receipts). Внедрять нечего — валидировано; ZK/optimistic-fallback → DR.

## 4. Machine economy: AP2 / A2A / x402 (для Money Forge)
Находки: стек MCP(tools)+A2A(talk)+x402(pay)+**AP2(authorize via tamper-proof signed mandates)**+ERC-8004;
AP2 (Google, 60+ орг): Intent-mandate + Cart-mandate = подписанное доказательство инструкций пользователя.
→ **Внедрено:** `agent_mandate` — user-signed Intent-mandate (allowed_action + amount cap + expiry); каждая
Cart (конкретное действие/платёж) авторизуется ТОЛЬКО внутри intent (та же action + в пределах cap);
tampered/expired/over-cap отвергнуты; выход proposal-only (requires action_authority + money_forge). Это
AP2 в нашем идиоме, поверх control_plane + Money Forge.

## Итог
27/27 suites, 257 adversarial-проверок. Внедрено 3 модуля из research (+16 проверок). Core-тезисы
(Evidence=receipts, Article-12=наш формат) подтверждены рынком. Глубокое (GPU-TEE compound attestation
для multi-hop цепочек, zkML для крупных моделей, формальная верификация политик) → DR-промпты docs/32.

## Источники
- Art.12: https://artificialintelligenceact.eu/article/12/ · https://www.helpnetsecurity.com/2026/04/16/eu-ai-act-logging-requirements/
- TEE: https://arxiv.org/abs/2605.03213 · https://www.bleepingcomputer.com/news/security/teefail-attack-breaks-confidential-computing-on-intel-amd-nvidia-cpus/
- Verifiable inference: https://arxiv.org/pdf/2603.10060 (Tool Receipts) · https://everstake.one/resources/blog/verifiable-ai-onchain-trust-layer
- AP2/x402: https://agentpaymentsprotocol.info/ · https://www.crossmint.com/learn/agentic-payments-protocols-compared
