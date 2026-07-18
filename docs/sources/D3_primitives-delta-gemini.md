ИССЛЕДОВАТЕЛЬСКИЙ ОТЧЕТ: COMPETITIVE PRIMITIVES DELTA STUDY
===========================================================

01\_EVIDENCE\_AUDIT
-------------------

Анализ архитектурных паттернов и инженерных заявлений (claims)
конкурентных систем требует строгой верификации перед их адаптацией в
экосистему ContinuityOS, BitEvo и Money Forge. Приведенная ниже таблица
систематизирует результаты аудита, основанные на изучении исходного
кода, бенчмарков и архитектурной документации целевых проектов.

  **Claim**                                                                                           **Source system**        **Official evidence**                                                                                                            **Verified status**   **Correction**                                                                                                                                                     **Confidence**
  --------------------------------------------------------------------------------------------------- ------------------------ -------------------------------------------------------------------------------------------------------------------------------- --------------------- ------------------------------------------------------------------------------------------------------------------------------------------------------------------ ----------------
  Чекпоинты поддерживают иммутабельное ветвление и путешествие во времени.                            LangGraph                Используются функции get\_state\_history, update\_state и invoke для ветвления состояния без деструктивного отката^1^.           Verified              Мутация состояния создает *новый* чекпоинт; исторические ветки остаются неизменными (read-only).                                                                   1.00
  Долгоживущие саги требуют остановок при неисправимых ошибках с последующим ручным вмешательством.   Temporal                 Логируется ActivityTaskFailed, процесс приостанавливается с ROLLBACK\_PENDING\_FIX, откат выполняется по LIFO-компенсациям^3^.   Verified              Компенсации должны быть строго идемпотентными и регистрироваться *до* выполнения прямого вызова (forward call).                                                    0.95
  Агенты могут безопасно и автономно управлять всей собственной памятью.                              Letta (MemGPT)           Инструменты core\_memory\_replace и archival\_memory\_insert вызываются агентами самостоятельно^5^.                              Partially Verified    Автономное управление полезно, но требует жестких политик (policy validation gates) перед мутацией канонической правды, чтобы избежать закрепления галлюцинаций.   0.85
  Инструменты MCP нативно изолируют аутентификацию и предотвращают несанкционированный доступ.        Model Context Protocol   Сквозная передача токенов (token passthrough) явно запрещена спецификацией для предотвращения атак Confused Deputy^7^.           False Claim           MCP *не* изолирует аутентификацию нативно. Клиенты обязаны самостоятельно реализовывать Zero-Trust и ограничивать возможности.                                     1.00
  Высокопроизводительные брокеры обеспечивают субмиллисекундную задержку (p99) для трейдинга.         Kafka / NATS / Redis     NATS Core дает субмиллисекундный p99; у Kafka p99 резко падает на 94-м перцентиле из-за дискового ввода-вывода^9^.               Verified              Для детерминированного локального Order Admission следует полностью избегать внешних сетевых брокеров.                                                             0.98
  Однопоточная MPSC-архитектура достаточна для логики HFT и алгоритмической торговли.                 NautilusTrader           MPSC-каналы передают данные в строго однопоточное ядро стратегии, изолированное от асинхронного I/O^11^.                         Verified              Асинхронный ввод-вывод (tokio) обрабатывает транспорт, а ядро детерминированно исполняет события без блокировок.                                                   0.95

Представленные доказательства ясно показывают, что перенос механизмов
«как есть» недопустим. В частности, интеграция памяти Letta требует
введения жизненного цикла промотирования фактов, поскольку прямое
доверие выводам LLM ведет к постепенному отравлению контекста.
Аналогично, хотя LangGraph обеспечивает механизм ветвления, его
применение требует интеграции с внешними системами примирения
(reconciliation) побочных эффектов, поскольку повтор исполнения (replay)
не должен приводить к дублированию финансовых транзакций^1^.

02\_PRIMITIVE\_ADOPTION\_MATRIX
-------------------------------

Стратегия адаптации пяти целевых примитивов распределена по плоскостям
исполнения (Planes), учитывая ограничения безопасности, требования к
задержкам и зрелость существующих решений.

  **Primitive**                **Adopt/Adapt/Reject**   **Plane**            **MVP status**          **Dependencies**                **Main risk**
  ---------------------------- ------------------------ -------------------- ----------------------- ------------------------------- ----------------------------------------------------------------------------------------
  **A. Immutable Branching**   ADAPT                    Control / Research   MVP                     DAG State Store, Audit Log      Неконтролируемое разрастание объема состояния (State bloat) при глубоком ветвлении.
  **B. Scoped Handoffs**       ADAPT                    Control / Forge      MVP                     Capability & Agent Registries   Атаки типа Confused Deputy, приводящие к эскалации привилегий.
  **C. Governed Memory**       ADAPT                    Control / Research   Reduced MVP             Policy & Approval Services      Инъекция отравленных данных (Poisoned memory) в канонический контекст.
  **D. Tiered Sandbox**        ADAPT                    Research / Forge     MVP (Только WASM/OCI)   Containerd / WASI runtime       Утечка метаданных хоста (Host metadata escape) из облачного окружения.
  **E. Hot-Path Transport**    DEFER                    Trading              Post-MVP                CPU Pinning, NUMA config        Ошибки конкурентного доступа (ABA, False sharing) при реализации lock-free алгоритмов.

Решение об адаптации (ADAPT) доминирует над прямым внедрением (ADOPT
DIRECTLY), так как готовые open-source примитивы не удовлетворяют
строгим требованиям ContinuityOS к консистентности и разделению
контроля^13^. Внедрение Ring Buffers (Primitive E) отложено (DEFER),
поскольку реализация сложного MPMC-транспорта до проведения строгих
бенчмарков прямого вызова (direct in-process call) нарушает принципы
разработки высокопроизводительных систем.

03\_ARCHITECTURE\_DELTA
-----------------------

Интеграция новых примитивов в существующую макроархитектуру (Multi-Agent
Operating Environment) требует точечной замены устаревших концепций и
внедрения новых, изолированных компонентов. Архитектурная дельта
концентрируется на модификации узлов маршрутизации, памяти и исполнения.
Представленные изменения охватывают ContinuityOS, BitEvo, Trading Cell,
Frontier Research Lab и Money Forge, не переписывая их базовые паттерны.

В первую очередь, глобальная мутабельная база данных состояния
заменяется на систему Branching & Reconciliation Engine. Данный
компонент реализует иммутабельное ветвление на основе DAG (Directed
Acyclic Graph), подобно подходу LangGraph, где каждое изменение
состояния порождает новый checkpoint\_id, сохраняя исторические данные в
режиме read-only^2^. Критическим дополнением к этому узлу является
ExternalReconciliationController. Его задача --- блокировать
автоматическое воспроизведение (replay) любых внешних побочных эффектов
(external side effects), таких как биржевые ордера в Trading Cell или
платежи в Money Forge. При обнаружении такого эффекта в исторической
ветке контроллер переводит процесс в статус HOLD, требуя идемпотентной
проверки или явного разрешения (policy decision / human approval).

