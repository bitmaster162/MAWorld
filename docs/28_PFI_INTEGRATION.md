# PFI → MAWorld: безопасная граница интеграции

Дата актуализации: **2026-07-16**

## Статус источника

Реальный PFI corpus в текущем workspace не подтверждён. Checked-in данные являются **representative fixture**, а не доказательством live ingestion или полноты внешнего PFI.

Поэтому любые прежние утверждения о прогоне «реального файла», полном количестве сигналов или фактической синхронизации следует считать отозванными до воспроизводимой приёмки на предоставленном corpus.

## Контракт

PFI — недоверенный внешний источник:

1. corpus/root и verification key задаются явно доверенным bootstrap-кодом;
2. default path и env-подстановка не дают authority;
3. размер файла, количество строк, схема и symlink/path traversal ограничиваются до парсинга;
4. вход проходит input/injection guard и provenance tagging;
5. сигнал сохраняется только как UNVERIFIED/PROPOSED;
6. предложенное действие не выполняется автоматически и не становится CANON;
7. direct-write путь в доверенное хранилище отключён;
8. любой последующий effect требует обычный signed ActionAuthority boundary.

## Что доказывают локальные тесты

PFI-контур входит в общий root adversarial-прогон **50/50 suites, 900 assertions**. Это подтверждает поведение checked-in fixture и fail-closed контрактов в локальном окружении.

Это не подтверждает:

- происхождение или полноту настоящего PFI corpus;
- сетевую синхронизацию с внешним PFI;
- корректность внешних источников;
- право автоматически изменять память, policy или canon;
- production scheduling и retention.

## Приёмка настоящего corpus

Для закрытия интеграции нужны:

- явно предоставленный immutable snapshot и его digest/signature;
- задокументированные schema/version/source;
- воспроизводимый parser run с quarantine-отчётом;
- signed evidence по числу принятых, отклонённых и дублированных записей;
- проверка, что все результаты остаются proposal-only;
- независимая проверка отсутствия direct write и live effects;
- повторный root и active-entrypoint прогон.

До этого PFI integration остаётся **fixture-validated, production-blocked**.

