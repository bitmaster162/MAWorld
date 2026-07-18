"""Agent registry — 'discover' stage (from Arthur lifecycle) + NHI/SPIFFE-style ephemeral identity.
Every agent is a Non-Human Identity with a short-lived, expiring registration. Actions from unknown or
expired agents are SHADOW (the '82% agents security didn't know about' problem) and are flagged."""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field

@dataclass
class NHIRegistration:
    agent_id: str
    workload: str                     # SPIFFE-like: spiffe://maworld/<role>
    expires_at: float
    spiffe_id: str = ""
    def valid(self, now=None):
        return (now or time.time()) < self.expires_at

class AgentRegistry:
    def __init__(self): self._reg = {}
    def register(self, role: str, ttl_sec=300) -> NHIRegistration:
        aid = "agent-" + uuid.uuid4().hex[:10]
        r = NHIRegistration(aid, "spiffe://maworld/" + role, time.time() + ttl_sec,
                            spiffe_id="spiffe://maworld/" + role + "/" + aid)
        self._reg[aid] = r; return r
    def is_known(self, agent_id, now=None):
        r = self._reg.get(agent_id)
        return bool(r and r.valid(now))
    def discover_shadow(self, observed_agent_ids, now=None):
        """Return agents acting in the system that are NOT registered/valid = shadow agents."""
        return [a for a in observed_agent_ids if not self.is_known(a, now)]
    def admit_action(self, agent_id, now=None):
        if not self.is_known(agent_id, now):
            return {"admit": False, "reason": "SHADOW or expired NHI (discover-stage block)"}
        return {"admit": True, "spiffe_id": self._reg[agent_id].spiffe_id}
