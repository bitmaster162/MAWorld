# DBOS durable workflows on PROD Postgres — crash-recovery, no duplicate effect (M8)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Слово `PROD` в заголовке и результаты ниже описывают
> прежний ephemeral spike, а не действующую production-процедуру или готовность MAWorld. Они не
> закрывают текущие Postgres/RLS/Rust authority-гейты, не разрешают запуск команд и не разрешают LIVE.
> Актуальные источники: [security-аудит](../../docs/44_SECURITY_HARDENING_2026-07-16.md),
> [DEPLOY.md](../../DEPLOY.md) и [Rust security HOLD](../../apps/knowledge-foundry/RUST_SECURITY_HOLD.md).
> **LIVE остаётся OFF.**

Closes ACT verdict **M8**: previously crash-recovery was proven only on SQLite (`control_spine_v0`).
Here it runs on **real PostgreSQL 16.4** with the DBOS system database in Postgres, and the durable
state survives a **full database restart** (not just a client reconnect).

## What ran (reproducible: `stage1.sh` then `stage2.sh`)
Rootless embedded Postgres 16.4 (zonky binaries, no root), fresh cluster on :5434.

**Stage 1 — init, migrate, crash**
- `initdb` fresh cluster; `createdb maworld dbos_sys`.
- Applied the **real KF migrations** (`001_intake_core_v1_1.sql` 8806B, `002_rls_roles.sql` 1678B) →
  9 public tables in `maworld`. This is exactly `DEPLOY.md §2`, proven on Postgres.
- DBOS launched with `system_database_url = postgresql://maworld@localhost:5434/dbos_sys`.
- Workflow `wf(order-M8FIXED)`: `step_effect` writes the external effect (simulated venue order),
  commits durably to Postgres, then the process **hard-crashes** (`os._exit(137)`) before `step_after`.
- Effect log after crash: **1** EFFECT line. PG stopped cleanly (`pg_ctl -m fast`).

**Stage 2 — restart DB, recover**
- Postgres **restarted from the same data dir** → durable workflow state survived a full DB restart.
- `DBOS._recover_pending_workflows(["local"])` → **recovered 1 workflow**, completed with
  `{'done': 'order-M8FIXED'}`.
- Effect fire count stays **1 → PASS no-duplicate-effect**.

## Why no duplicate (the mechanism, verified in Postgres)
`dbos.operation_outputs` recorded both `step_effect` and `step_after`. On recovery DBOS saw
`step_effect` already durably complete and **did not re-run it** — only `step_after` executed.
- `dbos` schema: **11 tables** in Postgres.
- `dbos.workflow_status`: `SUCCESS = 1` (recovered workflow reached terminal success).

## Result
| Claim | Evidence |
|---|---|
| KF prod migrations apply on Postgres | 001+002 applied, 9 tables |
| DBOS system DB on Postgres | `dbos` schema, 11 tables |
| Crash after effect → recovery, no duplicate | EFFECT count = 1 across crash+restart+recover |
| Durability survives full DB restart | recovered after `pg_ctl stop`/`start` on same data dir |

Remaining for the actual VPS: point `DBOS_SYSTEM_DATABASE_URL` at the managed Postgres and run the
same two stages. No code changes — this spike *is* the prod path, just on an ephemeral cluster.
