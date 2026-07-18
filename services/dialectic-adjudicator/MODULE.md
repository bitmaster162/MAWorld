# dialectic-adjudicator

The legacy external Python integration is disabled. It previously trusted a
caller-controlled import path and allowed the imported package to select a
writable runtime. That path is not a trustworthy adjudication boundary.

Current behavior:

- no external `mind` or ContinuityOS import;
- no `sys.path` or environment mutation;
- no live-state reads or report writes;
- no findings and no canon proposals;
- every execution entry point fails closed with `ExternalDialecticDisabled`.

`maworld_self_audit.py` reports only a non-authoritative `BLOCKED` status and
returns exit code 2 when executed directly.
