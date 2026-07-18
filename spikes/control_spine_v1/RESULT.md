# Control Spine v1 — RESULT (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Все PASS/claims/counts ниже ограничены старым spike и
> не являются текущим доказательством обязательного enforcement, authority или production readiness.
> Не использовать команды и выводы как deploy/live-гейт. Актуальные источники:
> [security-аудит](../../docs/44_SECURITY_HARDENING_2026-07-16.md), [DEPLOY.md](../../DEPLOY.md)
> и [Rust security HOLD](../../apps/knowledge-foundry/RUST_SECURITY_HOLD.md). **LIVE остаётся OFF.**

Второй виток спайка по итогам 4 документов (2 DR-отчёта, ContinuityOS Broker Integration, Canonical Synthesis v1.1). Оба прогона зелёные против **реального** ContinuityOS.

## 1. MCP-aware preflight normalizer — 11/11

`python3 test_mcp.py`
```
PASS valid 2025-11-25 request        -> ALLOW
PASS RC 2026-07-28 -> HOLD           -> HOLD      (не фризим поведение на RC)
PASS missing version -> HOLD
PASS unknown version -> HOLD
PASS unknown MCP header -> DENY       (спуфнутый заголовок не форвардится)
PASS missing origin -> DENY           (Streamable HTTP 403 semantics)
PASS bad origin -> DENY
PASS token passthrough -> DENY        (спека прямо запрещает)
PASS audience mismatch -> DENY        (RFC 8707 audience binding)
PASS scope challenge -> HOLD          (инкрементальный scope = новое policy-решение)
PASS task created != complete -> HOLD (accepted != completed)
```

## 2. Mandatory egress broker (HARDEN-FIRST) — PASSED

`python3 enforcement_demo.py`
```
sandbox mechanism        : bwrap
direct network from agent: BLOCKED_GOOD          (сеть физически недоступна)
broker allowlisted host  : ALLOW, egress_performed=True
broker denied host       : DENY,  egress_performed=False
broker DOWN -> egress    : NO_BROKER (fail-closed)
audit chain              : {'ok': True, verified: 6}
-- checks: 4/4 PASS --  ENFORCEMENT DEMO PASSED
```

## Что доказано

**Enforcement gap закрыт в миниатюре** (главный дефект по всем 3 отчётам: сегодня гейт opt-in и обходим). Агент в network-denied песочнице (`bwrap --unshare-all`) НЕ имеет прямого выхода наружу; единственный канал — unix-сокет к брокеру, который вызывает **реальный** `ContinuityOS.preflight()` до любого egress. Хост не в allowlist → DENY. Брокер упал → NO_BROKER (fail-closed). Всё пишется в реальный hash-chain Ledger.

Прод-цель (из broker-отчёта): gVisor `runsc` + egress-deny network namespace + veth-to-proxy. Локально bwrap + unix-сокет дают то же fail-closed свойство.

**MCP-гейт приведён к проверенной спеке.** Нормализатор реализует MCP **2025-11-25** (последняя финализированная): Origin-валидация, OAuth audience binding, запрет token passthrough, инкрементальный scope → HOLD, async tasks (accepted ≠ completed). Version-gating: RC **2026-07-28** и любые неизвестные версии → HOLD (не фризим поведение на нефинальной спеке — как требует Synthesis §6.4).

## ФАКТ-КОРРЕКЦИЯ (важно)

В раунде 2 я записал «MCP 2026-07-28 (stateless, OAuth 2.1)» как **финализированную** спеку. Это **неверно**. Проверено по официальному changelog:
- **2025-11-25** — последняя **финализированная** версия (Streamable HTTP, Origin 403, OAuth PRM/RFC 9728, incremental scope via WWW-Authenticate, experimental tasks).
- **2026-07-28** — **Release Candidate** (провизорный, движется к stateless, убирает session-id). Не фризить поведение на нём.

Отчёт GPT (D6-r2) поймал это; broker-отчёт (Gemini) описывал именно RC. Мастер-доки поправлены (00_MASTER §15, ADR-R2-07).

## Запуск
```
export CONTINUITYOS_PATH=C:/PROJECTS/continuityos
python3 test_mcp.py            # нормализатор
python3 enforcement_demo.py    # мандаторный брокер (нужен bwrap; WSL/Linux)
```
На Windows без bwrap enforcement_demo печатает `UNSAFE_fallback` — для честного прогона нужен WSL/Linux с `bwrap` (прод — gVisor).

## Файлы
- `mcp_preflight.py` — нормализатор MCP 2025-11-25 + version-gating (перед `preflight()`).
- `test_mcp.py` — 11 детерминированных кейсов.
- `egress_broker.py` — мандаторный брокер: единственная egress-capability + реальный gate.
- `sandboxed_agent.py` — агент внутри песочницы (доказывает: прямой сети нет, только брокер).
- `enforcement_demo.py` — оркестрация + falsification (fail-closed).
- `gate_bridge.py` — мост к реальному ContinuityOS preflight+Ledger (из v0).
