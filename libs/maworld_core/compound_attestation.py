"""Compound attestation with explicit signing and verification roles.

This module owns no key material and reads no signing secret from the
environment.  Attestation services receive sign-only issuer objects.  Relying
parties receive verifier-only objects whose issuer allowlists and capability
scope are copied and fixed at construction.

Attestation is not transitive by itself: every result signs the full hop payload
including the prior signed-result digest.  Secret release is a separate policy
and requires three independently verified, role-specific claims over the exact
same workload/secret subject.  Claim-supplied booleans are never evidence.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Callable, Mapping


ATTESTATION_RESULT_DOMAIN = b"MAWORLD/COMPOUND-ATTESTATION/RESULT/V1\x00"
ATTESTATION_DIGEST_DOMAIN = b"MAWORLD/COMPOUND-ATTESTATION/DIGEST/V1\x00"
QUOTE_CLAIM_DOMAIN = b"MAWORLD/SECRET-RELEASE/QUOTE/V1\x00"
PLATFORM_CLAIM_DOMAIN = b"MAWORLD/SECRET-RELEASE/PLATFORM/V1\x00"
ENROLLMENT_CLAIM_DOMAIN = b"MAWORLD/SECRET-RELEASE/ENROLLMENT/V1\x00"

_MAX_TTL_S = 300
_MAX_FUTURE_SKEW_S = 5
_MAX_CHAIN_HOPS = 32
_AR_VERDICTS = frozenset({"pass", "fail"})
_CONTROL_VERDICTS = frozenset({"pass", "fail"})

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _ttl(ttl_s: int) -> int:
    if (
        not isinstance(ttl_s, int)
        or isinstance(ttl_s, bool)
        or not 0 < ttl_s <= _MAX_TTL_S
    ):
        raise ValueError(f"ttl_s must be in 1..{_MAX_TTL_S}")
    return ttl_s


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_trust_map(name: str, values: Mapping[str, VerifyFn]) -> Mapping[str, VerifyFn]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"a fixed {name} issuer allowlist is required")
    copied = dict(values)
    if any(
        not isinstance(issuer_id, str)
        or not issuer_id.strip()
        or not callable(verify)
        for issuer_id, verify in copied.items()
    ):
        raise ValueError(f"{name} issuer allowlist is invalid")
    return MappingProxyType(copied)


def _signature_ok(verify: VerifyFn, message: bytes, signature: str) -> bool:
    try:
        return isinstance(signature, str) and bool(signature) and bool(
            verify(message, signature)
        )
    except Exception:
        return False


@dataclass(frozen=True)
class AttestationResult:
    issuer_id: str
    result_id: str
    session_id: str
    hop_index: int
    attester: str
    measurement: str
    parent_ar_digest: str
    capability_digest: str
    request_digest: str
    verdict: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "issuer_id": self.issuer_id,
            "result_id": self.result_id,
            "session_id": self.session_id,
            "hop_index": self.hop_index,
            "attester": self.attester,
            "measurement": self.measurement,
            "parent_ar_digest": self.parent_ar_digest,
            "capability_digest": self.capability_digest,
            "request_digest": self.request_digest,
            "verdict": self.verdict,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        })

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "AttestationResult | None":
        if not isinstance(raw, dict) or set(raw) != {
            "issuer_id", "result_id", "session_id", "hop_index", "attester",
            "measurement", "parent_ar_digest", "capability_digest",
            "request_digest", "verdict", "issued_at", "expires_at", "sig",
        }:
            return None
        try:
            result = cls(**raw)
        except TypeError:
            return None
        return result if _well_formed_result(result) else None


def _well_formed_result(result: AttestationResult) -> bool:
    return (
        all(
            isinstance(value, str) and bool(value.strip())
            for value in (
                result.issuer_id,
                result.result_id,
                result.session_id,
                result.attester,
                result.measurement,
                result.parent_ar_digest,
                result.capability_digest,
                result.request_digest,
                result.sig,
            )
        )
        and _is_int(result.hop_index)
        and result.hop_index >= 0
        and result.verdict in _AR_VERDICTS
        and _is_int(result.issued_at)
        and _is_int(result.expires_at)
    )


def _coerce_result(raw: object) -> AttestationResult | None:
    if isinstance(raw, AttestationResult):
        return raw if _well_formed_result(raw) else None
    return AttestationResult.from_dict(raw)


class AttestationResultIssuer:
    """Sign-only issuer held by a trusted attestation verifier service."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self,
        session_id: str,
        hop_index: int,
        attester: str,
        measurement: str,
        parent_ar_digest: str,
        capability_digest: str,
        request_digest: str,
        verdict: str = "pass",
        *,
        ttl_s: int = 60,
        now: int | None = None,
    ) -> AttestationResult:
        if not _is_int(hop_index) or hop_index < 0:
            raise ValueError("hop_index must be a non-negative integer")
        if verdict not in _AR_VERDICTS:
            raise ValueError(f"unsupported verdict {verdict!r}")
        ttl_s = _ttl(ttl_s)
        issued_at = int(self._clock()) if now is None else int(now)
        unsigned = AttestationResult(
            issuer_id=self.issuer_id,
            result_id=uuid.uuid4().hex,
            session_id=_required("session_id", session_id),
            hop_index=hop_index,
            attester=_required("attester", attester),
            measurement=_required("measurement", measurement),
            parent_ar_digest=_required("parent_ar_digest", parent_ar_digest),
            capability_digest=_required("capability_digest", capability_digest),
            request_digest=_required("request_digest", request_digest),
            verdict=verdict,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        signature = self.__sign(ATTESTATION_RESULT_DOMAIN + unsigned._payload())
        if not isinstance(signature, str) or not signature:
            raise ValueError("attestation signer returned an invalid signature")
        return AttestationResult(**{**unsigned.__dict__, "sig": signature})


def ar_digest(raw: object) -> str:
    """Digest the complete signed result envelope used as the next parent."""
    result = _coerce_result(raw)
    if result is None:
        raise ValueError("well-formed signed AttestationResult required")
    return hashlib.sha256(
        ATTESTATION_DIGEST_DOMAIN
        + _canonical({**json.loads(result._payload()), "sig": result.sig})
    ).hexdigest()


class AttestationChainVerifier:
    """Verifier-only relying-party policy with immutable trust and scope."""

    def __init__(
        self,
        issuer_verifiers: Mapping[str, VerifyFn],
        *,
        allowed_capability_digests: set[str] | frozenset[str],
        clock=time.time,
        max_ttl_s: int = _MAX_TTL_S,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
        max_hops: int = _MAX_CHAIN_HOPS,
    ):
        self._verifiers = _valid_trust_map("attestation-result", issuer_verifiers)
        if not allowed_capability_digests or any(
            not isinstance(value, str) or not value.strip()
            for value in allowed_capability_digests
        ):
            raise ValueError("a fixed non-empty capability allowlist is required")
        self._allowed_capabilities = frozenset(allowed_capability_digests)
        if not _is_int(max_ttl_s) or max_ttl_s <= 0 or max_ttl_s > _MAX_TTL_S:
            raise ValueError(f"max_ttl_s must be in 1..{_MAX_TTL_S}")
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        if not _is_int(max_hops) or not 1 <= max_hops <= _MAX_CHAIN_HOPS:
            raise ValueError(f"max_hops must be in 1..{_MAX_CHAIN_HOPS}")
        self._clock = clock
        self._max_ttl = max_ttl_s
        self._future_skew = max_future_skew_s
        self._max_hops = max_hops

    def verify(
        self,
        chain: object,
        session_id: str,
        delegated_scope: set[str] | frozenset[str] | None = None,
    ) -> dict:
        if not isinstance(session_id, str) or not session_id:
            return {"accepted": False, "reason": "invalid expected session"}
        if not isinstance(chain, (list, tuple)) or not chain:
            return {"accepted": False, "reason": "non-empty attestation chain required"}
        if len(chain) > self._max_hops:
            return {"accepted": False, "reason": "attestation chain too long"}

        allowed = self._allowed_capabilities
        if delegated_scope is not None:
            if (
                not isinstance(delegated_scope, (set, frozenset))
                or not delegated_scope
                or any(not isinstance(item, str) or not item for item in delegated_scope)
                or not delegated_scope.issubset(self._allowed_capabilities)
            ):
                return {"accepted": False, "reason": "delegated scope exceeds fixed policy"}
            allowed = frozenset(delegated_scope)

        now = int(self._clock())
        previous_digest = "ROOT"
        previous_issued_at: int | None = None
        previous_expires_at: int | None = None
        seen_result_ids: set[str] = set()
        for index, raw in enumerate(chain):
            result = _coerce_result(raw)
            if result is None:
                return {"accepted": False, "reason": "malformed attestation result", "hop": index}
            verify_signature = self._verifiers.get(result.issuer_id)
            if verify_signature is None:
                return {"accepted": False, "reason": "untrusted result issuer", "hop": index}
            if not _signature_ok(
                verify_signature,
                ATTESTATION_RESULT_DOMAIN + result._payload(),
                result.sig,
            ):
                return {"accepted": False, "reason": "verifier signature fail", "hop": index}
            if result.result_id in seen_result_ids:
                return {"accepted": False, "reason": "result replay", "hop": index}
            seen_result_ids.add(result.result_id)
            if result.session_id != session_id:
                return {"accepted": False, "reason": "session_id mismatch", "hop": index}
            if result.hop_index != index:
                return {"accepted": False, "reason": "hop_index non-monotonic", "hop": index}
            if result.parent_ar_digest != previous_digest:
                return {"accepted": False, "reason": "parent_ar_digest mismatch", "hop": index}
            if result.capability_digest not in allowed:
                return {"accepted": False, "reason": "capability scope escalation", "hop": index}
            if result.verdict != "pass":
                return {"accepted": False, "reason": "attestation verdict fail", "hop": index}
            if (
                result.issued_at > now + self._future_skew
                or now >= result.expires_at
                or result.expires_at <= result.issued_at
                or result.expires_at - result.issued_at > self._max_ttl
            ):
                return {"accepted": False, "reason": "invalid result lifetime", "hop": index}
            if previous_issued_at is not None and result.issued_at < previous_issued_at:
                return {"accepted": False, "reason": "chain time regression", "hop": index}
            if previous_expires_at is not None and result.issued_at >= previous_expires_at:
                return {"accepted": False, "reason": "parent expired before child", "hop": index}
            previous_digest = ar_digest(result)
            previous_issued_at = result.issued_at
            previous_expires_at = result.expires_at
        return {"accepted": True, "hops": len(chain), "chain_digest": previous_digest}


@dataclass(frozen=True)
class SecretReleaseSubject:
    session_id: str
    secret_id: str
    attester: str
    attester_key_id: str
    measurement: str
    platform_id: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _required(name, value)

    def to_dict(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, raw: object) -> "SecretReleaseSubject | None":
        if not isinstance(raw, dict) or set(raw) != {
            "session_id", "secret_id", "attester", "attester_key_id",
            "measurement", "platform_id",
        }:
            return None
        try:
            return cls(**raw)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class SecretControlClaim:
    issuer_id: str
    claim_id: str
    role: str
    subject: SecretReleaseSubject
    verdict: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "issuer_id": self.issuer_id,
            "claim_id": self.claim_id,
            "role": self.role,
            "subject": self.subject.to_dict(),
            "verdict": self.verdict,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        })

    def to_dict(self) -> dict:
        raw = asdict(self)
        return raw

    @classmethod
    def from_dict(cls, raw: object) -> "SecretControlClaim | None":
        if not isinstance(raw, dict) or set(raw) != {
            "issuer_id", "claim_id", "role", "subject", "verdict",
            "issued_at", "expires_at", "sig",
        }:
            return None
        subject = SecretReleaseSubject.from_dict(raw.get("subject"))
        if subject is None:
            return None
        values = dict(raw)
        values["subject"] = subject
        try:
            claim = cls(**values)
        except TypeError:
            return None
        return claim if _well_formed_control_claim(claim) else None


