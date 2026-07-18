from __future__ import annotations
import hmac, time
from dataclasses import dataclass
@dataclass
class OwnerBinding:
    owner_chat_id: int; webhook_secret: str; nonce_ttl_sec: int = 120
class ReplayGuard:
    def __init__(self): self._seen = {}
    def check_and_consume(self, nonce, now, ttl):
        self._seen = {n:t for n,t in self._seen.items() if now-t < ttl}
        if nonce in self._seen: return False
        self._seen[nonce] = now; return True
def verify_update(update, header_secret, binding, guard, now=None):
    now = time.time() if now is None else now
    if not hmac.compare_digest(header_secret or "", binding.webhook_secret):
        return False, "REJECTED_BAD_SECRET_TOKEN"
    chat_id = update.get("message",{}).get("chat",{}).get("id")
    if chat_id != binding.owner_chat_id: return False, "REJECTED_NOT_OWNER"
    ts = update.get("message",{}).get("date",0)
    if now-ts > binding.nonce_ttl_sec: return False, "REJECTED_STALE"
    nonce = update.get("message",{}).get("nonce","")
    if not nonce or not guard.check_and_consume(nonce, now, binding.nonce_ttl_sec):
        return False, "REJECTED_REPLAY_OR_NO_NONCE"
    return True, "OK"
