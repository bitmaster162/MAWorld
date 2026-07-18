Архитектурное исследование: Проектирование и интеграция детерминированного торгового ядра с LLM-аналитикой
==========================================================================================================

01\_EVIDENCE\_AUDIT
-------------------

В таблице ниже представлен исчерпывающий аудит утверждений, извлеченных
из технической документации, репозиториев и профильных научных
публикаций, с оценкой их достоверности для принятия критических
архитектурных решений.

  **Утверждение (Claim)**                                                                                                                                                           **Источник**               **Официальное доказательство (Evidence)**                                                                                                                                                **Статус вердикта**   **Коррекция**                                                                                         **Уверенность**
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- -------------------------- ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- --------------------- ----------------------------------------------------------------------------------------------------- -----------------
  NautilusTrader использует строго однопоточный цикл для детерминированного бэктестинга, но предоставляет параллелизм через BacktestNode.                                           \[cite: 1, 2, 3\]          Документация описывает BacktestNode с пулом процессов для параллельного запуска независимых конфигураций, сохраняя однопоточность внутри самого BacktestEngine.                          VERIFIED FACT         \-                                                                                                    1.00
  Ядро NautilusTrader v2 написано на Rust, использует фиксированную запятую и поддерживает PyO3 биндинги.                                                                           \[cite: 4, 5, 6\]          В release notes (v1.230.0 / v2 RC) указан переход на Rust+PyO3, использование 128-битной арифметики с фиксированной запятой и отказ от старого ядра Cython.                              VERIFIED FACT         \-                                                                                                    0.99
  Платформа hftbacktest поддерживает live trading, но этот функционал является экспериментальным и реализован только на Rust.                                                       \[cite: 7, 8, 9\]          Предупреждение в документации: \"The live bot feature has not undergone comprehensive testing yet\... Rust-only\".                                                                       VERIFIED FACT         Не подходит для Python-ориентированного Control Plane без написания кастомных C-FFI.                  0.98
  Биржи OKX и Bybit официально заблокированы в Таиланде решением регулятора (SEC).                                                                                                  \[cite: 10, 11, 12, 13\]   В июне 2025 года SEC Таиланда обязала провайдеров заблокировать доступ к нелицензированным платформам, включая Bybit, OKX и CoinEx.                                                      VERIFIED FACT         \-                                                                                                    1.00
  Binance TH является полностью лицензированной платформой в Таиланде, но в настоящее время ограничена предоставлением деривативов розничным клиентам.                              \[cite: 14, 15, 16\]       Лицензия получена от Министерства финансов. Кабинет министров одобрил расширение на деривативы, но SEC еще находится в процессе формирования детальных спецификаций контрактов.          SOURCE CLAIM          Доступна только спотовая торговля (THB/Crypto). Маржинальная торговля/фьючерсы ожидают легализации.   0.95
  Hyperliquid предоставляет ончейн-книгу ордеров (L1), не требует KYC и не блокирует IP-адреса из Таиланда.                                                                         \[cite: 17, 18, 19, 20\]   В официальных Terms of Use (раздел 1.6 \"Restricted Persons\") указаны США, Канада (Онтарио) и ряд санкционных стран. Таиланд отсутствует в списке гео-блокировок.                       VERIFIED FACT         \-                                                                                                    0.99
  API биржи Bitkub имеет жесткие лимиты (rate limits), привязанные к User ID, требующие алгоритмов Exponential Backoff.                                                             \[cite: 21, 22, 23\]       Документация описывает лимит в 150 req/sec для эндпоинтов вроде /api/market/my-open-orders и требует реализации задержек при получении ошибки HTTP 429.                                  VERIFIED FACT         \-                                                                                                    1.00
  СУБД ArcticDB поддерживает битемпоральность и нативные запросы Point-in-Time для Pandas DataFrames.                                                                               \[cite: 24, 25, 26, 27\]   API предоставляет метод read() с параметром as\_of, позволяющим извлекать данные на конкретный исторический срез, исключая влияние поздних модификаций.                                  VERIFIED FACT         \-                                                                                                    1.00
  Большие языковые модели подвержены эффекту \"Look-ahead bias\" из-за присутствия будущих котировок в их обучающей выборке.                                                        \[cite: 28, 29\]           Исследование Look-Ahead-Bench демонстрирует явление Alpha Decay --- падение доходности на 15-22% при переходе моделей от in-sample к out-of-sample периодам.                             VERIFIED FACT         \-                                                                                                    0.98
  Паттерн TradingAgents декомпозирует финансовый анализ на роли, включая дебаты Bull/Bear, и выводит структурированный результат.                                                   \[cite: 30, 31, 32, 33\]   Исходный код версии 0.2.4 включает Structured-output agents, LangGraph checkpoints и сохранение журнала решений в SQLite.                                                                VERIFIED FACT         \-                                                                                                    0.97
  NautilusTrader поддерживает автоматическую реконсиляцию при перезапуске системы (crash recovery).                                                                                 \[cite: 34, 35, 36, 37\]   Конфигурация reconciliation=True активирует метод refresh\_account\_state(), сверяющий стейт с биржей, и опционально использует generate\_missing\_orders.                               VERIFIED FACT         \-                                                                                                    1.00
  Биржа Interactive Brokers (IBKR) предоставляет API, однако доступ к Market Data требует оплаты подписок и не гарантирует сверхнизких задержек для неинституциональных клиентов.   \[cite: 38, 39, 40, 41\]   Данные тарифицируются пакетами, подписки активируются при минимальном балансе. Задержки (delay periods) существуют для множества глобальных бирж, если не оплачен Real Time Streaming.   VERIFIED FACT         \-                                                                                                    0.95

02\_VERDICTS
------------

Анализ архитектурных компонентов проведен с учетом заданных ограничений:
детерминированный горячий путь, использование NATS JetStream для
асинхронного обмена сообщениями в формате SBE, запрет на использование
float64 в финансовых вычислениях и жесткий контроль рисков через
выделенный компонент RiskService.

### Task 1: BUILD VS ADOPT (Core Engine)

Проектирование детерминированной торговой микросервисной архитектуры с
нуля представляет собой колоссальную инженерную задачу, особенно для
одиночного разработчика. Рассмотрение доступных на рынке открытых
решений выявило четкого фаворита, способного удовлетворить требования
архитектуры. Платформа NautilusTrader обеспечивает полную семантическую
паритетность между режимами бэктестинга и live-торговли за счет
использования единого ядра^42^. Механизм симуляции в NautilusTrader
является строго однопоточным, что гарантирует абсолютный детерминизм при
воспроизведении исторических данных и маршрутизации событий^1^.
Важнейшим фактором для нашей архитектуры является то, что платформа
использует внутренние типы данных на основе 128-битной арифметики с
фиксированной запятой, что полностью исключает риски потери точности,
присущие float64^4^. Переход платформы на версию v2, где ядро переписано
на Rust с использованием PyO3 биндингов, обеспечивает целевые показатели
задержки (sub-ms), не требуя при этом сверхнизких (ultra-low)
HFT-задержек^4^. NautilusTrader предоставляет идеальные точки расширения
для интеграции нашего шлюза ContinuityOS: встроенный модуль RiskEngine
позволяет перехватывать команды до их отправки на исполнение и
маршрутизировать их через наш детерминированный RiskService^46^.

Альтернативные движки не выдерживают критики в контексте наших жестких
архитектурных ограничений. Платформа hftbacktest обладает великолепными
моделями оценки очередей L3, однако её модуль реальной торговли заявлен
как экспериментальный и требует разработки исключительно на Rust, что
усложняет интеграцию с Python-ориентированным Control Plane^8^. Решения
вроде Freqtrade и Hummingbot ориентированы на розничный сегмент,
используют float вычисления и не обладают строгой replay-архитектурой на
уровне событий L2-книги ордеров. QuantConnect LEAN представляет собой
монолитную экосистему на базе C\#, которая избыточна для управления
одним оператором.

Интеграционный риск при выборе NautilusTrader заключается в отсутствии
нативного коннектора для NATS JetStream и сериализации SBE. Для
реализации связи между плоскостью управления (Control/Observation Plane)
и торговой ячейкой потребуется разработка кастомных компонентов
DataClient и ExecutionClient, взаимодействующих с шиной сообщений^48^.
Однако архитектура платформы явно поощряет такое расширение через
MessageBus.

-   **Вердикт**: **ADOPT** NautilusTrader (v2 Rust core).

-   **Уверенность**: 0.95

-   **Триггер пересмотра**: Возникновение непреодолимых проблем с
    производительностью PyO3 биндингов при интенсивной инъекции событий
    из NATS JetStream в LiveExecutionEngine.

### Task 2: VENUE AND CONNECTIVITY

Выбор торговых площадок для индивидуального оператора, базирующегося в
Таиланде, требует балансировки между регуляторными ограничениями,
качеством API и доступом к целевым финансовым инструментам.
Законодательство Таиланда и позиция SEC строго регулируют оборот
цифровых активов. В середине 2025 года регулятор предписал провайдерам
связи заблокировать доступ к нелицензированным глобальным платформам, в
результате чего OKX, Bybit и ряд других бирж стали недоступны для
локальных IP-адресов^10^. Попытки обхода блокировок через VPN для
алгоритмической торговли неприемлемы из-за рисков внезапной заморозки
аккаунтов и нарушения связности API.

Binance TH (совместное предприятие Gulf Binance) обладает лицензией SEC
Таиланда и предоставляет доступ к качественному API, унаследованному от
глобального Binance^15^. API поддерживает идемпотентность через параметр
newClientOrderId и имеет развитые эндпоинты для реконсиляции (Query
Order, Current Open Orders)^50^. Однако, несмотря на то что Кабинет
министров одобрил инициативу по включению цифровых активов в Derivatives
Act, Binance TH в настоящее время предоставляет розничным клиентам
доступ исключительно к спотовому рынку в парах с THB^14^. Биржа Bitkub,
также локально лицензированная, предоставляет приемлемый API, но
отличается жесткими лимитами (rate limits), привязанными к User ID (а не
к IP), что требует скрупулезной реализации Exponential Backoff и снижает
возможности высокочастотного управления ордерами^21^.

Для торговли деривативами (Perpetuals) оптимальным решением является
Hyperliquid. Это L1-блокчейн, реализующий полностью ончейн-книгу ордеров
с субсекундной финализацией. Hyperliquid не требует прохождения
процедуры KYC и, согласно официальным Terms of Use, гео-блокирует
пользователей из США и Канады, оставляя Таиланд в белом списке^18^. API
биржи безупречно поддерживает идемпотентность через 128-битный параметр
cloid (Client Order ID) и предоставляет широкие возможности для
управления левериджем^17^. Что касается традиционных брокеров,
Interactive Brokers (IBKR) доступен для резидентов Таиланда, однако
модель монетизации Market Data требует постоянных подписок, а
архитектура API (ограничения на количество snapshot-запросов и задержки
для бесплатных данных) не соответствует нашим требованиям к потоковой
обработке данных^38^.

  **Критерий**       **Hyperliquid**    **Binance TH**            **Bitkub**                 **Interactive Brokers**   **OKX / Bybit**
  ------------------ ------------------ ------------------------- -------------------------- ------------------------- -----------------------
  Инструменты        Perpetuals, Spot   Spot (THB)                Spot (THB)                 TradFi, FX                Perpetuals, Spot
  Регуляторика TH    Доступно (DeFi)    Лицензировано SEC         Лицензировано SEC          Доступно                  **Заблокировано SEC**
  Идемпотентность    Да (cloid)         Да (newClientOrderId)     Да (client\_id)            Ограниченно               Да
  Доступ к Testnet   Да                 Ограниченно               Нет                        Да (Paper account)        Да
  Ограничения API    Низкие             Средние (Weight limits)   Высокие (User ID limits)   Подписки на Market Data   Средние

-   **Вердикт**: **ADOPT** Hyperliquid в качестве основной площадки для
    торговли деривативами. **ADAPT** Binance TH в качестве вторичной
    площадки для фиатных шлюзов и спота. **REJECT** OKX, Bybit и Bitkub.

-   **Уверенность**: 0.98

-   **Триггер пересмотра**: Включение Таиланда в список Restricted
    Persons на платформе Hyperliquid или полноценный запуск торговли
    фьючерсами на Binance TH.

### Task 3: MARKET DATA LAYER

Подсистема Market Data должна обеспечивать высокую пропускную
способность записи, низкие операционные издержки для одного узла и,
самое главное, безупречную поддержку битемпоральности для предотвращения
утечки будущих данных (Look-ahead bias) в процессе обучения и работы
LLM-агентов. Рассмотрение классических баз данных временных рядов
выявило их функциональную избыточность или неоптимальность для специфики
нашего Research Plane. TimescaleDB (надстройка над PostgreSQL) требует
значительных ресурсов для обслуживания и настройки
партиционирования^52^. ClickHouse демонстрирует феноменальную скорость
выполнения аналитических запросов, однако обновление или удаление
исторических данных (что неизбежно при очистке тиков и корпоративных
действиях) в нем реализовано через сложные асинхронные мутации, что
повышает операционную нагрузку^52^. Использование DuckDB совместно с
файлами Parquet является отличным легковесным решением^53^, однако оно
не предоставляет нативных механизмов контроля версий данных и
Point-in-Time запросов.

Оптимальным решением становится ArcticDB (от Man Group). Эта
серверлесс-база данных спроектирована специально для работы с Pandas
DataFrames и обладает нативной поддержкой битемпоральности (Bitemporal
DataFrame storage)^24^. Все модификации данных в ArcticDB (через
операции update или append) автоматически версионируются^25^. Для
Research Plane это критически важно: LLM-агенты могут выполнять метод
read(symbol, as\_of=current\_simulation\_time), гарантированно получая
срез данных, идентичный тому, который был доступен системе в тот
конкретный момент истории^26^. База данных может использовать локальное
хранилище на базе LMDB, что идеально подходит для нашей одноузловой
конфигурации^26^. Для самого детерминированного горячего пути (Trading
Plane) и BacktestEngine целесообразно использовать нативный
ParquetDataCatalog из NautilusTrader, который предварительно загружает
данные в память^55^.

-   **Вердикт**: **ADOPT** ArcticDB как основной слой хранения для
    Research Plane и оффлайн-аналитики. **ADAPT** Nautilus
    ParquetDataCatalog для детерминированного Execution-цикла.

-   **Уверенность**: 1.00

-   **Триггер пересмотра**: Проблемы с производительностью ArcticDB при
    работе с LMDB бэкендом на объемах данных свыше 100 ГБ.

### Task 4: BACKTEST INTEGRITY FOR LLM SIGNALS

Интеграция Больших Языковых Моделей (LLMs) в процессы генерации торговых
сигналов сопряжена с фундаментальным риском: \"Look-ahead bias\"
(предвзятость заглядывания вперед). Современные LLM обучаются на
гигантских массивах интернет-текстов, включающих исторические котировки,
финансовые отчеты и новостные сводки. Исследования, проведенные с
использованием методологии Look-Ahead-Bench, наглядно демонстрируют, что
базовые модели (такие как Llama 3.1 или DeepSeek) демонстрируют
феноменальную фиктивную доходность (до 44%) на периодах (in-sample),
которые уже присутствовали в их обучающей выборке^28^. Однако при
переходе к историческим периодам после даты отсечения их знаний
(out-of-sample), доходность катастрофически обрушивается --- показатель
Alpha Decay составляет от 15 до 22 процентных пунктов^28^. Это явление
описывается метрикой Lookahead Propensity (LAP), которая статистически
коррелирует \"узнавание\" моделью определенных компаний с точностью
прогноза^57^.

Для защиты нашего детерминированного ядра от иллюзорной прибыльности мы
внедряем строгую дисциплину Point-in-Time. LLM-агентам запрещено иметь
прямой доступ в интернет (параметр online\_tools=False)^58^. Все запросы
к историческим данным маршрутизируются исключительно через ArcticDB с
принудительной подстановкой аргумента as\_of. Более того, необходимо
применять механизм \"Entity Embedding Neutralization\" --- анонимизацию
тикеров и названий компаний перед подачей в контекст LLM, чтобы
заблокировать активацию ассоциативной памяти модели о конкретном
активе^59^. Детерминированный контракт между плоскостями подразумевает
применение протокола Walk-Forward: LLM генерирует SignalProposal для
отрезка ![](media/image1.png){width="0.20849628171478565in"
height="0.27104440069991254in"}, после чего детерминированный движок
валидирует этот сигнал на отрезке
![](media/image3.png){width="0.20849628171478565in"
height="0.27104440069991254in"}. Любые расхождения между ожидаемой
уверенностью LLM (conviction\_score) и фактическим PnL на сдвинутом окне
приводят к отклонению стратегии на этапе BACKTEST.

-   **Вердикт**: **ADAPT** методологию валидации Look-Ahead-Bench и
    метрику Alpha Decay.

-   **Уверенность**: 0.98

-   **Триггер пересмотра**: Появление специализированных коммерческих
    Point-in-Time моделей (например, семейства Pitinf), способных
    аппаратно гарантировать отсутствие будущих знаний, что сделает
    анонимизацию излишней.

### Task 5: LLM ANALYST LAYER (Off Hot Path)

Для формирования структуры исследовательского слоя
(Research/Intelligence Plane) необходимо опираться на проверенные
архитектурные шаблоны мультиагентного взаимодействия. Фреймворк
TradingAgents (разработанный Tauric Research) предлагает
высокоэффективную декомпозицию ролей, имитирующую структуру реального
хедж-фонда^30^. Конвейер начинается с работы профильных специалистов
(Фундаментальный, Технический, Сентимент-аналитики), которые независимо
агрегируют данные. Ключевым архитектурным решением является введение
структурированных дебатов: \"Бычий\" (Bull) исследователь формирует
тезисы за открытие позиции, а \"Медвежий\" (Bear) исследователь
критически оспаривает их, указывая на макроэкономические риски и
слабость паттернов^32^.

Фреймворк версии 0.2.4 предоставляет возможность генерации
структурированных выводов (Structured Outputs) и сохранения всех шагов
рассуждения (Persistent decision log) в SQLite базу данных^31^. Это
безупречно ложится на наши требования к подсистеме аудита ContinuityOS.
Однако оригинальная имплементация TradingAgents наделяет LLM-агентов (в
роли Risk Management Team и Portfolio Manager) правом прямого одобрения
транзакций и отправки их на биржу^30^. Это категорически нарушает наш
фундаментальный принцип: LLM никогда не владеют авторитетным стейтом.

Мы принимаем ролевые промпты и структуру дебатов, но заменяем LLM-роль
\"Portfolio Manager\" на детерминированный алгоритмический Synthesizer.
Этот компонент агрегирует итоги дебатов и сериализует их в бинарный
пакет SignalProposal (через SBE). Этот пакет пересылается через NATS
JetStream в наш торговый контур, где жестко закодированный RiskService
осуществляет финальную математическую верификацию.

-   **Вердикт**: **ADAPT** ролевую модель и структуру диалектических
    дебатов из TradingAgents. **REJECT** любые модули маршрутизации или
    контроля рисков, основанные на LLM.

-   **Уверенность**: 1.00

-   **Триггер пересмотра**: Систематическая неспособность агентов
    (Bull/Bear) прийти к математически оцениваемому консенсусу
    (генерация противоречивых SignalProposal).

### Task 6: RECONCILIATION AND RECOVERY

Устойчивость детерминированной ячейки к программным или аппаратным сбоям
зависит от способности системы восстановить стейт без повторного
применения сайд-эффектов (дублирования ордеров). В контексте
алгоритмической торговли использование ключей идемпотентности является
абсолютным стандартом. При формировании OrderIntent стратегия обязана
генерировать уникальный идентификатор ClientOrderId на основе UUIDv7
(обеспечивающего лексикографическую сортировку по времени). Биржа
Hyperliquid поддерживает этот параметр под названием cloid^17^, а
Binance TH --- как newClientOrderId^50^.

Механизм восстановления после сбоя реализуется через внутренние
возможности LiveExecutionEngine платформы NautilusTrader. При старте
системы движок вызывает функцию адаптера refresh\_account\_state(),
которая загружает исторические сведения о балансах, открытых позициях и
ордерах через REST API площадки^34^. Включенная конфигурация
reconciliation=True активирует процесс сверки^35^. Движок использует
функцию is\_duplicate\_fill() для фильтрации событий, приходящих из
WebSocket-каналов, предотвращая повторный учет уже совершенных
сделок^47^. В случае обнаружения расхождений между локальным кешем и
стейтом биржи, если параметр generate\_missing\_orders=True,
NautilusTrader автоматически генерирует синтетические ордера с тегом
RECONCILIATION^34^. Эти ордера не отправляются на биржу, а служат
исключительно для выравнивания локальных внутренних позиций в
соответствии с объективной реальностью торговой площадки.

-   **Вердикт**: **ADOPT** встроенный механизм реконсиляции
    NautilusTrader совместно с обязательной привязкой ClientOrderId
    (UUIDv7) ко всем исходящим транзакциям.

-   **Уверенность**: 0.99

-   **Триггер пересмотра**: Обнаружение состояний \"Split NETTING
    ownership\" (когда несколько стратегий удерживают позиции по одному
    инструменту, и реконсиляция не может корректно распределить биржевую
    нетто-позицию)^34^.

