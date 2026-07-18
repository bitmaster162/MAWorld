# Spike: Control Spine v0 — falsification test

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот spike и его команды сохранены только как архив
> локального эксперимента. Они не доказывают текущий enforcement, production readiness или authority
> и не являются инструкцией к запуску. Не использовать старые PASS/counts как deploy-гейт.
> Актуальные источники: [security-аудит](../../docs/44_SECURITY_HARDENING_2026-07-16.md),
> [DEPLOY.md](../../DEPLOY.md) и [Rust security HOLD](../../apps/knowledge-foundry/RUST_SECURITY_HOLD.md).
> **LIVE остаётся OFF.**

**Что доказываем (D6 §MVP, самый маленький фальсифицируемый спайк):**

> Telegram → API Gateway → Orchestrator plan → ContinuityOS preflight → sandbox exec → verification → immutable audit. Убить процесс посреди исполнения, перезапустить, доказать что workflow возобновляется **без повторного внешнего side effect**, и что аудит-трейс сходится.

Если этот спайк падает на crash-recovery, authority-binding или audit-корреляции — контрольный хребет ещё не готов. Если проходит — у нас реальный MVP-путь, а не бумажный дизайн.

## Что здесь настоящее (не заглушки)

| Компонент | Реализация | Источник |
|---|---|---|
| Policy gate | **реальный** `continuityos.gate.preflight()` из `C:\PROJECTS\continuityos` | твой OSS-пакет v0.9.0 |
| Tamper-evident audit | **реальный** `continuityos.gate.ledger.Ledger` (hash-chain SQLite, `.verify()`) | твой OSS-пакет |
| Durable workflow | **DBOS 2.27** на SQLite (completed steps не пере-исполняются) | D6 вердикт: DBOS+Postgres, здесь SQLite для спайка |
| Sandbox Tier2 | **bubblewrap** (`bwrap`): unshare-all, network off, ro-bind, tmpfs | D6: прод-цель gVisor/rootless OCI; bwrap — локальный стенд того же механизма |
| Telegram ingress | HMAC-проверка `X-Telegram-Bot-Api-Secret-Token` + nonce + expiry | D6: webhook secret_token, nonce-approvals |
| External Effect Registry | idempotency_key + reversibility class, replay не пере-стреливает | contracts/workflow/ExternalEffectRecord.yaml (ADR-D1) |

## Файлы

- `telegram_ingress.py` — верификация вебхука (secret_token + nonce), контракт как у настоящего бота.
- `gate_bridge.py` — мост к реальному ContinuityOS gate + Ledger. Единственная точка, где решается ALLOW/DENY.
- `sandbox.py` — bwrap-исполнение недоверенного кода (Tier2 механизм; gVisor в проде).
- `effect_registry.py` — идемпотентный реестр внешних эффектов (SQLite): эффект стреляет ровно один раз по ключу.
- `workflow.py` — DBOS durable workflow: plan → gate → **external effect (once)** → sandbox verify → audit. Есть управляемая точка краха.
- `run_spike.py` — happy path целиком, печатает трейс.
- `killtest.py` — запускает workflow, убивает процесс `kill -9` сразу после коммита эффекта, перезапускает, проверяет: эффект == 1, workflow завершился, ledger.verify() OK.

## Запуск (Windows/WSL или Linux с python3, bwrap)

```bash
cd spikes/control_spine_v0
pip install dbos --break-system-packages
export CONTINUITYOS_PATH="C:/PROJECTS/continuityos"   # путь к твоему OSS-пакету
python3 run_spike.py        # happy path
python3 killtest.py         # crash-recovery фальсификация
```

На Windows без bwrap: `sandbox.py` сам переключается на fallback (subprocess без изоляции) и **громко** это логирует — для честного прогона нужен WSL/Linux с `bwrap`, либо gVisor.

## Критерий прохождения

`killtest.py` печатает `SPIKE PASSED` только если ВСЕ верны:
1. `external_effect_count == 1` (эффект не задублировался при recovery).
2. Workflow дошёл до `COMPLETED` после перезапуска.
3. `Ledger.verify()` → цепочка цела (аудит не подделан).
4. DENY-команда (`rm -rf /`) реально не исполнилась (gate заблокировал до side effect).
5. Telegram-запрос с неверным secret_token отклонён до старта workflow.

## Почему ContinuityOS подключаем первым (ответ на твой вопрос)

Да — первым. Это единственная точка, через которую проходят все side effects (MVP §1: инициализировать gate **до** любых LLM-ключей). Спайк уже импортирует твой реальный `preflight` и `Ledger` — то есть ContinuityOS здесь и есть подключённый первым модуль. Когнитивный `mind/` (CTHA-разум) садится ПОВЕРХ этого хребта следующим шагом — по его же MIND_ARCHITECTURE он «пишет только в mind/runtime, канон только читает», то есть он потребитель гейта, а не сам гейт.
