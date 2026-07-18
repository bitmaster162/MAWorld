"""Agent containment — from our OWN PFI signals ('47% saw unauthorized agent behavior, only 5% could
contain'; 'can't terminate a misbehaving agent = kill-switch demand'). Immediate revoke/quarantine of a
misbehaving NHI + a GLOBAL kill-switch. Once terminated, every action of that agent is blocked. Ties to
agent_registry (NHI identity)."""
from __future__ import annotations

class Containment:
    def __init__(self, registry):
        self.registry = registry
        self._terminated = set()      # agent_ids: all actions blocked
        self._quarantined = set()     # agent_ids: read-only (Safe Mode)
        self._global_kill = False
    def terminate(self, agent_id):    self._terminated.add(agent_id)
    def quarantine(self, agent_id):   self._quarantined.add(agent_id)
    def release(self, agent_id):      self._terminated.discard(agent_id); self._quarantined.discard(agent_id)
    def global_kill(self):            self._global_kill = True
    def global_restore(self):         self._global_kill = False
    def admit(self, agent_id, write=False):
        """Containment gate BEFORE the registry/discover check. Fail-closed under global kill."""
        if self._global_kill:
            return {"admit": False, "reason": "GLOBAL KILL-SWITCH active"}
        if agent_id in self._terminated:
            return {"admit": False, "reason": "agent TERMINATED (contained)"}
        if write and agent_id in self._quarantined:
            return {"admit": False, "reason": "agent QUARANTINED (read-only Safe Mode)"}
        base = self.registry.admit_action(agent_id)   # then normal discover/NHI check
        return base
