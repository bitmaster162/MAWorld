"""Entry Queue Calibration Model — implemented FROM the owner's own guide, not invented here.

Source: cryptoguidessite.vercel.app/guides/queue-calibration-model ("from bot v17", published 2026-06-25).
The crosswalk in cryptoguides_bridge flagged this guide as naming our OPEN GAP: arena_frictions shipped
with hard-coded gamma/eta and no way to learn from reality. The guide already had the answer — a closed
feedback loop that compares what the queue simulator EXPECTED with what the exchange ACTUALLY did.

The guide's algorithm, kept verbatim:
    Shortfall = max(0, Fill_Ratio_exp - Fill_Ratio_act)
    Overshoot = max(0, Latency_act - Clear_Time_exp)
    if Overshoot > latency_overshoot_alert_threshold (= 2.0 s) -> recalibrate_queue_simulator:
        reduce the FlowRate coefficient (make queue-time estimates more conservative)

What we ADD (and why): the guide says the system "automatically corrects the simulator". Unbounded
self-tuning of risk-relevant parameters is how a model quietly drifts into nonsense — so here the loop
is BOUNDED (max step, hard floor/ceiling) and every recalibration is a PROPOSAL carrying evidence, not
a silent write. Same posture as improvement_engine: bounded self-improvement, never self-authorised.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass, field

from maworld_core.action_authority import (
    ActionExecutor,
    ActionSpec,
    ActionVerifier,
    ConfusedDeputy,
    Decision,
    HumanConfirmation,
)

LATENCY_OVERSHOOT_ALERT_THRESHOLD = 2.0     # seconds — the guide's constant, unchanged
MAX_STEP = 0.20                             # ours: at most a 20% move per recalibration
FLOW_RATE_FLOOR, FLOW_RATE_CEIL = 0.10, 3.0 # ours: the loop can never tune itself to absurdity

@dataclass
class QueueExpectation:
    """What the simulator predicted before the order was sent."""
    fill_ratio_exp: float          # 0..1
    clear_time_exp: float          # seconds
    book_to_order_ratio: float = 1.0
    flow_rate: float = 1.0

@dataclass
class QueueOutcome:
    """What the exchange actually did."""
    fill_ratio_act: float          # 0..1
    latency_act: float             # seconds
    sent_qty: float = 0.0
    executed_qty: float = 0.0
    timeout: bool = False

def audit(exp: QueueExpectation, out: QueueOutcome) -> dict:
    """The guide's error metrics, exactly."""
    shortfall = max(0.0, exp.fill_ratio_exp - out.fill_ratio_act)
    overshoot = max(0.0, out.latency_act - exp.clear_time_exp)
    trigger = overshoot > LATENCY_OVERSHOOT_ALERT_THRESHOLD
    return {"shortfall": round(shortfall, 6), "overshoot": round(overshoot, 6),
            "recalibrate": trigger,
            "action": "recalibrate_queue_simulator" if trigger else "none",
            "threshold": LATENCY_OVERSHOOT_ALERT_THRESHOLD,
            "timeout": out.timeout}