Для устранения уязвимостей, связанных с эскалацией привилегий при
меж-агентском взаимодействии, внедряется Capability-Scoped Handoff
Router. Ранее агенты могли неявно передавать контекст или наследовать
авторизацию. Новый роутер внедряет модель Zero-Trust. Вместо полного
дампа истории чатов передается минималистичный HandoffEnvelope,
содержащий хеши и указатели на артефакты (artifact-pointers) и
ограничивающий бюджет контекста (context budget). Целевой агент (target
agent) обязан самостоятельно запрашивать доступ к артефактам в
Capability Registry, подтверждая свои права. Данный подход нивелирует
риски, описанные в спецификациях безопасности MCP, в частности проблемы
Confused Deputy и Token Passthrough^7^.

Подсистема памяти трансформируется в Governed Memory Service.
Вдохновляясь принципами Letta (MemGPT) по разделению контекста,
архитектура разделяется на Pinned Core Context (жестко лимитированный
объем, содержащий цели и критические правила), Working Memory (временный
Scratchpad, очищаемый по таймауту) и Archival Memory для долговременного
хранения^5^. Однако, в отличие от Letta, агенты не имеют права
самостоятельно делать свои спекуляции каноническими. Введен жизненный
цикл промотирования (Promotion Lifecycle), при котором любая запись от
агента получает статус PROPOSED и должна пройти через Validation Result
или Approval Service перед переходом в ACTIVE.

Для безопасного исполнения сгенерированного кода в Frontier Research Lab
и прототипирования в Money Forge разворачивается Tiered Sandbox
Dispatcher. Ввиду ограничений хост-инфраструктуры (наличие Windows/WSL,
отсутствие bare-metal KVM на некоторых узлах), использование MicroVM
(Firecracker) больше не является обязательным и единственным решением.
Диспетчер классифицирует нагрузку на уровни: Tier 0 (без исполнения),
Tier 1 (WASM), Tier 2 (Rootless OCI / gVisor) и Tier 3 (MicroVM).
Успешное выполнение кода в песочнице не делает артефакт доверенным; он
проходит проверку конвейера (Artifact Promotion), прежде чем получить
цифровую подпись.

Наконец, для Trading Cell определяется заглушка Local Transport
Admission Controller. В рамках MVP он использует in-process immutable
state reads и прямые вызовы функций (direct function calls), отвергая
немедленное внедрение сложных lock-free очередей или сетевых брокеров
вроде Redis и NATS на самом горячем пути. Механизм подготавливает
интерфейс для будущего внедрения SPSC ring buffers, но только после
прохождения строгих бенчмарков.

04\_STATE\_AND\_SEQUENCE\_DIAGRAMS
----------------------------------

Приведенные ниже диаграммы отражают измененное поведение системы,
фокусируясь исключительно на новых примитивах.

### 1. Workflow Fork and Replay

Этот процесс демонстрирует, как ветвление сохраняет оригинальную историю
неизменной, создавая новую ветку для альтернативного исполнения.

> Фрагмент кода
>
> sequenceDiagram\
> participant Client\
> participant BranchingEngine\
> participant Storage\
> participant WorkflowExecutor\
> \
> Client-\>\>BranchingEngine: ForkFromCheckpoint(chk\_0x4A,
> new\_state\_vars)\
> BranchingEngine-\>\>Storage: GetCheckpoint(chk\_0x4A)\
> Storage\--\>\>BranchingEngine: Immutable State Snapshot\
> BranchingEngine-\>\>BranchingEngine: Create new branch\_id, clone
> state\
> BranchingEngine-\>\>Storage: CreateCheckpoint(chk\_0x4B) (parent:
> chk\_0x4A)\
> BranchingEngine-\>\>WorkflowExecutor:
> ExecuteAlternativePath(chk\_0x4B)\
> WorkflowExecutor-\>\>Storage: Append sequential incremental
> checkpoints

### 2. External Side-Effect Reconciliation

Демонстрирует автомат состояний для защиты от случайного дублирования
финансовых или мутирующих операций при путешествии во времени (Time
Travel).

> Фрагмент кода
>
> stateDiagram-v2\
> \[\*\] \--\> PRE\_EXECUTION\
> PRE\_EXECUTION \--\> REVERSIBLE : Evaluate Idempotency Key\
> PRE\_EXECUTION \--\> COMPENSATABLE : Has Defined Compensation\
> PRE\_EXECUTION \--\> IRREVERSIBLE : External System Mutation\
> \
> IRREVERSIBLE \--\> HOLD : Replay Attempt Detected\
> HOLD \--\> APPROVAL\_REQUIRED : Query Policy Engine\
> APPROVAL\_REQUIRED \--\> EXECUTED : Operator / Policy Approved\
> APPROVAL\_REQUIRED \--\> ABANDONED : Denied / Timeout\
> \
> COMPENSATABLE \--\> COMPENSATION\_EXECUTION : Rollback Requested\
> COMPENSATION\_EXECUTION \--\> RECONCILED : Compensation Success\
> COMPENSATION\_EXECUTION \--\> HOLD : Compensation Failed

### 3. Capability-Scoped Handoff

Передача задачи между агентами. Основной упор сделан на передачу
указателей (artifact pointers), а не самих данных, требуя от принимающей
стороны подтверждения привилегий.

> Фрагмент кода
>
> sequenceDiagram\
> participant SourceAgent\
> participant HandoffGateway\
> participant AuthZRegistry\
> participant TargetAgent\
> \
> SourceAgent-\>\>HandoffGateway: Submit HandoffEnvelope (pointers,
> context\_budget)\
> HandoffGateway-\>\>AuthZRegistry: Check Target Role vs
> requested\_capabilities\
> AuthZRegistry\--\>\>HandoffGateway: Policy Approved\
> HandoffGateway-\>\>TargetAgent: Deliver HandoffEnvelope\
> TargetAgent-\>\>AuthZRegistry: Request underlying Artifacts via IDs\
> AuthZRegistry\--\>\>TargetAgent: Return Artifact Data (Scoped)\
> TargetAgent-\>\>HandoffGateway: ACCEPTED / NEEDS\_MORE\_EVIDENCE\
> TargetAgent-\>\>HandoffGateway: COMPLETED

### 4. Governed Memory Promotion

Жизненный цикл памяти агента. Агент не может самостоятельно сделать факт
каноническим (ACTIVE). Все гипотезы проходят валидацию.

