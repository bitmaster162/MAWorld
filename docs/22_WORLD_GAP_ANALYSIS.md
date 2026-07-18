# MAWorld — чего не хватает и как усилить весь мир (gap analysis), 2026-07-15

Проход по ВСЕМ модулям/проектам + сверка с «что команды упускают в проде агентов 2026» (OWASP AST10:
skill/plugin execution — самый рискованный слой; supply-chain/подписанные плагины; secrets/DLP;
избыточные права; governance human-in-loop). Ранжировано по риск×ценность.

## A. Пустые/скелетные слоты (заявлены, но кода нет) — закрыть первыми
| Слот | Что нужно | Чем усилить (готовая база у нас) |
|---|---|---|
| services/secrets-broker | НЕТ секрет-брокера (крит.). SOPS+age (dev)→Infisical/Vault; ключи по роли/классу данных; никакого plaintext | tier2 fail-closed + capability-модель; интегрировать с action_authority (ключи не в процессе-исполнителе) |
| agents/* (orchestrator/supervisor/challenger/executors) | Только конфиги-заглушки; нет реальных промптов/раннеров | CTHA proposer boundary (control_spine_v4) + LifeOS lifecycle; challenger = mind/dialectic (реальный) |
| apps/control-plane | Telegram approvals, API gateway, nonce | control_spine_v0 telegram_ingress (secret_token+nonce доказан) + action_authority (human confirm bound to hash) |
| services/trace-bridge | OTel спаны → Langfuse; нет | docs/16 вердикт (Langfuse+OTel); связать trace_id↔claim_id (Evidence) |
| services/handoff-gateway | HandoffEnvelope + capability resolver; нет | capability tokens (control_spine_v3) + fork без наследования authority (LifeOS) |
| services/memory-governor | promotion lifecycle; частично | canon_sod (SoD approval) + Governed Memory паттерн |
| services/improvement-engine | Improvement loop раннер; нет | EvalRegistry + ImprovementProposal (спроектированы) + Evidence Engine приёмка |

## B. Системные усиления (по аудиту GPT + внешнему ресёрчу)
1. **Один источник правды для security-модулей.** Есть дубли (effect registry, gate bridge, sandbox) —
   фикс одной копии не чинит остальные. Вынести в общий пакет `libs/` и импортировать; удалить копии.
2. **Supply-chain / подписанные артефакты.** Плагины/скиллы/MCP-сервера подписывать и верифицировать
   (OWASP AST10). Evidence Engine `commit_made`/`file_created` уже даёт хеш-приёмку — расширить на
   подпись поставщика.
3. **DLP / output filtering.** Агент не должен разглашать секреты/PII — фильтр на выходе + запрет чтения
   `.env` (уже соблюдаю). Добавить redaction-слой перед любым внешним эффектом.
4. **Least privilege везде.** Заменить строковые «capability» (SideEffectAdapter, LifeOS) на
   подписанные токены (как action_authority). Убрать prefix-проверку пути → строгий realpath-allowlist.
5. **Durable, не RAM.** BudgetRouter/CanonPromoter/replay-guard: состояние в durable store (не RAM);
   BudgetRouter — запретить отрицательную стоимость и абсолютный потолок над P0.
6. **Reproducibility/CI (freeze-блокер).** root pyproject+lock, Cargo.lock+workspace, pinned image
   digests (не `latest`), единый pytest/cargo-test вместо ad-hoc `sys.exit`, CI гоняет adversarial-suite.
7. **Observability замкнуть в приёмку.** «cost per verified outcome» = trace ↔ Evidence acceptance.
8. **Sandbox лимиты.** tier2: добавить CPU/RAM/disk/output-limits + уникальный runsc container id.

## C. Приоритетный порядок усиления (следующие тикеты)
1. `libs/` единый источник security-модулей + удалить дубли (сразу гасит класс «fix-once не проходит»).
2. secrets-broker (SOPS→Infisical) + DLP-redaction — самый рискованный слой (AST10).
3. Подписанные capability везде (SideEffectAdapter/LifeOS) + realpath-allowlist.
4. control-plane (Telegram approvals через action_authority human-confirm) — реальный human-in-loop.
5. CI + lockfiles + digest-pins + единый тест-раннер → снимает freeze-блокер по ops.
6. trace-bridge (Langfuse+OTel) + cost-per-verified-outcome.
7. Заполнить agents/* реальными раннерами поверх CTHA/LifeOS; improvement-engine на EvalRegistry.

## Инвариант усиления
Всё новое садится ПОВЕРХ доказанных примитивов (authority у детерминированного spine; приёмка через
Evidence Engine v2 подписанными доказательствами; эффекты через hardened registry; действия через
action_authority hash-binding). Ничего не помечается CLOSED без воспроизводимого adversarial-теста.
Live-эффекты OFF до зелёного CI по всей suite. Источник по «что упускают»: OWASP AST10 / prod-agent 2026.
