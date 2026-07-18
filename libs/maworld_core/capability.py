"""Signed capability tokens + realpath path guard (fixes 'string capability' + 'prefix path check').
A capability is a SIGNED binding of (subject, action, resource, expiry). A bare string is never a
capability. Paths are validated by realpath containment (resolves symlinks/.. — no prefix bypass).
"""
from __future__ import annotations
import hashlib, hmac, os, time

def mint_capability(key: bytes, subject: str, action: str, resource: str, exp: float) -> str:
    body = f"{subject}|{action}|{resource}|{int(exp)}"
    sig = hmac.new(key, body.encode(), hashlib.sha256).hexdigest()
    return body + "|" + sig

def verify_capability(key: bytes, token: str, subject: str, action: str, resource: str, now=None) -> bool:
    now = time.time() if now is None else now
    if not isinstance(token, str) or token.count("|") != 4:
        return False                                   # a bare string is NOT a capability
    body, sig = token.rsplit("|", 1)
    if not hmac.compare_digest(sig, hmac.new(key, body.encode(), hashlib.sha256).hexdigest()):
        return False
    s, a, r, exp = body.split("|")
    return s == subject and a == action and r == resource and now < int(exp)

def safe_path(path: str, allowed_roots) -> str:
    """Return the real absolute path IFF it is contained in an allowed root; else raise. Resolves
    symlinks and '..' so a prefix/traversal trick cannot escape (fixes 'vulnerable prefix check')."""
    rp = os.path.realpath(path)
    for root in allowed_roots:
        rr = os.path.realpath(root)
        if rp == rr or rp.startswith(rr + os.sep):
            return rp
    raise PermissionError(f"path {rp} escapes allowed roots")
