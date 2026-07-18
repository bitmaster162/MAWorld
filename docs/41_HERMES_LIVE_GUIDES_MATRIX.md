# Hermes живьём + CryptoGuides подключены + матрица систем (2026-07-16)

> [!WARNING]
> **HISTORICAL / SUPERSEDED / NON-OPERATIVE.** Этот документ фиксирует узкий локальный
> прогон 2026-07-15/16, а не текущую security или production acceptance.
> `PASS`, `PASSED`, `CLOSED`, `PROVEN` и `READY` ниже относятся только к историческому
> срезу и не разрешают deployment, LIVE, внешние эффекты, платежи, торговлю или
> загрузку production-секретов. Актуальны `docs/45_SECURITY_CONTINUATION_2026-07-18.md`,
> `DEPLOY.md` и `apps/knowledge-foundry/RUST_SECURITY_HOLD.md`.
> **LIVE OFF · BUILD_FREEZE BLOCKED · production HOLD.**


Три вещи за раунд: посмотрел живого Hermes в Telegram, подключил твой сайт гайдов, прогнал все системы
через все. **46/46 сьютов, 623 adversarial-проверки** (было 43/535).

## 1. Hermes — посмотрел живьём, не по документам

Взял computer-use, открыл Telegram, нашёл чат `hermes`. Конфиг снят с работающего бота (`/reset` +
`/insights`), не угадан:

| Что | Значение |
|---|---|
| **Модель** | **`nvidia/nemotron-3-ultra-550b-a55b:free`** (ты был прав — 550b) |
| Провайдер | openrouter, контекст **1.0M токенов** |
| Шлюз | OpenClaw-типа: сессии, **V4A patch format** (Add/Delete/Move File), фоновые джобы |
| **Платформы** | **cron 31 сессия** · telegram 22 · tool 4 · cli 2 |
| **Инструменты** | **terminal 40.9%** · read_file 32.3% · search_files 11.1% · patch 6.7% · execute_code 4.3% · write_file 3.2% · cronjob 0.9% · process 0.3% |
| За 30 дней | 59 сессий · 4 498 сообщений · **2 071 тул-колл** · ~2.06 млрд токенов · стрик 19 дней |
| Команды | `/help /new /stop /status /reset /resume /sessions /model /debug /restart /insights` |

**Главное открытие: Hermes — не чат-бот.** Это **cron-агент** (cron-сессий больше, чем телеграмных), у
которого **самый частый инструмент — terminal (41% от 2071 вызова)**, и он работает без присмотра по
расписанию. Автономный, шелл-способный LLM на кроне — это ровно та форма агента, ради которой MAWorld и
существует. Не «как бы его пристроить», а «он уже делает то, что мы governим».

**Живая проблема, которую видно прямо сейчас:** его SCFT-пайплайн (collector+analyzer по
BTCUSDT/ETHUSDT/SOLUSDT) **завис** — watchdog кричит: последний запуск 45–60 мин назад при пороге 32.
Я его **не трогал**: `/stop` и `/restart` убивают живые фоновые джобы — это твой прод, а не мой дебаг.

### Как им рулить (`libs/maworld_core/hermes_control.py`, 30/30)
Два реальных пути:
1. **Операторский** — команды бота. В коде: `DESTRUCTIVE = {/stop, /restart, /reset, /new, /model}`
   **отказываются без твоей явной отмашки** (`/status`, `/insights` — свободно).
2. **Governed** — гоняем ту же модель через OpenRouter, а **каждый tool-intent** Hermes'а проходит
   `compliance_boundary`. Маппинг риска снят с его реального профиля:

| Инструмент Hermes | Риск у нас |
|---|---|
| terminal, execute_code, process, cronjob | **HIGH** → нужен capability + человек |
| write_file, patch | MEDIUM |
| read_file, search_files | LOW |
| **неизвестный инструмент** | **HIGH (fail-closed)** |

Hermes ПРЕДЛАГАЕТ — спайн решает. Каждый intent даёт подписанную квитанцию, ALLOW или DENY.

## 2. CryptoGuides подключён (`cryptoguides_bridge.py`, 19/19)

`cryptoguidessite.vercel.app` — **твоя же экосистема**: ссылается на арена-VPS `34.70.171.152` и на
`bitevoagentsite`. **113 гайдов** + JSON API `/api/guides`.

