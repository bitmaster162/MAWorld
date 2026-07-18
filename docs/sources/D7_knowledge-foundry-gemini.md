Архитектура Knowledge Foundry: Проектирование системы управления знаниями и доказательствами MAWorld
====================================================================================================

01\_PROBLEM\_AND\_SCOPE\_DEFINITION
-----------------------------------

Программа MAWorld обладает обширным, но хаотичным и фрагментированным
корпусом данных, который поступает из множества разнородных источников:
от отчетов Deep Research и экспортов из Telegram до исходного кода и
архитектурных решений. Фундаментальная проблема заключается в том, что
информация поступает постепенно, содержит непреднамеренные противоречия,
устаревшие концепции, галлюцинации языковых моделей и неверифицированные
утверждения вендоров. Владелец системы не имеет возможности
предварительно очистить, классифицировать или структурировать весь
массив данных перед началом работы, что делает невозможным применение
традиционных подходов к инженерии данных.

Традиционные подходы к управлению знаниями, такие как базовые
RAG-системы или статические файловые хранилища, не способны решить эту
задачу. Они не обеспечивают строгую дифференциацию между сырым
артефактом, извлеченным атомарным утверждением (claim), подтверждающим
доказательством (evidence) и каноническим архитектурным решением.
Использование векторных баз данных в качестве единственного источника
истины приводит к потере контекста и невозможности отследить
происхождение данных^1^. Цель данного документа --- спроектировать
архитектуру единого рабочего пространства (Knowledge Foundry), которое
позволит системе стартовать с неполной информацией, инкрементально
накапливать знания, автоматически выявлять противоречия и предоставлять
единому владельцу (single-owner) эргономичный инструментарий для
принятия явных решений о канонизации или замещении архитектурных
артефактов. Данная архитектура фокусируется исключительно на управлении
знаниями, инфраструктуре исследований и системах доказательств, строго
исключая торговые движки, частную память агентов и операционное
исполнение.

02\_PRINCIPLES\_AND\_BOUNDARIES
-------------------------------

Проектирование Knowledge Foundry опирается на строгий набор инвариантных
принципов, нарушение которых ведет к деградации эпистемологического
доверия. Сырые артефакты абсолютно иммутабельны; исходный текст никогда
не является прямой инструкцией для исполнения. Векторный поиск
рассматривается исключительно как производный индекс, а не как
авторитетное состояние, что позволяет в любой момент перестроить его без
потери данных^1^. Любой производный объект обязан сохранять полную
криптографическую и логическую связь с источником (provenance).
Дубликаты связываются в кластеры, а не удаляются, а конфликты
поднимаются на уровень проверки, а не объединяются скрытыми алгоритмами.
Наконец, документированные намерения и фактическая реализация (исходный
код) сосуществуют в системе: код имеет приоритет только в описании того,
что он фактически делает, в то время как документация описывает то, что
должно было быть сделано.

Для обеспечения целостности, архитектура устанавливает жесткие системные
границы:

-   **Knowledge Foundry**: Владеет приемом артефактов, метаданными,
    графом происхождения (provenance), извлеченными утверждениями,
    связями доказательств, учетом противоречий, записями канонических
    решений, реестром открытых вопросов и маппингом реализации. Это ядро
    поиска истины.

-   **LifeOS Memory**: Управляет частной памятью агентов, реляционными
    связями жизненного цикла, навыками и участием в проектах. LifeOS
    может извлекать утвержденные объекты из Knowledge Foundry, но не
    имеет прав на прямую запись или продвижение собственных частных
    \"убеждений\" агента в ранг канонической истины проекта.

-   **ContinuityOS**: Владеет авторизацией, политиками, аудитом мутаций,
    медиацией побочных эффектов и принятием решений о доступе.

-   **Workflow Runtime**: Отвечает за фоновые задания (ingestion,
    extraction), задачи проверки, повторные попытки (retries), таймеры и
    управление графами выполнения.

-   **Evidence Engine**: Управляет статусами верификации,
    воспроизводимыми тестами, критериями приемки и качеством
    доказательств.

-   **Git / Code Repositories**: Являются хранилищем исходного кода,
    версионированных схем, политик, файлов ADR и тестов. Git выступает
    одним из коннекторов для Knowledge Foundry, но система не дублирует
    владение исходным кодом.

03\_REFERENCE\_ARCHITECTURE
---------------------------

Эталонная архитектура строится на принципе конвейерной обработки с
сохранением криптографически верифицируемого состояния на каждом этапе.
Сырые данные захватываются коннекторами, хешируются и помещаются в
неизменяемое хранилище. Затем изолированные песочницы извлекают
текстовое содержимое и метаданные, после чего языковые модели формируют
атомарные утверждения (claims). Эти утверждения проходят через графовую
и семантическую маршрутизацию для поиска дубликатов и противоречий.
Конечной точкой является рабочее место оператора, где принимаются
решения, замыкающие петлю обратной связи с репозиториями реализации.

> Фрагмент кода
>
> graph TD\
> subgraph Ingestion Layer\
> A1\[Local Folders\] \--\> C\[Ingestion Adapters\]\
> A2\[Git Repos\] \--\> C\
> A3\[Drive / APIs\] \--\> C\
> end\
> \
> subgraph Immutable Storage\
> C \--\> D\[Raw Object Store S3\]\
> D \--\> E\[Artifact Ledger Postgres\]\
> end\
> \
> subgraph Extraction & Provenance\
> E \--\> F\[MicroVM Parser Sandbox\]\
> F \--\> G\[Claim Extraction Engine\]\
> G \--\> H\[Provenance Graph Builder\]\
> end\
> \
> subgraph State & Retrieval\
> H \--\> I\[(Relational DB: Postgres)\]\
> H \--\> J\[(Vector Index: pgvector)\]\
> I \<\--\> K\[Contradiction Detector\]\
> end\
> \
> subgraph Human & Policy Loop\
> K \--\> L\[Human Review Workbench\]\
> L \--\> M\[Canonical Decision Ledger\]\
> end\
> \
> subgraph External Boundaries\
> M \--\> N\[Git / ADR Impact\]\
> M \--\> O\[ContinuityOS Policy\]\
> P\[LifeOS\] -.-\>\|Read Only\| I\
> end

Стратегическое решение о выборе единой транзакционной базы данных
обосновано анализом совокупной стоимости владения для системы с одним
администратором. Использование специализированных векторных баз данных
(таких как Qdrant) обеспечивает незначительное преимущество в скорости
(доли миллисекунд на 99-м перцентиле) и предоставляет продвинутые
механизмы квантизации^1^. Однако разделение документов и их векторных
представлений по разным базам данных неизбежно приводит к проблемам
рассинхронизации. Если транзакция обновления документа завершается
успешно, а запись в векторную базу падает, возникают \"осиротевшие\"
векторы (orphaned vectors) или скрытые документы, требующие внедрения
очередей недоставленных сообщений (dead-letter queues) и фоновых задач
сверки^1^.

-   **Decision**: Использовать PostgreSQL как единую транзакционную базу
    данных для реляционных связей, полнотекстового поиска и векторных
    эмбеддингов (через расширение pgvector).

-   **Evidence**: pgvector обеспечивает задержки менее 50 мс при
    правильной настройке HNSW-индексов, а размещение векторов в той же
    таблице, что и текстовые метаданные, гарантирует ACID-транзакции^1^.
    FTS в Postgres превосходит SQLite по масштабируемости при
    конкурентных запросах и предоставляет глобальную статистику корпуса
    для ранжирования^6^.