### Task 7: PROMOTION TOOLING

Лестница продвижения стратегии (от RESEARCH до RETIRED) гарантирует, что
ни один торговый алгоритм не получит доступ к реальному капиталу без
исчерпывающих проверок. NautilusTrader предоставляет мощную базу:
благодаря унифицированному классу Strategy, код алгоритма не требует
изменений при переносе из среды BacktestNode (работа с Parquet) в
TradingNode (работа с Live-адаптерами)^2^.

Тем не менее, стандартный инструментарий необходимо расширить для
поддержки промежуточных стадий нашей лестницы. На этапе FORWARD\_TEST и
PAPER мы можем использовать тестовые среды бирж (например, Hyperliquid
Testnet) напрямую через адаптеры. Однако стадия SHADOW требует
кастомного решения. В этом режиме стратегия работает в TradingNode,
подписана на реальные WebSocket-каналы Market Data и вычисляет
OrderIntent, но наш шлюз ContinuityOS перехватывает эти намерения.
Вместо маршрутизации в LiveExecutionClient, ордера симулируются внутри
OrderEmulator^46^. На этапе CANARY ордера проходят через RiskService,
который принудительно масштабирует размер позиции (quantity\_fixed) с
коэффициентом ![](media/image2.png){width="0.5177405949256343in"
height="0.25887029746281714in"}, проверяя исполнение на реальном рынке с
минимальным капитальным риском.

