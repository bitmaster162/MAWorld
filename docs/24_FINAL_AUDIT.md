# Финальный аудит (Devil-проход по всему наросшему) — 2026-07-15

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Адверсариальный проход по всем модулям раундов 12–17 + честная карта остаточных пробелов. Метод: тот
же, что и раньше — тезис CLOSED только на воспроизводимой рефутации; где не проверено против прод/live —
честно OPEN.

## Что реально доказано (145 проверок, 16/16 suites — `tests/run_all.py`)
| Область | Доказано adversarially | # |
|---|---|---|
| Evidence Engine v2 | no-shell (RCE закрыт), HMAC-signed результаты (self-attest закрыт), re-derive | 18 |
| Effect registry | атомарный exactly-once, 20-thread concurrency, crash-window reconcile | 9 |
| Action authority | confused-deputy закрыт (hash-bound), REQUIRE_CONFIRMATION не исполним без человека | 8 |
| Trading safety | units 1e6→lot/tick, обязательный RiskDecision, live OFF | 12 |
| Canon SoD | approval отдельным ключом, durable nonce, атомарная промоция, self-forge закрыт | 7 |
| MCP auth | RFC 8707 audience-bound, fail-closed, no passthrough | 8 |
| Secrets + DLP | reference не plaintext, enclave-only resolve, redaction утечек | 12 |
| Capability | подписанные токены (bare string ≠ cap), realpath (prefix/traversal закрыт) | 11 |
| Control plane | human-in-loop привязан к точному ActionSpec hash | 7 |
| Global-cycle (мировоззрение) | цикл от GLOBAL + top-down каскад + фрактал | 9 |
| Trace bridge | GLOBAL-rooted спаны, trace↔claim, cost-per-verified-outcome | 9 |
| Agents runner | proposal-only (CTHA boundary), challenger=dialectic | 9 |
| Budget router | durable, negative-reject, абсолютный потолок P0 | 9 |
| Sandbox limits | CPU/RAM/output-лимиты, unique container id | 5 |
| Money Forge v2 | только подписанное payment-proving событие | 4 |
| m6 e2e v2 | rewire на hardened-модули | (в наборе) |

## Остаточные ЧЕСТНЫЕ пробелы (Devil выжил — деплой/интеграция, не «провал»)
1. **Key custody = деплой.** HMAC-ключи (engine/approver/gate/human/cap) в dev = env/random. Реальная
   раздача (approver-ключ НЕ у промоутера; engine-ключ в enclave; всё через secrets-broker) — шаг деплоя.
2. **Trace cost — доверенный вход.** Стоимость метрится вызывающим; в прод источник = LLM-gateway/
   Langfuse, не агент. Пока cost-число доверяется.
3. **CTHA boundary агента — структурный + gate-enforced**, не защищён от враждебного in-process
   сабкласса (у агента нет handles + gate отвергает неподписанное; но сабкласс мог бы добавить методы).
   Реальная защита = рантайм не выдаёт capability + подписанный gate. Честно: не sandbox-против-кода.
4. **Rust вне единого libs.** Single-source покрывает Python; risk-service/kf-store (Rust) — отдельно.
5. **VPS-прод e2e не прогнан** (всё в dev-песочнице); **live-эффекты OFF**; **runsc** не запускался.
6. **CI написан, но не прогонялся на GitHub** (локально зелёный 16/16).
7. **7 spike-копий заморожены** как историческое evidence (не активны; fix в них не распространяется — но
   активные потребители уже на libs).

## Вердикт
Дьявол НЕ нашёл ни одного места, где активный security-механизм заявлен доказанным, но при проверке
ломается — все 145 проверок реальны и воспроизводимы. Остаток — это **деплой и раздача ключей**, не
переписывание. По сравнению с исходным GPT-аудитом (7 блокеров + десятки high-risk) остаток сжался до
пунктов выше.

**BUILD_FREEZE: всё ещё BLOCKED** (честно) до: реальной раздачи ключей через secrets-broker, VPS-прод
e2e + runsc, прогона CI на CI, консолидации Rust. **Live-эффекты OFF.** Ничего не CLOSED без
воспроизводимого теста. Прогресс: из «архитектурная лаборатория» (вердикт GPT) → «механизмы боевого
уровня доказаны, остался контролируемый деплой».
