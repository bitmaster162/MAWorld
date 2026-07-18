# Spike result — PASSED (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** `PASSED` ниже относится только к прежнему локальному
> spike и не означает закрытие текущих security/deploy-гейтов. Этот результат не доказывает
> production enforcement и не разрешает повторный запуск или LIVE. Актуальные источники:
> [security-аудит](../../docs/44_SECURITY_HARDENING_2026-07-16.md), [DEPLOY.md](../../DEPLOY.md)
> и [Rust security HOLD](../../apps/knowledge-foundry/RUST_SECURITY_HOLD.md). **LIVE остаётся OFF.**

Прогнано Claude в песочнице против **реального** ContinuityOS из `C:\PROJECTS\continuityos`.

## killtest.py (фальсификация)

```
[PHASE 1] crash injected right after external effect
  child exit code = 137        (killed after effect)   ✅
  effect fired_count after crash = 1                   ✅
[PHASE 2] restart -> DBOS recovery
  child(recover): recovered 1 workflow(s)              ✅
  child exit code = 0                                  ✅
--- RESULT ---
  external_effect fired_count : 1   (must be 1)        ✅
  orders.log lines            : 1   (must be 1)        ✅
  workflow.complete in audit  : True                   ✅
  ledger.verify()             : {'ok': True, 'verified': 6}  ✅
SPIKE PASSED
```

## run_spike.py (happy path)

```
[ingress] bad secret_token    -> ok=False (REJECTED_BAD_SECRET_TOKEN)   ✅
[ingress] valid owner request -> ok=True  (OK)                          ✅
[workflow] ALLOW -> COMPLETED, effect_fired=True, verify=bwrap          ✅
[workflow] DENY  -> BLOCKED, decision=DENY, effect_fired=False          ✅
[audit] ledger.verify() -> {'ok': True, 'verified': 8}                  ✅
```

## Что это доказывает (D6 §MVP)

Все 5 критериев зелёные:
1. Внешний эффект не задублировался при краше+recovery (idempotency + DBOS durable steps).
2. Workflow дошёл до COMPLETED после `os._exit(137)` и перезапуска.
3. Hash-chain аудит (**реальный** ContinuityOS Ledger) цел — `verify() ok`.
4. DENY (`rm -rf /`) заблокирован **реальным** `preflight()` ДО side effect.
5. Telegram-запрос с неверным `secret_token` отклонён до старта workflow.

Контрольный хребет — не бумага. ContinuityOS подключён первым и держит границу.

## Замечания среды

- **DBOS** гоняли на SQLite (`system_database_url=sqlite:///...`) — для спайка достаточно; в проде Postgres (вердикт D6).
- **Sandbox** — bubblewrap (`bwrap`, network off, ro-bind, unshare-all). Прод-цель Tier2 — gVisor/rootless OCI; bwrap — тот же класс механизма локально.
- **Запуск:** `export CONTINUITYOS_PATH=C:/PROJECTS/continuityos`, затем `python3 killtest.py`. На Windows-шаре держи `SPIKE_STATE` на локальной FS (WSL: `/tmp/...`) — SQLite WAL не любит сетевые маунты. `PYTHONDONTWRITEBYTECODE=1` желателен.
- Ledger'у добавлен потоко-переносимый connect (`check_same_thread=False`+lock), т.к. DBOS исполняет шаги/recovery в разных потоках. Это адаптер на нашей стороне, код ContinuityOS не трогали.
