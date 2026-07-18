# Как усилить MAWorld — план (2026 best practices + что забрали у конкурентов)

Исследование (docs/25) → построенные усиления (все adversarially протестированы) + остаток.

## Построено в этом раунде (что забрали у конкурентов, реализовано)
| Забрали у | Модуль | Что даёт | Тест |
|---|---|---|---|
| Cedar/OPA (policy-as-code) | `libs/maworld_core/policy_engine` | детерминированный runtime allow/deny, DEFAULT-DENY, FORBID overrides PERMIT, условия по контексту | 6/6 |
| OWASP Agentic (prompt injection) | `input_guard` | вход untrusted по умолчанию; trust-score по источнику; injection-маркеры блокируют goal-changing | 7/7 |
| OWASP Agentic (memory poisoning) | `memory_provenance` | provenance+HMAC на каждом воспоминании; trust-scored retrieval; инструкции только от owner-grade; poison в карантин | 8/8 |
| Arthur (discover-стадия) + SPIFFE/NHI | `agent_registry` | каждый агент = NHI с ephemeral SPIFFE-id; shadow-агенты (незарегистр.) блокируются | (в registry+custody 11/11) |
| Key custody (HSM/Vault-паттерн) | `key_custody` | домены ключей (engine/approver/gate/human/cap) у РАЗНЫХ держателей; gate-держатель НЕ может подписать approval → нет self-approval | 11/11 |

Полный прогон после усилений: **20/20 suites, 177 adversarial-проверок** (`tests/run_all.py`).

## Как это встраивается в существующее
- `policy_engine` садится ПЕРЕД `action_authority`: сначала policy-as-code (контекстное правило), потом
  hash-bound gate-решение, потом capability. Два независимых слоя = defense-in-depth.
- `input_guard` — на входе в agents-runner (любой untrusted вход через него до PROPOSE).
- `memory_provenance` — на retrieval из LifeOS/Governed Memory (защита от отложенного poisoning).
- `agent_registry` — discover-стадия перед любым действием агента (NHI known + не истёк).
- `key_custody` — реальная раздача ключей для secrets-broker (approver-ключ не у промоутера).

## Что ещё усилить (остаток, приоритет)
1. **Cedar-полный** (SMT-провабельность): наш policy_engine — детерминированный, но не доказывает свойства
   политик формально. Опция: подключить реальный Cedar/OPA для provably-correct политик.
2. **SPIFFE/SPIRE реальный**: сейчас NHI-модель наша; на VPS поднять SPIRE для X.509 SVID (ephemeral, без
   long-lived секретов) — заменит статические ключи workload-идентичностью.
3. **Red-team автоматизация**: подключить Promptfoo/DeepTeam-стиль прогоны OWASP-Top-10 в CI (сейчас
   input_guard покрывает prompt-injection; добавить tool-misuse chains, jailbreak-корпус).
4. **EU AI Act пакет доказательств**: у нас есть ledger+evidence+human-oversight — собрать в
   compliance-экспорт (lineage-backed audit trail) под требования авг-2026. Это ПРОДУКТОВЫЙ актив.
5. **Rust-консолидация**: risk-service/kf-store вне единого libs — вынести общий контракт.
6. **Discover в проде**: agent_registry + сетевое обнаружение реально работающих агентов на флоте.

## Продуктовый вывод
Рынок под EU AI Act требует ровно то, что у нас ядром: **enforce + evaluate + evidence + human oversight +
lineage audit**. Мы забрали недостающие грани (policy-as-code, discover, NHI-identity, prompt-injection и
memory-poisoning защиты, key custody). Дифференциатор остаётся: **proof-of-correctness (агент не принимает
свою работу) + детерминированный spine**, чего у Arthur/Fiddler/PlainID (post-hoc monitoring) нет.