class QueueCalibrator:
    """Bounded calibrator whose writes cross the canonical authority boundary.

    Observation is safe without an executor and remains proposal-only.  Applying a
    proposal requires a verifier and durable nonce store fixed at construction plus
    an exact, signed :class:`Decision`; a caller-supplied boolean is never authority.
    """

    _HANDLER_ID = "queue.calibration.apply"

    def __init__(self, flow_rate: float = 1.0, *, calibrator_id: str = "queue-default",
                 verifier: ActionVerifier | None = None, nonce_store=None):
        initial = float(flow_rate)
        if not math.isfinite(initial) or not FLOW_RATE_FLOOR <= initial <= FLOW_RATE_CEIL:
            raise ValueError("initial flow_rate is outside the bounded policy")
        if not isinstance(calibrator_id, str) or not calibrator_id.strip():
            raise ValueError("calibrator_id must be a non-empty string")
        if (verifier is None) != (nonce_store is None):
            raise ValueError("verifier and durable nonce_store must be configured together")
        self._flow_rate = initial
        self._calibrator_id = calibrator_id
        self.history: list[dict] = []
        self._executor = None
        if verifier is not None:
            self._executor = ActionExecutor(
                {self._HANDLER_ID: self._commit_authorized}, verifier, nonce_store
            )

    @property
    def flow_rate(self) -> float:
        return self._flow_rate

    def observe(self, exp: QueueExpectation, out: QueueOutcome) -> dict:
        a = audit(exp, out)
        proposal = None
        if a["recalibrate"]:
            # more overshoot -> more conservative flow rate, but never more than MAX_STEP at once
            severity = min(1.0, a["overshoot"] / max(1e-9, LATENCY_OVERSHOOT_ALERT_THRESHOLD) - 1.0)
            step = min(MAX_STEP, MAX_STEP * max(0.0, severity) + 0.05)
            target = max(FLOW_RATE_FLOOR, min(FLOW_RATE_CEIL, self.flow_rate * (1.0 - step)))
            proposal = {"param": "flow_rate", "from": round(self.flow_rate, 6),
                        "to": round(target, 6), "step_pct": round(step * 100, 2),
                        "reason": f"latency overshoot {a['overshoot']:.2f}s > "
                                  f"{LATENCY_OVERSHOOT_ALERT_THRESHOLD}s threshold",
                        "authoritative": False, "bounded_by": [FLOW_RATE_FLOOR, FLOW_RATE_CEIL, MAX_STEP]}
        rec = {**a, "proposal": proposal}
        self.history.append(rec)
        return rec

    def _normalize_proposal(self, proposal: dict) -> tuple[dict | None, str | None]:
        if not isinstance(proposal, dict) or not proposal:
            return None, "no proposal"
        if proposal.get("param") != "flow_rate" or proposal.get("authoritative") is not False:
            return None, "only a non-authoritative flow_rate proposal is accepted"
        try:
            source = float(proposal["from"])
            target = float(proposal["to"])
        except (KeyError, TypeError, ValueError):
            return None, "proposal endpoints must be finite numbers"
        if not math.isfinite(source) or not math.isfinite(target):
            return None, "proposal endpoints must be finite numbers"
        if abs(source - self._flow_rate) > 1e-9:
            return None, "proposal is stale or belongs to another calibrator state"
        if not FLOW_RATE_FLOOR <= target <= FLOW_RATE_CEIL:
            return None, f"out of bounds [{FLOW_RATE_FLOOR},{FLOW_RATE_CEIL}]"
        if abs(target - self._flow_rate) / max(1e-9, self._flow_rate) > MAX_STEP + 1e-9:
            return None, f"step exceeds MAX_STEP {MAX_STEP}"
        normalized = dict(proposal)
        normalized["from"] = source
        normalized["to"] = target
        try:
            json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            return None, "proposal must be canonical JSON"
        return normalized, None

    def action_spec(self, proposal: dict) -> ActionSpec:
        """Return the exact action that an external gate must sign."""
        normalized, reason = self._normalize_proposal(proposal)
        if normalized is None:
            raise ValueError(reason)
        encoded = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        return ActionSpec(
            "queue.calibration.apply",
            self._calibrator_id,
            (encoded, format(self._flow_rate, ".17g")),
            handler_id=self._HANDLER_ID,
        )

    def _commit_authorized(self, spec: ActionSpec) -> dict:
        proposal = json.loads(spec.params[0])
        normalized, reason = self._normalize_proposal(proposal)
        if normalized is None:
            raise ConfusedDeputy(reason)
        self._flow_rate = normalized["to"]
        return {"applied": True, "flow_rate": self._flow_rate}

    def apply(self, proposal: dict, decision: Decision | None = None,
              confirmation: HumanConfirmation | None = None) -> dict:
        """Apply only an externally signed decision bound to this exact proposal."""
        try:
            spec = self.action_spec(proposal)
        except (TypeError, ValueError) as exc:
            return {"applied": False, "reason": str(exc)}
        if self._executor is None:
            return {"applied": False, "reason": "authorized executor is not configured"}
        if not isinstance(decision, Decision):
            return {"applied": False, "reason": "signed action decision required"}
        try:
            result = self._executor.execute(spec, decision, confirmation=confirmation)
        except ConfusedDeputy as exc:
            return {"applied": False, "reason": str(exc)}
        return result["result"]

    def stats(self) -> dict:
        n = len(self.history)
        trig = [h for h in self.history if h["recalibrate"]]
        return {"observations": n, "recalibrations": len(trig), "flow_rate": round(self.flow_rate, 6),
                "mean_shortfall": round(sum(h["shortfall"] for h in self.history) / n, 6) if n else 0.0,
                "mean_overshoot": round(sum(h["overshoot"] for h in self.history) / n, 6) if n else 0.0}

# ---- the same feedback loop, pointed at arena_frictions (this is what closes OUR gap) ----
def calibrate_impact(predicted_bps: float, realized_bps: float, eta_coeff: float,
                     max_step: float = MAX_STEP) -> dict:
    """arena_frictions shipped with a guessed eta. The guide's pattern generalises: compare PREDICTED
    impact against REALIZED impact and nudge the coefficient, bounded. A proposal, never a silent write."""
    if predicted_bps <= 0: return {"proposal": None, "reason": "no prediction to calibrate against"}
    err = (realized_bps - predicted_bps) / predicted_bps        # >0 => we under-predicted impact
    step = max(-max_step, min(max_step, err))
    target = max(0.01, eta_coeff * (1.0 + step))
    return {"proposal": {"param": "eta_coeff", "from": eta_coeff, "to": round(target, 6),
                         "error_pct": round(err * 100, 2),
                         "direction": "under-predicted impact" if err > 0 else "over-predicted impact",
                         "authoritative": False, "bounded_step": max_step},
            "reason": "calibrated from realized vs predicted impact"}