-   **Вердикт**: **ADAPT** NautilusTrader Nodes. Внедрить модуль
    PromotionRouter в Control Plane для перехвата и масштабирования
    OrderIntent в зависимости от текущего статуса стратегии на лестнице
    промоушена.

-   **Уверенность**: 0.95

-   **Триггер пересмотра**: -

03\_ARCHITECTURE\_DELTA
-----------------------

Архитектура сохраняет концепцию трех изолированных плоскостей, однако
специфицирует компоненты: NATS JetStream выступает монопольной
транспортной шиной (без JSON, только SBE), ArcticDB берет на себя роль
bitemporal хранилища, а NautilusTrader становится сердцем
детерминированного горячего пути.

### Signal-to-Order Flow

На диаграмме ниже показан процесс превращения гипотезы LLM в исполненный
ордер. Обратите внимание на полное отсутствие LLM на горячем пути и
детерминированный контроль через RiskService.

> Фрагмент кода
>
> sequenceDiagram\
> autonumber\
> box Research Plane (LLMs, Python, Off-path)\
> participant ArcticDB as ArcticDB (Point-in-Time)\
> participant Agents as LLM Analysts & Debaters\
> end\
> \
> box Control Plane (ContinuityOS, NATS, SBE)\
> participant NATS as NATS JetStream\
> participant Telegram as Telegram Bot / Approval\
> end\
> \
> box Trading Plane (Rust/Nautilus, Hot-path)\
> participant Gateway as Preflight Gate (ContinuityOS)\
> participant Risk as RiskService (Deterministic)\
> participant Strategy as Nautilus Strategy\
> participant Adapter as Venue Adapter\
> end\
> \
> Agents-\>\>ArcticDB: read(as\_of=current\_timestamp)\
> ArcticDB\--\>\>Agents: Bitemporal Data (LazyDataFrames)\
> Agents-\>\>Agents: Bull vs Bear Debate -\> Synthesizer\
> Agents-\>\>NATS: Publish SignalProposal (SBE Encoded)\
> \
> NATS\--\>\>Gateway: Deliver SignalProposal\
> Gateway-\>\>Risk: Validate Risk Limits (Max Drawdown 10%, Risk \<=
> 1%)\
> \
> alt Limits Exceeded (e.g., Risk \> 1%)\
> Risk\--\>\>Gateway: DENY / HOLD\
> Gateway-\>\>Telegram: Alert: Signal Rejected\
> else Limits OK\
> Risk\--\>\>Gateway: ALLOW\
> Gateway-\>\>Strategy: Dispatch Signal\
> Strategy-\>\>Strategy: Execute Deterministic Logic\
> Strategy-\>\>Adapter: Emit OrderIntent (with UUIDv7 clientOrderId)\
> Adapter-\>\>Adapter: SBE Serialize / Network I/O\
> Adapter-\>\>Exchange: POST Order\
> end

