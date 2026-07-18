# Ресурсы флота + карта проекты→MAWorld + вывод по деплою (2026-07-16)

Инвентаризация под деплой (из канона `projects.json` + `2026-07-13_VPS_specs_for_k3s.md`, снято read-only
через Cloud Shell 3 дня назад — можно обновить вживую по отмашке).

## 1. Ресурсы флота (3 машины + кандидат)
| Хост | IP | Спеки | Что крутит | Свободно под MAWorld? |
|---|---|---|---|---|
| **arena-test-spot** (GCP us-central1, SPOT) | 34.70.171.152 | 2 vCPU · 15 GiB RAM (11 занято, **4.5 своб**) · диск **20GB 95% ПОЛОН** · Debian 12 | арена: 175 сервисов + 152 V-бота + Postgres; дашборды :8110/:8120; RaaS :8100; L2-коллекторы | ❌ диск 95%, RAM 11/15 — добьёт арену |
| **trading-bot / Brain fin35** (GCP europe-north1) | 35.217.10.153 | 2 vCPU · **1.9 GiB RAM** (своп занят) · диск **20GB 89%** · Debian 12 | OKX-NFT стек: 8 Docker (okx-nft ×3, parser, nft-brain, fastapi, redis, postgres); Brain :9100; ops :8090 | ❌ 1.9GB RAM, диск 89%, своп занят |
| **win185** (Windows Server 2022) | 185.231.154.149 | **8 GB RAM** (~5 своб) · WIN-2513OKBPOH9 | 3 Binance-NFT-бота (Selenium+Chrome) · BitEvo Full API :8080 · TradingOS paper · **Inner Circle (платящие)** · **Sovereign (реальные деньги)** | ❌ Windows (k3s/runsc не идёт) + боевая нагрузка с деньгами |
| **old144** (кандидат) | 144.124.250.14 | Linux, root/SSH; раньше OKX-NFT | помечен **«под decom»**, стек уехал на fin35 | ⏳ **ЕСЛИ decom подтверждён — готовый Linux-кандидат** |

## 2. Вывод по ресурсам под деплой MAWorld (главное)
**Весь текущий парк занят — под деплой MAWorld/runsc нужен ресурс.** Ни один из трёх не годится: arena
(диск 95%), trading-bot (1.9GB RAM), win185 (Windows + деньги). Два пути:
1. **Проверить/освободить old144** (144.124.250.14) — если decom реальный, это идеальный Linux+root бокс
   под MAWorld (runsc, прод-Postgres, CI-runner). Команда read-only-проверки готова (§ ниже).
2. **Взять свежий чистый VPS** — MAWorld лёгкий: Python-модули (libs) + Postgres + adversarial-suite +
   опц. Langfuse. Минимум: **2–4 vCPU, 4–8 GB RAM, 40+ GB SSD**, фаервол 6443/80/443. Один single-node
   хватит для старта (не HA).

MAWorld-футпринт (оценка): ядро (libs+tests) — десятки МБ, RAM <500MB; +Postgres ~300MB; +runsc rootfs
~200MB; +Langfuse (Postgres/ClickHouse) — если нужен, +2GB. То есть **4GB RAM бокс достаточно** для ядра
без тяжёлой observability.

Read-only проверка old144 (готова, запускать по отмашке через Cloud Shell):
```
ssh root@144.124.250.14 'nproc; free -h; df -h /; grep PRETTY_NAME /etc/os-release; docker ps 2>/dev/null | wc -l; ss -ltn | grep -E ":6443|:80|:443" || echo "6443/80/443 free"'
```

## 3. Карта: наши проекты → слоты MAWorld (что соединять, анти-задвоение)
| Проект (где) | Роль | Слот MAWorld | Статус связи |
|---|---|---|---|
| **continuity_os** (trunk, локально) | canon/gate/ledger/mind | ContinuityOS gate (control_spine) | ✅ подключён (реальный preflight) |
| **reflex/pfi** (4 расписания) | frontier intel | PFI bridge + autopull | ✅ подключён + автоматизирован |
| **reflex-layer** (arbiter OODA, gemini) | autonomous monitor | improvement-engine / agents-runner | 🔶 связать: proposal-only через gate |
| **state-authority-plane-live** (Loop B, 3410 LOC) | authority plane | capability + canon_sod | 🔶 связать: SAP→наш authority-слой |
| **trading-stack** (144/144, contracts 5-type) | paper trading runtime | Trading Cell (risk + venue + action_authority) | 🔶 их SignalReport→GateDecision→ApprovalDecision→ExecutionIntent→ExecutionEvent = наш gate→risk→mandate→venue→effect |
| **LIVE_TRADING btcusdt v7** | real Binance client | venue-adapters | ✅ подключён (M2 testnet) |
| **trading-arena** (Bingx paper, на arena VPS) | multi-variant paper | Trading Cell paper validation | 🔶 read-only export → evidence |
| **bitevo** (win185, FastAPI+Temporal+PG+vLLM+Playwright) | execution engine | policy boundary ПЕРЕД bitevo (action_authority+gate) | 🔶 bitevo_gatekeeper.py ↔ наш gate |
| **inner-circle-bot** | payments (Stripe/TG) | Money Forge | ⛔ HOLD (неавторитетный источник + payment-дефекты) |
| **DTaaP** (Z3 verifier, MemOS) | digital twin | Evidence Engine / verifier | 🔶 Z3 → формальная верификация политик (Cedar-трек) |
| **GPT-S:CORE SDK** (Z3, MoA, S-Score, Anti-Self) | cognitive SDK | dialectic + eval-registry | 🔶 MoA-консенсус → challenger; S-Score → eval |
| **sovereign-core** (Bifrost, MemIR, SSGM) | agent trust layer | capability + memory_provenance | 🔶 MemIR ↔ Governed Memory |
| **universe_hub** (arena :8120) | system registry UI | Operator Cockpit | ✅ выровнен (manifest → cockpit) |
| **delist-ews** | monitoring signal | PFI/agents signal | 🔶 alerts → PROPOSED intel |

Легенда: ✅ подключён · 🔶 готов к связке (proposal-only через gate, анти-задвоение) · ⛔ HOLD.

## 4. Порядок (от глобального вниз — global-cycle)
1. **Ресурс:** проверить old144 (decom?) ИЛИ взять чистый VPS 4–8GB. Без ресурса деплой некуда.
2. На чистом боксе: key custody → CI-на-CI → runsc → прод-Postgres (docs/27).
3. Связать проекты proposal-only: trading-stack (contracts→наш gate), bitevo (gatekeeper↔gate),
   reflex-layer (OODA→improvement-engine), SAP Loop B → capability. Всё как предложения через spine.
4. Inner Circle — оставить HOLD до авторитетного источника + починки payment-дефектов (наш money_forge_v2
   уже требует подписанное payment-proving событие — это и есть починка).

## Инвариант
Реальные деньги (win185 Sovereign, Inner Circle платящие) — НЕ трогаем; live-эффекты OFF; связки —
proposal-only через детерминированный spine; ресурс под MAWorld — отдельный чистый бокс, не боевые.
