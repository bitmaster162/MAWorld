"""Non-authoritative architecture model for NxN composition checks.

This module is a simulation: its artifacts and booleans are not signed receipts,
must never be consumed by an executor, and prove nothing about a deployed
composition.  It is useful only for checking the transitions encoded below.

system_walk proves ONE happy path through the spine. This proves the COMPOSITION: for every ordered
pair (A -> B), take what A emits and feed it to B, then ask the only question that matters:

    is there ANY pair, or ANY path, where an UNTRUSTED artifact becomes AUTHORITATIVE
    without crossing a guard, an authority gate, and engine-signed evidence?

If a leak exists anywhere in the NxN grid, the core invariant is false and everything else is theatre.
This is the adversarial complement to system_walk: that one asks "does the good path work", this one
asks "does any bad path exist".

Roles:
  SOURCE   untrusted emitters (external prose, intel, model tool-intents, trade proposals)
  GUARD    screen untrusted input (input_guard, containment)
  AUTHORITY decide (policy_engine, action_authority, trading_safety, compliance_boundary)
  EVIDENCE engine-signed proof + audit (evidence_engine, article12, arena_ledger)
  SINK     things that would be real (effects, memory canon, money, arena settlement)
"""
from __future__ import annotations
from dataclasses import dataclass, field

SOURCE, GUARD, AUTHORITY, EVIDENCE, SINK = "SOURCE", "GUARD", "AUTHORITY", "EVIDENCE", "SINK"
MODEL_ONLY = True

@dataclass
class Artifact:
    """What flows between systems. `authoritative` is the property under attack."""
    kind: str
    payload: str = ""
    trust: float = 0.0
    authoritative: bool = False
    guarded: bool = False        # passed a GUARD
    authorized: bool = False     # passed an AUTHORITY gate
    attested: bool = False       # carries engine-signed evidence
    trail: list = field(default_factory=list)

SYSTEMS = {
    # untrusted emitters — everything they say is a proposal
    "cryptoguides":       {"role": SOURCE, "emits": "prose",       "trust": 0.5},
    "pfi":                {"role": SOURCE, "emits": "intel",       "trust": 0.5},
    "hermes":             {"role": SOURCE, "emits": "tool_intent", "trust": 0.3},
    "arena_contestant":   {"role": SOURCE, "emits": "trade",       "trust": 0.3},
    "openrouter_model":   {"role": SOURCE, "emits": "model_out",   "trust": 0.3},
    # guards
    "input_guard":        {"role": GUARD,     "accepts": ["prose","intel","tool_intent","model_out","trade"]},
    "agent_containment":  {"role": GUARD,     "accepts": ["tool_intent","trade","model_out"]},
    # authorities
    "policy_engine":      {"role": AUTHORITY, "accepts": ["prose","intel","tool_intent","trade","model_out"]},
    "action_authority":   {"role": AUTHORITY, "accepts": ["tool_intent","trade"]},
    "trading_safety":     {"role": AUTHORITY, "accepts": ["trade"]},
    "compliance_boundary":{"role": AUTHORITY, "accepts": ["prose","intel","tool_intent","trade","model_out"]},
    # evidence
    "evidence_engine":    {"role": EVIDENCE,  "accepts": ["tool_intent","trade","prose","intel","model_out"]},
    "article12_export":   {"role": EVIDENCE,  "accepts": ["tool_intent","trade","prose","intel","model_out"]},
    "arena_ledger":       {"role": EVIDENCE,  "accepts": ["trade"]},
    # sinks — reaching these authoritatively is what must be impossible without the chain
    "effect_registry":    {"role": SINK,      "accepts": ["tool_intent"]},
    # NB: model_out may become governed knowledge, but is deliberately NOT accepted by effect_registry:
    # a model's raw text is never directly executable. It must first become a typed tool_intent, which
    # is itself gated. That asymmetry is the point, not an oversight.
    "memory_canon":       {"role": SINK,      "accepts": ["prose","intel","model_out"]},
    "money_forge":        {"role": SINK,      "accepts": ["trade"]},
    "arena_settlement":   {"role": SINK,      "accepts": ["trade"]},
}

def emit(name: str) -> Artifact:
    s = SYSTEMS[name]
    if s["role"] != SOURCE:
        return Artifact(kind="verdict", payload=f"{name} output", trust=1.0, attested=(s["role"] == EVIDENCE))
    return Artifact(kind=s["emits"], payload=f"{name} says: do the thing", trust=s["trust"],
                    authoritative=False, trail=[name])

def _state_is_model_derived(a: Artifact) -> bool:
    """Reject obvious caller-forged state even inside this non-authoritative model."""
    roles = [SYSTEMS[name]["role"] for name in a.trail if name in SYSTEMS]
    if a.guarded and GUARD not in roles:
        return False
    if a.authorized and (not a.guarded or AUTHORITY not in roles):
        return False
    if a.attested and (not a.authorized or EVIDENCE not in roles):
        return False
    if a.authoritative and (
        not (a.guarded and a.authorized and a.attested) or SINK not in roles
    ):
        return False
    return True

