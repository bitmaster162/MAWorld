"""Model-only optimistic eligibility planner.

This module never executes an effect and never asserts PRODUCT_SUCCESS.  It can
classify a holdable/compensatable proposal during a challenge window;
irreversible work is rejected.  A separate signed authority/effect boundary is
required after an ``eligible_proposal`` result.
"""
from __future__ import annotations
import math, time, uuid
from dataclasses import dataclass, field

EFFECT_CLASSES = {"holdable", "compensatable", "irreversible"}
MODEL_ONLY = True

@dataclass
class OptimisticEffect:
    effect: str
    effect_class: str
    challenge_window_s: float = 30
    id: str = field(default_factory=lambda: "oe-"+uuid.uuid4().hex[:8])
    status: str = "provisional_plan"       # rejected|provisional_plan|eligible_proposal
    effect_state: str = "none"             # model state only; never evidence that an effect fired
    opened_at: float = field(default_factory=time.time)

def accept_provisional(effect: str, effect_class: str, challenge_window_s=30):
    if (
        not isinstance(effect, str) or not effect.strip()
        or isinstance(challenge_window_s, bool)
        or not isinstance(challenge_window_s, (int, float))
        or not math.isfinite(float(challenge_window_s))
        or not 0 <= float(challenge_window_s) <= 86_400
    ):
        raise ValueError("bounded effect name and challenge window required")
    e = OptimisticEffect(effect, effect_class, challenge_window_s)
    if effect_class not in EFFECT_CLASSES:
        e.status="rejected"; e.effect_state="none"; return e
    if effect_class == "irreversible":
        # the core fix: irreversible cannot go optimistic
        e.status="rejected"; e.effect_state="none"; e.reason="irreversible_effect_requires_final_verification"
        return e
    if effect_class == "holdable":
        e.effect_state = "hold_proposed"
    else:  # compensatable
        e.effect_state = "compensatable_proposed"
    return e

def challenge(e: OptimisticEffect, model_fraud_signal: bool):
    """Fail-safe model transition; a signal can only reject, never authorize."""
    if not model_fraud_signal: return e
    if e.effect_state in {"hold_proposed", "compensatable_proposed"}:
        e.effect_state = "voided"
    e.status = "rejected"; return e

def finalize(e: OptimisticEffect):
    """Mark a plan eligible using the local clock; grants no execution authority."""
    now = time.time()
    if e.status == "rejected": return e
    if now - e.opened_at < e.challenge_window_s:
        return e   # window still open — NOT yet PRODUCT_SUCCESS
    e.status = "eligible_proposal"; e.effect_state = "eligible_final_effect"; return e

def is_product_success(e: OptimisticEffect) -> bool:
    """A model result can never establish product success."""
    return False


def is_eligible_proposal(e: OptimisticEffect) -> bool:
    return e.status == "eligible_proposal" and e.effect_state == "eligible_final_effect"
