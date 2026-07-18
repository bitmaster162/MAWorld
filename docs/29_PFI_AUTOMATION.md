# PFI фулл-автоматика + внедрённые темы из GPT-дайджеста

## 4 расписания PFI (изучены, как GPT-дайджест)
Включённые задачи ContinuityOS, кормящие интеллект (созданы в этом окружении):
| Расписание | Когда | Выход | Формат сигнала |
|---|---|---|---|
| `pfi-frontier-sweep` | пн 08:06 | `pfi_signals.json` (cap 100) → `pfi_sync` → Brain canon + cos memory | {category,title,description,source,action(learn/sell/test/avoid/advantage),reasoning,confidence,evidence} |
| `pfi-robotics-beat` | каждые 12ч | `robotics_beat_signals.json` → Brain canon (EDGE gate) | тот же + decision=EDGE |
| `machine-economy-weekly-monitor` | пн 10:09 | x402/L402/MPP дайджест → Pandora Forge | сигналы/отчёт |
| `daily-trading-snapshot` | ежедн 08:07 | снимок торговых данных | JSON снапшот |

## Автоматика (донастроено — без ручного ввода)
`libs/maworld_core/pfi_autopull.py` (6/6): читает выходы расписаний (`pfi_signals.json`,
`robotics_beat_signals.json`, `cosmos3_signals.json`) → `pfi_bridge` (input_guard + memory_provenance) →
пишет `apps/pfi-intake/pfi_feed.json` (PROPOSED-интел для Cockpit). Мягко деградирует на пустых/битых.

**Scheduled task `maworld-pfi-autopull-daily` (ежедневно 08:32)** — после утренних sweep'ов тянет всё в
контур MAWorld автоматически. Первый прогон на РЕАЛЬНЫХ данных: **frontier 53 + robotics 100 + cosmos3 8
= 161 сигнал → 156 PROPOSED-интел, 161 gated-action, 0 инъекций**. Инвариант: сигнал=PROPOSED (не canon),
action=gated proposal (policy_engine→action_authority→human_confirm), injection-сигналы автоотвергаются.

## Внедрённые темы из GPT-дайджеста (изучил на наши темы → реальные модули, 15/15)
| Сигнал дайджеста | Модуль MAWorld | Что делает |
|---|---|---|
| **Ghostcommit** (prompt injection в PNG через AGENTS.md → чтение .env → кража секретов) | `multimodal_guard` | образы/PDF/config/AGENTS.md = untrusted executable surface; извлекает строки и сканит на injection; агенту запрещено читать `.env`/ключи; secret-export/CI → confirm |
| **Bonzo Lend** ($9.05M: verifier принял unsigned price, +12 порядков) | `signed_oracle` | price-update только: подписан авторизованным signer + ≥2 независимых источника + в пределах deviation; иначе fail-closed |
| **GOLD EAGLE** (US AI vuln-coordination) | `vulnerability_claim` | объект proof→affected→risk→owner→allowed-action→fix-status; без proof/owner → HOLD; critical → gated remediation proposal |

## OWASP red-team корпус в CI (12/12)
`tests/test_owasp_redteam.py` — прогон OWASP Top-10 for Agentic Apps 2026 против всех защит: prompt
injection (A01), tool-misuse/confused-deputy (A02/A08 confirm-bypass), memory-poisoning (A03),
excessive-agency (A04, agent proposal-only + policy default-deny), multimodal Ghostcommit (A05),
shadow-agent (A06), unsigned-oracle (A07), self-approval (A08 SoD), untrusted-input high-impact (A10).
Все блокируются. Гоняется единым `tests/run_all.py`.

## Итог
PFI подключён и **автоматизирован** (scheduled auto-pull на реальных данных); интел из GPT-дайджеста
интернализован тремя боевыми защитами; OWASP-корпус в CI. Полный прогон: **24/24 suites, 219
adversarial-проверок**. Wedge подтверждён самим дайджестом: «недоверенные данные → policy → allow/warn/
hold → audit».
