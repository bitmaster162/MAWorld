# secrets-broker

Целевая роль: выдача runtime-секретов по роли и классу данных с коротким сроком жизни, изоляцией и независимой ротацией.

Infisical выбран как возможное направление для внешнего runtime, а SOPS+age — для bootstrap. Это проектное решение, не подтверждение действующей или принятой production-интеграции. Текущий локальный контур не заменяет отдельный broker process, KMS/HSM custody и общий transactional replay store для replicas.

Целевые правила: ключи класса `FINANCIAL_SENSITIVE` изолированы и доступны только разрешённым ZDR-провайдерам; ротация одной роли не нарушает другие роли. Vault/SPIFFE рассматриваются как вариант при multi-node росте. Эти внешние свойства требуют отдельной acceptance-проверки.

Статус: **Production HOLD**. Infisical/runtime custody и multi-node enforcement не приняты; production-ключи загружать нельзя, LIVE остаётся OFF. Актуальные ограничения — в [`docs/44_SECURITY_HARDENING_2026-07-16.md`](../../docs/44_SECURITY_HARDENING_2026-07-16.md).