> Фрагмент кода
>
> stateDiagram-v2\
> \[\*\] \--\> PROPOSED : Agent Writes Speculation\
> PROPOSED \--\> VALIDATED : Hash & Semantic Conflict Check\
> VALIDATED \--\> APPROVED : Human or Policy Gate Pass\
> APPROVED \--\> ACTIVE : Injected to Pinned/Archival Memory\
> ACTIVE \--\> SUPERSEDED : Newer Fact Validated & Approved\
> ACTIVE \--\> ARCHIVED : Task TTL Expired / Context Rotation

### 5. Risk-Tiered Sandbox Lifecycle

Конвейер выполнения недоверенного кода, гарантирующий, что успешное
выполнение не приравнивается к безопасному или готовому к продакшену
артефакту.

> Фрагмент кода
>
> stateDiagram-v2\
> \[\*\] \--\> TIER\_CLASSIFICATION\
> TIER\_CLASSIFICATION \--\> TIER\_1\_WASM : Deterministic / No Network\
> TIER\_CLASSIFICATION \--\> TIER\_2\_OCI : Build / Reproducible Test\
> TIER\_CLASSIFICATION \--\> TIER\_3\_MICROVM : Untrusted Interpreter\
> \
> TIER\_3\_MICROVM \--\> EXECUTED : Exit Code 0\
> EXECUTED \--\> SECURITY\_SCAN : Static/Dynamic Analysis\
> SECURITY\_SCAN \--\> PROVENANCE\_RECORDED : Passed All Checks\
> PROVENANCE\_RECORDED \--\> SIGNED : Cryptographic Signature\
> SIGNED \--\> APPROVED\_FOR\_TARGET

### 6. Local Trading Hot Path

Топология для низколатентного транспорта внутри Trading Cell. Обратите
внимание на использование прямых вызовов там, где это возможно, и
кольцевых буферов SPSC для развязки I/O.

> Фрагмент кода
>
> graph TD\
> A\[Market Data Provider\] \--\>\|SPSC Queue\| B\[Producer Ring
> Buffer\]\
> B \--\>\|Publish with Release Semantics\| C{Atomic Sequential State}\
> C \--\>\|Read with Acquire Semantics\| D\[Single-Threaded Strategy
> Kernel\]\
> D \--\>\|Direct In-Process Call\| E\[Order Admission Service\]\
> E \--\>\|SPSC Queue\| F\[Execution Network IO\]

### 7. Kill-Switch Atomic State and Notification

Механизм, гарантирующий, что остановка системы (Kill-Switch) не зависит
исключительно от доставки сообщений через очередь. Применяется атомарное
чтение состояния.

> Фрагмент кода
>
> sequenceDiagram\
> participant RiskService\
> participant AtomicMemory\
> participant OrderAdmission\
> participant AsyncRingBuffer\
> \
> RiskService-\>\>AtomicMemory: CAS(status: ACTIVE -\> HALTED)\
> RiskService-\>\>AsyncRingBuffer: Enqueue(KILL\_EVENT, sequence)\
> OrderAdmission-\>\>AtomicMemory: LoadAcquire() check before admission\
> OrderAdmission\--\>\>OrderAdmission: Block new orders (Reads HALTED)\
> AsyncRingBuffer-\>\>OrderAdmission: Process KILL\_EVENT async (Audit)

05\_DATA\_CONTRACTS
-------------------

Следующие контракты определяют структуру данных для реализации пяти
примитивов. Использование float64 в финансовых полях строго исключено во
избежание потери точности.

### WorkflowCheckpoint & WorkflowBranch (Primitive A)

Данные структуры обеспечивают иммутабельность исторического графа.
Использование криптографических хешей для конфигураций и артефактов
гарантирует, что любая попытка модификации прошлой ветки будет
немедленно обнаружена^2^.

