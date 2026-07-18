"""Global-cycle invariant — MAWorld worldview, canon of ContinuityOS.

"Любой цикл начинается от глобального." Two facets, enforced structurally:

  1) TOP-DOWN CASCADE: every cycle MUST open at the GLOBAL scope. A sub-scope can ONLY be derived from
     its parent (GLOBAL -> STRATEGIC -> TACTICAL -> EXECUTION). You cannot create a tactical/execution
     node at top level, and you cannot skip a level. Anomalies/signals are inputs, never cycle roots.
  2) FRACTAL SELF-SIMILARITY: every node carries a reflection of the whole — the immutable `worldview`
     hash + the global objective id. "Каждый узел содержит отражение целого" (canon).

Canon source: continuity_os/00_CANON/HUMAN_CANON.md (Изучение→Создание→Деплой→Интеграция, boot reads
GLOBAL canon first), COEVOLUTION_HUMAN_AI_ARCHITECTURE_v1.md (стратегические циклы), fractal principle.
Authority-neutral: this shapes the SHAPE of every cycle; it does not grant power.
"""
from __future__ import annotations
import hashlib, json, uuid
from dataclasses import dataclass, field

SCOPES = ["GLOBAL", "STRATEGIC", "TACTICAL", "EXECUTION"]
_ORDER = {s: i for i, s in enumerate(SCOPES)}


class CycleInvariantError(RuntimeError):
    """Raised when a cycle would violate 'начинается от глобального' (top-down cascade / fractal)."""


def worldview_hash(worldview: dict) -> str:
    return hashlib.sha256(json.dumps(worldview, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class CycleNode:
    scope: str
    intent: str
    worldview: str                 # fractal: reflection of the whole (immutable across the cycle)
    global_objective_id: str       # every node points back to the global objective
    node_id: str = field(default_factory=lambda: "cyc-" + uuid.uuid4().hex[:10])
    parent_id: str | None = None
    def reflects_whole(self) -> bool:
        return bool(self.worldview) and bool(self.global_objective_id)


def open_global(objective: str, worldview: dict) -> CycleNode:
    """The ONLY way to root a cycle. Everything descends from here."""
    wv = worldview_hash(worldview)
    gid = "obj-" + hashlib.sha256((objective + wv).encode()).hexdigest()[:10]
    return CycleNode("GLOBAL", objective, wv, gid, parent_id=None)


def derive(parent: CycleNode, intent: str) -> CycleNode:
    """Descend exactly ONE level. Cannot skip levels, cannot go up, cannot exceed EXECUTION.
    The child inherits the whole (worldview + global objective) — fractal self-similarity."""
    ci = _ORDER[parent.scope] + 1
    if ci >= len(SCOPES):
        raise CycleInvariantError(f"cannot descend below {parent.scope} (EXECUTION is terminal)")
    return CycleNode(SCOPES[ci], intent, parent.worldview, parent.global_objective_id,
                     parent_id=parent.node_id)


def validate_chain(chain: list[CycleNode]) -> bool:
    """A well-formed cycle: starts at GLOBAL, descends one level at a time, every node reflects the
    whole with the SAME worldview + global objective as the root."""
    if not chain or chain[0].scope != "GLOBAL" or chain[0].parent_id is not None:
        raise CycleInvariantError("cycle must start from GLOBAL (начинается от глобального)")
    root = chain[0]
    for i, n in enumerate(chain):
        if not n.reflects_whole():
            raise CycleInvariantError(f"node {n.scope} does not reflect the whole (fractal broken)")
        if n.worldview != root.worldview or n.global_objective_id != root.global_objective_id:
            raise CycleInvariantError(f"node {n.scope} lost the global reflection")
        if i > 0:
            if _ORDER[n.scope] != _ORDER[chain[i-1].scope] + 1:
                raise CycleInvariantError(f"level skip/ascent at {n.scope} (top-down cascade broken)")
            if n.parent_id != chain[i-1].node_id:
                raise CycleInvariantError(f"{n.scope} not derived from its parent")
    return True
