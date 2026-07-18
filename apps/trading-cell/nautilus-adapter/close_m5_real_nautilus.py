"""Retired historical Nautilus backtest spike.

The original spike embedded a permissive local gate and caller-supplied
reconciliation flag. It is intentionally non-runnable: active integrations
must use ``maworld_core.nautilus_bridge.NautilusRiskGate``, which consumes a
verified short-lived risk snapshot and emits proposals only.
"""

raise SystemExit(
    "historical spike retired; use the canonical proposal-only Nautilus bridge"
)