### Crash Recovery & Reconciliation Flow

Механизм восстановления стейта после критического сбоя, опирающийся на
возможности LiveExecutionEngine платформы NautilusTrader.

> Фрагмент кода
>
> sequenceDiagram\
> autonumber\
> box Trading Plane (Hot-path)\
> participant App as TradingNode / LiveExecutionEngine\
> participant Cache as In-Memory State\
> participant Adapter as Venue Adapter\
> end\
> box External\
> participant Venue as Exchange (Hyperliquid/Binance TH)\
> end\
> \
> App-\>\>App: Process Restart / Crash Recovery Initiated\
> App-\>\>Adapter: ensure\_instruments\_initialized\_async()\
> Adapter-\>\>Venue: REST /instruments\
> Venue\--\>\>Adapter: Instrument Definitions (Precision, Tick Size)\
> App-\>\>Adapter: refresh\_account\_state()\
> Adapter-\>\>Venue: REST /positions & /orders\
> Venue\--\>\>Adapter: Current Venue Truth\
> Adapter-\>\>App: AccountState Event (SBE)\
> App-\>\>Cache: Rebuild positions & balances\
> \
> App-\>\>App: is\_duplicate\_fill() & Order Deduplication\
> App-\>\>App: Identify Discrepancies (Local vs Venue Net Position)\
> \
> alt Discrepancy Found & reconciliation=True\
> App-\>\>Adapter: generate\_missing\_orders\
> Adapter-\>\>Cache: Update Local State (Synthetic Order, Tag:
> RECONCILIATION)\
> end\
> \
> App-\>\>Adapter: WebSocket Connect\
> Adapter-\>\>Venue: Subscribe (Order Updates, Fills)\
> App-\>\>App: Set TradingState = ACTIVE

