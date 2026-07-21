# kf-intake — локальный Rust intake

Локальный вертикальный срез Knowledge Foundry: подписанный one-time mandate, one-time
authority→PostgreSQL grant, RawBlob CAS, occurrence/version identity, append-only metadata ledger и
RFC 8785/JCS canonicalization.

> **SECURITY HOLD (2026-07-22).** Локальный intake реализует fail-closed Ed25519 authority v3:
> signed scope связан с explicit database security domain и одноразовым PostgreSQL grant. Current
> locked Rust gates и отдельный dedicated disposable PostgreSQL 16 acceptance прошли; точные данные
> приведены ниже. Это локальный PASS, не production authority. Registry contents закреплены
> build digest, однако binary provenance, location/host filesystem, registrar credential, DB
> transport и часы локально доверенные; external custody и deployment attestation не приняты.
> Durable scoped intake fail-closed отключён на Windows и поддерживается только в pinned Linux runtime.
> LIVE остаётся выключен.

## Authority contract

`kf ingest` не имеет unsigned/default/demo пути. До создания `cas`, `meta` и их событий он:

1. read-only и bounded способом считает SHA-256 и размер regular non-symlink source;
2. требует exact lowercase registry SHA-256, встроенный в binary на этапе сборки через
   `option_env!("MAWORLD_KF_TRUST_REGISTRY_SHA256")`; unpinned/invalid-pin binary не способен ingest;
3. читает bounded registry bytes, сравнивает их digest с build pin **до JSON parse**, затем читает
   strict envelope;
4. проверяет exact claims version, `Ed25519`, audience `maworld.kf-intake`, action `ingest`,
   timestamps и TTL не более 300 секунд;
5. требует exact binding `actor`, canonical UUID `authority_domain_id`, canonical UUID `project_id`,
   canonical UUID `database_grant_id`, `database_session_user`, canonical store root, content
   hash/size, source system/native key, issuer/key ID и nonce;
6. выбирает ключ только по bounded `key_id` из registry и применяет его immutable policy:
   allowed actors/authority domains/projects/database session users/canonical roots и key-specific
   TTL ceiling;
7. выполняет `VerifyingKey::verify_strict` над
   `MAWORLD\0KF-INTAKE\0AUTHORITY\0V3\0 || JCS(claims)`;
8. под exclusive sidecar lock строго переигрывает hash-chained nonce ledger и вызывает
   `sync_data` после one-time consume ключа `(issuer, key_id, nonce)`;
9. после проверки возвращает opaque, non-cloneable `ConsumedIngestAuthority`; CAS consume-ит его и
   возвращает только `StoredIngestAuthority` после durable exact-byte publish;
10. registrar принимает borrowed stored proof для точного retry, повторно открывает CAS и потоково
    сверяет hash/size в ограниченном blocking-pool прямо перед SQL, после чего PostgreSQL ещё раз
    проверяет signed domain/project/source/content/session scope и сохранённый role OID. Runtime
    caller передаёт только `grant_id`; exact function ACL и client/server 5s lock / 30s statement
    timeout ограничивают доступ и ожидание.

Dependency закреплён exact:

```toml
ed25519-dalek = { version = "=3.0.0", default-features = false }
```

`hazmat`, `legacy_compatibility`, batch, key generation и PEM/PKCS#8 features не включены.

### Strict trust registry

Registry обязан существовать вне writable intake root. Symlink, unknown fields, duplicate
`key_id`, non-canonical/non-existing root, oversized registry и key ID, который не равен
`ed25519:` + lowercase SHA-256 raw public-key bytes, отклоняются.

Путь registry остаётся location-параметром CLI, но его содержимое не self-selected: verifier
принимает только exact bytes, digest которых был зафиксирован при компиляции. Runtime environment
не читается и digest CLI-флага нет. Обычные CI/local verification builds намеренно удаляют
`MAWORLD_KF_TRUST_REGISTRY_SHA256` из build environment: их тесты проходят, но полученный binary
fail-closed для ingest. Pinned release требует отдельного контролируемого build/provenance процесса.

```json
{
  "version": "maworld.kf.ed25519-key-registry.v3",
  "keys": [
    {
      "issuer": "operator-service",
      "key_id": "ed25519:<64-lowercase-hex>",
      "public_key_hex": "<64-lowercase-hex>",
      "allowed_actors": ["intake-worker-1"],
      "allowed_authority_domain_ids": ["dddddddd-dddd-4ddd-8ddd-dddddddddddd"],
      "allowed_projects": ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
      "allowed_database_session_users": ["kf_runtime_login"],
      "allowed_store_roots": ["/srv/maworld/kf-store"],
      "max_ttl_seconds": 120
    }
  ]
}
```

Claims внутри envelope имеют strict schema (`deny_unknown_fields`):

```json
{
  "algorithm": "Ed25519",
  "claims": {
    "version": "maworld.kf.ingest-authority.v3",
    "issuer": "operator-service",
    "key_id": "ed25519:<64-lowercase-hex>",
    "actor": "intake-worker-1",
    "authority_domain_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    "project_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "database_grant_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "database_session_user": "kf_runtime_login",
    "store_root": "/srv/maworld/kf-store",
    "content_sha256": "<64-lowercase-hex>",
    "content_size": 123,
    "source_system_id": "local-folder",
    "source_native_id": "maworld::00_MASTER.md",
    "nonce": "<16..128 token chars>",
    "issued_at_unix": 1900000000,
    "expires_at_unix": 1900000120,
    "audience": "maworld.kf-intake",
    "action": "ingest"
  },
  "signature_hex": "<128-lowercase-hex>"
}
```

## CLI

Все authority-параметры explicit; defaults отсутствуют:

