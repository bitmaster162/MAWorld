# canon-promoter

Legacy `canon_promoter.py` is permanently fail-closed. It does not import
ContinuityOS, hold approval/promoter secrets, issue credentials, or write canon.

The only supported implementation is `canon_sod.py`, a shim to
`libs/maworld_core/canon_sod.py`. It requires a separate verify-only approver
boundary and durable replay/idempotency state.

Checks:

- `python -B test_canon_promoter.py` — legacy API lockdown.
- `python -B test_canon_sod.py` — canonical separation-of-duties adversarial suite.