04\_CONTRACTS
-------------

Ниже приведены логические контракты (в формате YAML) для ключевых
сущностей системы. В процессе межпроцессного взаимодействия эти
структуры транслируются в спецификации SBE (Simple Binary Encoding).
Обратите внимание на использование int64 для цен и объемов
(соответствует политике отказа от float64).

### SignalProposal.yaml

Контракт, генерируемый плоскостью Research Plane после завершения
дебатов агентов. Представляет собой непроверенную гипотезу.

> YAML
>
> schema\_version: \"1.0\"\
> message\_type: \"SignalProposal\"\
> description: \"Output from LLM Synthesizer, strictly validated before
> routing.\"\
> fields:\
> signal\_id:\
> type: \"uuid\_v7\"\
> description: \"Unique identifier for idempotency and SQLite audit
> tracing.\"\
> timestamp\_utc\_ns:\
> type: \"uint64\"\
> description: \"Signal generation timestamp in nanoseconds since UNIX
> epoch.\"\
> instrument:\
> type: \"string\"\
> description: \"Normalized asset pair (e.g., \'BTC-USD-PERP\').\"\
> direction:\
> type: \"enum\"\
> values: \[\"LONG\", \"SHORT\", \"FLAT\"\]\
> conviction\_score:\
> type: \"uint8\"\
> description: \"LLM synthesis confidence metric (0-100).\"\
> proposed\_risk\_pct:\
> type: \"uint16\"\
> description: \"Basis points (1 = 0.01%) of portfolio risk to allocate.
> Max 100 (1%).\"\
> valid\_until\_ns:\
> type: \"uint64\"\
> description: \"Time-to-Live (TTL) for the signal.\"\
> llm\_provenance:\
> type: \"string\"\
> description: \"Hash of the prompt/debate log in SQLite for post-trade
> audit.\"

### OrderIntent.yaml

Контракт, формируемый детерминированной стратегией в горячем пути после
одобрения RiskService. Отражает твердое намерение совершить транзакцию.

> YAML
>
> schema\_version: \"1.0\"\
> message\_type: \"OrderIntent\"\
> description: \"Deterministic intent generated by Strategy, requires
> RiskService ALLOW.\"\
> fields:\
> client\_order\_id:\
> type: \"uuid\_v7\"\
> description: \"Mandatory Idempotency key (cloid for Hyperliquid,
> newClientOrderId for Binance TH).\"\
> instrument\_id:\
> type: \"string\"\
> side:\
> type: \"enum\"\
> values: \[\"BUY\", \"SELL\"\]\
> order\_type:\
> type: \"enum\"\
> values: \[\"MARKET\", \"LIMIT\", \"STOP\_MARKET\",
> \"TRAILING\_STOP\"\]\
> time\_in\_force:\
> type: \"enum\"\
> values: \[\"GTC\", \"IOC\", \"FOK\"\]\
> quantity\_fixed:\
> type: \"int64\"\
> description: \"Fixed-point representation of size (scaled by
> instrument precision multiplier).\"\
> price\_fixed:\
> type: \"int64\"\
> description: \"Fixed-point representation of price. Must be 0 for
> MARKET orders.\"\
> reduce\_only:\
> type: \"boolean\"\
> description: \"Mandatory constraint flag for risk mitigation and
> position closing.\"\
> post\_only:\
> type: \"boolean\"\
> description: \"Ensures the order adds liquidity (Maker only).\"

### ReconciliationReport.yaml

Контракт для инкапсуляции результатов сверки состояний при запуске
LiveExecutionEngine.

> YAML
>
> schema\_version: \"1.0\"\
> message\_type: \"ReconciliationReport\"\
> description: \"Used by startup sequence to align local cache with
> external reality.\"\
> fields:\
> account\_id:\
> type: \"string\"\
> instrument\_id:\
> type: \"string\"\
> venue\_reported\_net\_position:\
> type: \"int64\"\
> description: \"Fixed-point quantity currently open at the exchange.\"\
> local\_cached\_net\_position:\
> type: \"int64\"\
> description: \"Net position according to the local Nautilus cache
> before sync.\"\
> discrepancy:\
> type: \"int64\"\
> description: \"Delta requiring a synthetic RECONCILIATION order (local
> - venue).\"\
> action\_taken:\
> type: \"enum\"\
> values: \[\"NONE\", \"SYNTHETIC\_ORDER\_GENERATED\",
> \"HALT\_REQUESTED\"\]

### VenueAdapter.yaml

Определяет интерфейс, который должен реализовывать любой кастомный
адаптер для подключения к бирже.

> YAML
>
> schema\_version: \"1.0\"\
> interface: \"VenueAdapter\"\
> description: \"Mandatory contract for all implementations connecting
> Nautilus to an Exchange.\"\
> methods:\
> - name: \"ensure\_instruments\_initialized\_async\"\
> returns: \"Result\<void\>\"\
> description: \"Fetches and caches trading rules, tick sizes, and lot
> sizes via REST.\"\
> - name: \"refresh\_account\_state\"\
> returns: \"AccountState\"\
> description: \"Fetches current balances and positions for crash
> recovery.\"\
> - name: \"submit\_order\"\
> inputs:\
> - \"intent: OrderIntent\"\
> returns: \"Result\<ClientOrderId\>\"\
> description: \"Translates OrderIntent to Venue API request. Must
> enforce UUIDv7.\"\
> - name: \"cancel\_order\"\
> inputs:\
> - \"client\_order\_id: uuid\_v7\"\
> returns: \"Result\<void\>\"