```text
kf ingest <file> --project <canonical-project-uuid> \
  --authority-domain <canonical-security-domain-uuid> \
  --database-grant <canonical-grant-uuid> --database-session-user <runtime-login> \
  --source-system <system> --source-id <native-id> \
  --root <existing-store> --authority <envelope.json> \
  --authority-registry <operator-owned-trust.json>
```

Metadata verification не создаёт missing root, ledger или lock sidecar:

```text
kf verify --root <existing-store>
```

## Локально подтверждено

- mutation, unknown fields, wrong project/root/hash/source/audience/action;
- valid signature вне actor/project/root/key TTL policy;
- expiry, future issuance, reversed time и excessive TTL;
- replay после restart и concurrent replay с ровно одним победителем;
- authority-domain/project/grant/session substitution, non-canonical/nil UUID и session user вне
  key policy;
- PostgreSQL runtime payload не содержит caller-controlled project/source/content scope: он передаёт
  только grant ID; occurrence/version UUID генерирует SQL, а scope извлекается из
  зарегистрированного signed grant;
- guarded PostgreSQL acceptance с реальными NOINHERIT runtime/registrar logins подтвердил
  missing/revoked/expired/wrong-session grant, wrong database domain, recreated same-name role,
  deleted CAS blob, arbitrary GUC, raw read, identifier substitution, dual-member registrar и
  cross-root replay: **1/1 PASS за 37.00s**; domain
  `dddddddd-dddd-4ddd-8ddd-dddddddddddd`, grants=7, consumed=3,
  raw_blob/occurrences/versions=3/3/3; disposable container удалён;
- malformed/partial replay ledger fail-closed;
- CAS TOCTOU: изменённые после mandate bytes не публикуются;
- direct `cas`/`meta`, dangling ledger и оба CAS hash-prefix symlink escape отклоняются;
- hash-prefix creation, blob chmod/publish и ledger changes требуют успешный directory fsync;
- invalid/missing authority не создаёт CAS/meta/replay state;
- semantic-identical registry с иными bytes отклоняется build digest pin до parse;
- обычный binary без compiled registry pin не способен вызвать ingest;
- crash после occurrence и до version восстанавливается новым валидным mandate;
- `kf-intake`: **27 library + 43 binary = 70 PASS**; весь Rust workspace: **109 PASS / 0 FAIL /
  1 ignored**;
- fmt PASS; Clippy `-D warnings` PASS; pinned RustSec: **169 crate dependencies, 0 vulnerabilities,
  1166 advisories loaded**;
- `Cargo.lock` SHA-256:
  `714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171`.

## Остаточные границы

- Trust registry location задаётся локальной CLI-конфигурацией, а contents закреплены build digest.
  Это всё ещё не доказывает OS ownership, ACL, immutable binary/build provenance или HSM/KMS
  custody. Локальный pin не является production trust bootstrap.
- Время берётся из local system clock. Production требует trusted clock/anti-rollback policy.
- Durable consume намеренно выполняется до target side effect. Crash или source mutation после
  consume сжигает nonce и может оставить CAS blob без полного metadata tail; для продолжения нужен
  новый mandate. Missing version repair покрыт, но весь filesystem intake не является атомарной
  транзакцией.
- Между local nonce consume и PostgreSQL registration остаётся fail-safe availability gap: crash
  сжигает local mandate, не создавая DB grant. Это не разрешает неподписанную запись, но требует
  нового mandate/reconciliation и пока не является production recovery protocol.
- Cooperative file locks и path checks не защищают от hostile/root host, который может переписать
  registry, clock или ledger. Совместное удаление marker+ledger, valid-prefix rollback и pathname
  check/use race неотличимы без external monotonic anchor и descriptor-based boundary. Нужны process
  isolation и external transactional replay/custody.
- Atomic PostgreSQL/RLS broker в `schema/003+004` и `kf-store-pg` связывает stored signed authority
  с explicit singleton `authority_domain_id`, current runtime role OID и one-time DB grant. `004`
  намеренно one-shot (`55000` при повторном применении), а unprovisioned domain fail-closed. Сейчас
  поддержан только bootstrap нового пустого volume; existing-volume upgrade/crash/restore не принят.
- Snapshot/clone наследует authority domain и DB state. До допуска клона нужны quarantine, revoke/
  очистка outstanding grants и coordinated rotation `authority_domain_id`, runtime/registrar
  credentials и issuer policy; HA/DR semantics ещё не формализованы.
- Runtime/registrar admission проверяет roles и ACL, но не требует PostgreSQL TLS/`verify-full` или
  channel binding. Confidentiality credentials должна обеспечиваться отдельным production deploy
  gate, которого сейчас нет.
- Runtime outcome больше не раскрывает global blob ID или `*_created` flags. Но отсутствие
  timing/lock/error membership side-channel для global dedup ещё не доказано; нужны tenant/keyed
  dedup либо отдельная non-interference acceptance.
- CAS revalidation ловит удаление/подмену до регистрации, но не атомизирует pathname с DB commit.
  Hostile writer после revalidation остаётся storage/TOCTOU blocker без object-store retention/custody
  либо transactional finalize/reconciler protocol.

## Файлы

- `src/authority.rs` — strict policy/signature verification и durable replay consume.
- `src/lib.rs` — общий opaque authority boundary для local intake и PostgreSQL registrar.
- `src/cas.rs` — bounded expected-hash CAS publish/recovery.
- `src/meta.rs` — locked metadata ledger и read-only verification path.
- `src/identity.rs` — strict RawBlob/Occurrence/Version payloads.
- `src/jcs.rs` — JCS canonical bytes.
- `src/main.rs` — fail-closed CLI и единственный authorized ingest entry point.
