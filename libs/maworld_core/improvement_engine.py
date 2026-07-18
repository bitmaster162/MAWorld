"""Improvement engine — bounded self-improvement (docs/04). Cycle (global-rooted):
SENSE -> PROPOSE -> EVALUATE -> GATE -> CANARY. Regression BLOCKS. FORBIDDEN classes (touching the
gate / authority / kill-switch / capability keys) are ALWAYS blocked, even if metrics improve. Any
evaluation error -> kill-switch fail-closed (HOLD). Proposals are proposal-only (authoritative=False):
an approved improvement still executes via action_authority + human confirm, never by the engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from maworld_core.global_cycle import open_global, derive

FORBIDDEN = {"gate", "authority", "kill_switch", "capability_key", "canon_writer", "secrets_broker"}

@dataclass
class ImprovementProposal:
    target: str
    change: str
    metric_before: float
    touches: set = field(default_factory=set)   # subsystems the change modifies
    authoritative: bool = False                 # proposal-only, always

@dataclass
class Verdict:
    stage: str; decision: str; reason: str; metric_after: float | None = None

def sense(signal_metric: float, threshold: float) -> bool:
    return signal_metric < threshold   # e.g., acceptance-rate below target -> improvement warranted

def run_improvement(prop: ImprovementProposal, evaluate, worldview: dict) -> Verdict:
    # global-rooted cycle (invariant)
    g = open_global("improve:" + prop.target, worldview); derive(g, "evaluate-improvement")
    # GATE — forbidden classes blocked FIRST, regardless of metrics
    if prop.touches & FORBIDDEN:
        return Verdict("GATE", "BLOCK", f"forbidden class touched: {sorted(prop.touches & FORBIDDEN)}")
    # EVALUATE against golden/eval set; kill-switch fail-closed on error
    try:
        metric_after = float(evaluate(prop))
    except Exception as e:
        return Verdict("EVALUATE", "HOLD", f"kill-switch fail-closed: {str(e)[:40]}")
    # regression blocks
    if metric_after < prop.metric_before:
        return Verdict("EVALUATE", "BLOCK", "regression", metric_after)
    if metric_after == prop.metric_before:
        return Verdict("EVALUATE", "HOLD", "no improvement", metric_after)
    # CANARY — approved improvement is a PROPOSAL for gated rollout, engine does not apply it itself
    return Verdict("CANARY", "PROPOSE_ROLLOUT", "improved, gated canary proposed", metric_after)
