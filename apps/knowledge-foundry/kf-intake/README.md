# kf-intake — локальный Rust intake

Локальный вертикальный срез Knowledge Foundry: подписанный one-time mandate, RawBlob CAS,
occurrence/version identity, append-only metadata ledger и RFC 8785/JCS canonicalization.

> **SECURITY HOLD (2026-07-18).** Локальный intake теперь fail-closed по Ed25519 authority,
> но это не production authority service. Registry contents закреплены build digest, однако binary
> provenance, location/host filesystem и часы всё ещё локально доверенные; внешняя custody ключей и
> production PostgreSQL deployment/acceptance не приняты.
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
5. требует exact binding `actor`, project, canonical store root, content hash/size,
   source system/native key, issuer/key ID и nonce;
6. выбирает ключ только по bounded `key_id` из registry и применяет его immutable policy:
   allowed actors/projects/canonical roots и key-specific TTL ceiling;
7. выполняет `VerifyingKey::verify_strict` над
   `MAWORLD\0KF-INTAKE\0AUTHORITY\0V1\0 || JCS(claims)`;
8. под exclusive sidecar lock строго переигрывает hash-chained nonce ledger и вызывает
   `sync_data` после one-time consume ключа `(issuer, key_id, nonce)`;
9. только после consume повторно читает source. CAS публикует blob лишь если повторно
   вычисленный SHA-256 и размер совпали с mandate.

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
  "version": "maworld.kf.ed25519-key-registry.v1",
  "keys": [
    {
      "issuer": "operator-service",
      "key_id": "ed25519:<64-lowercase-hex>",
      "public_key_hex": "<64-lowercase-hex>",
      "allowed_actors": ["intake-worker-1"],
      "allowed_projects": ["maworld"],
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
    "version": "maworld.kf.ingest-authority.v1",
    "issuer": "operator-service",
    "key_id": "ed25519:<64-lowercase-hex>",
    "actor": "intake-worker-1",
    "project": "maworld",
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
kf ingest <file> --project <project> --source-system <system> --source-id <native-id> \
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
- malformed/partial replay ledger fail-closed;
- CAS TOCTOU: изменённые после mandate bytes не публикуются;
- direct `cas`/`meta`, dangling ledger и оба CAS hash-prefix symlink escape отклоняются;
- hash-prefix creation, blob chmod/publish и ledger changes требуют успешный directory fsync;
- invalid/missing authority не создаёт CAS/meta/replay state;
- semantic-identical registry с иными bytes отклоняется build digest pin до parse;
- обычный binary без compiled registry pin не способен вызвать ingest;
- crash после occurrence и до version восстанавливается новым валидным mandate;
- `cargo test -p kf-intake --locked`: **35 PASS**;
- package fmt и Clippy `-D warnings`: **PASS**;
- pinned RustSec: **169 dependencies scanned, 0 findings**.

## Остаточные границы

- Trust registry location задаётся локальной CLI-конфигурацией, а contents закреплены build digest.
  Это всё ещё не доказывает OS ownership, ACL, immutable binary/build provenance или HSM/KMS
  custody. Локальный pin не является production trust bootstrap.
- Время берётся из local system clock. Production требует trusted clock/anti-rollback policy.
- Durable consume намеренно выполняется до target side effect. Crash или source mutation после
  consume сжигает nonce и может оставить CAS blob без полного metadata tail; для продолжения нужен
  новый mandate. Missing version repair покрыт, но весь filesystem intake не является атомарной
  транзакцией.
- Cooperative file locks и path checks не защищают от hostile/root host, который может переписать
  registry, clock или ledger. Совместное удаление marker+ledger, valid-prefix rollback и pathname
  check/use race неотличимы без external monotonic anchor и descriptor-based boundary. Нужны process
  isolation и external transactional replay/custody.
- Atomic PostgreSQL/RLS broker реализован локально в `schema/003` и `kf-store-pg`, но dedicated
  real-DB acceptance, end-to-end authority wiring и production deployment trust остаются HOLD.
- Global PostgreSQL dedup различает existing/new hash и metadata conflict. До обязательного verified
  proof-of-content либо tenant/keyed dedup с неразличимым outcome это membership oracle.

## Файлы

- `src/authority.rs` — strict policy/signature verification и durable replay consume.
- `src/cas.rs` — bounded expected-hash CAS publish/recovery.
- `src/meta.rs` — locked metadata ledger и read-only verification path.
- `src/identity.rs` — strict RawBlob/Occurrence/Version payloads.
- `src/jcs.rs` — JCS canonical bytes.
- `src/main.rs` — fail-closed CLI и единственный authorized ingest entry point.
