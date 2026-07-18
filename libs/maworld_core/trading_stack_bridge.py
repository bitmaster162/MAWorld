"""Trading-stack bridge — connect the real continuity_os `trading-stack` (144/144 tests) to MAWorld,
proposal-only. Their contracts.py 5-type pipeline maps 1:1 onto the MAWorld spine:

  SignalReport      -> input_guard (untrusted) + risk admit          (is the signal safe/allowed?)
  GateDecision      -> policy_engine + action_authority (hash-bound)  (does policy+gate authorize THIS?)
  ApprovalDecision  -> control_plane human-confirm (high-impact)       (did the owner confirm?)
  ExecutionIntent   -> trading_safety (units) + agent_mandate          (unit-safe + within a signed mandate)
  ExecutionEvent    -> hardened_effect_registry (exactly-once) + Article12 record + Evidence acceptance

Live OFF: everything returns PROPOSALS (authoritative=False); actual execution stays behind the gate +
capability + human confirm on a real box. No live capital.
"""
from __future__ import annotations
import time
from maworld_core.input_guard import admit_input
from maworld_core.action_authority import ActionSpec
from maworld_core.trading_safety import RiskDecision, InstrumentSpec, fixed_to_qty
from maworld_core.article12_export import Article12Record, ComplianceLog
from decimal import Decimal

def process_signal(signal: dict, risk_bps: int, spec: InstrumentSpec, compliance: ComplianceLog):
    """One pass of the 5-type pipeline as PROPOSALS + an Article-12 record."""
    out = {"stages": {}, "authoritative": False}
    # 1) SignalReport -> untrusted-input + risk
    adm = admit_input(str(signal.get("rationale","")), source=signal.get("source","internal"))
    if not adm["admit"]:
        out["stages"]["SignalReport"] = {"blocked": adm["reason"]}; out["decision"] = "REJECT"; return out
    rd = RiskDecision("ALLOW", risk_bps) if risk_bps <= 100 else RiskDecision("DENY", risk_bps, "RISK>1%")
    out["stages"]["SignalReport"] = {"admitted": True, "risk": rd.kind}
    if rd.kind != "ALLOW":
        out["decision"] = "RISK_DENY"; _log(compliance, signal, "DENY", risk_bps); return out
    # 2) GateDecision -> action_authority (hash-bound to the exact order)
    ordspec = ActionSpec("venue.order", signal.get("instrument","BTCUSDT"),
                         (signal.get("side","BUY"), str(signal.get("qty_fixed",0))))
    # Proposal only: a trusted external DecisionIssuer must later sign this exact
    # spec with REQUIRE_CONFIRMATION.  This bridge cannot mint executable authority.
    out["stages"]["GateDecision"] = {
        "spec_hash": ordspec.hash()[:12],
        "verdict": "REQUIRE_CONFIRMATION",
        "requires": "external DecisionIssuer",
        "authoritative": False,
    }
    # 3) ApprovalDecision -> control_plane (owner confirm bound to hash) — PROPOSED, not auto
    out["stages"]["ApprovalDecision"] = {"needs": "signed owner confirmation bound to Decision digest", "authoritative": False}
    # 4) ExecutionIntent -> unit-safe quantity
    try:
        qty = fixed_to_qty(int(signal.get("qty_fixed", 0)), spec)
        out["stages"]["ExecutionIntent"] = {"qty": str(qty), "unit_safe": True}
    except Exception as e:
        out["stages"]["ExecutionIntent"] = {"blocked": str(e)[:50]}; out["decision"] = "UNIT_REJECT"; return out
    # 5) ExecutionEvent -> would go through hardened_effect_registry (exactly-once), live OFF
    out["stages"]["ExecutionEvent"] = {"status": "PROPOSED (live OFF; needs gate+confirm+registry on box)"}
    _log(compliance, signal, "REQUIRE_CONFIRMATION", risk_bps, ordspec.hash())
    out["decision"] = "PROPOSE_GATED_ORDER"
    return out

def _log(compliance, signal, decision, risk_bps, spec_hash=""):
    compliance.append(Article12Record(
        agent_id=signal.get("agent_id","trading-stack"), action="venue.order.proposal",
        event_time=time.time(), decision=decision, capability_ref="cap-trading",
        risk_level="high" if risk_bps>100 else "low", evidence_ref=spec_hash))