05\_BACKLOG
-----------

Стратегический бэклог (Epics/Tasks) для реализации архитектуры от фазы
исследования до MVP.

  **Title**                      **Component**    **Rationale**                                                                                               **Dependencies**      **Acceptance Criteria**                                                                    **Security / Benchmark**
  ------------------------------ ---------------- ----------------------------------------------------------------------------------------------------------- --------------------- ------------------------------------------------------------------------------------------ -----------------------------------------------------------------
  Интеграция NautilusTrader v2   Trading Cell     Миграция на Rust-ядро необходима для обеспечения детерминизма и аппаратной безопасности работы с памятью.   Нет                   Ядро успешно компилируется с флагом python. Настроены логгеры и Clock.                     Память без утечек. Задержка диспетчеризации ивентов \< 1 ms.
  Реализация RiskService Gate    ContinuityOS     Детерминированное отклонение OrderIntent, нарушающих лимиты.                                                NautilusTrader Core   Ордера, нарушающие лимит риска в 1% или drawdown в 10%, получают статус DENY.              Атомарное чтение регистра kill-switch \< 10 µs.
  NATS JetStream DataClient      Adapters         Обмен SignalProposal между плоскостями без использования JSON на горячем пути.                              Сервер NATS           Сообщения сериализуются/десериализуются через SBE. Адаптер инжектит ивенты в MessageBus.   Пропускная способность шины: \> 10,000 msg/sec.
  Hyperliquid Adapter            Adapters         Основная площадка для деривативов, поддерживающая cloid и доступная из Таиланда.                            NATS DataClient       Поддержка WebSocket (L2 Order Book). REST для отправки ордеров с UUIDv7.                   Авто-реконсиляция при разрыве соединения восстанавливает стейт.
  ArcticDB Bitemporal Store      Market Data      Хранение данных Point-in-Time для предотвращения Look-ahead bias в Research Plane.                          Нет                   Битемпоральные запросы as\_of возвращают DataFrame без утечки будущих котировок.           Чтение 1 млн строк LazyDataFrame \< 500 ms.
  LLM TradingAgents Pipeline     Research Plane   Ролевой анализ (Bull/Bear дебаты) на основе исторических данных.                                            ArcticDB              Изолированный скрипт/контейнер. Сброс SignalProposal в NATS через SBE.                     Тестирование Alpha Decay по метрике Look-Ahead-Bench.
  Binance TH Adapter             Adapters         Резервная спот-площадка. Лицензирована SEC Таиланда.                                                        NATS DataClient       Поддержка newClientOrderId. Управление Rate Limits (Exponential Backoff).                  Строгое соблюдение лимитов x-mbx-used-weight.
  Promotion Router Module        Control Plane    Управление стадиями SHADOW и CANARY без изменения кода стратегий.                                           RiskService           На стадии SHADOW ордера перенаправляются в OrderEmulator. На CANARY масштабируются.        Отсутствие случайных отправок реальных ордеров в режиме SHADOW.

06\_MVP\_DECISION
-----------------

**Решение по минимально жизнеспособному продукту (MVP) для первичного
тестирования гипотез (Falsification Spike)**:

Первый MVP не предназначен для извлечения реальной прибыли; его
единственная цель --- фальсифицируемость базовых архитектурных гипотез с
минимальными затратами времени и полным отсутствием капитального риска.

1.  **Окружение и Площадка**: Запуск **Paper Trading** будет
    > производиться исключительно в среде **Hyperliquid Testnet**. Это
    > позволит избежать сложностей с регуляторикой (SEC Таиланда) на
    > начальном этапе, обеспечит мгновенный доступ к деривативным
    > инструментам (Perpetuals) и позволит протестировать механику
    > идемпотентности cloid без реальных финансовых потерь при
    > неизбежных логических ошибках.

2.  **Ядро (Hot Path)**: Развертывание NautilusTrader v2 (Rust+PyO3) на
    > одном узле (Linux VPS, Thailand region). Главная задача на этом
    > этапе --- интеграция встроенного модуля реконсиляции
    > (reconciliation=True, generate\_missing\_orders=True).
    > Запланированы стресс-тесты: принудительное завершение процесса
    > (kill -9) во время нахождения ордеров In-Flight и проверка
    > корректности восстановления стейта при перезапуске без
    > дублирования транзакций.

3.  **Обмен сообщениями**: Развертывание NATS JetStream и жесткое
    > внедрение сериализации SBE. Полное исключение парсеров JSON на
    > стороне Trading Cell. Любое сообщение, не соответствующее
    > бинарному контракту SBE, будет отбрасываться на уровне сетевого
    > сокета.

4.  **Слой аналитики (Research Plane)**: Использование базового
    > дебатного графа (Bull vs Bear -\> Synthesizer) на основе ролевой
    > модели TradingAgents. Агенты будут получать данные исключительно
    > из ArcticDB, принудительно передавая аргумент as\_of. Для
    > валидации гипотезы Look-Ahead-Bench будет проведена серия тестов с
    > анонимизированными тикерами для измерения уровня Alpha Decay.

5.  **Контроль рисков (Preflight Gate)**: Внедрение детерминированного
    > шлюза RiskService, который является абсолютным авторитетом.
    > RiskService будет блокировать любой OrderIntent со стороны
    > Nautilus Strategy, если он превышает жестко закодированный лимит в
    > 1% от текущего баланса счета, полностью игнорируя уровень
    > убежденности (conviction\_score), переданный LLM-агентами.

Такой MVP обладает минимальной поверхностью атаки, нулевым капитальным
риском и позволяет в кратчайшие сроки верифицировать работоспособность
связки \"NATS --- SBE --- NautilusTrader --- RiskService\", доказав
жизнеспособность архитектуры перед переходом к этапу SHADOW или CANARY
на реальных средствах.

#### Источники

