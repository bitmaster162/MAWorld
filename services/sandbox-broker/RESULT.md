# Tier-2 runner — результат hardening

Дата: **2026-07-16**

## Проверка

```powershell
python services/sandbox-broker/tier2_acceptance.py
```

Результат на текущем Windows host:

```text
TALLY tier2 acceptance: PASS=42 FAIL=0 SKIP=5
```

## Исправлено и подтверждено локально

- устранён validation-to-exec path TOCTOU для `runsc`: защищённые parent paths
  проходят no-follow descriptor walk, проверенный бинарник исполняется из того
  же удерживаемого FD;
- rootfs также descriptor-pinned, привязан к device/inode/mount-id и допускается
  только с read-only host mount;
- root-owned/non-group/world-writable policy применяется ко всей parent chain,
  а не только к конечному файлу или каталогу;
- SHA-256 backend проверяется по открытому FD;
- PATH discovery и все unsafe fallback API fail-closed;
- окружение очищено; shell и `preexec_fn` не используются;
- код, output, timeout, ресурсы и global concurrency ограничены;
- OCI profile остаётся least-privilege, но сам по себе не называется runtime
  proof;
- process exit success никогда не выставляет `isolated`/`egress_denied`;
- caller-asserted acceptance hard-disabled;
- прежние одиночные TCP и `/etc` probes удалены из security acceptance: они
  не могли доказать deny-egress или полное write confinement.

## Пять явных SKIP

1. функциональный запуск реального pinned Linux/runsc backend;
2. функциональное timeout/termination через реальный runsc;
3. fixed-key verification подписанной deployment-attestation, связывающей
   backend digest/file identity, rootfs image digest/mount identity, OCI policy,
   host identity, freshness и nonce;
4. контролируемая multi-vector egress проверка TCP/UDP/IPv4/IPv6/DNS вместе с
   host firewall evidence;
5. полная mount/LSM/runtime проверка host-write и namespace confinement.

## Вердикт

**Локальный fail-closed контракт усилен; production acceptance не пройден.**

Windows не предоставляет поддержанного Tier-2 backend. Даже успешный прогон на
Linux будет только функциональным smoke, пока отдельная доверенная система не
проверит signed/digest-pinned deployment evidence. Локальный runner не принимает
attestation key, подпись или итоговые booleans от вызывающего кода и потому не
может самопровозгласить production assurance.