def _well_formed_control_claim(claim: SecretControlClaim) -> bool:
    return (
        all(
            isinstance(value, str) and bool(value.strip())
            for value in (claim.issuer_id, claim.claim_id, claim.role, claim.sig)
        )
        and isinstance(claim.subject, SecretReleaseSubject)
        and claim.verdict in _CONTROL_VERDICTS
        and _is_int(claim.issued_at)
        and _is_int(claim.expires_at)
    )


def _coerce_control_claim(raw: object) -> SecretControlClaim | None:
    if isinstance(raw, SecretControlClaim):
        return raw if _well_formed_control_claim(raw) else None
    return SecretControlClaim.from_dict(raw)


class _SecretControlIssuer:
    role: str
    domain: bytes

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self,
        subject: SecretReleaseSubject,
        verdict: str = "pass",
        *,
        ttl_s: int = 60,
        now: int | None = None,
    ) -> SecretControlClaim:
        if not isinstance(subject, SecretReleaseSubject):
            raise TypeError("exact SecretReleaseSubject required")
        if verdict not in _CONTROL_VERDICTS:
            raise ValueError(f"unsupported verdict {verdict!r}")
        ttl_s = _ttl(ttl_s)
        issued_at = int(self._clock()) if now is None else int(now)
        unsigned = SecretControlClaim(
            issuer_id=self.issuer_id,
            claim_id=uuid.uuid4().hex,
            role=self.role,
            subject=subject,
            verdict=verdict,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        signature = self.__sign(self.domain + unsigned._payload())
        if not isinstance(signature, str) or not signature:
            raise ValueError("control-claim signer returned an invalid signature")
        return SecretControlClaim(**{**unsigned.__dict__, "sig": signature})


class QuoteVerificationIssuer(_SecretControlIssuer):
    role = "quote_verification"
    domain = QUOTE_CLAIM_DOMAIN


class PlatformBindingIssuer(_SecretControlIssuer):
    role = "platform_binding"
    domain = PLATFORM_CLAIM_DOMAIN


class EnrollmentIssuer(_SecretControlIssuer):
    role = "attester_enrollment"
    domain = ENROLLMENT_CLAIM_DOMAIN


class SecretReleaseVerifier:
    """Verifier-only release policy with a distinct trust map for each role."""

    def __init__(
        self,
        quote_verifiers: Mapping[str, VerifyFn],
        platform_verifiers: Mapping[str, VerifyFn],
        enrollment_verifiers: Mapping[str, VerifyFn],
        *,
        clock=time.time,
        max_ttl_s: int = _MAX_TTL_S,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        self._quote_verifiers = _valid_trust_map("quote", quote_verifiers)
        self._platform_verifiers = _valid_trust_map("platform", platform_verifiers)
        self._enrollment_verifiers = _valid_trust_map("enrollment", enrollment_verifiers)
        if not _is_int(max_ttl_s) or max_ttl_s <= 0 or max_ttl_s > _MAX_TTL_S:
            raise ValueError(f"max_ttl_s must be in 1..{_MAX_TTL_S}")
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._clock = clock
        self._max_ttl = max_ttl_s
        self._future_skew = max_future_skew_s

    def _verify_role(
        self,
        raw: object,
        expected_subject: SecretReleaseSubject,
        role: str,
        domain: bytes,
        trust_map: Mapping[str, VerifyFn],
    ) -> tuple[bool, str, SecretControlClaim | None]:
        claim = _coerce_control_claim(raw)
        if claim is None:
            return False, f"missing or malformed {role} claim", None
        if claim.role != role:
            return False, f"wrong role for {role} claim", claim
        if claim.subject != expected_subject:
            return False, f"{role} subject mismatch", claim
        verify_signature = trust_map.get(claim.issuer_id)
        if verify_signature is None:
            return False, f"untrusted {role} issuer", claim
        if not _signature_ok(verify_signature, domain + claim._payload(), claim.sig):
            return False, f"invalid {role} signature", claim
        now = int(self._clock())
        if (
            claim.issued_at > now + self._future_skew
            or now >= claim.expires_at
            or claim.expires_at <= claim.issued_at
            or claim.expires_at - claim.issued_at > self._max_ttl
        ):
            return False, f"invalid {role} lifetime", claim
        if claim.verdict != "pass":
            return False, f"{role} verdict fail", claim
        return True, "ok", claim

    def authorize(
        self,
        subject: SecretReleaseSubject,
        quote_claim: object,
        platform_claim: object,
        enrollment_claim: object,
    ) -> dict:
        if not isinstance(subject, SecretReleaseSubject):
            return {"release": False, "reason": "exact SecretReleaseSubject required"}
        checks = (
            self._verify_role(
                quote_claim, subject, QuoteVerificationIssuer.role,
                QUOTE_CLAIM_DOMAIN, self._quote_verifiers,
            ),
            self._verify_role(
                platform_claim, subject, PlatformBindingIssuer.role,
                PLATFORM_CLAIM_DOMAIN, self._platform_verifiers,
            ),
            self._verify_role(
                enrollment_claim, subject, EnrollmentIssuer.role,
                ENROLLMENT_CLAIM_DOMAIN, self._enrollment_verifiers,
            ),
        )
        for accepted, reason, _claim in checks:
            if not accepted:
                return {"release": False, "reason": reason}
        claim_ids = {claim.claim_id for _, _, claim in checks if claim is not None}
        if len(claim_ids) != 3:
            return {"release": False, "reason": "control claim replay"}
        return {
            "release": True,
            "reason": "all role-specific claims verified for exact subject",
            "subject_digest": subject.digest(),
        }


def issue_attestation_result(
    session_id,
    hop_index,
    attester,
    measurement,
    parent_ar_digest,
    capability_digest,
    request_digest,
    verdict="pass",
    *,
    issuer: AttestationResultIssuer | None = None,
    ttl_s: int = 60,
    now: int | None = None,
):
    """Compatibility helper; signing is impossible without an explicit issuer."""
    if not isinstance(issuer, AttestationResultIssuer):
        raise RuntimeError("explicit AttestationResultIssuer required")
    return issuer.issue(
        session_id,
        hop_index,
        attester,
        measurement,
        parent_ar_digest,
        capability_digest,
        request_digest,
        verdict,
        ttl_s=ttl_s,
        now=now,
    )


def verify_chain(
    chain,
    session_id,
    delegated_scope=None,
    *,
    verifier: AttestationChainVerifier | None = None,
):
    """Compatibility helper; no implicit verifier or trust anchor exists."""
    if not isinstance(verifier, AttestationChainVerifier):
        return {"accepted": False, "reason": "explicit AttestationChainVerifier required"}
    return verifier.verify(chain, session_id, delegated_scope)


def authorize_secret_release(
    subject,
    quote_claim,
    platform_claim,
    enrollment_claim,
    *,
    verifier: SecretReleaseVerifier | None = None,
):
    """Authorize release only through an explicit verifier-only policy object."""
    if not isinstance(verifier, SecretReleaseVerifier):
        return {"release": False, "reason": "explicit SecretReleaseVerifier required"}
    return verifier.authorize(subject, quote_claim, platform_claim, enrollment_claim)


def secret_release_ok(*_args, **_kwargs):
    """Removed boolean API.  Legacy calls always fail closed."""
    return {
        "release": False,
        "reason": (
            "legacy boolean API disabled; use signed role-specific claims with "
            "authorize_secret_release and an explicit SecretReleaseVerifier"
        ),
    }


__all__ = [
    "ATTESTATION_RESULT_DOMAIN",
    "ATTESTATION_DIGEST_DOMAIN",
    "QUOTE_CLAIM_DOMAIN",
    "PLATFORM_CLAIM_DOMAIN",
    "ENROLLMENT_CLAIM_DOMAIN",
    "AttestationResult",
    "AttestationResultIssuer",
    "AttestationChainVerifier",
    "SecretReleaseSubject",
    "SecretControlClaim",
    "QuoteVerificationIssuer",
    "PlatformBindingIssuer",
    "EnrollmentIssuer",
    "SecretReleaseVerifier",
    "ar_digest",
    "issue_attestation_result",
    "verify_chain",
    "authorize_secret_release",
    "secret_release_ok",
]
