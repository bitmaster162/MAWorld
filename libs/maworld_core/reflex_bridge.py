"""Reflex OODA bridge — connect the real continuity_os reflex arbiter (OODA monitor: anomaly ->
generate_objectives -> SAP-Reviewer gemini generator->critic -> /proposals; exec() DISABLED in prod) to
MAWorld, proposal-only. An anomaly is an INPUT, never a cycle root (global_cycle). Each generated
objective becomes a bounded improvement PROPOSAL run through improvement_engine (SENSE->EVALUATE->GATE->
CANARY): regression BLOCKS, forbidden classes (gate/kill-switch/authority) ALWAYS blocked, evaluation
error -> kill-switch fail-closed. The bridge NEVER executes — reflex's op commands route to gated
proposals (action_authority + human confirm), not auto-exec."""
from __future__ import annotations
from maworld_core.improvement_engine import ImprovementProposal, run_improvement, FORBIDDEN
from maworld_core.action_authority import ActionSpec

def objective_to_proposal(objective: dict, evaluate, worldview: dict):
    """objective: {op, target, anomaly, touches, metric_before}. Returns a gated verdict; never executes."""
    prop = ImprovementProposal(
        target=objective.get("target","unknown"),
        change=f"reflex objective from anomaly: {objective.get('anomaly','')[:60]}",
        metric_before=float(objective.get("metric_before", 0.7)),
        touches=set(objective.get("touches", [])))
    verdict = run_improvement(prop, evaluate, worldview)
    # reflex 'op' (execute_code/patch) never auto-runs — it becomes a gated ActionSpec proposal
    op = objective.get("op")
    gated = None
    if op:
        spec = ActionSpec("reflex."+op, prop.target, (objective.get("anomaly","")[:40],))
        gated = {"spec_hash": spec.hash()[:12], "authoritative": False,
                 "requires": ["policy_engine","action_authority","human_confirm"]}
    return {"verdict": verdict.decision, "reason": verdict.reason, "metric_after": verdict.metric_after,
            "gated_op": gated, "executed": False}   # invariant: bridge never executes