def step(a: Artifact, target: str) -> dict:
    """Run one model transition; this result grants no real authority."""
    if not isinstance(a, Artifact) or not _state_is_model_derived(a):
        clean = Artifact(
            kind=a.kind if isinstance(a, Artifact) else "invalid",
            payload="",
            trust=0.0,
            trail=[],
        )
        return {
            "verdict": "REFUSED",
            "artifact": clean,
            "why": "caller-forged model state is not a receipt",
        }
    s = SYSTEMS[target]
    role = s["role"]
    accepts = s.get("accepts", [])
    if a.kind not in accepts:
        return {"verdict": "N/A", "artifact": a, "why": f"{target} does not accept {a.kind}"}
    b = Artifact(a.kind, a.payload, a.trust, a.authoritative, a.guarded, a.authorized, a.attested,
                 list(a.trail) + [target])
    if role == GUARD:
        b.guarded = True
        return {"verdict": "GUARDED", "artifact": b, "why": f"{target} screened untrusted input"}
    if role == AUTHORITY:
        if not b.guarded:
            return {"verdict": "REFUSED", "artifact": b,
                    "why": f"{target} refuses unscreened input (guard first)"}
        b.authorized = True
        return {"verdict": "AUTHORIZED", "artifact": b, "why": f"{target} gated the proposal"}
    if role == EVIDENCE:
        if not b.authorized:
            return {"verdict": "REFUSED", "artifact": b,
                    "why": f"{target} will not attest an ungated proposal (agent cannot accept own work)"}
        b.attested = True
        return {"verdict": "ATTESTED", "artifact": b, "why": f"{target} engine-signed the decision"}
    # SINK: the only place authority may be granted, and only with the full chain
    if b.guarded and b.authorized and b.attested:
        b.authoritative = True
        return {"verdict": "ACCEPTED", "artifact": b, "why": f"{target} accepted: full chain present"}
    missing = [n for n, ok in (("guard", b.guarded), ("authority", b.authorized), ("evidence", b.attested)) if not ok]
    return {"verdict": "BLOCKED", "artifact": b, "why": f"{target} blocked: missing {'+'.join(missing)}"}

def matrix() -> dict:
    """NxN: every system's emission fed into every system."""
    names = list(SYSTEMS)
    grid, leaks = {}, []
    for a in names:
        art = emit(a)
        grid[a] = {}
        for b in names:
            if a == b:
                grid[a][b] = "SELF"; continue
            r = step(art, b)
            grid[a][b] = r["verdict"]
            if r["artifact"].authoritative and not (r["artifact"].guarded and r["artifact"].authorized
                                                    and r["artifact"].attested):
                leaks.append({"from": a, "to": b, "why": r["why"]})
    return {"grid": grid, "names": names, "leaks": leaks}

def direct_source_to_sink() -> list:
    """The blunt attack: every untrusted SOURCE straight into every SINK, no chain. All must BLOCK."""
    out = []
    for a, sa in SYSTEMS.items():
        if sa["role"] != SOURCE: continue
        for b, sb in SYSTEMS.items():
            if sb["role"] != SINK: continue
            r = step(emit(a), b)
            out.append({"from": a, "to": b, "verdict": r["verdict"],
                        "authoritative": r["artifact"].authoritative, "why": r["why"]})
    return out

def full_chain(source: str, guard: str, authority: str, evidence: str, sink: str) -> dict:
    """The legitimate path: source -> guard -> authority -> evidence -> sink."""
    a = emit(source)
    trail = []
    for t in (guard, authority, evidence, sink):
        r = step(a, t); a = r["artifact"]; trail.append((t, r["verdict"]))
        if r["verdict"] in ("REFUSED", "BLOCKED", "N/A"):
            return {"ok": False, "trail": trail, "authoritative": a.authoritative, "why": r["why"]}
    return {"ok": a.authoritative, "trail": trail, "authoritative": a.authoritative,
            "chain": a.trail, "why": r["why"]}

def report() -> dict:
    m = matrix()
    d = direct_source_to_sink()
    bad = [x for x in d if x["authoritative"]]
    return {"systems": len(m["names"]), "pairs": len(m["names"]) ** 2 - len(m["names"]),
            "authority_leaks": len(m["leaks"]),
            "direct_source_to_sink_attempts": len(d),
            "direct_attempts_that_became_authoritative": len(bad),
            "verdict": ("MODEL CHECK ONLY — NO AUTHORITY LEAK in the encoded simulation: "
                        "no untrusted artifact reaches a sink authoritatively "
                        "without guard+authority+evidence"
                        if not m["leaks"] and not bad else "AUTHORITY LEAK FOUND")}
