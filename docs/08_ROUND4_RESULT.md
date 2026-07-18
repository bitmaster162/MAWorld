# Round 4 — Implementation Result (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


По просьбе «делай и то и то» + GPT Synthesis v1.3 (ревью моего Rust intake). Оба внедрения зелёные, все против **реального** софта (ContinuityOS, PostgreSQL 16.4).

## A. MCP normalizer врезан в workflow — `spikes/control_spine_v2/` PASSED

`python3 run_v2.py`
```
[1] valid MCP 2025-11-25   -> COMPLETED, effect_fired=True
[2] spoofed MCP header      -> BLOCKED (stage=mcp), effect_fired=False
[3] RC 2026-07-28           -> BLOCKED (HOLD),       effect_fired=False
[audit] {'ok': True, verified: 13}
V2 PASSED
```
MCP-нормализатор теперь стоит в DBOS-workflow ПЕРЕД ContinuityOS gate; решение шага = `stricter(mcp, policy)`. DENY/HOLD блокируют до любого side effect. Крэш-безопасность из v0 сохранена.

## B. Knowledge Foundry Postgres/sqlx MetaStore + RLS — PASSED (real PostgreSQL 16.4)

### B1. RLS project-isolation (v1.3 §7) — 8/8, `schema/rls_isolation_test.py`
```
PASS 1. A-scope sees only A            PASS 3b. pool reuse does not leak
PASS    B-scope sees only B            PASS 2. blob only via authorized occurrence
PASS 3. missing scope -> 0 (fail-closed) PASS 7. injection in scope value cannot widen
PASS 6. deleted occ removes blob linkage PASS 5. admin bypass sees all (audited sep.)
RLS ISOLATION PROVEN
```
Миграции `001_intake_core_v1_1.sql` + `002_rls_roles.sql` применяются чисто. Scope задаётся `SET LOCAL` (транзакционно, не session state) под non-superuser ролью `kf_runtime` → нет утечки при переиспользовании пула. Admin/seed — отдельный superuser-путь. `raw_blob` без RLS (байты глобальны), доступен только через авторизованную occurrence.

### B2. Rust `PostgresMetaStore` (sqlx) — `kf-store-pg/`, integration test PASSED
```
cargo test --test dedup  (KF_TEST_DATABASE_URL -> live pg)
PG METASTORE OK: 1 blob, 2 occurrences, dedup + idempotency verified
```
Тот же трейт `MetaStore`, что у offline JSONL-импла (v1.3 step C). sqlx runtime-queries (компилится без БД; CI добавит `cargo sqlx prepare --check` — KF-RUST-007). Доказано на реальном Postgres: одинаковые байты под двумя source-id → один RawBlob, две Occurrence; идемпотентная повторная observation находит существующую.

## Корректировки из v1.3, внесённые

| v1.3 | Что сделано |
|---|---|
| §4 hard-link caveat | CAS больше НЕ зависит от hard links: `hard_link` при поддержке, иначе `create_new`+copy (портируемо на Windows/network FS). kf-intake пересобран, demo зелёный. |
| §7 RLS `SET LOCAL` + pool-leak + admin separation | Реализовано в `002_rls_roles.sql` + доказано (B1). |
| §6 sqlx | PostgresMetaStore на sqlx (B2); offline-prepare — в CI-тикет. pgvector НЕ в intake-срезе (как и требует §6). |
| §10 reproducibility package | `kf-intake/repro/MANIFEST.json` (toolchain, source hashes, release-binary sha256) + `acceptance.log` + `rust-toolchain.toml`. |
| §2 language boundary | Принята уточнённая формулировка: авторитет — от владения сервисом/политики/контрактов, НЕ от языка. Обновлён `06_KNOWLEDGE_FOUNDRY_RUST_VERDICT.md`. |

## Промоушен-гейт v1.3 §14 — статус

Закрыто в этой сессии (независимо воспроизведено): DDL применяется к чистому Postgres ✓; RLS-изоляция проходит ✓; точное восстановление байт по хешу ✓; дубль-intake → 1 RawBlob + N Occurrence ✓; идемпотентность ✓; audit-цепочка ловит подмену ✓; нет cross-project утечки ✓; repro-манифест+SBOM-хеши ✓. Остаётся для полного `VERIFIED_IMPLEMENTATION_EVIDENCE`: независимая пересборка на твоей машине по `repro/MANIFEST.json`.

## Как прогнать у себя
```
# MCP+workflow
cd spikes/control_spine_v2 && export CONTINUITYOS_PATH=C:/PROJECTS/continuityos && python3 run_v2.py
# RLS (нужен Postgres)
python3 apps/knowledge-foundry/schema/rls_isolation_test.py <host> <port> <user> <db> \
    apps/knowledge-foundry/schema/001_intake_core_v1_1.sql apps/knowledge-foundry/schema/002_rls_roles.sql
# Rust PostgresMetaStore
cd apps/knowledge-foundry/kf-store-pg && KF_TEST_DATABASE_URL=postgres://user@host:port/db cargo test -- --nocapture
```
Заметка: Postgres в этой сессии поднят rootless (zonky embedded 16.4) — тот же способ годится для CI без root.
