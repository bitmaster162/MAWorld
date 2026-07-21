# MAWorld — текущий статус

Дата: **2026-07-22**

- LIVE: **OFF**
- BUILD_FREEZE: **BLOCKED**
- production: **HOLD**

Текущий tree подтверждён полным `VERIFY.ps1` (**exit 0**), digest-pinned Rust gate и отдельным
guarded disposable PostgreSQL 16 acceptance. Это локальное evidence не снимает production HOLD.

- root: **54/54 suites, 1086 assertions**
- active: **20/21 green, 411 checks, 1 explicit external PostgreSQL RLS SKIP**
- runner-integrity: **22/22**
- release-status: **14/14**
- single-source: **10/10**
- Tier-2 Windows: **42 PASS / 0 FAIL / 5 SKIP**
- Python supply: **3 SHA-256/wheel-only profiles, 71 entries; OSV 44 pairs / 0 findings**
- Rust authority v3: **109 PASS / 0 FAIL / 1 ignored PostgreSQL acceptance; fmt + Clippy PASS**
- PostgreSQL 16 authority/RLS v3: **1/1 PASS, 37.00s** в guarded disposable run; domain
  `dddddddd-dddd-4ddd-8ddd-dddddddddddd`, grants=7, consumed=3, blobs/occurrences/versions=3/3/3;
  disposable container удалён
- Rust supply: **169 crate dependencies / 0 vulnerabilities; 1166 advisories loaded**
- `Cargo.lock` SHA-256: `714e1bc8ecd38fd2eb92fa9b5e8a047d57e86b02abcb8d3bd5b633e2dc941171`
- containers: **Compose config PASS; 3/3 images pinned to exact SHA-256 digests**

Предыдущий независимый clean-copy прогон предшествует signed-authority и migration `003`; он
**superseded** и не считается evidence для текущего дерева. Старые 52/52 относятся только к срезу
2026-07-16. Current authority-v3/`004` evidence приведено выше; local PASS не является production
deployment acceptance.

Жёсткие production-блокеры: Linux/runsc без SKIP; external key и registrar credential
custody/rotation; trusted clock и external monotonic anchor против local replay rollback; immutable
build/VCS provenance для build-pinned Rust authority; PostgreSQL TLS и credential confidentiality;
one-shot `004` existing-volume upgrade/backup/forced-crash/restore acceptance; clone quarantine с
rotation `authority_domain_id` и credentials; signed schema/policy/function attestation и drift
monitoring; non-interference proof для timing/lock/error side-channel global dedup; descriptor-based
CAS boundary вместо hostile pathname replacement;
trusted risk observation provenance; реальные Stripe/venue acceptances; production NATS/MinIO
auth/TLS; signed release/CI/SBOM/artifact provenance и независимый review.

`MAWorld_review_package.zip`, `apps/knowledge-foundry/kf-intake/repro/MANIFEST.json` и старые
docs/spikes — historical, не current evidence и не deployment artifacts.

Текущий отчёт: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