1.  Backtesting Multi-processing and data streaming · nautechsystems
    > nautilus\_trader · Discussion \#3736 - GitHub,
    > [[https://github.com/nautechsystems/nautilus\_trader/discussions/3736]{.underline}](https://github.com/nautechsystems/nautilus_trader/discussions/3736)

2.  nautilus\_trader/docs/getting\_started/backtest\_high\_level.py at
    > develop - GitHub,
    > [[https://github.com/nautechsystems/nautilus\_trader/blob/develop/docs/getting\_started/backtest\_high\_level.py]{.underline}](https://github.com/nautechsystems/nautilus_trader/blob/develop/docs/getting_started/backtest_high_level.py)

3.  Backtesting - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/backtesting/]{.underline}](https://nautilustrader.io/docs/latest/concepts/backtesting/)

4.  nautilus\_trader/RELEASES.md at develop - GitHub,
    > [[https://github.com/nautechsystems/nautilus\_trader/blob/develop/RELEASES.md]{.underline}](https://github.com/nautechsystems/nautilus_trader/blob/develop/RELEASES.md)

5.  oakwoodgates/NTP: Platform to experiment with NautilusTrader -
    > GitHub,
    > [[https://github.com/oakwoodgates/NTP]{.underline}](https://github.com/oakwoodgates/NTP)

6.  Rust - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/developer\_guide/rust/]{.underline}](https://nautilustrader.io/docs/latest/developer_guide/rust/)

7.  hftbacktest 0.9.4 - Docs.rs,
    > [[https://docs.rs/crate/hftbacktest/latest]{.underline}](https://docs.rs/crate/hftbacktest/latest)

8.  High-frequency trading and market-making backtesting tool with
    > accurate order fill simulation - HftBacktest,
    > [[https://nkaz001-hftbacktest-16.mintlify.app/introduction]{.underline}](https://nkaz001-hftbacktest-16.mintlify.app/introduction)

9.  Best Crypto Wallet in Thailand for 2026 \| Ledger,
    > [[https://www.ledger.com/academy/topics/country-guides/best-crypto-wallet-in-thailand]{.underline}](https://www.ledger.com/academy/topics/country-guides/best-crypto-wallet-in-thailand)

10. OKX Supported & Restricted Countries for 2026 - Datawallet,
    > [[https://www.datawallet.com/crypto/okx-restricted-countries]{.underline}](https://www.datawallet.com/crypto/okx-restricted-countries)

11. The best VPN for Bybit: how to use Bybit in the US and other
    > restricted countries (2026),
    > [[https://vpnpro.com/best-vpn-services/vpn-for-bybit/]{.underline}](https://vpnpro.com/best-vpn-services/vpn-for-bybit/)

12. Thailand puts digital assets on a firmer footing - Bangkok Post,
    > [[https://www.bangkokpost.com/business/investment/3195574/thailand-puts-digital-assets-on-a-firmer-footing]{.underline}](https://www.bangkokpost.com/business/investment/3195574/thailand-puts-digital-assets-on-a-firmer-footing)

13. Binance TH Lands Global Certifications, Showcasing the Platform\'s
    > Security And Privacy Excellence,
    > [[https://www.binance.com/en/blog/ecosystem/5697895448520202144]{.underline}](https://www.binance.com/en/blog/ecosystem/5697895448520202144)

14. Binance TH by Gulf Binance Now Open to All Eligible Users \| Binance
    > Blog,
    > [[https://www.binance.com/en/blog/regulation/7846087428943809900]{.underline}](https://www.binance.com/en/blog/regulation/7846087428943809900)

15. Cancel order by cloid \| Hyperliquid exchange - Chainstack Docs,
    > [[https://docs.chainstack.com/reference/hyperliquid-exchange-cancel-order-by-cloid]{.underline}](https://docs.chainstack.com/reference/hyperliquid-exchange-cancel-order-by-cloid)

16. Hyperliquid Supported and Restricted Countries (2026) - Datawallet,
    > [[https://www.datawallet.com/crypto/hyperliquid-supported-and-restricted-countries]{.underline}](https://www.datawallet.com/crypto/hyperliquid-supported-and-restricted-countries)

17. Hyperliquid vs Other Crypto Exchanges: What Makes It Stand Out? \|
    > OneBullEx,
    > [[https://www.onebullex.com/explore/hyperliquid-vs-other-crypto-exchanges-what-makes-it-stand-out]{.underline}](https://www.onebullex.com/explore/hyperliquid-vs-other-crypto-exchanges-what-makes-it-stand-out)

18. Terms of Use - Hyperliquid,
    > [[https://app.hyperliquid.xyz/terms]{.underline}](https://app.hyperliquid.xyz/terms)

19. Endpoint Rate Limits - Bitkub API Documentation,
    > [[https://api.bitkub.com/docs/rate-limits]{.underline}](https://api.bitkub.com/docs/rate-limits)

20. Implementation of New API Rate Limiting by User ID on Public API V3
    > starting on 08/08/2024 at 05:00 PM (GMT+7) onwards \| Bitkub
    > Support,
    > [[https://support.bitkub.com/en/solutions/articles?id=151000195907]{.underline}](https://support.bitkub.com/en/solutions/articles?id=151000195907)

21. bitkub-official-api-docs/restful-api.md at master - GitHub,
    > [[https://github.com/bitkub/bitkub-official-api-docs/blob/master/restful-api.md]{.underline}](https://github.com/bitkub/bitkub-official-api-docs/blob/master/restful-api.md)

22. arctic - PyPI,
    > [[https://pypi.org/project/arctic/]{.underline}](https://pypi.org/project/arctic/)

23. Frequently Asked Questions - ArcticDB,
    > [[https://docs.arcticdb.io/6.18.0/faq/]{.underline}](https://docs.arcticdb.io/6.18.0/faq/)

24. ArcticDB: Introduction,
    > [[https://docs.arcticdb.io/]{.underline}](https://docs.arcticdb.io/)

25. Library - ArcticDB,
    > [[https://docs.arcticdb.io/4.4.0/api/library/]{.underline}](https://docs.arcticdb.io/4.4.0/api/library/)

26. a Standardized Benchmark of Look-ahead Bias in Point-in-Time LLMs
    > for Finance - arXiv,
    > [[https://arxiv.org/pdf/2601.13770]{.underline}](https://arxiv.org/pdf/2601.13770)

27. Look-Ahead-Bench: a Standardized Benchmark of Look-ahead Bias in
    > Point-in-Time LLMs for Finance - IDEAS/RePEc,
    > [[https://ideas.repec.org/p/arx/papers/2601.13770.html]{.underline}](https://ideas.repec.org/p/arx/papers/2601.13770.html)

28. TradingAgents: Multi-Agents LLM Financial Trading Framework -
    > GitHub,
    > [[https://github.com/tauricresearch/tradingagents]{.underline}](https://github.com/tauricresearch/tradingagents)

29. TradingAgents:Open-Source LLM Trading Framework - Apidog,
    > [[https://apidog.com/blog/tradingagents-multi-agent-llm-trading/]{.underline}](https://apidog.com/blog/tradingagents-multi-agent-llm-trading/)

30. TradingAgents Framework Analysis \| PDF - Scribd,
    > [[https://www.scribd.com/document/906410736/Tauri-Research]{.underline}](https://www.scribd.com/document/906410736/Tauri-Research)

31. TradingAgents: Multi-Agents LLM Financial Trading Framework - arXiv,
    > [[https://arxiv.org/html/2412.20138v6]{.underline}](https://arxiv.org/html/2412.20138v6)

32. Live Trading - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/live/]{.underline}](https://nautilustrader.io/docs/latest/concepts/live/)

33. Configure a Live Trading Node \| NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/how\_to/configure\_live\_trading/]{.underline}](https://nautilustrader.io/docs/latest/how_to/configure_live_trading/)

34. \[Reconciliation\] LiveExecEngine fails to reconcile long-lived
    > Binance Futures positions for HEDGING · Issue \#3104 ·
    > nautechsystems/nautilus\_trader - GitHub,
    > [[https://github.com/nautechsystems/nautilus\_trader/issues/3104]{.underline}](https://github.com/nautechsystems/nautilus_trader/issues/3104)

35. Market Data Pricing \| Interactive Brokers LLC,
    > [[https://www.interactivebrokers.com/en/pricing/market-data-pricing.php]{.underline}](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)

36. Market Data Pricing - Interactive Brokers Hong Kong Limited,
    > [[https://www.interactivebrokers.com.hk/en/pricing/market-data-pricing.php]{.underline}](https://www.interactivebrokers.com.hk/en/pricing/market-data-pricing.php)

37. Adding Trading Permissions & Subscribing to Market Data and Research
    > Subscriptions,
    > [[https://www.interactivebrokers.com/campus/trading-lessons/trade-permissions-mkt/]{.underline}](https://www.interactivebrokers.com/campus/trading-lessons/trade-permissions-mkt/)

38. NautilusTrader Documentation,
    > [[https://nautilustrader.io/docs/latest/]{.underline}](https://nautilustrader.io/docs/latest/)

39. Chapter 1: Introduction to NautilusTrader - DEV Community,
    > [[https://dev.to/henry\_lin\_3ac6363747f45b4/chapter-1-introduction-to-nautilustrader-5552]{.underline}](https://dev.to/henry_lin_3ac6363747f45b4/chapter-1-introduction-to-nautilustrader-5552)

40. VioletSakura-7/my\_nautilus\_trader: A high-performance algorithmic
    > trading platform and event-driven backtester - GitHub,
    > [[https://github.com/VioletSakura-7/my\_nautilus\_trader]{.underline}](https://github.com/VioletSakura-7/my_nautilus_trader)

41. NautilusTrader: open-source algorithmic trading platform,
    > [[https://nautilustrader.io/]{.underline}](https://nautilustrader.io/)

42. Strategies - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/strategies/]{.underline}](https://nautilustrader.io/docs/latest/concepts/strategies/)

43. Execution - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/execution/]{.underline}](https://nautilustrader.io/docs/latest/concepts/execution/)

44. Adapters - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/adapters/]{.underline}](https://nautilustrader.io/docs/latest/concepts/adapters/)

45. Adapters - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/developer\_guide/adapters/]{.underline}](https://nautilustrader.io/docs/latest/developer_guide/adapters/)

46. REST Open API v1.0.0 - Binance TH,
    > [[https://www.binance.th/api-docs/en/]{.underline}](https://www.binance.th/api-docs/en/)

47. binance-th/docs/plans/hld.md at main - GitHub,
    > [[https://github.com/lumduan/binance-th/blob/main/docs/plans/hld.md]{.underline}](https://github.com/lumduan/binance-th/blob/main/docs/plans/hld.md)

48. should I use timescaledb, influxdb, or questdb as a time series
    > database? - Reddit,
    > [[https://www.reddit.com/r/algotrading/comments/1dquw93/should\_i\_use\_timescaledb\_influxdb\_or\_questdb\_as\_a/]{.underline}](https://www.reddit.com/r/algotrading/comments/1dquw93/should_i_use_timescaledb_influxdb_or_questdb_as_a/)

49. What DB do you use? : r/algotrading - Reddit,
    > [[https://www.reddit.com/r/algotrading/comments/1l2gywd/what\_db\_do\_you\_use/]{.underline}](https://www.reddit.com/r/algotrading/comments/1l2gywd/what_db_do_you_use/)

50. Introduction - ArcticDB,
    > [[https://docs.arcticdb.io/dev/]{.underline}](https://docs.arcticdb.io/dev/)

51. Data \| NautilusTrader Documentation - AiDocZh,
    > [[https://www.aidoczh.com/nautilustrader/docs/nightly/concepts/data/index.html]{.underline}](https://www.aidoczh.com/nautilustrader/docs/nightly/concepts/data/index.html)

52. When AI models cheat: The danger of look-ahead bias in financial
    > LLMs - Finance Alliance,
    > [[https://www.financealliance.io/the-hidden-danger-of-look-ahead-bias-in-financial-llms/]{.underline}](https://www.financealliance.io/the-hidden-danger-of-look-ahead-bias-in-financial-llms/)

53. Detecting Lookahead Bias in LLM Forecasts - IDEAS/RePEc,
    > [[https://ideas.repec.org/p/arx/papers/2512.23847.html]{.underline}](https://ideas.repec.org/p/arx/papers/2512.23847.html)

54. TradingAgents: Multi-Agents LLM Financial Trading Framework -
    > GitHub,
    > [[https://github.com/yoursxiong/tradingagents]{.underline}](https://github.com/yoursxiong/tradingagents)

55. Assessing Look-Ahead Bias in Stock Return Predictions Generated By
    > GPT Sentiment Analysis - IDEAS/RePEc,
    > [[https://ideas.repec.org/p/arx/papers/2309.17322.html]{.underline}](https://ideas.repec.org/p/arx/papers/2309.17322.html)

56. TradingAgents: Multi-Agents LLM Financial Trading Framework - arXiv,
    > [[https://arxiv.org/pdf/2412.20138]{.underline}](https://arxiv.org/pdf/2412.20138)

57. Mgiri1234/TradingAgents\_llm: TradingAgents: Multi-Agents LLM
    > Financial Trading Framework - GitHub,
    > [[https://github.com/Mgiri1234/TradingAgents\_llm]{.underline}](https://github.com/Mgiri1234/TradingAgents_llm)
