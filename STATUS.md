# MAWorld — текущий статус

Дата: **2026-07-18**

- LIVE: **OFF**
- BUILD_FREEZE: **BLOCKED**
- production: **HOLD**
- root: **54/54 suites, 1086 assertions**
- active: **20/21 green, 411 checks, 1 explicit PostgreSQL SKIP**
- runner-integrity: **22/22**
- release-status: **14/14**
- single-source: **10/10**
- Tier-2 Windows: **42 PASS / 0 FAIL / 5 SKIP**
- formats: **291 Python / 5 JSON / 8 TOML / 24 YAML, 0 failures**
- Python supply: **3 SHA-256/wheel-only profiles, 71 entries; OSV 44 pairs / 0 findings**
- Rust: **72 PASS / 0 FAIL / 1 explicit ignored PostgreSQL acceptance; fmt + Clippy PASS**
- Rust supply: **169 dependencies / 0 RustSec findings**
- containers: **3/3 compose images pinned to exact SHA-256 digests**
- high-confidence credentials / reparse points: **0 / 0**

Предыдущий независимый clean-copy прогон предшествует signed-authority и migration `003`; он
**superseded** и не считается evidence для текущего дерева. Текущий baseline выше получен повторным
полным прогоном рабочей копии и digest-pinned Linux Rust gate. Старые 52/52 относятся только к
срезу 2026-07-16.

Жёсткие production-блокеры: Linux/runsc без SKIP; external key custody/rotation, trusted clock и
shared replay; immutable build/VCS provenance для build-pinned Rust authority; end-to-end
authority→project-scope wiring; dedicated disposable-cluster PostgreSQL migration/RLS/pool/concurrency/crash acceptance;
signed PostgreSQL schema/policy/function attestation and drift monitoring; proof-of-content либо
tenant/keyed dedup с неразличимым outcome вместо cross-project hash-membership oracle;
trusted risk observation provenance; реальные Stripe/venue acceptances; production NATS/MinIO
auth/TLS; signed release/CI/SBOM/artifact provenance и независимый review.

`MAWorld_review_package.zip`, `apps/knowledge-foundry/kf-intake/repro/MANIFEST.json` и старые
docs/spikes — historical, не current evidence и не deployment artifacts.

Текущий отчёт: [docs/45_SECURITY_CONTINUATION_2026-07-18.md](docs/45_SECURITY_CONTINUATION_2026-07-18.md).
