"""Trace bridge — OTel/OpenInference spans + cost-per-verified-outcome.

Follows the global-cycle invariant: every trace is ROOTED at a GLOBAL span and descends
(GLOBAL->STRATEGIC->TACTICAL->EXECUTION) — spans mirror cycles. Each span binds to an Evidence
`claim_id`, so cost-per-verified-outcome = total spend on the trace / number of ACCEPTED claims.
Emits OpenInference/OTel gen_ai.* attributes; Langfuse is one exporter behind an interface.
"""
from __future__ import annotations
import time, uuid
from dataclasses import dataclass, field
from maworld_core.global_cycle import open_global, derive, CycleNode, _ORDER, SCOPES, CycleInvariantError


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    scope: str
    name: str
    node: CycleNode
    attributes: dict = field(default_factory=dict)   # OpenInference gen_ai.* etc.
    cost_usd: float = 0.0
    claim_id: str | None = None
    ts: float = field(default_factory=time.time)


class Trace:
    def __init__(self, objective: str, worldview: dict):
        self.trace_id = "tr-" + uuid.uuid4().hex[:12]
        self._root_node = open_global(objective, worldview)     # GLOBAL root (invariant)
        self.spans: list[Span] = []
        self.root = self._span(None, self._root_node, "global:" + objective)

    def _span(self, parent_span, node, name, attrs=None):
        sp = Span(self.trace_id, "sp-" + uuid.uuid4().hex[:10],
                  parent_span.span_id if parent_span else None, node.scope, name, node,
                  dict(attrs or {}))
        self.spans.append(sp); return sp

    def child(self, parent_span: Span, name: str, attrs=None) -> Span:
        node = derive(parent_span.node, name)   # descends exactly one level (global-cycle enforced)
        # OpenInference/OTel gen_ai shape
        a = {"gen_ai.operation.name": name, "maworld.scope": node.scope,
             "maworld.global_objective_id": node.global_objective_id}
        a.update(attrs or {})
        return self._span(parent_span, node, name, a)

    def record_cost(self, span: Span, usd: float, model=None, tokens=None):
        span.cost_usd += usd
        if model: span.attributes["gen_ai.request.model"] = model
        if tokens is not None: span.attributes["gen_ai.usage.total_tokens"] = tokens

    def bind_claim(self, span: Span, claim_id: str):
        span.claim_id = claim_id
        span.attributes["maworld.claim_id"] = claim_id

    def total_cost(self) -> float:
        return round(sum(s.cost_usd for s in self.spans), 6)

    def cost_per_verified_outcome(self, accepted_claim_ids: set) -> float | None:
        bound = {s.claim_id for s in self.spans if s.claim_id}
        verified = bound & set(accepted_claim_ids)
        if not verified: return None                 # no verified outcome yet -> undefined (honest)
        return round(self.total_cost() / len(verified), 6)


class LangfuseExporter:
    """One exporter behind an interface (MIT, self-host). Emits OpenInference-shaped spans."""
    def __init__(self): self.exported = []
    def export(self, trace: Trace):
        for s in trace.spans:
            self.exported.append({"trace_id": s.trace_id, "span_id": s.span_id,
                                  "parent": s.parent_span_id, "name": s.name,
                                  "attributes": s.attributes, "cost_usd": s.cost_usd,
                                  "claim_id": s.claim_id})
        return len(self.exported)
