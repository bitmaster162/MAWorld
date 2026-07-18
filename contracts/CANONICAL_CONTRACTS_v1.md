# MAWorld Canonical Contracts v1 (DR2 0x13)

Единый источник для 24 сущностей. Без дублей полей: общие поля вынесены в `BaseObject`; связи — junction-таблицы (не UUID-массивы); деньги — fixed-point int64 (никогда float). Каждая сущность: поля, владелец-хранилище, serialization profile, версия. Заменяет разрозненные YAML прошлых раундов (`contracts/*/*.yaml` остаются как detail, но канон — здесь).

## Соглашения
- **BaseObject** (наследуют все производные): `object_id: uuid`, `schema_version: string`, `created_at: timestamp`, `created_by: string`, `project_id: uuid|null`, `data_class: enum[PUBLIC,INTERNAL,CONFIDENTIAL,FINANCIAL_SENSITIVE,SECRET,CREDENTIAL]`.
- **Serialization profiles:** `jcs` = RFC 8785 canonical JSON + SHA-256 (для хешируемых/подписываемых); `sbe` = Simple Binary Encoding (только Trading hot-path); `json` = обычный JSON (control/intelligence).
- **Промоушен-гейты** (обязательны на версионируемых): `policy_version, code_version, prompt_version, tool_versions, configuration_hash`.
- **Rust/Python/PG mapping:** uuid→`Uuid`/`str`/`uuid`; int64 fixed-point→`i64`/`int`/`bigint`; timestamp→`OffsetDateTime`/`float`/`timestamptz`; enum→Rust enum/`str`+CHECK/`text`+CHECK.

## Knowledge Foundry identity (Postgres-owned, JCS для канона)
| # | Сущность | Ключевые поля (сверх Base) | Владелец | Serial |
|---|---|---|---|---|
| 1 | **RawBlob** | `sha256`, `byte_size:i64`, `storage_uri`, `storage_version_id`, `media_type_detected` — БЕЗ project_id (байты глобальны) | RawBlob CAS + PG `raw_blob` | jcs |
| 2 | **SourceOccurrence** | `source_system_id`, `source_native_id`, `observed_path_uri`, `blob_id→1`, UNIQUE(project,source_system,source_native) | PG `artifact_occurrence` (RLS) | json |
| 3 | **LogicalDocument** | `preferred_version_id→4`, `identity_rationale` | PG `logical_document` (RLS) | json |
| 4 | **ArtifactVersion** | `occurrence_id→2`, `blob_id→1`, `source_revision_key`, `parent_version_id→4?`, `tombstone:bool` | PG `artifact_version` (RLS) | json |

## Claims / decisions / canon (JCS + подпись)
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 5 | **CanonicalDecision** | `decision_type:enum[ADR,SCHEMA,INVARIANT,GLOSSARY]`, `statement`, `claim_id?`, `approved_by`, `signature`, `supersedes_decision_id?`, `status:enum[CANDIDATE_CANON,CANONICAL,SUPERSEDED,STALE,QUARANTINED]` | KF (authoritative) PG `canonical_decision` | jcs+sig |
| 6 | **CanonSnapshot** | `decisions:[5]`, `merkle_root`, `taken_at`, `read_only:true` | KF derived; экспорт read-only | jcs |
| 17 | **CanonPromotionRequest** | `candidate_id`, `source_decision_id→5`, `source_decision_hash`, `supersedes_canon_id?`, `promoter_credential_ref` | CanonPromoter (отд. credential) | jcs |

## Proposer boundary (untrusted → normalized)
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 7 | **BeliefArtifact** | `brain_run_id`, `belief`, `confidence:float`, `read_set`, `evidence_refs` — status всегда PROPOSED | mind/runtime (не авторитетно) | json |
| 8 | **ProposedActionSpec** | `proposal_id`, `source_trace_id`, `brain_run_id`, `target{adapter,path}`, `content_sha256`, `evidence_refs`, `expires_at` — authority-маркеры ЗАПРЕЩЕНЫ/срезаются | Proposal Bridge (вход) | json |
| 9 | **ProposalValidationResult** | `ok:bool`, `reason`, `stripped:[string]`, `action_spec→10?` | Proposal Bridge (выход) | json |

