"""SAP Loop B bridge — connect continuity_os state_authority_plane_live (Loop B: reconcile pipelines +
adaptive delegation gate + machine_verified promotion) to MAWorld authority. Promotion of a fact to
authoritative state goes ONLY through the governed path: machine_verified evidence AND a separate-key
approval (canon_sod). Delegation is a signed capability, never inferred from reputation. Proposal-only."""
from __future__ import annotations
from maworld_core.canon_sod import CanonPromoter, candidate_hash
from maworld_core.capability import mint_capability, verify_capability

# truth ladder (SAP): claimed -> evidenced -> machine_verified -> (governed) -> authoritative
LADDER = ["claimed", "evidenced", "machine_verified"]

def can_promote(truth_level: str) -> bool:
    return truth_level == "machine_verified"   # only machine_verified is eligible for governed promotion

def promote_entity(entity: dict, approval: dict, promoter: CanonPromoter):
    """entity: {id, truth_level, ...}. Promotion requires machine_verified + separate-key approval."""
    if not can_promote(entity.get("truth_level")):
        return {"promoted": False, "reason": f"truth_level '{entity.get('truth_level')}' not machine_verified"}
    return promoter.promote(entity, approval)   # canon_sod: separate-key approval + durable nonce + atomic

def delegate(cap_key: bytes, subject: str, action: str, resource: str, exp: float) -> str:
    """Adaptive delegation = a SIGNED capability bound to (subject, action, resource). Not reputation."""
    return mint_capability(cap_key, subject, action, resource, exp)

def check_delegation(cap_key: bytes, token: str, subject: str, action: str, resource: str) -> bool:
    return verify_capability(cap_key, token, subject, action, resource)
