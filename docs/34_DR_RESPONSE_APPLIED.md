# Ответ на 2 DR-отчёта (GPT crypto-verifiability + Gemini infra/compliance) — принято и внедрено

Оба отчёта пришли ровно по моим промптам (`docs/32`) и нашли **реальные рефутации** моих же модулей.
Это Challenger как задумано: тезис CLOSED только на verified-рефутации → эти «закрытые» переоткрылись и
починены. Не защищался — принял и внедрил (все с failing→passing тестами из самих отчётов).

## GPT-отчёт (Cryptographic Verifiability) — 5 рефутаций, все закрыты
| # | Рефутация (что было неверно) | Фикс (модуль) | Тест |
|---|---|---|---|
| 1-2 | attestation НЕ транзитивна; nonce-chain недостаточен | `compound_attestation`: цепочка **verifier-signed AttestationResults**, каждый hop вяжет parent_ar_digest+session+hop_index+capability/request digests; splice/scope-escalation/non-monotonic отвергнуты | 11/11 |
| 3 | quote — не самодостаточный root (TEE.Fail подделывает TDX-quote, проходящий Intel QVL) | `secret_release_ok`: quote-only НЕДОСТАТОЧЕН — нужны platform-binding + enrolled key (внешние компенсирующие контроли) | ↑ |
| 4 | «provisional-accepted + уже сработавший irreversible = optimistic EXPOSURE» | `optimistic_verification`: irreversible ЗАПРЕЩЁН для optimistic (нужна финальная верификация до исполнения); holdable→held, compensatable→fired_pending_comp; PRODUCT_SUCCESS только после чистого finalize | batch1 14/14 |
| 5 | AP2 Intent+Cart недостаточно без payee+cart_hash+settlement idempotency | `agent_mandate_v2`: merchant-signed canonical cart, PaymentMandate вяжет точный cart_digest, payment_identifier уникален; **replay/cart-substitution/payee-substitution закрыты** | ↑ |

## Gemini-отчёт (Infra/Compliance) — принято и внедрено
| Находка | Фикс | Тест |
|---|---|---|
| **Art.26(6) violation**: авто-удаление логов через 90д < «at least six months» (183д deployer) — штраф до €35M/7% | `article12.validate_retention`: блок при <183д с `ComplianceViolationError` + agent-governance field-checklist | batch1 |
| Нет битемпоральности (vs Zep/Graphiti) → слепые зоны аудита, race | `bitemporal_memory`: valid_time+transaction_time; supersede ЗАКРЫВАЕТ старый факт (не перезапись); поверх memory_provenance | batch2 |
| ASI06 delayed memory-poisoning | тест: low-trust факты не промоутятся в governed truth | batch2 |
| ASI03 identity/privilege abuse (expired SVID reuse) | тест: expired SVID отвергнут | batch2 |

## Что осталось прод-шагами (из DR, за деплоем)
- **Cedar symcc + cvc5** (Gemini): реальное SMT-доказательство «no ExecuteLiveAction без human_confirmed» через `cedar-policy-symcc` (Rust) — апгрейд нашего z3-доказательства. → добавлено в DR-трек.
- **SPIRE на VPS** (Gemini): готовые `server.conf`/`agent.conf` + join_token + entry create + acceptance (`spire-agent api fetch x509`, TTL 1h) — в деплой-раннбук `docs/27`.
- **Broken TEE root** — остаточный риск, НЕ чинится композицией (честно): наш defense-in-depth (capability+gate) остаётся обязательным.
- Bitemporal migration LifeOS (Gemini миграционный скрипт) — при деплое памяти.

## Итог
Все 5 GPT-рефутаций + 4 Gemini-находки закрыты на модульном уровне: **34/34 suites, 324 adversarial-
проверки**. Ключевой урок обоих отчётов совпал с нашим ядром: коллапс к трём слоям доверия —
**verifier-signed AttestationResults + deterministic tool receipts + settlement receipts**, и «receipts
по умолчанию, TEE для секретов, ZK только где реально нужна вычислительная корректность».