## Authority / policy (control plane)
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 10 | **ActionSpec** | `action_id`, `tool`, `operation`, `target`, `risk_class`, `blast_radius`, `idempotency_key`, `authority_binding{delegation_grant_id,capability_token_id,policy_decision_id}`, `mcp{→21}`, `provider_constraints` | ContinuityOS gate вход | jcs |
| 11 | **DelegationGrant** | `grant_id`, `subject`, `capabilities:[string]`, `expires_at`, `signature` | Authority (signed) | jcs+sig |
| 12 | **CapabilityToken** | `token_id`, `grant_id→11`, `action_spec_id→10`, `capability`, `exp`, `sig` — one-time | Authority (one-time) | jcs+sig |
| 13 | **PolicyDecision** | `decision:enum[ALLOW,WARN,HOLD,DENY,REQUIRE_CONFIRMATION,DRY_RUN_ONLY]`, `reasons:[string]`, `rollback_plan`, `ledger_hash` | ContinuityOS gate выход | jcs |
| 14 | **Approval** | `approval_id`, `candidate_id`, `nonce`, `ts`, `signer`, `sig` — one-time | Human/Telegram (nonce) | jcs+sig |

## Effects / reconciliation
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 15 | **ExternalEffectRecord** | `effect_id`, `idempotency_key`, `external_system`, `execution_status:enum[PENDING,SENT,CONFIRMED,FAILED,UNKNOWN]`, `reversibility_class:enum[REVERSIBLE,COMPENSATABLE,IRREVERSIBLE,UNKNOWN]`, `compensation_status`, `reconciliation_status` | ExternalEffectRegistry (PG/SQLite) | json |
| 16 | **ReconciliationResult** | `effect_id→15`, `probe:enum[CONFIRMED,ABSENT,AMBIGUOUS]`, `outcome:enum[RECONCILED_CONFIRMED,SAFE_TO_RETRY,HOLD_AMBIGUOUS]`, `reconciled_at` | ExternalEffectRegistry | json |

## Trace / evidence / audit
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 18 | **TraceContext** | `trace_id`, `span_id`, `parent_span_id`, `correlation_id`, `causation_id`, `workflow_id`, `branch_id`, `action_id`, `external_effect_id`, `eval_run_id` | TraceBridge→OTel | json |
| 19 | **Evidence** | `kind`, `verified:bool`, `source`, `detail`, `content_hash?` | Evidence Engine | jcs |
| 20 | **VerificationResult** | `subject_id`, `passed:bool`, `checks:[{name,status}]`, `evidence_refs:[19]` | Evidence Engine | jcs |
| 24 | **AuditEvent** | `seq:i64`, `kind`, `payload_jcs:bytes`, `payload_sha`, `prev_hash`, `hash` — append-only hash-chain | ContinuityOS Ledger | jcs |

## MCP / sandbox
| # | Сущность | Ключевые поля | Владелец | Serial |
|---|---|---|---|---|
| 21 | **MCPRequestContext** | `protocol_version`, `transport_mode`, `session_id_hash`, `origin`, `resource_server_uri`, `oauth{resource,challenged_scopes,audience_validated}`, `server_fingerprint`, `tool_descriptor_hash` | MCPAuthorizationResolver | json |
| 22 | **MCPTaskState** | `task_external_id`, `action_spec_id→10`, `delegation_grant_id→11`, `trace_id`, `state:enum[CREATED,RUNNING,INPUT_REQUIRED,RESULT_READY,RESULT_FETCHED,VERIFIED,COMPLETED,FAILED,EXPIRED,CANCELLED]` | AsyncTaskRegistry | json |
| 23 | **SandboxExecutionSpec** | `execution_id`, `artifact_id`, `sandbox_tier:enum[TIER0,TIER1_WASM,TIER2_GVISOR_OCI,TIER3_MICROVM,TIER4_DEDICATED_GPU]`, `network_policy:enum[DENY_ALL,ALLOWLIST,OFFLINE]`, `egress_allowlist`, `cpu/memory/disk/process limits`, `timeout`, `cleanup_policy` | Sandbox Broker / Tier2Runner | json |

## Trading (SBE hot-path, отдельный namespace)
Не входят в 24 control-контракта, но канонизируются здесь для полноты домена A:
- **SignalProposal** (untrusted, off hot-path): `signal_id`, `instrument`, `direction`, `conviction_score:u8` (ИГНОРИРУЕТСЯ риском), `proposed_risk_bps:u32`, `valid_until_ns`. Serial: sbe на транспорте.
- **OrderIntent** (после RiskService ALLOW): `client_order_id:uuid_v7`, `instrument`, `side`, `order_type`, `quantity_fixed:i64`, `price_fixed:i64`, `reduce_only`, `post_only`. Serial: sbe.
- **KillSwitchState**: `state_version:u64`, `enabled:bool`, `reason_code`, `effective_at_mono_ns:u64`. Читается admission-path напрямую.

## Правила версионирования
`schema_version` обязателен везде. Major-изменение → новый namespace/gRPC package. Minor — только additive поля, игнорируемые старыми консюмерами. Промоушен-гейты (`policy_version` и др.) — часть контракта, не декор. Реализации ссылаются сюда; поля не дублируются под разными именами между Rust/Python/PG.
