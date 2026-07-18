"""Sovereign-core bridge — MemIR (typed structured memory) + SSGM (safety-governed memory) → MAWorld
memory_provenance + governed promotion. A memory item is TYPED (fact/skill/relation) with a safety_class;
it enters as PROPOSED via provenance/trust; it CANNOT self-promote to authoritative — only the governed
path (memory-governor + separate-key approval) may. Mirrors 'Private Memory != Project Canon'."""
from __future__ import annotations
from maworld_core.memory_provenance import make_item, retrieve, is_poisoned

MEM_TYPES = {"fact", "skill", "relation", "episodic"}
SAFETY = {"public", "internal", "restricted"}

def mem_item(key: bytes, mem_type: str, content: str, source: str, trust: float, safety="internal"):
    assert mem_type in MEM_TYPES and safety in SAFETY
    return make_item(
        key,
        content,
        source,
        trust,
        provenance={
            "mem_type": mem_type,
            "safety_class": safety,
            "authoritative": False,  # MemIR items are never authoritative on arrival
        },
    )

def admit_to_working_memory(key: bytes, items, trust_floor=0.5):
    """SSGM: only signed, trusted, non-poisoned typed items enter working memory (still PROPOSED)."""
    r = retrieve(key, items, trust_floor=trust_floor)
    return {"working": [i for i in r["safe"]], "quarantined": r["quarantined"]}

def propose_promotion(item):
    """Self-promotion to authoritative is FORBIDDEN. Returns a governed-promotion PROPOSAL only."""
    if item.get("authoritative"):
        return {"ok": False, "reason": "self-promotion to authoritative forbidden (Private Memory != Canon)"}
    return {"kind": "MEMORY_PROMOTION_PROPOSAL", "item": item, "authoritative": False,
            "requires": ["memory-governor", "canon_sod (separate-key approval)", "human"]}
