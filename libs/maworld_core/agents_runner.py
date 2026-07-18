"""Agents runner — orchestrator / challenger / executor as PROPOSAL-ONLY runners (CTHA boundary).

Invariants:
  * Every agent cycle STARTS FROM GLOBAL and cascades (global_cycle): objective -> STRATEGIC ->
    TACTICAL -> EXECUTION. Anomalies are inputs, never cycle roots.
  * CTHA boundary: an agent holds NO gate/ledger/canon/secret/tool/effect handle. Its ONLY output is a
    proposal (ActionSpec, authoritative=False). It physically cannot fire an effect — execution happens
    OUTSIDE the agent via action_authority (hash-bound gate) + a signed capability it does not possess.
  * Challenger = dialectic: a proposal SURVIVES only if the challenger does not produce a verified
    refutation (else it is held, not executed).
Every cycle is traced from the GLOBAL span down (trace_bridge), fractal: each node reflects the whole.
"""
from __future__ import annotations
from dataclasses import dataclass
from maworld_core.global_cycle import open_global, derive
from maworld_core.action_authority import ActionSpec
from maworld_core.trace_bridge import Trace


@dataclass
class Proposal:
    action_spec_type: str
    target: str
    params: tuple
    proposed_by: str
    authoritative: bool = False      # ALWAYS False — an agent proposes, never authorizes
    def to_action_spec(self) -> ActionSpec:
        return ActionSpec(self.action_spec_type, self.target, self.params)


class Agent:
    """Base proposal-only agent. Deliberately has NO effect/gate/ledger/capability attributes."""
    def __init__(self, name): self.name = name
    # NOTE: no execute(), no submit(), no ledger/gate handle -> CTHA boundary by construction.


class Orchestrator(Agent):
    def run_cycle(self, objective: str, worldview: dict, target: str, params: tuple):
        """Global-rooted cascade -> emits a PROPOSAL at EXECUTION. Never executes."""
        tr = Trace(objective, worldview)
        g = open_global(objective, worldview)
        strat = derive(g, "strategy"); tac = derive(strat, "tactic"); ex = derive(tac, "emit-proposal")
        s1 = tr.child(tr.root, "strategy"); s2 = tr.child(s1, "tactic"); s3 = tr.child(s2, "emit-proposal")
        prop = Proposal("venue.order", target, params, self.name)
        return {"trace": tr, "cascade": [g.scope, strat.scope, tac.scope, ex.scope], "proposal": prop}


class Challenger(Agent):
    """Dialectic: returns objections. A proposal only survives with NO verified refutation."""
    def critique(self, proposal: Proposal, refutations: list[str] | None = None):
        refutations = refutations or []
        survives = len(refutations) == 0
        return {"survives": survives, "refutations": refutations,
                "verdict": "ACT" if survives else "HOLD"}
