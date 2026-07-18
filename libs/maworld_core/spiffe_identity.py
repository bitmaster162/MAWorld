"""Signed, short-lived SPIFFE-shaped workload identity model.

The module owns no key.  Issuance and verification are separate objects; the
verifier holds a fixed issuer allowlist and validates the full identity,
session, trust-domain and lifetime binding.  This models an SVID for local
tests, but does not claim to replace a real SPIRE X.509/JWT-SVID deployment.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Callable, Mapping


SVID_DOMAIN = b"MAWORLD/SPIFFE-SVID-MODEL/V1\x00"
DEFAULT_TRUST_DOMAIN = "maworld"
MAX_TTL_S = 600
MAX_FUTURE_SKEW_S = 5
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _segment(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SEGMENT.fullmatch(value):
        raise ValueError(f"{name} must be one safe SPIFFE path segment")
    return value


@dataclass(frozen=True)
class SVID:
    issuer_id: str
    trust_domain: str
    spiffe_id: str
    workload: str
    session_id: str
    svid_id: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({k: v for k, v in asdict(self).items() if k != "sig"})

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw) -> "SVID | None":
        if not isinstance(raw, dict) or set(raw) != {
            "issuer_id", "trust_domain", "spiffe_id", "workload", "session_id",
            "svid_id", "issued_at", "expires_at", "sig",
        }:
            return None
        try:
            value = cls(**raw)
        except TypeError:
            return None
        return value if value.well_formed() else None

    def well_formed(self) -> bool:
        try:
            _segment("issuer_id", self.issuer_id)
            _segment("trust_domain", self.trust_domain)
            _segment("workload", self.workload)
            _segment("session_id", self.session_id)
            _segment("svid_id", self.svid_id)
        except ValueError:
            return False
        return (
            isinstance(self.spiffe_id, str)
            and isinstance(self.sig, str) and bool(self.sig)
            and isinstance(self.issued_at, int) and not isinstance(self.issued_at, bool)
            and isinstance(self.expires_at, int) and not isinstance(self.expires_at, bool)
        )


class SVIDIssuer:
    def __init__(self, issuer_id: str, sign: Callable[[bytes], str], *,
                 trust_domain: str = DEFAULT_TRUST_DOMAIN, clock=time.time):
        self.issuer_id = _segment("issuer_id", issuer_id)
        self.trust_domain = _segment("trust_domain", trust_domain)
        if not callable(sign):
            raise TypeError("sign callable required")
        self.__sign = sign
        self._clock = clock

    def issue(self, workload: str, *, session_id: str, ttl_s: int = 300,
              now: int | None = None) -> SVID:
        workload = _segment("workload", workload)
        session_id = _segment("session_id", session_id)
        if not isinstance(ttl_s, int) or isinstance(ttl_s, bool) or not 0 < ttl_s <= MAX_TTL_S:
            raise ValueError(f"ttl_s must be in 1..{MAX_TTL_S}")
        issued_at = int(self._clock()) if now is None else int(now)
        svid_id = uuid.uuid4().hex
        unsigned = SVID(
            self.issuer_id, self.trust_domain,
            f"spiffe://{self.trust_domain}/{workload}/{session_id}/{svid_id}",
            workload, session_id, svid_id, issued_at, issued_at + ttl_s,
        )
        sig = self.__sign(SVID_DOMAIN + unsigned._payload())
        if not isinstance(sig, str) or not sig:
            raise ValueError("SVID signer returned invalid signature")
        return SVID(**{**unsigned.__dict__, "sig": sig})


class SVIDVerifier:
    def __init__(self, issuer_verifiers: Mapping[str, Callable[[bytes, str], bool]], *,
                 trust_domain: str = DEFAULT_TRUST_DOMAIN, clock=time.time,
                 max_ttl_s: int = MAX_TTL_S, max_future_skew_s: int = MAX_FUTURE_SKEW_S):
        copied = dict(issuer_verifiers)
        if not copied or any(not _SEGMENT.fullmatch(k or "") or not callable(v)
                             for k, v in copied.items()):
            raise ValueError("fixed SVID issuer allowlist required")
        self._verifiers = MappingProxyType(copied)
        self._trust_domain = _segment("trust_domain", trust_domain)
        self._clock = clock
        if (not isinstance(max_ttl_s,int) or isinstance(max_ttl_s,bool)
                or not 0 < max_ttl_s <= MAX_TTL_S):
            raise ValueError(f"max_ttl_s must be in 1..{MAX_TTL_S}")
        if (not isinstance(max_future_skew_s,int) or isinstance(max_future_skew_s,bool)
                or max_future_skew_s < 0):
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._max_ttl = max_ttl_s
        self._future_skew = max_future_skew_s

    def verify(self, raw, *, workload: str, session_id: str, now: int | None = None) -> bool:
        svid = raw if isinstance(raw, SVID) else SVID.from_dict(raw)
        if svid is None or not svid.well_formed():
            return False
        try:
            workload = _segment("workload", workload)
            session_id = _segment("session_id", session_id)
        except ValueError:
            return False
        expected_id = f"spiffe://{self._trust_domain}/{workload}/{session_id}/{svid.svid_id}"
        if (
            svid.trust_domain != self._trust_domain
            or svid.workload != workload
            or svid.session_id != session_id
            or svid.spiffe_id != expected_id
        ):
            return False
        verify = self._verifiers.get(svid.issuer_id)
        try:
            signature_ok = verify is not None and bool(
                verify(SVID_DOMAIN + svid._payload(), svid.sig)
            )
        except Exception:
            signature_ok = False
        current = int(self._clock()) if now is None else int(now)
        return bool(signature_ok) and not (
            svid.issued_at > current + self._future_skew
            or current >= svid.expires_at
            or svid.expires_at <= svid.issued_at
            or svid.expires_at - svid.issued_at > self._max_ttl
        )


def mint_svid(workload: str, ttl_sec: int = 300, *, issuer: SVIDIssuer | None = None,
              session_id: str = ""):
    if not isinstance(issuer, SVIDIssuer):
        raise RuntimeError("explicit external SVIDIssuer required")
    return issuer.issue(workload, session_id=session_id, ttl_s=ttl_sec).to_dict()


def valid_svid(svid, now=None, *, verifier: SVIDVerifier | None = None,
               workload: str = "", session_id: str = "") -> bool:
    if not isinstance(verifier, SVIDVerifier):
        return False
    return verifier.verify(svid, workload=workload, session_id=session_id, now=now)


TRUST_DOMAIN = DEFAULT_TRUST_DOMAIN
__all__ = ["SVID_DOMAIN", "TRUST_DOMAIN", "SVID", "SVIDIssuer", "SVIDVerifier",
           "mint_svid", "valid_svid"]
