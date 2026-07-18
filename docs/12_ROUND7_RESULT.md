# Round 7 — Implementation Result (2026-07-15)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


«Гони» — доделал остаток DR-2 closure. Три keystone-модуля, все зелёные против реального софта (ContinuityOS, git 2.34, bwrap).

## A. CanonPromoter (DR2 0x0B) — 10/10 — `services/canon-promoter/`
Единственный путь материализации canon в MAWorld-режиме. Knowledge Foundry CanonicalDecision — авторитетна; ContinuityOS `canon` namespace становится **производным compatibility view**, писать в него может ТОЛЬКО CanonPromoter после полной цепочки:
```
CanonCandidate → Foundry evidence validation → ContinuityOS policy → human approval →
CanonPromoter (отдельный credential, подписанный источник, точный source-hash, идемпотентность,
supersession, audit) → материализация canon
```
Доказано на **реальном** ContinuityOS: прямой `Continuity.add_canon()` агентом → `CanonWriteForbidden` (структурно, GuardedContinuity); промоушен без evidence/policy-ALLOW/human-approval/правильного promoter-credential → DENY_*; идемпотентность по source-hash (повтор не дублирует canon); supersession помечает старую запись; audit-цепочка цела. Это закрывает риск 0x0B — «add_canon() пишет напрямую без авторизации».

## B. ExternalEffectRegistry (DR2 0x0C) — 7/7 — `services/workflow-runtime/`
Формальный реестр внешних эффектов поверх idempotent fire-once: **reversibility class** (REVERSIBLE/COMPENSATABLE/IRREVERSIBLE/UNKNOWN) + **reconciliation** + **compensation**.
- Эффект стреляет один раз; replay → REPLAYED_NO_REFIRE.
- Краш между SENT и CONFIRMED → `reconcile()` пробит внешний мир: **CONFIRMED** → усыновить без повторного выстрела; **ABSENT** → безопасный retry; **AMBIGUOUS** → **HOLD** (никогда не авто-ретраить в side effect).
- COMPENSATABLE → компенсация исполняется; **IRREVERSIBLE → HOLD** для человека.

## C. Spike B — git commit + push HOLD (v1.4 §7) — 7/7 — `spikes/spike_b_git/`
Первый реалистичный Codex-workflow. Владелец просит «подготовить патч и закоммитить»; DelegationGrant даёт `repo.read/worktree.write/test/git.commit`, но **НЕ `git.push`**.
```
worktree.write в песочнице (bwrap)  : ok
commit под capability                : ALLOW, sha=adc6990f7d
git push                             : HOLD (capability не в гранте)  ✅
краш после commit до записи CONFIRMED → reconcile против git log → CONFIRMED, БЕЗ повторного коммита
replay commit                        : REPLAYED_NO_REFIRE, коммитов с маркером 1→1  ✅
evidence: 1 file changed, 1 insertion(+)
```
Ключевое: commit — IRREVERSIBLE внешний эффект; после «краша» recovery сверяется с реальным git log и **не создаёт дубль коммита**; push остаётся за явным одобрением. Соединяет capability tokens (R5) + ExternalEffectRegistry (B) + sandbox.

## Статус DR-2
Было OPEN из-за: CanonPromoter, формального ExternalEffectRegistry, Spike B — **все три закрыты и доказаны**. Обновлён `11_DR2_GAP_BYPASS_MATRIX.md`.

Осталось (не-keystone, MED/LOW): полный набор side-effect адаптеров (Git/Network/MCP/Secret/Deployment/Notification/Trading как единый интерфейс), MCPAuthorizationResolver как отдельный сервис, BudgetRouter+PriceCatalog, EvalRegistry runner, консолидация 24 контрактов (0x13) в единый JSON-Schema+Rust+Python+PG набор, gVisor runsc вместо bwrap на Linux VPS.

## Запуск
```
CONTINUITYOS_PATH=C:/PROJECTS/continuityos python3 services/canon-promoter/test_canon_promoter.py   # 10/10
python3 services/workflow-runtime/test_external_effect_registry.py                                   # 7/7
python3 spikes/spike_b_git/spike_b_git.py                                                            # SPIKE B PASSED
```
