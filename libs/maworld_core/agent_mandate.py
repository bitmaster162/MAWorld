"""Agent mandate (AP2 pattern, from machine-economy research: MCP=tools, A2A=talk, x402=pay, AP2=authorize
via tamper-proof signed mandates). An agent may act/pay ONLY within a user-signed INTENT mandate; each
concrete action is a CART mandate that must fall inside the intent (amount cap + allowed action). Mirrors
our control_plane human-confirm + Money Forge. Payment-agnostic (card/bank/crypto)."""
from __future__ import annotations
import hashlib, hmac, time

def _sig(key, body): return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()

def sign_intent(user_key: bytes, user: str, allowed_action: str, max_amount_cents: int, exp: float) -> dict:
    body = f"INTENT:{user}:{allowed_action}:{max_amount_cents}:{int(exp)}"
    return {"user": user, "allowed_action": allowed_action, "max_amount_cents": max_amount_cents,
            "exp": int(exp), "sig": _sig(user_key, body)}

def verify_intent(user_key: bytes, m: dict, now=None) -> bool:
    now = now or time.time()
    body = f"INTENT:{m['user']}:{m['allowed_action']}:{m['max_amount_cents']}:{m['exp']}"
    return now < m["exp"] and hmac.compare_digest(m.get("sig",""), _sig(user_key, body))

def authorize_cart(user_key: bytes, intent: dict, action: str, amount_cents: int, now=None):
    """A concrete action (cart) is authorized ONLY if a valid intent covers it: same action + within cap."""
    if not verify_intent(user_key, intent, now):
        return {"authorized": False, "reason": "invalid/expired intent mandate"}
    if action != intent["allowed_action"]:
        return {"authorized": False, "reason": f"action '{action}' not in intent '{intent['allowed_action']}'"}
    if amount_cents > intent["max_amount_cents"]:
        return {"authorized": False, "reason": f"amount {amount_cents} exceeds intent cap {intent['max_amount_cents']}"}
    return {"authorized": True, "authoritative": False, "requires": ["action_authority", "money_forge_verify"]}
