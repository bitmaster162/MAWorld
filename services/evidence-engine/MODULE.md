# evidence-engine (DR-4 core)

Формализует `Audit ≠ Evidence ≠ Acceptance` и поток:
`Claim → EvidenceRequirement → EvidenceCollection → VerificationResult → AcceptanceDecision → RegressionFixture`.

## Инварианты (fail-closed, протестировано 24/24)
- **Агент не принимает свою работу.** `accept()` требует `VERIFIED` от детерминированного верификатора;
  self-claim «готово» без доказательства → reject.
- **Vanity ≠ acceptance** (Money Forge): views/likes/model_interest/artifacts_created НИКОГДА не
  доказательство успеха продукта — только payment/renewal/signed_pilot/retained_usage.
- **Failure → asset:** каждый провал даёт `RegressionFixture` (failure_class + repro) для CI.

## Реальные верификаторы
`file` (sha256/substr) · `code_tests` (реальный exit-code) · `commit` (`git cat-file` + diff paths) ·
`workflow_recovered` (effect fired ровно 1 — тот же инвариант, что M8) · `memory_promoted`
(promotion state ACTIVE + human approval) · `continuity_preserved` (model-swap test) ·
`product_success` (hard economic signal).

## Pilot gate
`pilot_gate(pilots)` → SCALE только если ≥5 пилотов и ≥3 платят/продлевают ($199), иначе HOLD.

## Границы
Authority-нейтрален: ПРОВЕРЯЕТ claims, не исполняет эффекты и не пишет canon. Ремонт по проваленной
проверке — отдельное gated-действие через ContinuityOS. Прогон в едином e2e: `services/integration/m6_e2e.py`.

## Тест
`python3 test_evidence_engine.py` → 24/24 (accept реального доказательства + reject подделки/недостатка
по каждому виду claim).
