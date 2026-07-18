"""Z3 checks for a small, explicit Boolean policy IR.

This module does not claim to prove the Python ``PolicyEngine``.  It proves only
properties of :class:`LiveActionPolicyIR` and :class:`DefaultDenyPolicyIR`, whose
runtime relation is encoded independently as an equality before the invariant is
negated.  A future compiler from the production policy representation is required
before these results can be called production-policy proofs.

Only ``unsat`` is reported as PROVEN.  ``unknown`` and a missing backend are
explicit non-proof states.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    import z3
except ImportError:
    z3 = None


def solver_backend_available() -> bool:
    return z3 is not None


@dataclass(frozen=True)
class LiveActionPolicyIR:
    allow_non_live: bool = True
    allow_live_with_confirmation: bool = True
    allow_live_without_confirmation: bool = False

    def __post_init__(self):
        if any(
            not isinstance(value, bool)
            for value in (
                self.allow_non_live,
                self.allow_live_with_confirmation,
                self.allow_live_without_confirmation,
            )
        ):
            raise TypeError("LiveActionPolicyIR fields must be booleans")


@dataclass(frozen=True)
class DefaultDenyPolicyIR:
    default_allow: bool = False

    def __post_init__(self):
        if not isinstance(self.default_allow, bool):
            raise TypeError("default_allow must be boolean")


def _backend_unavailable():
    return "BACKEND_UNAVAILABLE", {"reason": "z3-solver is not installed"}


def _finish(solver, symbols):
    status = solver.check()
    if status == z3.unsat:
        return "PROVEN", None
    if status == z3.sat:
        model = solver.model()
        counterexample = {
            name: bool(z3.is_true(model.eval(symbol, model_completion=True)))
            for name, symbol in symbols.items()
        }
        return "VIOLATED", counterexample
    return "UNKNOWN", {"reason": solver.reason_unknown() or "solver returned unknown"}


def prove_no_live_without_confirm(policy: LiveActionPolicyIR | bool):
    """Check ``allowed and live -> confirmed`` for the restricted policy IR.

    A bool is accepted as a compatibility shorthand for the IR field
    ``allow_live_without_confirmation``.
    """
    if z3 is None:
        return _backend_unavailable()
    if isinstance(policy, bool):
        policy = LiveActionPolicyIR(
            allow_live_without_confirmation=policy
        )
    if not isinstance(policy, LiveActionPolicyIR):
        raise TypeError("policy must be LiveActionPolicyIR or bool shorthand")

    is_live, has_confirm, allowed = z3.Bools(
        "live_ir_is_live live_ir_has_confirm live_ir_allowed"
    )
    runtime_relation = z3.Or(
        z3.And(z3.Not(is_live), z3.BoolVal(policy.allow_non_live)),
        z3.And(
            is_live,
            has_confirm,
            z3.BoolVal(policy.allow_live_with_confirmation),
        ),
        z3.And(
            is_live,
            z3.Not(has_confirm),
            z3.BoolVal(policy.allow_live_without_confirmation),
        ),
    )
    solver = z3.Solver()
    solver.add(allowed == runtime_relation)
    solver.add(allowed, is_live, z3.Not(has_confirm))
    return _finish(solver, {
        "allowed": allowed, "is_live": is_live, "has_confirm": has_confirm,
    })


def prove_default_deny(policy: DefaultDenyPolicyIR | bool = False):
    """Check that no request is allowed without a matching permit in the IR."""
    if z3 is None:
        status, detail = _backend_unavailable()
        return status, detail
    if isinstance(policy, bool):
        policy = DefaultDenyPolicyIR(default_allow=policy)
    if not isinstance(policy, DefaultDenyPolicyIR):
        raise TypeError("policy must be DefaultDenyPolicyIR or bool shorthand")

    permit, allowed = z3.Bools("default_ir_permit default_ir_allowed")
    runtime_relation = z3.Or(permit, z3.BoolVal(policy.default_allow))
    solver = z3.Solver()
    solver.add(allowed == runtime_relation)
    solver.add(allowed, z3.Not(permit))
    return _finish(solver, {"allowed": allowed, "permit": permit})