> JSON
>
> {\
> \"WorkflowCheckpoint\": {\
> \"checkpoint\_id\": \"uuid\",\
> \"branch\_id\": \"uuid\",\
> \"workflow\_id\": \"uuid\",\
> \"parent\_checkpoint\_id\": \"uuid\",\
> \"state\_hash\": \"sha256\",\
> \"event\_history\_cursor\": \"string\",\
> \"input\_artifact\_hashes\": \[\"sha256\"\],\
> \"versions\": {\
> \"policy\_version\": \"v2.1\",\
> \"schema\_version\": \"v1.4\",\
> \"code\_version\": \"git-sha\",\
> \"model\_binding\": \"grok-4.5\",\
> \"prompt\_version\": \"v3\"\
> },\
> \"metadata\": {\
> \"creator\": \"system\|user\",\
> \"reason\": \"string\",\
> \"creation\_timestamp\": \"iso8601\"\
> }\
> }\
> }

### ExternalEffectRecord & CompensationPlan (Primitive A)

При путешествии во времени (replay) система сверяется с этим контрактом
для определения необходимости компенсации или запроса ручного
подтверждения^4^. Поле reversibility\_class критично для автоматизации
отката.

> JSON
>
> {\
> \"ExternalEffectRecord\": {\
> \"effect\_id\": \"uuid\",\
> \"action\_spec\_id\": \"uuid\",\
> \"idempotency\_key\": \"string\",\
> \"external\_system\": \"string\",\
> \"execution\_status\": \"PENDING\|CONFIRMED\|FAILED\",\
> \"external\_confirmation\": \"string\",\
> \"reversibility\_class\":
> \"REVERSIBLE\|COMPENSATABLE\|IRREVERSIBLE\|UNKNOWN\",\
> \"compensation\_action\": \"string\",\
> \"compensation\_status\": \"PENDING\|EXECUTED\|FAILED\",\
> \"CompensationPlan\": {\
> \"action\_type\": \"CANCEL\_ORDER\|REFUND\|WEBHOOK\_REVERSE\",\
> \"parameters\": {},\
> \"deadline\": \"iso8601\"\
> }\
> }\
> }

### HandoffEnvelope & HandoffResponse (Primitive B)

Контракт HandoffEnvelope реализует концепцию передачи указателей, а не
сырых данных. Поля requested\_capabilities и forbidden\_capabilities
используются для применения политик Zero-Trust при маршрутизации задачи
к целевому агенту^8^.

> JSON
>
> {\
> \"HandoffEnvelope\": {\
> \"schema\_version\": \"v1.0\",\
> \"handoff\_id\": \"uuid\",\
> \"event\_id\": \"uuid\",\
> \"correlation\_id\": \"uuid\",\
> \"causation\_id\": \"uuid\",\
> \"trace\_id\": \"uuid\",\
> \"workflow\_id\": \"uuid\",\
> \"branch\_id\": \"uuid\",\
> \"task\_id\": \"uuid\",\
> \"source\_agent\_id\": \"uuid\",\
> \"source\_role\": \"string\",\
> \"target\_role\": \"string\",\
> \"requested\_capabilities\": \[\"string\"\],\
> \"forbidden\_capabilities\": \[\"string\"\],\
> \"objective\": \"string\",\
> \"acceptance\_criteria\": \[\"string\"\],\
> \"artifact\_references\": \[\"artifact\_id\_hash\"\],\
> \"evidence\_references\": \[\"evidence\_id\_hash\"\],\
> \"relevant\_decision\_references\": \[\"decision\_id\_hash\"\],\
> \"context\_budget\": 8192,\
> \"data\_class\": \"PUBLIC\|INTERNAL\|CONFIDENTIAL\",\
> \"priority\": 1,\
> \"risk\_class\": \"LOW\|MEDIUM\|HIGH\|CRITICAL\",\
> \"expires\_at\": \"iso8601\",\
> \"idempotency\_key\": \"string\",\
> \"payload\_hash\": \"sha256\",\
> \"workflow\_signature\": \"ed25519\_signature\",\
> \"policy\_decision\_id\": \"uuid\"\
> }\
> }

### MemoryMutationProposal & MemoryPromotionDecision (Primitive C)

Описывает процесс, при котором агент предлагает факт для запоминания.
Поле validation\_state изначально установлено в PROPOSED, не позволяя
факту загрязнить канонический контекст без одобрения (Policy или Human).

> JSON
>
> {\
> \"MemoryMutationProposal\": {\
> \"memory\_id\": \"uuid\",\
> \"project\_id\": \"uuid\",\
> \"scope\": \"GLOBAL\|PROJECT\|TASK\",\
> \"data\_class\": \"string\",\
> \"source\": \"AGENT\_INFERENCE\|USER\_INPUT\",\
> \"provenance\": \"trace\_id\",\
> \"creator\": \"agent\_id\",\
> \"confidence\": 0.85,\
> \"validation\_state\":
> \"PROPOSED\|VALIDATED\|APPROVED\|ACTIVE\|SUPERSEDED\|ARCHIVED\",\
> \"content\_hash\": \"sha256\",\
> \"created\_at\": \"iso8601\",\
> \"expires\_at\": \"iso8601\",\
> \"supersedes\": \"previous\_memory\_id\",\
> \"policy\_version\": \"string\",\
> \"access\_control\": \[\"role:analyst\"\]\
> },\
> \"MemoryPromotionDecision\": {\
> \"decision\_id\": \"uuid\",\
> \"memory\_id\": \"uuid\",\
> \"status\": \"APPROVED\|REJECTED\",\
> \"approver\": \"system\|user\",\
> \"reason\": \"string\"\
> }\
> }

### SandboxExecutionSpec & SandboxExecutionResult (Primitive D)

Спецификация песочницы жестко определяет лимиты и запреты (например,
отсутствие сетевого доступа). Это предотвращает атаки типа Fork Bomb и
утечки через метаданные облачных инстансов.

> JSON
>
> {\
> \"SandboxExecutionSpec\": {\
> \"execution\_id\": \"uuid\",\
> \"artifact\_id\": \"uuid\",\
> \"source\_hash\": \"sha256\",\
> \"sandbox\_tier\": 1,\
> \"image\_digest\": \"sha256\",\
> \"kernel\_version\": \"string\",\
> \"rootfs\_digest\": \"sha256\",\
> \"limits\": {\
> \"cpu\": 1.0,\
> \"memory\_mb\": 512,\
> \"disk\_mb\": 100,\
> \"process\_max\": 32,\
> \"timeout\_ms\": 3000\
> },\
> \"filesystem\_mounts\": \[{\"src\": \"path\", \"dst\": \"path\",
> \"ro\": true}\],\
> \"read\_only\_inputs\": \[\"path1\"\],\
> \"writable\_output\_path\": \"path2\",\
> \"network\_policy\": \"DENY\_ALL\",\
> \"egress\_allowlist\": \[\],\
> \"dns\_policy\": \"NONE\",\
> \"secret\_references\": \[\],\
> \"allowed\_syscalls\": \[\"read\", \"write\", \"exit\"\],\
> \"environment\_variables\": {\"KEY\": \"VALUE\"},\
> \"expected\_outputs\": \[\"file.json\"\],\
> \"output\_size\_limit\_mb\": 10,\
> \"cleanup\_policy\": \"CRYPTOGRAPHIC\_ERASURE\",\
> \"evidence\_requirements\": \[\"syslog\", \"strace\"\]\
> }\
> }

### HotPathEvent & KillSwitchState (Primitive E)

Данные структуры используют Protobuf для минимизации задержек
десериализации^17^. Крайне важно, что финансовые значения передаются как
int64 (фиксированная точка), исключая непредсказуемое округление чисел с
плавающей запятой, неприемлемое для торговых ядер^11^.

> Protocol Buffers
>
> syntax = \"proto3\";\
> \
> message KillSwitchState {\
> // Атомарное чтение (LoadAcquire) для синхронизации\
> uint32 status = 1; // 0 = ACTIVE, 1 = HALTED\
> uint64 last\_update\_ts = 2;\
> string reason\_code = 3;\
> }\
> \
> message HotPathEvent {\
> uint64 sequence = 1;\
> uint64 timestamp = 2;\
> int32 event\_class = 3; // 1 = MARKET\_DATA, 2 = SIGNAL, 3 =
> ORDER\_INTENT\
> // Строго запрещено использование float64\
> int64 fixed\_price = 4; // Normalized tick size\
> int64 fixed\_qty = 5; // Normalized quantity step\
> string idempotency\_key = 6;\
> }

06\_API\_CONTRACTS
------------------

Определения API используют архитектуру gRPC для высокопроизводительного
Control Plane (внутри кластера) и REST для интеграции с внешними
системами. Все контракты строго следуют правилам версионирования и
контроля идемпотентности.

### Общие принципы API

-   **Idempotency Behavior:** Все мутирующие операции (создание веток,
    передача артефактов) требуют поля idempotency\_key. Сервисы кэшируют
    ключи идемпотентности на уровне Redis (или in-memory для локальных
    тестов) на 24 часа. При дублировании ключа возвращается сохраненный
    ответ без повторного выполнения бизнес-логики.

-   **Authorization:** Использование Bearer-токенов. Поле
    continuity\_os\_signature используется только для верификации
    целостности событий (event signature), но не заменяет AuthZ.
    Политики Zero-Trust требуют явного указания Capabilities в
    токене^8^.

-   **Versioning:** URI включает версию (например, /v1/handoffs).
    Изменения схемы, ломающие обратную совместимость, требуют перехода
    на v2.

-   **Timeout Behavior:** На уровне gRPC устанавливаются жесткие
    дедлайны (context.WithTimeout). Для Control Plane --- 2000 мс. Для
    взаимодействия с Sandbox --- ограничено значением timeout\_ms в
    спецификации. Для Trading Plane --- таймауты исключены в пользу
    неблокирующих прямых вызовов (non-blocking direct calls) или
    try\_send в каналы^11^.

-   **Error Model:** Стандартизированная модель ошибок Google RPC
    (например, FAILED\_PRECONDITION при несовпадении хешей,
    DEADLINE\_EXCEEDED при превышении лимита времени песочницы).

### WorkflowBranchingService (gRPC)

Обеспечивает управление графом состояний (DAG).

-   rpc ForkFromCheckpoint(ForkRequest) returns (WorkflowBranch)\
    Создает новую ветку. Если state\_hash в запросе не совпадает с
    реальным состоянием указанного fork\_checkpoint\_id, возвращает
    FAILED\_PRECONDITION.

-   rpc ReplayFromCheckpoint(ReplayRequest) returns (WorkflowBranch)\
    Запускает повторное выполнение.

-   rpc ReconcileExternalEffects(ReconcileRequest) returns
    (CompensationPlan)\
    Если при повторном воспроизведении обнаруживается сайд-эффект с
    классом IRREVERSIBLE, API возвращает ошибку ABORTED и переводит
    статус в HOLD.

### HandoffGateway (REST / gRPC)

Маршрутизирует задачи между агентами.

-   POST /v1/handoffs или rpc ProposeHandoff(HandoffEnvelope) returns
    (HandoffResponse)\
    Gateway проверяет requested\_capabilities целевого агента через
    Policy Store. Если целевой агент не обладает нужными правами,
    возвращается ошибка PERMISSION\_DENIED
    (REJECTED\_CAPABILITY\_MISMATCH).

### GovernedMemoryService (gRPC)

Управляет трехуровневой памятью агента^6^.

-   rpc ProposeMutation(MemoryMutationProposal) returns
    (MemoryPromotionDecision)\
    Агент предлагает факт. Состояние PROPOSED.

-   rpc RequestRetrieval(MemoryRetrievalRequest) returns
    (MemoryRetrievalResult)\
    Извлекает данные. Включает логику определения конфликтов
    (conflicting facts metadata) и карантина отравленной памяти
    (poisoned-memory detection). Отклоняет кросс-проектные запросы, если
    не предоставлены соответствующие токены.

### SandboxOrchestrator (gRPC)

-   rpc ExecuteSandboxed(SandboxExecutionSpec) returns
    (SandboxExecutionResult)\
    Оркестрирует развертывание WASM или OCI. Жесткий таймаут: при
    истечении срока отправляет SIGKILL процессу и возвращает
    DEADLINE\_EXCEEDED. Никакие остаточные процессы не сохраняются.

07\_SECURITY\_DELTA
-------------------

Пять примитивов формируют совершенно новую поверхность атаки (attack
surface). Ниже представлены специфичные угрозы и меры противодействия
(controls), в том числе адаптированные из последних спецификаций
безопасности Model Context Protocol (MCP)^7^.

1.  **Immutable Workflow Branching (Primitive A):**

    -   *Threat:* Вредоносная модификация метаданных ветки (например,
        подмена policy\_version или code\_version) при создании форка,
        чтобы заставить систему выполнить код по устаревшим, уязвимым
        правилам.

    -   *Control:* Криптографическое связывание. state\_hash включает
        хеши всех версий и конфигураций. Promotion ветки генерирует
        immutable audit event, предотвращая тихие откаты политик
        безопасности.

2.  **Capability-Scoped Handoffs (Primitive B):**

    -   *Threat:* Confused Deputy / Privilege Escalation. MCP-сервер или
        агент с низкими привилегиями передает зараженный запрос (Tool
        Poisoning) целевому агенту с высокими правами^7^.

    -   *Control:* Неявное наследование токенов (Token Passthrough)
        строго запрещено. Handoff передает только идентификаторы
        артефактов (artifact pointers), а не их содержимое по умолчанию.
        Целевой агент обязан получить собственный токен с
        соответствующей аудиенцией и областью видимости для чтения этих
        артефактов. Конфиденциальные артефакты не маршрутизируются
        несертифицированным провайдерам.

3.  **Governed Memory Paging (Primitive C):**

    -   *Threat:* Prompt Injection / Poisoned Memory. Вредоносные
        инструкции встраиваются в память агента через внешние документы,
        заставляя агента выполнять несанкционированные действия при
        последующем извлечении (Retrieval)^20^.

    -   *Control:* Агент не имеет права напрямую писать в каноническое
        состояние (ACTIVE). Любая запись помечается как PROPOSED.
        Реализуется карантин подозрительных паттернов. Authoritative
        state (финансовые балансы, лимиты рисков) не может быть изменено
        через сервис памяти.

4.  **Risk-Tiered Sandbox Execution (Primitive D):**

    -   *Threat:* Host Metadata Escape / SSRF. Выполнение недоверенного
        кода в контейнере приводит к сканированию локальной сети
        (например, 169.254.169.254) и извлечению AWS IAM токенов, а
        также к атакам типа fork-bomb^8^.

    -   *Control:* Уровневая изоляция. Для Tier 1 (WASM) и Tier 2 (OCI)
        применяется жесткая сетевая политика DENY\_ALL (egress deny).
        Блокируется проброс Docker socket. Применяются ограничения
        Cgroups (pids\_max, memory.limit\_in\_bytes). Для Tier 3
        (MicroVM) используется jailer с уникальными UID/GID, изоляция
        пространств имен сети и жесткий seccomp BPF-фильтр.

5.  **Benchmark-Gated Hot-Path Transport (Primitive E):**

    -   *Threat:* Denial of Service (DoS) через переполнение буфера на
        критическом пути или отравление кэш-линий (cache-line false
        sharing), что приведет к катастрофическому падению
        производительности Order Admission^11^.

    -   *Control:* Жесткое разделение политик переполнения (overflow
        policies). Для Market Data применяется drop oldest или
        коалесценция. Для Order Intents применяется fail closed / reject
        producer. Атомарное состояние Kill-Switch читается напрямую в
        обход очереди (direct memory read).

08\_BENCHMARK\_PLAN
-------------------

Для принятия обоснованных инженерных решений в отношении каждого из
примитивов разработан следующий план измерений (Benchmark Harnesses).
Измерения должны проводиться на изолированном окружении: Linux-ядро, CPU
C-states отключены, потоки привязаны к ядрам (thread pinning), учет
NUMA-топологии.

-   **Harness 1: Checkpoint Creation & Branch Replay (Primitive A)**

    -   *Methodology:* Измерение времени создания чекпоинта из состояния
        размером 10 MB (in-memory, SQLite WAL, PostgreSQL). Сбор метрик:
        p50, p95, p99.

    -   *Acceptance Target:* Создание in-memory форка \< 15 мс; SQLite
        (durable) \< 50 мс.

-   **Harness 2: Handoff Payload Size & Serialization (Primitive B)**

    -   *Methodology:* Сравнение сериализации полного дампа контекста
        (Full Conversation) против HandoffEnvelope (Artifact-pointer
        only).

    -   *Acceptance Target:* Размер полезной нагрузки Handoff \< 5 KB.
        Время парсинга JSON \< 1 мс.

-   **Harness 3: Sandbox Cold/Warm Start & Teardown (Primitive D)**

    -   *Methodology:* Замер задержки (latency) от API-вызова до первого
        выполненного CPU-цикла пользовательского кода внутри песочницы.
        Сравнение WASM, Rootless OCI и Firecracker.

    -   *Acceptance Target:* WASM (Warm) \< 5 мс; OCI (Cold start) \<
        300 мс; Firecracker (Cold start) \< 150 мс. Песочница
        гарантированно уничтожается при таймауте без утечек процессов.

-   **Harness 4: Local Trading Hot Path Transport (Primitive E)**

    -   *Methodology:* Fuzzing и стресс-тестирование MPMC/SPSC кольцевых
        буферов в сравнении с прямыми вызовами функций (Direct Function
        Call). Сбор метрик: CPU usage, cache misses (L1/L2 contention),
        context switches, consumer lag^11^.

    -   *Acceptance Target:* Для Direct Function Call ---
        субмикросекундная (sub-microsecond) задержка. Для SPSC queue ---
        \< 500 наносекунд на передачу события. Очереди, использующие
        runtime.Gosched(), должны быть проверены на джиттер (jitter).

-   **Harness 5: Kill-Switch Visibility (Primitive E)**

    -   *Methodology:* Измерение задержки между атомарной записью
        CAS(Halted) процессом RiskMonitor и моментом, когда процесс
        OrderAdmission замечает изменение через LoadAcquire.

    -   *Acceptance Target:* \< 50 наносекунд (время инвалидации
        кэш-линии на x86/ARM архитектурах).

0x08 --- REQUIRED CORRECTION OF THE PROVIDED GEMINI CODE
--------------------------------------------------------

**Аудит предложенной реализации Go Lock-Free Queue**

Предоставленный (гипотетический) концепт lock-free очереди для языка Go
содержит критические архитектурные и алгоритмические изъяны. Подобный
код характерен для наивных LLM-генераций, но абсолютно неприемлем для
детерминированного финансового ядра (Hot Path). Детальный анализ выявил
следующие проблемы:

1.  **Publication-before-write race:** Алгоритм инкрементирует видимый
    > индекс записи (например, через atomic.AddUint64) *до* фактического
    > копирования данных в слот. Это позволяет Consumer\'у увидеть
    > индекс как доступный и прочитать пустую или частично
    > перезаписанную структуру.

2.  **Unsafe MPMC Semantics & ABA Problem:** Отсутствует по-слотовое
    > состояние публикации (per-slot sequence state). MPMC очереди
    > требуют сложной реализации, гарантирующей, что Consumer читает ту
    > же \"эпоху\" слота, которую записал Producer.

3.  **Ambiguous Cache Padding (False Sharing):** Нет явного заполнения
    > кэш-линий (cache padding) между индексами Head и Tail (например,
    > \_ \[7\]uint64). Они попадут в одну L1 кэш-линию, вызывая
    > постоянную инвалидацию кэша (cache thrashing) между потоками.

4.  **\"float64\" Financial Fields:** Использование типа float64 для
    > представления цены и количества. IEEE 754 не обладает достаточной
    > точностью для финансовых систем. Данные значения обязаны
    > нормализоваться в типы с фиксированной запятой (int64 basis points
    > / ticks)^11^.

5.  **Scheduler-Yield Jitter:** Использование runtime.Gosched() или
    > наивного busy-spin без адаптивной стратегии (adaptive spin) в
    > цикле ожидания приводит к непредсказуемым микросекундным задержкам
    > со стороны планировщика Go.

**Decision (Решение):** ОТВЕРГНУТЬ предложенный кастомный код (REJECT).
Не пытаться чинить его косметическими правками.

**Resolution (Альтернатива):** Для архитектуры Trading Cell, подобно
дизайну NautilusTrader^11^, детерминированное однопоточное ядро
стратегии прекрасно работает на основе **Direct In-Process Calls**
(прямые вызовы функций в рамках одного потока для бизнес-логики) и
**Bounded SPSC Channels** (ограниченные каналы или проверенные SPSC
ring-buffers на входе/выходе для развязки сетевого I/O). Создание
кастомного MPMC кода без формальной модели памяти, fuzzing-тестов и
стресс-тестирования несет недопустимые риски.

09\_BUILD\_OR\_BUY\_MATRIX
--------------------------

Оценка реализации пяти примитивов через призму нативной разработки
(Build), покупки управляемого сервиса (Buy) или адаптации open-source
(Hybrid Adapter).

  **Component**                **Native Implementation (Build)**                       **Managed Service (Buy)**                                       **Open-Source Component**              **Hybrid Adapter (Decision)**
  ---------------------------- ------------------------------------------------------- --------------------------------------------------------------- -------------------------------------- ----------------------------------------------------------------------------------------------------------------------------------
  **Workflow Branching (A)**   Высокие затраты на поддержку, риск ошибок State DAG.    Temporal Cloud (Избыточные расходы для локального агента)^4^.   LangGraph / Temporal Core              **Hybrid:** Интеграция концепций LangGraph checkpointing над встроенным SQLite для ContinuityOS.
  **Scoped Handoffs (B)**      **Build:** Требуется кастомная обертка с явным AuthZ.   OpenAI Swarm (Устарело, примитивно).                            Semantic Kernel / LangChain            **Build:** Собственный HandoffGateway для изоляции Capabilities, запрещающий сквозную передачу токенов^8^.
  **Governed Memory (C)**      Слишком сложно реализовать RAG + AuthZ с нуля.          MemGPT Cloud (Нарушает принцип Zero-Cloud).                     Letta Open Source^5^.                  **Hybrid:** Адаптация логики Pinned/Archival Letta, но с жестким Policy Promotion гейтом над локальным SQLite.
  **Sandbox Execution (D)**    Экстремальный риск (побег из песочницы).                E2B / Daytona (Хорошо, но требует Cloud).                       gVisor / Firecracker / WASI            **Hybrid:** WASI (Tier 1) и Rootless OCI (Tier 2) локально. MicroVM (Tier 3) интеграция E2B/Firecracker только после бенчмарков.
  **Hot-Path Transport (E)**   Экстремальный риск (False sharing, ABA bugs).           N/A (Cloud-решения не подходят для Sub-ms)^9^.                  LMAX Disruptor / NautilusTrader^11^.   **OSS/Hybrid:** Использование проверенных паттернов SPSC; внутри ядра --- только прямые вызовы (Direct Calls).

10\_BACKLOG\_DELTA
------------------

Приведенные элементы бэклога фокусируются исключительно на интеграции
новых примитивов в архитектуру.

-   **Ticket:** ARC-101 --- Immutable Checkpoint Forking Engine

    -   *Component:* Workflow Runtime / ContinuityOS.

    -   *Rationale:* Для реализации Time Travel агенты должны
        возвращаться к предыдущим состояниям. Использование
        деструктивного отката (destructive rollback) запрещено.
        Необходим DAG чекпоинтов^1^.

    -   *Dependencies:* None.

    -   *Acceptance Criteria:* Вызов ForkFromCheckpoint сохраняет
        оригинальную историю неизменной (read-only); попытка изменения
        прошлых состояний возвращает ошибку.

    -   *Security Test:* Сбой валидации policy\_version блокирует
        создание новой ветки и Promotion.

    -   *Benchmark:* Время создания форка в RAM \< 15ms.

    -   *Recommended Executor:* Core Engine Team.

    -   *Verifier:* Lead Architect.

    -   *Evidence Artifact:* Test logs showing DAG immutability.

-   **Ticket:** ARC-102 --- External Side-Effect Reconciliation Gateway

    -   *Component:* Control Plane.

    -   *Rationale:* Replay не должен вслепую дублировать внешние
        действия (ордера, платежи). Требуется идемпотентный контроль и
        ручное подтверждение для необратимых действий^3^.

    -   *Dependencies:* ARC-101.

    -   *Acceptance Criteria:* При воспроизведении ветки сайд-эффект с
        классом IRREVERSIBLE перехватывается, а статус выполнения
        переходит в HOLD.

    -   *Security Test:* Неоднозначность внешнего примирения
        (reconciliation ambiguity) всегда приводит к статусу HOLD.

    -   *Benchmark:* N/A.

    -   *Recommended Executor:* Integration Team.

-   **Ticket:** SEC-201 --- Capability-Scoped Handoff Router

    -   *Component:* Agent Framework.

    -   *Rationale:* Передача задач между агентами не должна передавать
        полномочия неявно. Необходима реализация Zero-Trust для
        предотвращения Confused Deputy атак^8^.

    -   *Dependencies:* Capability Registry.

    -   *Acceptance Criteria:* Маршрутизатор принимает HandoffEnvelope
        только с идентификаторами артефактов; целевой агент запрашивает
        доступ независимо.

    -   *Security Test:* Истекший Handoff отклоняется; Handoff не может
        расширить права целевого агента (Token Passthrough blocked).

    -   *Recommended Executor:* Security Engineering.

-   **Ticket:** SEC-301 --- Tier 1 & 2 Execution Sandbox Dispatcher

    -   *Component:* Frontier Research Lab / Money Forge.

    -   *Rationale:* Не весь генерируемый код требует накладных расходов
        Firecracker MicroVM. Уровни WASM и Rootless OCI покроют 90% нужд
        для статического анализа и тестов.

    -   *Dependencies:* WASI runtime, Containerd.

    -   *Acceptance Criteria:* Диспетчер анализирует профиль риска и
        направляет код в соответствующий уровень (Tier 1 или Tier 2).
        Успешный запуск не означает Promotion артефакта.

    -   *Security Test:* Политика egress deny работает исправно; атаки
        fork bomb и исчерпание диска (disk exhaustion) изолируются.

    -   *Benchmark:* WASM (warm start) \< 5ms.

-   **Ticket:** TRD-401 --- Trading Plane: Benchmark Direct Call vs SPSC

    -   *Component:* Trading Cell / Hot-Path Transport.

    -   *Rationale:* Необходимо избежать преждевременной оптимизации с
        использованием кастомных MPMC lock-free очередей до проведения
        замеров^11^.

    -   *Dependencies:* None.

    -   *Acceptance Criteria:* Создан тестовый harness; собраны метрики
        (p50, p95, p99.9) для прямых вызовов (direct calls) и SPSC
        очередей под нагрузкой.

    -   *Security Test:* Race detector не выдает предупреждений.

    -   *Benchmark:* См. раздел 08 (Harness 4).

11\_MVP DECISION
----------------

Анализ базовой гипотезы и принятие решений о включении примитивов в
первую версию MVP:

-   **Workflow branching (Primitive A): MVP.** Подтверждено.
    Неизменяемые (immutable) чекпоинты критически важны для безопасной
    работы автономных агентов и предоставления операторам возможности
    отладки (Time Travel) без разрушения аудиторского следа. Адаптация
    концепций LangGraph и Temporal является приоритетной^4^.

-   **Artifact handoffs (Primitive B): MVP.** Подтверждено. Ввиду
    высоких рисков эскалации привилегий в multi-agent системах,
    внедрение HandoffEnvelope и запрет неявного делегирования полномочий
    (Token Passthrough) необходимы с первого дня запуска для Money Forge
    и Control Plane^8^.

-   **Governed memory paging (Primitive C): Reduced MVP version.**
    Подтверждено. Реализация полномасштабной семантической векторной
    базы данных для Archival Memory может быть отложена. MVP должен
    сфокусироваться на жестком разделении Pinned Core Context и Working
    Memory, а также на внедрении процесса PROPOSED -\> VALIDATED для
    предотвращения закрепления галлюцинаций в authoritative state^5^.

-   **Sandbox adapter (Primitive D): MVP, but provider chosen after
    feasibility test.**\
    Подтверждено. Песочницы необходимы для безопасного прототипирования.
    В MVP следует внедрить WASM (Tier 1) для детерминированных
    трансформаций и Rootless OCI контейнеры (Tier 2). Firecracker
    (Tier 3) будет внедрен только после оценки инфраструктурных
    ограничений (отсутствие nested virtualization).

-   **Lock-free hot-path transport (Primitive E): Defer until trading
    benchmark.** Подтверждено. Внедрение кастомных ring buffers несет
    катастрофические риски (ABA, False Sharing). Ядро алгоритмической
    торговли должно использовать детерминированные In-process immutable
    state reads и Direct function calls^11^. Использование NATS или
    Kafka допускается только для телеметрии и аудита вне горячего пути
    (off-hot-path)^9^. Внедрение SPSC очередей откладывается до
    получения результатов бенчмарков (Ticket TRD-401).

12\_FINAL VERDICT
-----------------

-   **Primitive A (Immutable Workflow Branching): GO.** Начать
    реализацию Branching & Reconciliation Engine с поддержкой DAG,
    гарантируя блокировку дублирования внешних сайд-эффектов через
    систему статусов HOLD.

-   **Primitive B (Capability-Scoped Handoffs): GO.** Внедрить
    HandoffGateway как стандарт меж-агентской коммуникации, базирующийся
    на указателях (artifact pointers) и явном Zero-Trust подтверждении
    прав.

-   **Primitive C (Governed Memory Paging): NARROW.** Ограничить MVP
    реализацией жестко лимитированного Pinned Core и очищаемого Working
    Memory. Ограничить права агентов на автоматическое промотирование
    фактов в ACTIVE.

-   **Primitive D (Risk-Tiered Sandbox Execution): NARROW.** Внедрить
    только Tier 1 (WASM/WASI) и Tier 2 (Rootless OCI). Tier 3+ (MicroVM)
    требует отдельного архитектурного спайка и оценки хост-окружения.

-   **Primitive E (Benchmark-Gated Hot-Path Transport): HOLD / STOP.**
    Остановить разработку lock-free кольцевых буферов. Строго запретить
    использование float64 в финансовых структурах.

**Implementation Spike (Falsification Test):**

Создать минимально жизнеспособный тестовый стенд (Spike) для сравнения
Direct Call Engine (прямые вызовы в однопоточном ядре) против Go Channel
/ Bounded SPSC и против гипотетической Unsafe Lock-Free Queue. Измерить
p99 и p99.9 latency на генерации и обработке 1 000 000 событий ордеров
(order intents).

*Если Direct In-Process Call демонстрирует задержку менее 500 наносекунд
и нулевую аллокацию мусора (zero-allocation), гипотеза о необходимости
сложного Lock-Free Ring Buffer окончательно отвергается, и архитектура
жестко фиксируется на детерминированном, синхронном ядре обработки
событий для Trading Cell.*

*This is for informational purposes only. For medical advice or
diagnosis, consult a professional.*

#### Источники

1.  Use time-travel - Docs by LangChain,
    > [[https://docs.langchain.com/oss/python/langgraph/use-time-travel]{.underline}](https://docs.langchain.com/oss/python/langgraph/use-time-travel)

2.  Time Travel in Agentic AI - Towards AI,
    > [[https://pub.towardsai.net/time-travel-in-agentic-ai-3063c20e5fe2]{.underline}](https://pub.towardsai.net/time-travel-in-agentic-ai-3063c20e5fe2)

3.  Events and Event History \| Temporal Platform Documentation,
    > [[https://docs.temporal.io/workflow-execution/event]{.underline}](https://docs.temporal.io/workflow-execution/event)

4.  Recover Failed Workflow Steps Without Restarting - Temporal,
    > [[https://temporal.io/blog/keep-business-processes-moving]{.underline}](https://temporal.io/blog/keep-business-processes-moving)

5.  Memory blocks (core memory) \| Letta Docs,
    > [[https://docs.letta.com/guides/core-concepts/memory/memory-blocks]{.underline}](https://docs.letta.com/guides/core-concepts/memory/memory-blocks)

6.  Archival memory \| Letta Docs,
    > [[https://docs.letta.com/guides/core-concepts/memory/archival-memory]{.underline}](https://docs.letta.com/guides/core-concepts/memory/archival-memory)

7.  Model Context Protocol: Security Risks & Mitigations - SOC Prime,
    > [[https://socprime.com/blog/mcp-security-risks-and-mitigations/]{.underline}](https://socprime.com/blog/mcp-security-risks-and-mitigations/)

8.  Security Best Practices - Model Context Protocol,
    > [[https://modelcontextprotocol.io/docs/tutorials/security/security\_best\_practices]{.underline}](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)

9.  NATS vs. Kafka vs. Redis Streams for Java Microservices: When
    > \"Simpler\" Actually Wins,
    > [[https://www.javacodegeeks.com/2026/03/nats-vs-kafka-vs-redis-streams-for-java-microservices-when-simpler-actually-wins.html]{.underline}](https://www.javacodegeeks.com/2026/03/nats-vs-kafka-vs-redis-streams-for-java-microservices-when-simpler-actually-wins.html)

10. Kafka vs RabbitMQ vs NATS vs SQS: Choosing the Right Message Broker
    > \| BackendBytes,
    > [[https://backendbytes.com/articles/message-queue-comparison/]{.underline}](https://backendbytes.com/articles/message-queue-comparison/)

11. Architecture - NautilusTrader,
    > [[https://nautilustrader.io/docs/latest/concepts/architecture/]{.underline}](https://nautilustrader.io/docs/latest/concepts/architecture/)

12. The Missing Piece in Your LangGraph Workflow \| by OverTheHead - AWS
    > in Plain English,
    > [[https://aws.plainenglish.io/the-missing-piece-in-your-langgraph-workflow-a5c390ed2af4]{.underline}](https://aws.plainenglish.io/the-missing-piece-in-your-langgraph-workflow-a5c390ed2af4)

13. [[https://github.com/bitmaster162/continuityos/blob/master/CANONICAL\_TRUTH.md]{.underline}](https://github.com/bitmaster162/continuityos/blob/master/CANONICAL_TRUTH.md)

14. continuityos/CHANGELOG.md at master - GitHub,
    > [[https://github.com/bitmaster162/continuityos/blob/master/CHANGELOG.md]{.underline}](https://github.com/bitmaster162/continuityos/blob/master/CHANGELOG.md)

15. LangGraph in Production: Building Stateful AI Agents - Kalvium Labs,
    > [[https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/]{.underline}](https://www.kalviumlabs.ai/blog/langgraph-in-production-stateful-multi-step-agents/)

16. Model Context Protocol (MCP): Security Design Considerations for
    > AI-Driven Automation,
    > [[https://www.nsa.gov/Portals/75/documents/Cybersecurity/CSI\_MCP\_SECURITY.pdf]{.underline}](https://www.nsa.gov/Portals/75/documents/Cybersecurity/CSI_MCP_SECURITY.pdf)

17. Cap\'n Proto, FlatBuffers, and SBE,
    > [[https://capnproto.org/news/2014-06-17-capnproto-flatbuffers-sbe.html]{.underline}](https://capnproto.org/news/2014-06-17-capnproto-flatbuffers-sbe.html)

18. Wire formats - comparison & benchmarking - Tapestry,
    > [[https://www.laeith.com/posts/2021-04-04-wire-formats/]{.underline}](https://www.laeith.com/posts/2021-04-04-wire-formats/)

19. Model Context Protocol (MCP): Understanding security risks and
    > controls - Red Hat,
    > [[https://www.redhat.com/en/blog/model-context-protocol-mcp-understanding-security-risks-and-controls]{.underline}](https://www.redhat.com/en/blog/model-context-protocol-mcp-understanding-security-risks-and-controls)

20. Model Context Protocol Threat Modeling and Analysis of
    > Vulnerabilities to Prompt Injection with Tool Poisoning - MDPI,
    > [[https://www.mdpi.com/2624-800X/6/3/84]{.underline}](https://www.mdpi.com/2624-800X/6/3/84)
