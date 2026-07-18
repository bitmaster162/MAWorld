# УСТАРЕВШИЙ деплой-раннбук — HISTORICAL / SUPERSEDED / NON-OPERATIVE

> [!CAUTION]
> **НЕ ИСПОЛНЯТЬ НИ ОДНУ КОМАНДУ ИЗ ЭТОГО ФАЙЛА — ни локально, ни на CI, ни на сервере.**
> Разделы 0–5 сохранены только как исторический журнал и не являются процедурой деплоя. Старые
> количества `11/11`, `20/20`, `177`, `16/16`, прежние install-команды и любые описанные здесь
> live-гейты недействительны. Этот файл не выдаёт authority и не разрешает LIVE.
>
> Действующие источники: [полный security-аудит](44_SECURITY_HARDENING_2026-07-16.md),
> [текущий deploy-gate](../DEPLOY.md) и [Rust security HOLD](../apps/knowledge-foundry/RUST_SECURITY_HOLD.md).
> **LIVE остаётся OFF; BUILD FREEZE остаётся BLOCKED до закрытия текущих гейтов.**

Ниже записан прежний, ныне отменённый порядок. Даже явное «go» владельца не делает эти команды
актуальными: сначала требуется пройти гейты из текущего `DEPLOY.md` и security-аудита.

## 0. Key custody (ИСТОРИЧЕСКИ; КОМАНДЫ НЕ ИСПОЛНЯТЬ)
Раздать домены ключей РАЗНЫМ держателям (модель `libs/maworld_core/key_custody.py`, 11/11):
```bash
# dev -> SOPS+age, потом Vault/KMS. Каждый домен в СВОЁМ хранилище/держателе.
sops --encrypt --age <AGE_PUB> secrets/engine.key   > secrets/engine.key.enc     # у verifier-энклейва
sops --encrypt --age <AGE_PUB> secrets/approver.key > secrets/approver.key.enc    # у approver-сервиса (НЕ у промоутера)
sops --encrypt --age <AGE_PUB> secrets/gate.key     > secrets/gate.key.enc        # у gate
sops --encrypt --age <AGE_PUB> secrets/human.key    > secrets/human.key.enc       # у control-plane
sops --encrypt --age <AGE_PUB> secrets/cap.key      > secrets/cap.key.enc         # у capability-issuer
# Инвариант (тест key_custody): промоутер держит gate-ключ и НЕ может подписать approver-домен.
```
Приёмка: `PYTHONPATH=libs python3 tests/test_registry_custody.py` (11/11) на целевой раскладке ключей.

## 1. CI на CI (ИСТОРИЧЕСКИ; КОМАНДЫ И СТАРЫЕ COUNTS НЕ ИСПОЛЬЗОВАТЬ)
На момент этой записки `.github/workflows/ci.yml` гонял тогдашний набор проверок. Указанные ниже
числа устарели и не являются текущей приёмкой.
```bash
git add libs services apps tests .github pyproject.toml && git commit -m "adversarial suite + single source"
git push   # GitHub Actions: check_single_source (6/6) + run_all (20/20, 177 проверок) должны быть зелёными
```
Приёмка: зелёный workflow. До этого — freeze не снимаем.

## 2. runsc (M7; ИСТОРИЧЕСКИ; INSTALL-КОМАНДЫ НЕ ИСПОЛНЯТЬ)
```bash
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor.gpg
echo "deb [signed-by=/usr/share/keyrings/gvisor.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt-get update && sudo apt-get install -y runsc
# подготовить rootfs (python3) в /var/lib/tier2/rootfs; затем:
python3 services/sandbox-broker/tier2_acceptance.py   # тот же 16/16, но механизм=runsc
```
Приёмка: acceptance зелёный на механизме runsc; bypass-матрица fail-closed.

## 3. DBOS → managed Postgres (ИСТОРИЧЕСКИ; НЕ PROD-ПРОЦЕДУРА)
```bash
createdb maworld
psql maworld -f apps/knowledge-foundry/schema/001_intake_core_v1_1.sql
psql maworld -f apps/knowledge-foundry/schema/002_rls_roles.sql
# RLS runtime-роль (non-superuser, NOBYPASSRLS) — по apps/knowledge-foundry/schema/rls_scoped_test.sh
# pgbouncer ТОЛЬКО transaction-mode (RLS+SET LOCAL несовместимы со statement-pooling)
export DBOS_SYSTEM_DATABASE_URL="postgres://maworld@<host>/maworld"
bash spikes/dbos-postgres-m8/stage1.sh && bash spikes/dbos-postgres-m8/stage2.sh  # crash-recovery, effect x1
```
Приёмка: recovery без дубля на managed PG; RLS-изоляция держится на runtime-роли.

## 4. Observability (ИСТОРИЧЕСКОЕ ПРЕДЛОЖЕНИЕ)
Langfuse self-host (MIT) + OTel/OpenInference; `services/trace-bridge` эмитит спаны от GLOBAL вниз,
`trace_id ↔ claim_id` → cost-per-verified-outcome виден по одному прогону.

## 5. Live (ОТМЕНЕНО; НЕ ЯВЛЯЕТСЯ LIVE-GATE)
Старый порядок testnet → SHADOW → CANARY не разрешает торговлю и не является достаточной приёмкой.
`RiskService` здесь был только архитектурным предложением: он **не authority**, а его Rust-реализация
не прошла необходимую toolchain/overflow/authority-проверку. Никакая формулировка этого раздела не
разрешает LIVE; актуальный статус берётся только из текущего `DEPLOY.md`.

## Текущий статус этого файла
Этот runbook целиком superseded. Он не может закрывать гейты и не должен использоваться как checklist.
Следовать только `DEPLOY.md`, `docs/44_SECURITY_HARDENING_2026-07-16.md` и
`apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
