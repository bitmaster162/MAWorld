# sandbox-broker

Актуально на **2026-07-16**.

Tier-2 выполняет недоверенный Python только через явно сконфигурированный
Linux + gVisor `runsc`. Поиск через `PATH`, direct-Python и bwrap fallback
отсутствуют. На Windows выполнение fail-closed недоступно.

## Локально принудительные инварианты

- backend задаётся абсолютным путём и точным SHA-256;
- каждый parent-компонент backend/rootfs открывается от `/` через descriptor
  walk с `O_NOFOLLOW`; каталоги должны быть root-owned и не
  group/world-writable;
- backend проверяется по типу, владельцу, mode, inode/device/size/mtime и
  SHA-256, затем запускается именно через удерживаемый `/proc/self/fd/<n>`;
  повторного разрешения проверенного имени перед `exec` нет;
- rootfs открывается через удерживаемый directory FD, привязывается к
  device/inode/mount-id и обязан находиться на read-only mount;
- `root.readonly=true` в OCI config считается только настройкой контейнера и
  не подменяет проверку read-only host mount;
- host wrapper получает пустое окружение и запускается без shell/preexec hook;
- код, stdout/stderr, timeout, память, файл, процессы и process-global
  concurrency имеют жёсткие пределы;
- OCI profile требует отдельный network namespace, `noNewPrivileges`, пустые
  capabilities, uid/gid 65534, read-only root и только ephemeral writable
  tmpfs без host RW bind;
- `RunResult.ok` означает лишь успешное завершение процесса;
  `isolated=false` и `egress_denied=false` всегда остаются локально;
- caller booleans и локальные acceptance-объекты отключены.

## Что локальный runner намеренно не утверждает

Runner не вычисляет и не заверяет identity всего rootfs image, не доказывает
работу host firewall/LSM и не выпускает собственную deployment-attestation.
Read-only mount предотвращает обычную мутацию источника во время запуска, но
не является доказательством происхождения образа или защиты от root-level
изменения host policy.

До production отдельный fixed-key verifier обязан проверить подписанную,
свежую и replay-safe attestation, которая связывает как минимум:

- `backend_sha256` и `backend_file_identity`;
- digest доверенного rootfs image и фактический `rootfs_mount_identity`;
- digest OCI policy;
- host identity;
- `issued_at`, `expires_at` и уникальный `nonce`.

Один неуспешный TCP connect или одна запрещённая запись в `/etc` не считаются
доказательством deny-egress/write-confinement. Для этого нужны контролируемые
multi-vector TCP/UDP/IPv4/IPv6/DNS проверки плюс подписанные host
firewall/mount/LSM/runtime evidence.

## Текущий статус

На текущем Windows host:

```text
TALLY tier2 acceptance: PASS=42 FAIL=0 SKIP=5
```

Пять SKIP — две реальные Linux/runsc функциональные проверки и три внешние
assurance-проверки (подписанная deployment-attestation, multi-vector egress,
полное host-write/namespace confinement). Поэтому production acceptance
остаётся заблокирован.

Подробнее: [RESULT.md](RESULT.md).