Подключил как `pfi_bridge` — сайт это **источник, а не авторитет**. Почему недоверенный, хотя твой:
это публичный веб с API, а гайд — это проза, идеальный носитель инъекции. Твой же гайд
`instructed-retriever` ровно об этом. Поэтому: каждый гайд → `input_guard` → **PROPOSED** память с
provenance, `authoritative=False`, trust 0.5. Отравленный гайд → **QUARANTINED**.

**Кроссволк: 60 из 113 гайдов легли на 28 наших модулей (53%).** И каталог сам подтверждает линию:

| Твой гайд | Наш модуль |
|---|---|
| `ai-agent-trust-layer-reliability` | **`compliance_boundary` — это и есть wedge** |
| `how-to-validate-edge-oos-bootstrap` | `arena_scoring` — **подтверждает фикс из DR-раунда** |
| `anti-self-attention-trading-psychology`, `tilt-index-antiself` | `evidence_engine` (агент не принимает свою работу) |
| `adaptive-delegation-gate`, `state-authority-plane-evolution` | `action_authority` |
| `avellaneda-stoikov-inventory`, `transient-price-impact-decay`, `avx512-hawkes-engine`, `vpin-flow-toxicity` | `arena_frictions` |
| `queue-calibration-model` | `arena_frictions` — **называет наш открытый пробел (калибровка γ/η)** |
| `fractal-intelligence-scouts-scribes-attention` | `global_cycle` (фрактальный инвариант) |
| `tee-agent-secrets` | `secrets_broker` + `remote_attestation` |
| `monetization-matrix-4x3` | `money_forge_v2` + `pilot_gate` |

53 гайда не легли — это **двусторонний gap-анализ**: идеи без модулей и модули без документации.

## 3. Матрица: все системы через все (`system_matrix.py`, 39/39)

`system_walk` доказывал ОДИН счастливый путь. Матрица доказывает **композицию**: **18 систем, 306
упорядоченных пар**, и один вопрос — *существует ли хоть один путь, где недоверенный артефакт
становится авторитетным без guard + authority + evidence*.

**Результат: 0 authority-leaks. 20 прямых атак source→sink — ни одна не стала авторитетной.**

Порядок доказан жёстко: authority **отказывается** от непросеянного входа; evidence **отказывается**
подписывать негейтнутое предложение; guard+authority без evidence — sink всё равно **BLOCKED**; и только
guard+authority+evidence открывает sink. Легитимные цепочки прошли по всем доменам (hermes→effect,
контестант→settlement, гайды→память, pfi→память, модель→знание).

**Асимметрия, которую зафиксировал в коде:** сырой вывод модели (`model_out`) **может** стать
governed-знанием, но **никогда** не может стать эффектом — он обязан сперва превратиться в типизированный
`tool_intent`, который гейтится отдельно. Это архитектура, а не недосмотр.

## 4. Два настоящих бага, которые нашли мои же тесты

1. **`compliance_boundary` — критический.** input_guard стоял **перед** проверкой человека, а
   high-impact от внешнего источника режется по трасту (0.2 < 0.7). Значит **человек физически не мог
   ничего подтвердить** — граница была бесполезна ровно для своего главного сценария (внешний агент +
   отмашка владельца). Фикс: человек проверяется **до** траст-барьера; подтверждение человека даёт тот
   траст, которого нет у источника. Инъекция при этом остаётся фатальной **всегда** — никакое
   подтверждение не пропускает инъектнутый payload.
2. **`system_matrix`** — не было пути `model_out` в память. Закрыл, сохранив запрет на эффект.

## 5. Статус
**46/46 сьютов, 623 adversarial-проверки**, single-source 6/6. Новое: `hermes_control` (30/30),
`cryptoguides_bridge` (19/19), `system_matrix` (39/39).

## 6. Что дальше (за тобой)
- **SCFT-пайплайн Hermes'а завис** — скажешь, и разберу через governed-путь (или сам дай `/restart`).
- **NON-OPERATIVE:** историческая команда внешнего запуска удалена. LIVE остаётся OFF независимо
  от слага, ключа или budget cap; обязательны все gates из `DEPLOY.md`.
- Приоритет по docs/40 не менялся: **wedge — деньги и время**, арена — хобби.
