"""Signed DelegationGrant + one-time CapabilityToken (report 06 secrets acceptance test).

Authority must NOT live in a transport session. It is carried by a short-lived, signed
DelegationGrant and minted into a one-time CapabilityToken bound to a specific action_spec_id.
- expired grant  -> rejected
- token reuse    -> rejected (single-use)
- cross-project  -> blocked (project scope on the grant)
- capability enlargement -> impossible (token capabilities are a subset of the grant)
HMAC signing here is the spike stand-in; production swaps an asymmetric signer / KMS.
"""
from __future__ import annotations
import hmac, hashlib, json, time, uuid
from dataclasses import dataclass, field


def _sign(secret: bytes, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


@dataclass
class DelegationGrant:
    grant_id: str
    project_id: str
    subject: str                    # workload/agent identity the grant is issued to
    capabilities: frozenset         # e.g. {"repo.read","worktree.write","git.commit"}
    expires_at: float
    signature: str = ""

    def payload(self):
        return {"grant_id": self.grant_id, "project_id": self.project_id, "subject": self.subject,
                "capabilities": sorted(self.capabilities), "expires_at": self.expires_at}


class Authority:
    def __init__(self, secret: bytes):
        self._secret = secret
        self._spent_tokens: set[str] = set()

    def issue_grant(self, project_id, subject, capabilities, ttl_sec=300) -> DelegationGrant:
        g = DelegationGrant(str(uuid.uuid4()), project_id, subject, frozenset(capabilities),
                            time.time() + ttl_sec)
        g.signature = _sign(self._secret, g.payload())
        return g

    def _grant_valid(self, g: DelegationGrant, now: float) -> tuple[bool, str]:
        if _sign(self._secret, g.payload()) != g.signature:
            return False, "GRANT_BAD_SIGNATURE"
        if now > g.expires_at:
            return False, "GRANT_EXPIRED"
        return True, "OK"

    def mint_token(self, g: DelegationGrant, action_spec_id, project_id, capability, now=None):
        """Mint a one-time CapabilityToken for ONE action. Returns (token|None, reason)."""
        now = time.time() if now is None else now
        ok, reason = self._grant_valid(g, now)
        if not ok:
            return None, reason
        if project_id != g.project_id:
            return None, "CROSS_PROJECT_BLOCKED"
        if capability not in g.capabilities:
            return None, "CAPABILITY_NOT_IN_GRANT"   # cannot enlarge scope
        token = {"token_id": str(uuid.uuid4()), "grant_id": g.grant_id,
                 "action_spec_id": action_spec_id, "project_id": project_id,
                 "capability": capability, "exp": g.expires_at}
        token["sig"] = _sign(self._secret, token)
        return token, "OK"

    def redeem(self, token: dict, action_spec_id, capability, now=None) -> tuple[str, str]:
        """Redeem a one-time token for exactly the action it was minted for. (decision, reason)."""
        now = time.time() if now is None else now
        sig = token.get("sig")
        chk = {k: token[k] for k in token if k != "sig"}
        if _sign(self._secret, chk) != sig:
            return "DENY", "TOKEN_BAD_SIGNATURE"
        if now > token.get("exp", 0):
            return "DENY", "TOKEN_EXPIRED"
        if token["token_id"] in self._spent_tokens:
            return "DENY", "TOKEN_REUSE_BLOCKED"      # one-time only
        if token.get("action_spec_id") != action_spec_id:
            return "DENY", "ACTION_MISMATCH"          # token bound to one action
        if token.get("capability") != capability:
            return "DENY", "CAPABILITY_MISMATCH"
        self._spent_tokens.add(token["token_id"])
        return "ALLOW", "OK"