-   **Assumptions**: Объем корпуса не превысит 5 миллионов векторов в
    среднесрочной перспективе, что позволяет избежать потребности в
    горизонтальном шардировании^1^.

-   **Alternatives**: PostgreSQL + Qdrant; Weaviate; SQLite + FTS5.

-   **Rejected Alternatives**: Qdrant и Weaviate отклонены из-за высоких
    операционных издержек на поддержание второй инфраструктуры и
    усложнения логики транзакций^1^. SQLite отклонен из-за проблем с
    блокировками на запись в многопоточной среде конвейерной обработки
    данных^6^.

-   **Risks**: Конкуренция за память (shared\_buffers) между графовыми
    запросами и HNSW-индексами.

-   **Confidence**: 0.95.

-   **Acceptance Test**: Вставка артефакта, извлечение метаданных и
    генерация векторного эмбеддинга выполняются и откатываются как
    единая атомарная операция базы данных.

-   **Revisit Trigger**: Достижение объема в 5 млн векторов или
    регулярное превышение задержки HNSW-поиска свыше 200 мс.

04\_ARTIFACT\_IDENTITY\_AND\_VERSIONING
---------------------------------------

Система идентичности артефактов фундаментально разделяет физический
бинарный поток, его логическую сущность в бизнес-домене и его
семантическое содержимое. Идентичность строится вокруг
криптографического хеширования (SHA-256) оригинального бинарного потока.
Любое изменение в файле, даже незначительное, порождает новый
artifact\_id. Логическое связывание различных версий одного документа
реализуется через абстракцию logical\_document\_id и графовые связи
parent\_version\_id. Подобный подход заимствован из архитектуры
современных хранилищ метаданных data lake систем, таких как lakeFS, где
иммутабельные файлы в объектном хранилище связываются мутабельными
указателями в KV-хранилище или реляционной базе^2^.

