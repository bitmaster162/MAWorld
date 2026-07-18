# Python dependency locks

These files are generated security artifacts, not hand-maintained dependency lists.

- `default.lock.txt`: universal Python 3.10+ resolution for the default project dependencies.
- `trading.lock.txt`: universal resolution for default + `trading` extra.
- `ci-verification.lock.txt`: minimal Cedar/Z3 environment used by CI.
- `ci-verification.in`: direct CI pins; `tools/check_supply_chain.py` verifies they match `pyproject.toml`.

Every emitted requirement is exact-versioned and carries SHA-256 hashes. Source builds are excluded during resolution and installation. Candidate packages are capped at the audit snapshot timestamp `2026-07-16T00:00:00Z`.

Regenerate from the repository root:

```powershell
powershell -File .\tools\refresh_python_locks.ps1
python .\tools\check_supply_chain.py
python .\tools\audit_python_locks_osv.py
```

The OSV audit collects every unique package/version pair without evaluating environment markers, so universal branches for other Python/OS combinations are not silently skipped. It is a point-in-time known-vulnerability check, not proof that unknown vulnerabilities are absent.

CI installs the minimal verification environment with:

```text
python -m pip install --require-hashes --only-binary=:all: -r requirements/ci-verification.lock.txt
```

Universal locks intentionally contain every allowed wheel hash for supported marker branches. A production release should additionally mirror the selected wheels in an immutable internal wheelhouse and sign the resulting artifact/SBOM.
