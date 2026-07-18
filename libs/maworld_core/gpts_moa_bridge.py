"""GPT-S:CORE bridge — MoA consensus + S-Score (cognitive honesty) + Anti-Self (bias) → MAWorld challenger.
A proposal SURVIVES only if: MoA agreement Q>=threshold AND S-Score (honesty) above bar AND no Anti-Self
collusion flag. Feeds dialectic as a proposer/critic — verified-only, never authoritative."""
from __future__ import annotations
from collections import Counter

def moa_consensus(proposals, q_threshold=0.66):
    """proposals: list of {answer, confidence, proposer}. Consensus if top answer's share >= q_threshold."""
    if not proposals: return {"answer": None, "agreement": 0.0, "verified": False}
    votes = Counter(p["answer"] for p in proposals)
    ans, n = votes.most_common(1)[0]
    agreement = n / len(proposals)
    return {"answer": ans, "agreement": round(agreement, 3), "verified": agreement >= q_threshold}

def s_score(claim):
    """Cognitive honesty: high confidence WITHOUT evidence is dishonest -> low score. calibrated -> high."""
    conf = float(claim.get("confidence", 0.5)); has_ev = bool(claim.get("evidence"))
    if conf > 0.7 and not has_ev: return round(1.0 - conf, 3)   # overconfident, unsupported -> penalized
    return round(0.5 + 0.5 * (has_ev), 3)

def anti_self(proposals):
    """Bias/collusion: one proposer casting most votes, or identical proposers -> flagged."""
    proposers = [p.get("proposer") for p in proposals]
    if len(set(proposers)) <= len(proposals) // 2:
        return {"flagged": True, "reason": "too few distinct proposers (self-agreement/collusion)"}
    return {"flagged": False}

def challenge(proposals, q_threshold=0.66, honesty_bar=0.4):
    con = moa_consensus(proposals, q_threshold)
    bias = anti_self(proposals)
    top = [p for p in proposals if p["answer"] == con["answer"]]
    honest = min((s_score(p) for p in top), default=0.0) >= honesty_bar
    survives = con["verified"] and honest and not bias["flagged"]
    return {"verdict": "ACT" if survives else "HOLD", "consensus": con,
            "honest": honest, "anti_self": bias, "authoritative": False}
