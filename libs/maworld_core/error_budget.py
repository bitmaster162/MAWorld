"""Error budget (SRE-for-agents, from research): reliability = decision quality + safe-halt behavior.
An agent earns autonomy with a clean record; a burning budget triggers exhaustion_action
(ALERT->THROTTLE->FREEZE->CIRCUIT_BREAK). Ties to agent_containment (circuit-break = terminate)."""
from __future__ import annotations
import time
from dataclasses import dataclass, field

@dataclass
class Budget:
    budget: float = 1.0            # 1.0 = full monthly error budget
    burn: float = 0.0
    window_start: float = field(default_factory=time.time)
    def record(self, failed: bool, cost=0.05):
        if failed: self.burn += cost
    def remaining(self): return round(max(0.0, self.budget - self.burn), 4)
    def burn_rate(self):  # fraction consumed
        return round(self.burn / self.budget, 4) if self.budget else 1.0

def exhaustion_action(b: Budget):
    r = b.burn_rate()
    if r >= 1.0: return "CIRCUIT_BREAK"     # -> agent_containment.global_kill / terminate
    if r >= 0.75: return "FREEZE_DEPLOYMENTS"
    if r >= 0.5: return "THROTTLE"
    if r >= 0.25: return "ALERT"
    return "OK"

def autonomy_grant(b: Budget, clean_days: float):
    """Clean 30-day record earns autonomy; any burn or short record -> supervised."""
    return "AUTONOMOUS" if (b.burn == 0 and clean_days >= 30) else "SUPERVISED"
