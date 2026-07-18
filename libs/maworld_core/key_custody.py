"""Key custody — separates key domains so one process cannot forge another's authority (closes the
'HMAC keys env/random, promoter could self-approve' gap). Each domain (engine/approver/gate/human/cap)
is held by a DIFFERENT holder. A holder can sign ONLY with its own domain key; verification is public.
Dev = in-proc holders; prod = SOPS/Vault/HSM/enclave per domain."""
from __future__ import annotations
import hashlib, hmac, os

DOMAINS = ["engine", "approver", "gate", "human_confirm", "capability"]

class KeyHolder:
    """Holds ONE domain key. Can sign for its domain; cannot access other domains' keys."""
    def __init__(self, domain: str, key: bytes):
        assert domain in DOMAINS
        self.domain = domain
        self.__key = key                      # name-mangled; not exposed
    def sign(self, domain: str, msg: bytes) -> str:
        if domain != self.domain:
            raise PermissionError(f"holder of '{self.domain}' cannot sign for '{domain}'")
        return hmac.new(self.__key, msg, hashlib.sha256).hexdigest()

class Custody:
    """Wires holders. NB: the promoter gets the 'gate' holder but NOT the 'approver' holder."""
    def __init__(self, keys: dict): self.holders = {d: KeyHolder(d, keys[d]) for d in DOMAINS}
    def holder(self, domain): return self.holders[domain]
    def verifier(self, keys):
        def verify(domain, msg, sig):
            return hmac.compare_digest(sig, hmac.new(keys[domain], msg, hashlib.sha256).hexdigest())
        return verify