> Фрагмент кода
>
> erDiagram\
> LOGICAL\_DOCUMENT \|\|\--o{ ARTIFACT\_VERSION : tracks\
> ARTIFACT\_VERSION \|\|\--\|\| ARTIFACT : manifests\
> ARTIFACT\_VERSION \|\|\--o{ DUPLICATE\_CLUSTER : belongs\_to\
> \
> ARTIFACT {\
> uuid artifact\_id PK\
> string content\_hash\
> string source\_system\_id\
> string source\_native\_id\
> }\
> \
> ARTIFACT\_VERSION {\
> uuid version\_id PK\
> uuid parent\_version\_id FK\
> boolean is\_superseded\
> }\
> \
> DUPLICATE\_CLUSTER {\
> uuid cluster\_id PK\
> string canonical\_artifact\_id FK\
> }

Разрешение дубликатов происходит не путем физического удаления файлов,
что нарушило бы принцип сохранения истории, а через назначение им общего
duplicate\_cluster\_id. Точные дубликаты (стопроцентное совпадение
content\_hash) группируются автоматически. Близкие дубликаты (например,
один и тот же отчет, сохраненный в форматах DOCX и Markdown, дающий
совпадение семантического вектора \>0.98) помечаются для явной проверки
человеком. Частичные экспорты, извлеченные вложения или сгенерированные
сводки классифицируются как производные версии, имеющие явную
направленную связь parent\_version\_id с оригиналом. Это гарантирует,
что система может детерминированно ответить на вопрос о том, какая
версия является новейшей, не опираясь исключительно на ненадежные
временные метки файловой системы.

05\_PROVENANCE\_AND\_TRUST
--------------------------

Для управления происхождением данных (provenance) архитектура глубоко
интегрирует семантику спецификаций W3C PROV-O и PROV-DM^12^. Базовые
концепции PROV --- Entity (Артефакты, Утверждения), Activity (Парсинг,
Вывод модели, Трансформация) и Agent (Пользователь, Модель GPT-4,
Коннектор) --- используются для создания иммутабельного реестра
происхождения, который семантически совместим с базовыми формальными
онтологиями (BFO)^13^. Любой производный объект в Knowledge Foundry
сохраняет полную историю того, как именно он был получен, включая
параметры окружающей среды в момент создания.

> Фрагмент кода
>
> graph LR\
> A((Agent: DeepSeek-R1)) \--\>\|wasAssociatedWith\| B\[Activity: Claim
> Extraction\]\
> C(Entity: Raw PDF Report) \--\>\|used\| B\
> B \--\>\|wasGeneratedBy\| D(Entity: Extracted Claim)\
> D \--\>\|wasDerivedFrom\| C\
> E((Agent: Owner)) \--\>\|actedOnBehalfOf\| A\
> F(Entity: Extraction Prompt v2) \--\>\|used\| B

Классификация доверия является многомерной и гранулярной. Артефакту не
присваивается глобальный числовой балл доверия. Вместо этого доверие
специфично для домена и источника (например, PRIMARY\_CODE для
функциональности, проистекающей из Git-репозитория,
INDEPENDENT\_RESEARCH для отчетов Deep Research, UNVERIFIED\_IMPORT для
исторических экспортов Telegram, VENDOR\_CLAIM для маркетинговых
материалов). Если языковая модель генерирует сводку, в реестр
ProvenanceRecord записывается точная версия промпта, температурные
параметры модели и content\_hash исходного документа. Это гарантирует
возможность полной детерминированной реконструкции или массовой
инвалидации целого кластера знаний при обнаружении уязвимости в
конкретной версии парсера или галлюцинаций в конкретной версии модели.

06\_CLAIM\_EVIDENCE\_MODEL
--------------------------

Документ не рассматривается как неделимая единица истины. Базируясь на
архитектуре наборов данных для фактчекинга, таких как FEVER (Fact
Extraction and VERification) и ClaimDB, система извлекает из текстов
атомарные утверждения (claims)^18^. Каждое утверждение представляет
собой изолированную семантическую единицу, нормализованную в структуру
(subject, predicate, object), жестко привязанную к точному фрагменту
источника (exact\_source\_excerpt). Это предотвращает размытие
контекста, характерное для длинных текстовых фрагментов в стандартных
RAG-системах.

Вместо плоской структуры внедряется многоуровневая (multi-hop) система
верификации, где утверждение может опираться на доказательства из
нескольких независимых артефактов, формируя сложный граф подтверждений и
опровержений^20^.

> Фрагмент кода
>
> graph TD\
> A\[Source Document: Vendor PDF\] \--\>\|Extraction\| B(Claim 101:
> System X supports 10k QPS)\
> C\[Source Code Repo: Test Suite\] \--\>\|Extraction\| D(Claim 102:
> Benchmark fails at 2k QPS)\
> \
> B \--\> E{Evidence Link 1}\
> A -.-\> E\
> E \--\>\|Support Type\| F\[SUPPORTS\]\
> \
> B \--\> G{Evidence Link 2}\
> C -.-\> G\
> G \--\>\|Support Type\| H\[REFUTES\]\
> \
> F \--\> I\[Claim Status: CONTRADICTED\]\
> H \--\> I

Статусы утверждения строго определены конечным автоматом: PROPOSED,
SUPPORTED, VERIFIED, DISPUTED, CONTRADICTED, STALE, SUPERSEDED,
UNVERIFIABLE, REJECTED^18^. Разделение между claim (утверждением) и
decision (решением) фундаментально. Утверждение \"Продукт Y
масштабируется до 1000 узлов\" может быть извлечено из маркетингового
PDF (VENDOR\_CLAIM), получить статус SUPPORTED через независимый
бенчмарк, но это не делает его архитектурным решением проекта, пока
оператор не создаст объект CanonicalDecision.

07\_CONTRADICTION\_MANAGEMENT
-----------------------------

Противоречия рассматриваются не как ошибки системы, требующие скрытого
сглаживания, а как важнейший полезный сигнал. Архитектура внедряет
механизмы автоматического и человеко-машинного выявления конфликтов.
Автоматическое выявление использует семантический анализ векторных
пространств (поиск соседей с высокой семантической близостью, но
инвертированным смыслом) и формальные проверки схем.

> Фрагмент кода
>
> stateDiagram-v2\
> \[\*\] \--\> DETECTED : Semantic Match / Schema Drift\
> DETECTED \--\> TRIAGE : Human or Policy Review\
> TRIAGE \--\> OPEN\_QUESTION : Needs Deep Research\
> TRIAGE \--\> REQUIRED\_EXPERIMENT : Needs Runtime Test\
> TRIAGE \--\> FALSE\_POSITIVE : Discard / Unrelated\
> OPEN\_QUESTION \--\> RESOLVED : Decision Made\
> REQUIRED\_EXPERIMENT \--\> RESOLVED : Evidence Collected\
> RESOLVED \--\> \[\*\]

Для каждого конфликта создается объект ContradictionRecord. Он связывает
затронутые объекты Claim, назначает владельца, определяет серьезность и
текущее состояние. Например, если исходный код противоречит
задокументированной архитектуре (ImplementationMismatch), система не
отдает автоматический приоритет коду. Код констатирует реальность, но
может содержать баг. Конфликт остается открытым до тех пор, пока
оператор не примет явное решение: либо обновить схему и документацию
(подняв поведение кода до статуса канона), либо создать тикет в бэклоге
на исправление кода (сохранив документацию как канон).

08\_CANONICALIZATION
--------------------

Канонизация --- это не автоматический процесс агрегации; это явный акт
(explicit decision) принятия ответственности за истинность, терминологию
или системный инвариант. Состояния канонизации образуют строгую конечную
машину, предотвращающую случайное изменение согласованных параметров.

> Фрагмент кода
>
> stateDiagram-v2\
> RAW \--\> PARSED\
> PARSED \--\> INDEXED\
> INDEXED \--\> CLAIMS\_EXTRACTED\
> CLAIMS\_EXTRACTED \--\> REVIEW\_REQUIRED\
> REVIEW\_REQUIRED \--\> ACCEPTED\_AS\_EVIDENCE\
> ACCEPTED\_AS\_EVIDENCE \--\> CANDIDATE\_CANON\
> CANDIDATE\_CANON \--\> CANONICAL : Explicit Owner Approval\
> CANONICAL \--\> SUPERSEDED : New Decision Overrides\
> CANONICAL \--\> STALE : Time/Trigger based Decay\
> CANONICAL \--\> QUARANTINED : Security Revocation

Требования к утверждению зависят от классификации риска. Изменение
глоссария с низким риском может быть одобрено одним кликом или
делегировано доверенной политике ContinuityOS. Однако изменение
параметра торгового риска, правила обработки секретов в production-среде
или конституции агента требует криптографически подписанного события
решения (CanonicalDecision), которое становится иммутабельной записью в
реестре. Понятие \"канонический\" не означает \"перманентный\" ---
канонические объекты регулярно переходят в статус SUPERSEDED при
поступлении новых данных или изменении бизнес-требований.

09\_DECISION\_IMPLEMENTATION\_GRAPH
-----------------------------------

Знания бесполезны, если они не воплощены в реальности или если
реальность расходится со знаниями. Knowledge Foundry устанавливает
строгий граф маппинга от первоисточника до среды выполнения. Эта система
устраняет разрыв между принятым Architecture Decision Record (ADR) и
фактическим исходным кодом.

> Фрагмент кода
>
> graph LR\
> A\[Source Artifact\] \--\> B\[Claim\]\
> B \--\> C\[Evidence Link\]\
> C \--\> D\[Canonical Decision\]\
> D \--\> E\[ADR Document\]\
> E \--\> F\[Repository Schema\]\
> D \--\> G\[Backlog Ticket\]\
> G \--\> H\[Git Commit\]\
> H \--\> I\[Deployment State\]\
> I \--\> J\[Runtime Evidence\]\
> J -.-\>\|Automated Feedback Loop\| C

Для эффективного обхода этого иерархического графа система использует
рекурсивные обобщенные табличные выражения (Recursive CTE)
PostgreSQL^22^. Рекурсивные запросы WITH RECURSIVE позволяют базе данных
самостоятельно обходить неограниченно глубокие цепочки связей от корня
(базового решения) до листьев (задеплоенного кода) без переноса всего
массива данных в память приложения^23^. Это позволяет системе мгновенно
отвечать на запросы о покрытии: \"Показать все принятые архитектурные
решения, у которых отсутствуют связанные тикеты реализации\" или
\"Показать все задеплоенные микросервисы, для которых исходное
каноническое решение было переведено в статус SUPERSEDED\".

10\_RESEARCH\_RUN\_MANAGEMENT
-----------------------------

Для независимых исследовательских прогонов (Deep Research) вводится
профессиональный объект ResearchRun. Это необходимо, поскольку
результаты исследований часто генерируются языковыми моделями на основе
сложного контекста, и этот точный контекст должен быть зафиксирован для
обеспечения воспроизводимости.

> Фрагмент кода
>
> stateDiagram-v2\
> PLANNED \--\> RUNNING\
> RUNNING \--\> RESULT\_RECEIVED\
> RESULT\_RECEIVED \--\> SOURCES\_AUDITED\
> SOURCES\_AUDITED \--\> CLAIMS\_EXTRACTED\
> CLAIMS\_EXTRACTED \--\> DELTA\_REVIEWED\
> DELTA\_REVIEWED \--\> MERGED\_OR\_REJECTED\
> MERGED\_OR\_REJECTED \--\> ARCHIVED

Объект ContextManifest фиксирует криптографические хеши всех файлов,
поданных модели на вход. Это гарантирует, что система поддерживает
\"слепые\" независимые прогоны (blind independent runs), где разным
моделям даются одинаковые входные данные. Если две модели приходят к
противоположным выводам на одном и том же манифесте контекста, система
генерирует DecisionConflict и автоматически связывает оба отчета.
Интеграция с инструментами трассировки, такими как Langfuse или Phoenix,
обеспечивает видимость промежуточных шагов рассуждения
(chain-of-thought) модели во время прогона.

11\_SEARCH\_AND\_RETRIEVAL
--------------------------

Подсистема поиска должна обеспечивать точный поиск по идентификаторам,
полнотекстовый поиск (FTS), семантический векторный поиск, графовый
обход и поиск с учетом оси времени.

-   **Decision**: Использовать встроенный полнотекстовый поиск
    PostgreSQL (tsvector, pg\_trgm) в комбинации с расширением pgvector
    для HNSW семантического индексирования.

-   **Evidence**: pgvector обеспечивает задержки менее 50 мс для наборов
    до 1 миллиона векторов, что полностью покрывает нужды одного
    владельца^1^. Встроенный FTS в Postgres превосходит SQLite FTS5, так
    как Postgres поддерживает глобальную статистику корпуса для более
    точного релевантного ранжирования (в то время как SQLite FTS5
    реализует BM25, но сталкивается с проблемами при масштабировании
    пула соединений)^6^.

-   **Assumptions**: Операционные затраты (DevOps, мониторинг) для
    владельца-одиночки должны быть минимизированы. Единая реляционная БД
    значительно снижает когнитивную нагрузку по сравнению с
    полиглот-архитектурой^1^.

-   **Alternatives**: SQLite FTS5^7^; Qdrant + Postgres^4^;
    ElasticSearch / OpenSearch.

-   **Rejected Alternatives**: Qdrant отклонен, так как его внедрение
    требует синхронизации двух независимых систем хранения, написания
    логики повторных попыток (retries) и фоновой очистки для устранения
    неконсистентности^1^. ElasticSearch отклонен как избыточный для
    корпуса MVP.

-   **Risks**: Недостаточная гибкость квантизации (quantization) в
    pgvector по сравнению с Qdrant при экстремальном росте данных.

-   **Confidence**: 0.98.

-   **Acceptance Test**: SQL-запрос успешно выполняет JOIN между
    таблицей Claim, FTS индексом и HNSW векторным поиском, возвращая
    отфильтрованные по метаданным результаты за \<100мс.

-   **Revisit Trigger**: Если время построения векторного индекса или
    время ответа превысит установленные пороговые значения при
    увеличении базы свыше 5 миллионов записей.

12\_CONNECTORS
--------------

Для обеспечения поэтапного приема хаотичной информации разрабатываются
коннекторы (ingestion adapters). MVP реализует минимальный набор: Local
Folder Connector (опрос файловой системы с инкрементальным курсором) и
Git Repo Connector (чтение коммитов).

Каждый коннектор отвечает за строгую идемпотентность: повторное чтение
одного и того же файла не создает логических дубликатов. Внешний
идентификатор source\_native\_id (например, Google Drive File ID или Git
SHA) жестко привязывается к artifact\_id. Если источник удален,
коннектор не удаляет артефакт в Knowledge Foundry. Вместо этого он
добавляет в лог событие происхождения (\"объект удален в источнике\"),
сохраняя локальную иммутабельную копию в хранилище сырых объектов.

> Фрагмент кода
>
> graph LR\
> A\[External System: Git / Drive\] \--\>\|Polling / Webhook\|
> B\[Connector Factory\]\
> B \--\> C{Idempotency Cursor Check}\
> C \--\>\|New Content Hash\| D\[Immutable Raw Store S3\]\
> D \--\> E\[Create Artifact Record\]\
> C \--\>\|Known Hash\| F\[Update Metadata & Observed Timestamp\]\
> C \--\>\|Source Deleted\| G\[Log Deletion Event, Keep Raw\]

13\_SECURITY
------------

Учитывая, что в систему поступают неконтролируемые данные (отчеты с
возможными инъекциями промптов, вредоносные PDF, скраппинг веб-страниц),
архитектура внедряет строгие границы безопасности. Текст из документа
никогда не получает полномочий инструкции (Source text is not an
instruction). Запрещено использовать механизмы, позволяющие агенту
напрямую изменять каноническое состояние на основе прочитанного.

-   **Decision**: Использовать эфемерные изолированные микро-виртуальные
    машины (MicroVMs), такие как Docker Sandboxes (на базе Firecracker
    или gVisor), для извлечения текста и парсинга сложных файлов^30^.

-   **Evidence**: Традиционные Docker контейнеры разделяют ядро ОС с
    хостом, что оставляет вектор атак при использовании уязвимых
    библиотек парсинга или внедрении вредоносного кода, сгенерированного
    LLM^32^. MicroVM обеспечивают аппаратную изоляцию с собственным
    ядром и приватным Docker-демоном, предотвращая побег на
    хост-систему, при сохранении времени холодного старта в
    миллисекунды^30^.

-   **Assumptions**: Система извлечения должна работать автономно,
    потребляя файлы из карантинной зоны без доступа к внутренней сети
    проекта (Blocked Egress)^35^.

-   **Alternatives**: Обычные Docker контейнеры; Native OS processes;
    SaaS API (AWS Textract).

-   **Rejected Alternatives**: Обычные контейнеры недостаточно изолируют
    угрозы инъекций промптов^35^. SaaS API передают чувствительные
    корпоративные данные третьим лицам.

-   **Risks**: Усложнение локальной среды разработки оркестрацией
    MicroVM.

-   **Confidence**: 0.90.

-   **Acceptance Test**: Парсер, зараженный эксплойтом zip bomb или
    уязвимостью переполнения буфера в PDF-библиотеке, падает внутри
    MicroVM, не воздействуя на процессы Knowledge Foundry и не получая
    доступа к сети.

-   **Revisit Trigger**: Неприемлемо высокие задержки при массовой
    обработке тысяч мелких текстовых файлов (для простых форматов вроде
    TXT/Markdown можно будет использовать более легкий внутрипроцессный
    конвейер).

> Фрагмент кода
>
> graph TD\
> A\[Raw Artifact Store S3\] \--\>\|Read-only volume mount\| B\[MicroVM
> Sandbox Boundary\]\
> B \--\> C\[PDF/Docx Parsing Runtime\]\
> C \--\>\|Sanitized Text + Metadata JSON\| D\[Extraction Record\]\
> C -.-x\|Network Egress Dropped\| E\[Internal / External Network\]\
> C -.-x\|Syscall Filtered\| F\[Host Kernel\]

14\_BUILD\_VS\_ADOPT
--------------------

Стратегия компонентизации направлена на снижение совокупной стоимости
владения (TCO) и операционной нагрузки для одного
разработчика/владельца.

  **Уровень / Компонент**     **Стратегия**   **Технология**              **Обоснование и триггер пересмотра**                                                                    **Операционная стоимость**
  --------------------------- --------------- --------------------------- ------------------------------------------------------------------------------------------------------- --------------------------------------------
  **Relational DB / Graph**   Adopt           **PostgreSQL**              Обеспечивает ACID транзакции, WITH RECURSIVE для графов^6^. *Триггер: недоступен.*                      Низкая (Managed RDS или локальный Docker).
  **Vector Index**            Adopt           **pgvector**                Устраняет нужду в синхронизации с Qdrant^1^. *Триггер: 5M+ векторов.*                                   Нулевая (встроено в Postgres).
  **Raw Object Storage**      Adopt           **S3-compatible (MinIO)**   Универсальный стандарт для неизменяемых блобов. *Триггер: Переход полностью в облако (AWS S3).*         Низкая.
  **Object Versioning**       Adapt           **lakeFS concepts**         Адаптируем модель указателей метаданных для артефактов без запуска тяжелого сервера lakeFS^2^.          Включено в разработку схемы Postgres.
  **Research Traces**         Adopt           **Langfuse / Phoenix**      Мощная визуализация цепочек LLM, не стоит строить с нуля. *Триггер: переход на проприетарные модели.*   Средняя (SaaS подписка).
  **Document Mgmt**           Reject          **Notion / Obsidian**       Не позволяют строить глубокий граф происхождения и изолировать Private Memory от Canonical Truth.       \-
  **Search Engine**           Reject          **ElasticSearch**           Избыточен для MVP; FTS в Postgres достаточно^6^.                                                        \-

15\_OPERATOR\_WORKBENCH
-----------------------

Human Review Workbench --- это минимальный графический интерфейс
оператора, необходимый для контроля над системой. Так как Telegram
пригоден только для простых алертов и не может отображать сложные графы,
создается специализированный веб-дашборд.

Основные визуальные компоненты:

1.  **Inbox / Unclassified Artifacts**: Входящая очередь для новых или
    > нераспознанных данных, ожидающих классификации чувствительности.

2.  **Duplicate and Version Clusters**: Визуализация кластеров близких
    > дубликатов для ручного слияния или разметки версионности.

3.  **Contradictions / Claims Awaiting Review**: Центр принятия решений
    > по выявленным конфликтам. Показывает Side-by-side сравнение
    > противоречивых утверждений и их выделенных в тексте источников.

4.  **Architecture Map / Implementation Coverage**: Тепловая карта
    > системы (где есть реализованный код, но нет ADR, или где
    > документация описывает несуществующий функционал).

Действия оператора строго типизированы: accept, reject, merge, link as
version, mark duplicate, promote to canonical, supersede, quarantine.

> Фрагмент кода
>
> graph TD\
> A\[Human Review Workbench\] \--\> B\[Inbox Queue View\]\
> A \--\> C\[Conflict Resolution Screen\]\
> A \--\> D\[Canonical Ledger Map\]\
> \
> C \--\> E\[Claim A: SUPPORTS (Model Output)\]\
> C \--\> F\[Claim B: REFUTES (Code Runtime)\]\
> \
> E \--\> G{Owner Action}\
> F \--\> G\
> G \--\>\|Accept Code as Truth\| H\[Create Schema Conflict Ticket\]\
> G \--\>\|Accept Model as Truth\| I\[Create Implementation Ticket\]\
> H \--\> J\[Mutate Canonical State\]\
> I \--\> J

16\_SCHEMAS\_AND\_APIS
----------------------

Для реализации требуется строгая типизация на уровне базы данных. Ниже
представлены спроектированные схемы, объединяющие 24 требуемых сущности.
Все производные объекты содержат базовые поля: object\_id,
schema\_version, created\_at, created\_by, project\_scope, data\_class,
status, policy\_context.

**Базовые схемы (Ingestion & Identity):**

-   SourceSystem: system\_id, name, connector\_type, auth\_method,
    rate\_limits.

-   Artifact: artifact\_id, content\_hash, source\_system\_id,
    source\_native\_id, mime\_type, byte\_size, storage\_uri,
    observed\_timestamp.

-   ArtifactVersion: version\_id, artifact\_id, parent\_version\_id,
    duplicate\_cluster\_id, is\_superseded.

-   DuplicateCluster: cluster\_id, canonical\_artifact\_id,
    resolution\_status.

-   IngestionRun: run\_id, source\_system\_id, cursor\_state,
    started\_at, completed\_at, records\_processed.

-   DataClassification: class\_id, artifact\_id, sensitivity\_level
    (e.g., PUBLIC, INTERNAL, SECRET).

**Извлечение и Происхождение (Extraction & Provenance):**

-   ExtractionRecord: extraction\_id, artifact\_id, parser\_version,
    sandbox\_id, extracted\_text\_uri, metadata\_json.

-   ProvenanceRecord: provenance\_id, derived\_object\_id,
    activity\_type, agent\_id, prompt\_version\_id,
    parent\_artifact\_ids\[\], trust\_level.

-   SourceLedger: ledger\_id, run\_id, artifact\_ids\[\],
    priority\_weights.

**Утверждения и Доказательства (Claims & Evidence):**

-   Claim: claim\_id, normalized\_assertion, exact\_source\_excerpt,
    subject, predicate, object, time\_validity, author, confidence,
    status.

-   EvidenceLink: link\_id, claim\_id, evidence\_artifact\_id,
    support\_type (SUPPORTS, REFUTES, NOT\_ENOUGH\_INFO), independence,
    freshness, quality.

**Противоречия и Решения (Contradictions & Decisions):**

-   ContradictionRecord: contradiction\_id, affected\_claim\_ids\[\],
    severity, owner, resolution\_state, proposed\_tests.

-   OpenQuestion: question\_id, context\_claim\_ids\[\], status,
    assigned\_research\_run\_id.

-   CanonicalDecision: decision\_id, claim\_id, decision\_type (ADR,
    SCHEMA, INVARIANT), approved\_by, approved\_at,
    cryptographic\_signature.

-   SupersessionRecord: supersession\_id, old\_decision\_id,
    new\_decision\_id, reason.

**Маппинг реализации и архитектуры (Implementation & Architecture):**

-   ArchitectureImpact: impact\_id, decision\_id, affected\_systems\[\],
    risk\_level.

-   ImplementationLink: link\_id, decision\_id, repository\_path,
    commit\_sha, deployment\_id.

-   ADRReference: reference\_id, decision\_id, adr\_artifact\_id,
    status.

-   BacklogReference: reference\_id, decision\_id, ticket\_id, status.

**Исследования и Политики (Research & Policy):**

-   ResearchRun: run\_id, task\_id, exact\_prompt,
    context\_manifest\_id, model\_provider, start\_time, end\_time,
    raw\_result\_artifact\_id, reviewer\_decision.

-   ContextManifest: manifest\_id, run\_id,
    included\_artifact\_hashes\[\], excluded\_scopes\[\].

-   DecisionDelta: delta\_id, run\_id, proposed\_changes\[\], status.

-   ReviewTask: task\_id, object\_id, object\_type, assigned\_to,
    deadline, status.

-   AccessPolicy: policy\_id, data\_class, allowed\_roles\[\],
    routing\_rules\[\].

17\_MONOREPO
------------

Физическая структура исходного кода для Knowledge Foundry должна
отражать архитектурные границы и обеспечивать инкрементальное
развертывание MVP.

/maworld-knowledge-foundry

├── /contracts \# JSON Schemas, Protobuf/OpenAPI specs for the 24
schemas

├── /infrastructure \# Terraform/Docker Compose (Postgres, MinIO, Docker
Sandboxes)

├── /ingestion \# Connectors (Local Folder, Git, Telegram Export)

│ ├── /adapters

│ └── /idempotency\_store

├── /extraction \# MicroVM parsing logic, Content Disarm &
Reconstruction

├── /knowledge\_graph \# Claim extraction engine, FEVER modeling,
Provenance tracking

├── /canonical\_engine \# Conflict detection (SQL jobs), Decision State
Machine

├── /workbench \# Next.js/React UI for the human operator

└── /tests \# E2E Scenarios, Failure tests, Poisoned PDF fixtures

18\_INCREMENTAL\_MIGRATION\_PLAN
--------------------------------

Система спроектирована для работы с неполной информацией. Требуется
полный отказ от попыток ручной предварительной сортировки (pre-sort)
всего корпуса перед запуском.

-   **Phase 0 --- Empty Workspace**: Разворачивается монорепозиторий,
    создаются таблицы PostgreSQL, поднимается локальный S3 (MinIO).
    Подключается только один коннектор --- Local Folder Connector.

-   **Phase 1 --- Current Seed Corpus**: В систему загружаются только
    ключевые документы: 00\_MASTER.md,
    01\_RESEARCH\_ADDENDUM\_2026-07.md, отчеты D1--D4, текущие промпты
    Deep Research и выбранные файлы кода ContinuityOS. Проверяется
    конвейер Extraction → Claim → Evidence.

-   **Phase 2 --- Ongoing Intake**: Коннекторы переводятся в
    автоматический режим. Входящие отчеты Deep Research или новые
    документы автоматически попадают в Inbox для классификации
    чувствительности.

-   **Phase 3 --- Architecture Integration**: Включается графовая логика
    Decision → ADR → Schema → Backlog. Оператор начинает видеть тикеты,
    не имеющие архитектурного обоснования, или реализованный код без
    документации.

-   **Phase 4 --- Historical Migration**: Старые экспорты Telegram,
    устаревшие чаты и черновики медленно обрабатываются системой в
    фоновом режиме. Приоритезация обработки: *Актуальность для активного
    проекта \> Степень риска \> Новизна \> Уникальность \> Ценность
    доказательств \> Влияние на реализацию*.

19\_MVP\_VERTICAL\_SLICE
------------------------

Самый маленький жизнеспособный продукт (MVP) должен быть реализован до
того, как весь архив будет собран, и предоставить сквозную ценность для
одного документа.

**Required Vertical Slice**:

DROP OR SELECT A FILE → HASH AND STORE RAW → EXTRACT TEXT/METADATA →
CLASSIFY → CREATE ARTIFACT RECORD → EXTRACT CLAIMS → LINK SOURCES →
DETECT DUPLICATE/CONTRADICTION → HUMAN REVIEW → CREATE CANONICAL
DECISION OR OPEN QUESTION → LINK TO ADR/TICKET → SHOW CHANGELOG.

**Seed Corpus для MVP**:

Один master документ, один аддендум, два противоречащих друг другу
отчета Deep Research, один файл исходного кода и одна архитектурная
схема.

**Acceptance**:

Сырые файлы сохранены в MinIO; каждый извлеченный Claim имеет ссылку на
файл; дублирующиеся отчеты объединены в DuplicateCluster; система
выявила конфликт между двумя отчетами; оператор создал
CanonicalDecision, связал его с тикетом и смог успешно перевести его в
статус SUPERSEDED; семантический индекс HNSW перестроен с нуля; загрузка
новых файлов не ломает существующий граф.

> Фрагмент кода
>
> sequenceDiagram\
> participant Owner\
> participant Connector\
> participant Postgres\
> participant Extractor\
> participant LLM\
> \
> Owner-\>\>Connector: Drops 00\_MASTER.md\
> Connector-\>\>Postgres: Create Artifact (Hash: 0xAbC)\
> Connector-\>\>Extractor: Trigger Job in MicroVM\
> Extractor-\>\>LLM: Prompt FEVER Claim Extraction\
> LLM\--\>\>Extractor: JSON Claims\
> Extractor-\>\>Postgres: Insert Claims & Provenance\
> Postgres\--\>\>Owner: Workbench shows new claims\
> Owner-\>\>Postgres: Approve -\> CanonicalDecision -\> Backlog

20\_FAILURE\_AND\_EVALUATION\_TESTS
-----------------------------------

Надежность архитектуры проверяется через 30 жестких сценариев отказа.

  **\#**   **Сценарий**                              **Acceptance Test (Ожидаемое поведение)**
  -------- ----------------------------------------- -------------------------------------------------------------------------------------------------------
  1        **Duplicate upload**                      Коннектор вычисляет тот же content\_hash. Новый артефакт не создается (идемпотентность).
  2        **Renamed duplicate**                     Имя файла изменено, но content\_hash совпадает. Добавляется в существующий DuplicateCluster.
  3        **Old content, new timestamp**            Игнорируется временная метка ОС; контент-хеш управляет идентичностью.
  4        **Same document in DOCX and Markdown**    Хеши разные. После извлечения Claim семантика совпадает (\>0.98), помечается как Near Duplicate.
  5        **Conflicting architecture decisions**    Генерируется ContradictionRecord. Предыдущий канон не перезаписывается молча.
  6        **Poisoned prompt inside PDF**            MicroVM изолирует парсер. LLM-инструкция обернута; текст документа отклоняется как системная команда.
  7        **Fake citations**                        EvidenceLink требует точного совпадения exact\_source\_excerpt. Проверка падает, статус UNVERIFIABLE.
  8        **Missing source**                        Артефакт не принимается без криптографического подтверждения источника.
  9        **Deleted source**                        Артефакт сохраняется локально в неизменяемом S3. Удаление в источнике логируется, данные не теряются.
  10       **Code contradicts documentation**        Создается ImplementationMismatch. Владелец решает, чья сторона побеждает в CanonicalDecision.
  11       **Doc describes unimplemented feature**   Тикет получает статус \"Ожидает реализации\", связанный с каноническим ADR.
  12       **Stale vendor pricing**                  При истечении TTL или появлении нового прайса старый Claim переходит в STALE.
  13       **Corrupted file**                        Ошибка парсера записывается в ExtractionRecord. Песочница уничтожается без утечек памяти.
  14       **Parser failure**                        Аналогично №13, артефакт помечается PARSING\_FAILED для ручного разбора.
  15       **Extraction retry**                      После обновления версии парсера система перезапускает извлечение для упавших артефактов.
  16       **Connector outage**                      При рестарте читается курсор из idempotency\_store. Продолжение с места обрыва.
  17       **Partial upload**                        Несовпадение заявленного байтового размера отменяет транзакцию приема.
  18       **Secret in document**                    Сканер секретов маскирует токены до отправки в LLM; данные получают класс SECRET.
  19       **Cross-project access attempt**          RLS (Row Level Security) в Postgres блокирует чтение несанкционированным агентом.
  20       **Unauthorized canonicalization**         Отсутствие криптографической подписи владельца или роли ContinuityOS откатывает транзакцию.
  21       **Canonical decision supersession**       Новый канон ссылается на старый через supersedes\_decision\_id, старый помечается SUPERSEDED.
  22       **Schema conflict**                       Блокируется слияние (merge) до явного ручного разрешения конфликта оператором.
  23       **Duplicate ticket**                      Графовый обход выявляет, что два тикета ссылаются на один Claim. Выводится алерт в UI.
  24       **Research result with wrong task**       Валидация ContextManifest отклоняет результат, не соответствующий задаче.
  25       **Incomplete report**                     Прием только подтвержденных Claims; остальное требует повторного прогона (Retry).
  26       **Model-generated unsupported claim**     Статус PROPOSED, не может стать VERIFIED без источника в сыром корпусе.
  27       **Vector index loss and rebuild**         Таблица векторов очищается и перестраивается из реляционной таблицы Claim за \<5 минут.
  28       **Database restart**                      Полное восстановление ACID; pgvector корректно загружает индексы HNSW с диска.
  29       **Raw object storage unavailable**        Очередь Ingestion приостанавливается, запросы к графу БД продолжают работать в read-only.
  30       **Human review backlog**                  Дашборд пагинирует задачи; приоритет отдается конфликтам с наибольшим числом зависимостей.
  31       **Migration interrupted and resumed**     Восстановление идет с последнего observed\_timestamp в логе IngestionRun.

21\_FIRST\_20\_TICKETS
----------------------

Первичное наполнение бэклога разработки (Backlog Impact):

1.  **INFRA-01**: Развернуть PostgreSQL (Docker) с расширениями pgvector
    > и pg\_trgm.

2.  **INFRA-02**: Развернуть MinIO (S3-compatible) для Raw Object Store.

3.  **SCHEMA-01**: Реализовать DDL для Artifact, ArtifactVersion,
    > DuplicateCluster.

4.  **SCHEMA-02**: Реализовать DDL для Claim, EvidenceLink и
    > ProvenanceRecord.

5.  **CONN-01**: Создать Local Folder Ingestion скрипт (идемпотентный
    > обход, SHA-256).

6.  **EXTR-01**: Настроить Docker Sandbox обертку для безопасного
    > парсинга текста.

7.  **EXTR-02**: Интегрировать библиотеку экстракции PDF/DOCX внутри
    > песочницы.

8.  **LLM-01**: Разработать DSPy/LangChain промпт для извлечения
    > атомарных Claim (FEVER format).

9.  **GRAPH-01**: Написать WITH RECURSIVE SQL-запрос для получения
    > истории происхождения артефакта.

10. **GRAPH-02**: Интегрировать генерацию векторных эмбеддингов для
    > Claim.normalized\_assertion.

11. **CORE-01**: Реализовать транзакционный API: Вставка Артефакта +
    > Провенанс.

12. **CONFLICT-01**: Написать SQL-джоб поиска векторных совпадений с
    > противоположным смыслом.

13. **CANON-01**: Реализовать конечный автомат Candidate -\> Canonical
    > -\> Superseded.

14. **CANON-02**: Реализовать DDL для маппинга ImplementationLink и
    > ADRReference.

15. **UI-01**: Разработать дашборд Inbox (список неклассифицированных
    > файлов).

16. **UI-02**: Разработать компонент Side-by-side сравнения
    > дубликатов/конфликтов.

17. **UI-03**: Разработать визуализацию графа решений и реализации
    > (Coverage Map).

18. **MIGR-01**: Настроить Phase 1 Seed (подготовка 5 ключевых
    > документов MVP).

19. **TEST-01**: Написать E2E тест на сценарий Duplicate Upload.

20. **TEST-02**: Написать E2E тест на изоляцию Poisoned PDF внутри
    > MicroVM.

22\_SEVEN\_DAY\_BUILD\_PLAN
---------------------------

Основываясь на философии \"работать с частичным корпусом с первого
дня\", план первых 7 дней направлен исключительно на MVP:

  **День**     **Фокус**                **Ожидаемый результат**
  ------------ ------------------------ ------------------------------------------------------------------------------------------------
  **День 1**   Хранилище и Схемы        Поднят Postgres + pgvector + MinIO. Выполнены DDL миграции базовых схем.
  **День 2**   Базовый Коннектор        Скрипт сканирует папку, вычисляет SHA-256, пишет блоб в MinIO и метаданные в Postgres.
  **День 3**   Извлечение Утверждений   LLM API преобразует текст 00\_MASTER.md в структурированные Claim объекты.
  **День 4**   Векторизация и Поиск     Воркер генерирует эмбеддинги для Claim. FTS и HNSW поиск функциональны.
  **День 5**   Логика Конфликтов        SQL-скрипт выявляет противоречия между двумя тестовыми отчетами и создает ContradictionRecord.
  **День 6**   Интерфейс Оператора      Запущен локальный веб-дашборд с таблицей Claim и кнопками Approve/Reject.
  **День 7**   Вертикальный Срез        Прогон полного цикла MVP. Сырые файлы неизменны, решения принимаются явно в UI.

23\_30\_60\_90\_ROADMAP
-----------------------

-   **30 Дней (Стабилизация Ядра)**: Завершение интеграции
    Git-коннектора для связи исходного кода с архитектурными решениями.
    Обогащение графа реализаций (ImplementationLink), связывающего
    канонические решения с тикетами в бэклоге. Жесткое внедрение MicroVM
    для безопасности парсинга всех форматов, отличных от plain text.

-   **60 Дней (Управление Исследованиями)**: Внедрение сущностей
    ResearchRun и ContextManifest. Автоматический захват результатов
    Deep Research, криптографический аудит источников, автоматическое
    выявление расхождений с текущим архитектурным каноном. Интеграция
    трассировки (Langfuse).

-   **90 Дней (Масштабирование и Интеграция LifeOS)**: Запуск Historical
    Migration (Phase 4) для фоновой обработки старых экспортов Telegram.
    Интеграция с LifeOS Memory в режиме строгого чтения.

> Фрагмент кода
>
> graph TD\
> subgraph Knowledge Foundry (Canonical Truth)\
> A\[Canonical Decision\] \--\> B\[Implementation Schema\]\
> end\
> \
> subgraph LifeOS Integration (Day 90)\
> C\[Agent Planning Logic\] \--\>\|1. Query Canon\| A\
> C \--\>\|2. Generate Intent\| D\[Action Intent\]\
> D \--\>\|3. Policy Check\| E\[ContinuityOS\]\
> E \--\>\|Approve\| F\[Execution\]\
> end

24\_FINAL\_VERDICT
------------------

**NARROW AND BUILD.** Архитектура готова к сборке, однако масштаб
первоначальной реализации должен быть жестко сужен до минимального
вертикального среза (MVP). Попытка внедрить сложные графовые базы данных
(такие как Neo4j) или распределенные полиглот-архитектуры (Postgres +
Qdrant) на старте приведет к неоправданным операционным издержкам для
одного разработчика и проблемам с согласованностью данных^1^. Комбинация
PostgreSQL (использующая pgvector и Recursive CTE)^4^, MinIO для
неизменяемых блобов и модели доказательств на базе FEVER^18^ полностью
удовлетворяет жестким требованиям к устойчивой к хаосу системе.
Архитектура фундаментально запрещает неявные мутации знания и
гарантирует, что владелец сможет восстановить точный контекст и
происхождение любого архитектурного решения.

25\_FIRST\_CONCRETE\_ACTION
---------------------------

**Развернуть базовую инфраструктуру транзакционной базы данных и
неизменяемого хранилища.**

Создать файл docker-compose.yml, включающий образ PostgreSQL с
предустановленным расширением pgvector (например,
pgvector/pgvector:pg16), инстанс MinIO для объектного хранилища S3 и
инициирующий SQL-скрипт для применения первых трех DDL-схем: Artifact,
ProvenanceRecord и Claim. Выполнить первый успешный INSERT в эти таблицы
для тестового файла-пустышки, подтвердив транзакционную связь между
криптографическим хешем файла, метаданными происхождения и извлеченным
атомарным утверждением.

#### Источники

1.  pgvector vs Qdrant: PostgreSQL Extension or Dedicated Vector
    > Database - Encore Cloud,
    > [[https://encore.dev/articles/pgvector-vs-qdrant]{.underline}](https://encore.dev/articles/pgvector-vs-qdrant)

2.  Metadata Management In Data Lakes - lakeFS,
    > [[https://lakefs.io/blog/metadata-management-data-lakes-challenges/]{.underline}](https://lakefs.io/blog/metadata-management-data-lakes-challenges/)

3.  Qdrant vs pgvector: Same Speed. The Bottleneck Isn\'t the Vector
    > DB - Medium,
    > [[https://medium.com/\@TheWake/qdrant-vs-pgvector-theyre-the-same-speed-5ac6b7361d9d]{.underline}](https://medium.com/@TheWake/qdrant-vs-pgvector-theyre-the-same-speed-5ac6b7361d9d)

4.  pgvector vs Qdrant: 5 key differences and how to choose - NetApp
    > Instaclustr,
    > [[https://www.instaclustr.com/education/vector-database/pgvector-vs-qdrant-5-key-differences-and-how-to-choose/]{.underline}](https://www.instaclustr.com/education/vector-database/pgvector-vs-qdrant-5-key-differences-and-how-to-choose/)

5.  Qdrant vs PgVector: Vector Databases Comparison - IngestIQ,
    > [[https://ingestiq.ai/resources/comparisons/qdrant-vs-pgvector]{.underline}](https://ingestiq.ai/resources/comparisons/qdrant-vs-pgvector)

6.  PostgreSQL vs SQLite: Dive into Two Very Different Databases - DEV
    > Community,
    > [[https://dev.to/lovestaco/postgresql-vs-sqlite-dive-into-two-very-different-databases-5a90]{.underline}](https://dev.to/lovestaco/postgresql-vs-sqlite-dive-into-two-very-different-databases-5a90)

7.  Full text search over Postgres: Elasticsearch vs. alternatives \|
    > Hacker News,
    > [[https://news.ycombinator.com/item?id=41173288]{.underline}](https://news.ycombinator.com/item?id=41173288)

8.  Postgresql full text search 8 times slower than sqlite fts search -
    > Stack Overflow,
    > [[https://stackoverflow.com/questions/66244830/postgresql-full-text-search-8-times-slower-than-sqlite-fts-search]{.underline}](https://stackoverflow.com/questions/66244830/postgresql-full-text-search-8-times-slower-than-sqlite-fts-search)

9.  Vector Databases Compared: pgvector vs Pinecone vs Qdrant vs
    > Weaviate - Kalvium Labs,
    > [[https://www.kalviumlabs.ai/blog/vector-databases-compared-pgvector-pinecone-qdrant-weaviate/]{.underline}](https://www.kalviumlabs.ai/blog/vector-databases-compared-pgvector-pinecone-qdrant-weaviate/)

10. lakeFS/design/accepted/metadata\_kv/index.md at master - GitHub,
    > [[https://github.com/treeverse/lakeFS/blob/master/design/accepted/metadata\_kv/index.md]{.underline}](https://github.com/treeverse/lakeFS/blob/master/design/accepted/metadata_kv/index.md)

11. Architecture - lakeFS Documentation,
    > [[https://docs.lakefs.io/understand/architecture/]{.underline}](https://docs.lakefs.io/understand/architecture/)

12. PROV-O,
    > [[https://cartool-ec.github.io/eGovERA\_BA\_RA/id-3d54d4b1/elements/id-6984879aa17f46b8b22ba57b2329337f.html]{.underline}](https://cartool-ec.github.io/eGovERA_BA_RA/id-3d54d4b1/elements/id-6984879aa17f46b8b22ba57b2329337f.html)

13. W3C Prov - Wikipedia,
    > [[https://en.wikipedia.org/wiki/W3C\_Prov]{.underline}](https://en.wikipedia.org/wiki/W3C_Prov)

14. (PDF) A semantic approach to mapping the Provenance Ontology to
    > Basic Formal Ontology,
    > [[https://www.researchgate.net/publication/389069473\_A\_semantic\_approach\_to\_mapping\_the\_Provenance\_Ontology\_to\_Basic\_Formal\_Ontology]{.underline}](https://www.researchgate.net/publication/389069473_A_semantic_approach_to_mapping_the_Provenance_Ontology_to_Basic_Formal_Ontology)

15. PROV-O: The PROV Ontology - W3C,
    > [[https://www.w3.org/TR/prov-o/]{.underline}](https://www.w3.org/TR/prov-o/)

16. PROV-DM: The PROV Data Model - W3C,
    > [[https://www.w3.org/TR/prov-dm/]{.underline}](https://www.w3.org/TR/prov-dm/)

17. The W3C PROV standard: data model for the provenance of information,
    > and enabler for trustworthy publication and exchange of open
    > data - Slideshare,
    > [[https://www.slideshare.net/slideshow/nii-provtalk/36864067]{.underline}](https://www.slideshare.net/slideshow/nii-provtalk/36864067)

18. FEVER Dataset - Fact Extraction and VERification,
    > [[https://fever.ai/dataset/fever.html]{.underline}](https://fever.ai/dataset/fever.html)

19. ClaimDB: A Fact Verification Benchmark over Large Structured Data -
    > arXiv,
    > [[https://arxiv.org/html/2601.14698v2]{.underline}](https://arxiv.org/html/2601.14698v2)

20. EX-FEVER: A Dataset for Multi-hop Explainable Fact Verification -
    > arXiv,
    > [[https://arxiv.org/html/2310.09754v3]{.underline}](https://arxiv.org/html/2310.09754v3)

21. Schema Playground: A tool for authoring, extending, and using
    > metadata schemas to improve FAIRness of biomedical data - PMC,
    > [[https://pmc.ncbi.nlm.nih.gov/articles/PMC9176648/]{.underline}](https://pmc.ncbi.nlm.nih.gov/articles/PMC9176648/)

22. PostgreSQL Recursive Query - Neon,
    > [[https://neon.com/postgresql/tutorial/recursive-query]{.underline}](https://neon.com/postgresql/tutorial/recursive-query)

23. PostgreSQL Recursive CTE,
    > [[https://www.pgtutorial.com/postgresql-tutorial/postgresql-recursive-cte/]{.underline}](https://www.pgtutorial.com/postgresql-tutorial/postgresql-recursive-cte/)

24. PostgreSQL - Recursive Query - GeeksforGeeks,
    > [[https://www.geeksforgeeks.org/postgresql/postgresql-recursive-query/]{.underline}](https://www.geeksforgeeks.org/postgresql/postgresql-recursive-query/)

25. Graph Algorithms in a Database: Recursive CTEs and Topological Sort
    > with Postgres,
    > [[https://www.fusionbox.com/blog/detail/graph-algorithms-in-a-database-recursive-ctes-and-topological-sort-with-postgres/620/]{.underline}](https://www.fusionbox.com/blog/detail/graph-algorithms-in-a-database-recursive-ctes-and-topological-sort-with-postgres/620/)

26. Using the PostgreSQL Recursive CTE -- Part One \| Yugabyte -
    > YugabyteDB,
    > [[https://www.yugabyte.com/blog/using-postgresql-recursive-cte-part-1-employee-hierarchy/]{.underline}](https://www.yugabyte.com/blog/using-postgresql-recursive-cte-part-1-employee-hierarchy/)

27. Fun with SQL: Recursive CTEs in Postgres - Citus Data,
    > [[https://www.citusdata.com/blog/2018/05/15/fun-with-sql-recursive-ctes/]{.underline}](https://www.citusdata.com/blog/2018/05/15/fun-with-sql-recursive-ctes/)

28. The Hidden Cost of Vector Database Pricing Models - Actian
    > Corporation,
    > [[https://www.actian.com/blog/databases/the-hidden-cost-of-vector-database-pricing-models/]{.underline}](https://www.actian.com/blog/databases/the-hidden-cost-of-vector-database-pricing-models/)

29. r/programming on Reddit: Postgres Full Text Search is better than,
    > [[https://www.reddit.com/r/programming/comments/12yhhcg/postgres\_full\_text\_search\_is\_better\_than/]{.underline}](https://www.reddit.com/r/programming/comments/12yhhcg/postgres_full_text_search_is_better_than/)

30. Docker Sandboxes: Containers vs MicroVMs - When to Use What? - Ajeet
    > Singh Raina,
    > [[https://www.ajeetraina.com/docker-sandboxes-containers-vs-microvms-when-to-use-what/]{.underline}](https://www.ajeetraina.com/docker-sandboxes-containers-vs-microvms-when-to-use-what/)

31. Docker Sandboxes,
    > [[https://docs.docker.com/ai/sandboxes/]{.underline}](https://docs.docker.com/ai/sandboxes/)

32. Docker Sandboxes and microVMs, explained - InfoWorld,
    > [[https://www.infoworld.com/article/4177309/docker-sandboxes-and-microvms-explained.html]{.underline}](https://www.infoworld.com/article/4177309/docker-sandboxes-and-microvms-explained.html)

33. Best microVM Sandboxes for AI Code Execution in 2026 \| Modal Blog,
    > [[https://modal.com/resources/best-microvm-sandboxes-ai-code-execution]{.underline}](https://modal.com/resources/best-microvm-sandboxes-ai-code-execution)

34. Why MicroVMs: The Architecture Behind Docker Sandboxes,
    > [[https://www.docker.com/blog/why-microvms-the-architecture-behind-docker-sandboxes/]{.underline}](https://www.docker.com/blog/why-microvms-the-architecture-behind-docker-sandboxes/)

35. How to Sandbox Claude Code: Docker, VMs & Container Security Guide
    > \| MintMCP Blog,
    > [[https://www.mintmcp.com/blog/sandbox-claude-code]{.underline}](https://www.mintmcp.com/blog/sandbox-claude-code)

36. Using Dremio, lakeFS & Python for Multimodal Data Management,
    > [[https://www.dremio.com/blog/using-dremio-lakefs-python-for-multimodal-data-management/]{.underline}](https://www.dremio.com/blog/using-dremio-lakefs-python-for-multimodal-data-management/)
