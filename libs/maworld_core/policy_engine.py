"""Policy-as-code engine (Cedar/OPA-style, taken from competitor research). Deterministic runtime
decision on top of capability/gate. DEFAULT-DENY; an explicit FORBID ALWAYS overrides any PERMIT
(provably safe ordering). Fine-grained: principal × action × resource × context-condition."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

@dataclass
class Policy:
    effect: str                       # "PERMIT" | "FORBID"
    principal: str                    # agent id / role / "*"
    action: str
    resource: str                     # "*" or exact
    condition: Callable[[dict], bool] = lambda ctx: True
    def _match(self, principal, action, resource):
        return ((self.principal in ("*", principal)) and (self.action in ("*", action))
                and (self.resource in ("*", resource)))

@dataclass
class Decision:
    allow: bool; reason: str; matched: list = field(default_factory=list)

class PolicyEngine:
    def __init__(self, policies): self.policies = list(policies)
    def evaluate(self, principal, action, resource, context=None):
        ctx = context or {}
        forbids, permits = [], []
        for p in self.policies:
            if p._match(principal, action, resource) and p.condition(ctx):
                (forbids if p.effect == "FORBID" else permits).append(p)
        if forbids:                                  # FORBID overrides everything
            return Decision(False, "explicit FORBID", [f"{p.effect}:{p.action}" for p in forbids])
        if permits:
            return Decision(True, "PERMIT and no FORBID", [f"{p.effect}:{p.action}" for p in permits])
        return Decision(False, "default-deny (no matching PERMIT)")   # DEFAULT DENY
