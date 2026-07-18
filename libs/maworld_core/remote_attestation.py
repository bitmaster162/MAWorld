"""Remote-attestation verification and fixed secret-release policy.

This module owns no signing key and reads no attestation secret from the
environment.  Attesters receive a sign-only :class:`QuoteIssuer`; relying
parties receive a verifier-only :class:`QuoteVerifier` with a copied, fixed
issuer allowlist.  Secret release additionally requires a signed capability
checked by a validator and a release handler registry fixed when the gate is
constructed.

The HMAC callbacks used by tests are only a stand-in for a vendor certificate
chain verifier.  Production callers can inject SEV-SNP/TDX verification
callbacks without changing the trust-boundary shape.
"""
from __future__ import annotations

import json
import time
from types import MappingProxyType
from typing import Callable, Mapping


QUOTE_DOMAIN = b"MAWORLD/REMOTE-ATTESTATION/QUOTE/V1\x00"
ATTESTED_RELEASE_ACTION = "attestation.release"

_QUOTE_VERSION = 1
_MAX_QUOTE_TTL_S = 300
_MAX_FUTURE_SKEW_S = 5
_QUOTE_FIELDS = frozenset(
    {
        "version",
        "issuer_id",
        "measurement",
        "challenge",
        "issued_at",
        "expires_at",
        "sig",
    }
)

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]
SignedCapabilityValidator = Callable[[object, str, str, str], bool]
ReleaseHandler = Callable[[], object]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _ttl(value: object) -> int:
    if not _is_int(value) or not 0 < value <= _MAX_QUOTE_TTL_S:
        raise ValueError(f"ttl_s must be in 1..{_MAX_QUOTE_TTL_S}")
    return value


def _unsigned_quote(quote: Mapping[str, object]) -> dict:
    return {name: quote[name] for name in _QUOTE_FIELDS if name != "sig"}


def _signature_ok(verify: VerifyFn, message: bytes, signature: object) -> bool:
    if not isinstance(signature, str) or not signature:
        return False
    try:
        return bool(verify(message, signature))
    except Exception:
        return False


class QuoteIssuer:
    """Sign-only attester role; it contains no verification trust policy."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(self, measurement: str, challenge: str, *, ttl_s: int = 60) -> dict:
        measurement = _required("measurement", measurement)
        challenge = _required("challenge", challenge)
        ttl_s = _ttl(ttl_s)
        issued_at = int(self._clock())
        unsigned = {
            "version": _QUOTE_VERSION,
            "issuer_id": self.issuer_id,
            "measurement": measurement,
            "challenge": challenge,
            "issued_at": issued_at,
            "expires_at": issued_at + ttl_s,
        }
        signature = self.__sign(QUOTE_DOMAIN + _canonical(unsigned))
        if not isinstance(signature, str) or not signature:
            raise ValueError("quote signer returned an invalid signature")
        return {**unsigned, "sig": signature}


class QuoteVerifier:
    """Verifier-only role with fixed issuer trust and lifetime policy."""

    def __init__(
        self,
        issuer_verifiers: Mapping[str, VerifyFn],
        *,
        clock=time.time,
        max_ttl_s: int = 60,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not isinstance(issuer_verifiers, Mapping) or not issuer_verifiers:
            raise ValueError("a fixed quote issuer allowlist is required")
        copied = dict(issuer_verifiers)
        if any(
            not isinstance(issuer_id, str)
            or not issuer_id.strip()
            or not callable(verify)
            for issuer_id, verify in copied.items()
        ):
            raise ValueError("quote issuer allowlist is invalid")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if (
            not _is_int(max_ttl_s)
            or not 0 < max_ttl_s <= _MAX_QUOTE_TTL_S
        ):
            raise ValueError(f"max_ttl_s must be in 1..{_MAX_QUOTE_TTL_S}")
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._issuer_verifiers = MappingProxyType(copied)
        self._clock = clock
        self._max_ttl_s = max_ttl_s
        self._max_future_skew_s = max_future_skew_s

    def check(
        self,
        quote: object,
        expected_measurement: str,
        expected_challenge: str,
    ) -> tuple[bool, str]:
        if not isinstance(quote, dict) or frozenset(quote) != _QUOTE_FIELDS:
            return False, "malformed quote"
        if quote.get("version") != _QUOTE_VERSION:
            return False, "unsupported quote version"
        if not isinstance(expected_measurement, str) or not expected_measurement:
            return False, "expected measurement required"
        if not isinstance(expected_challenge, str) or not expected_challenge:
            return False, "expected challenge required"

        issuer_id = quote.get("issuer_id")
        measurement = quote.get("measurement")
        challenge = quote.get("challenge")
        issued_at = quote.get("issued_at")
        expires_at = quote.get("expires_at")
        if (
            not isinstance(issuer_id, str)
            or not issuer_id
            or not isinstance(measurement, str)
            or not measurement
            or not isinstance(challenge, str)
            or not challenge
            or not _is_int(issued_at)
            or not _is_int(expires_at)
        ):
            return False, "malformed quote payload"

        verify_signature = self._issuer_verifiers.get(issuer_id)
        if verify_signature is None:
            return False, "untrusted quote issuer"
        if not _signature_ok(
            verify_signature,
            QUOTE_DOMAIN + _canonical(_unsigned_quote(quote)),
            quote.get("sig"),
        ):
            return False, "invalid quote signature"

        if measurement != expected_measurement:
            return False, "measurement mismatch"
        if challenge != expected_challenge:
            return False, "challenge mismatch"

        now = int(self._clock())
        if issued_at > now + self._max_future_skew_s:
            return False, "quote issued in the future"
        if expires_at <= issued_at:
            return False, "invalid quote lifetime"
        if expires_at - issued_at > self._max_ttl_s:
            return False, "quote lifetime exceeds policy"
        if now >= expires_at:
            return False, "quote expired"
        return True, "ok"

    def verify(
        self,
        quote: object,
        expected_measurement: str,
        expected_challenge: str,
    ) -> bool:
        return self.check(quote, expected_measurement, expected_challenge)[0]


class AttestedReleaseGate:
    """Fixed two-factor release gate: trusted quote plus signed capability."""

    def __init__(
        self,
        quote_verifier: QuoteVerifier,
        signed_capability_validator: SignedCapabilityValidator,
        release_handlers: Mapping[str, ReleaseHandler],
    ):
        if not isinstance(quote_verifier, QuoteVerifier):
            raise TypeError("explicit QuoteVerifier required")
        if not callable(signed_capability_validator):
            raise TypeError("fixed signed-capability validator required")
        if not isinstance(release_handlers, Mapping) or not release_handlers:
            raise ValueError("a non-empty fixed release handler map is required")
        copied = dict(release_handlers)
        if any(
            not isinstance(release_id, str)
            or not release_id.strip()
            or not callable(handler)
            for release_id, handler in copied.items()
        ):
            raise ValueError("release handler map is invalid")
        self._quote_verifier = quote_verifier
        self._capability_validator = signed_capability_validator
        self._release_handlers = MappingProxyType(copied)

    @staticmethod
    def _deny(reason: str) -> dict:
        return {"released": False, "reason": reason}

    def release(
        self,
        quote: object,
        expected_measurement: str,
        expected_challenge: str,
        capability_token: object,
        release_id: str,
    ) -> dict:
        if not isinstance(release_id, str) or not release_id:
            return self._deny("release id required")
        handler = self._release_handlers.get(release_id)
        if handler is None:
            return self._deny("release handler is not registered")

        attested, reason = self._quote_verifier.check(
            quote, expected_measurement, expected_challenge
        )
        if not attested:
            return self._deny(f"attestation denied: {reason}")

        try:
            if not self._capability_validator(
                capability_token,
                expected_measurement,
                ATTESTED_RELEASE_ACTION,
                release_id,
            ):
                return self._deny("signed capability denied")
        except Exception:
            return self._deny("signed capability denied")

        try:
            value = handler()
        except Exception:
            return self._deny("release handler failed")
        return {"released": True, "value": value}


# Compatibility surface.  There is deliberately no implicit issuer, verifier,
# key, capability boolean, or caller-provided release function.
def make_quote(
    code_measurement: str,
    nonce: str,
    ts=None,
    *,
    issuer: QuoteIssuer | None = None,
    ttl_s: int = 60,
) -> dict:
    if not isinstance(issuer, QuoteIssuer) or ts is not None:
        return {}
    try:
        return issuer.issue(code_measurement, nonce, ttl_s=ttl_s)
    except (TypeError, ValueError):
        return {}


def verify_quote(
    quote: object,
    expected_measurement: str,
    nonce: str,
    max_age=None,
    now=None,
    *,
    verifier: QuoteVerifier | None = None,
) -> bool:
    if not isinstance(verifier, QuoteVerifier) or max_age is not None or now is not None:
        return False
    return verifier.verify(quote, expected_measurement, nonce)


def attested_release(
    quote: object,
    expected_measurement: str,
    nonce: str,
    capability_token: object = None,
    release_id: object = None,
    *,
    gate: AttestedReleaseGate | None = None,
) -> dict:
    if not isinstance(gate, AttestedReleaseGate):
        return {"released": False, "reason": "explicit AttestedReleaseGate required"}
    if not isinstance(release_id, str):
        return {"released": False, "reason": "registered release id required"}
    return gate.release(
        quote,
        expected_measurement,
        nonce,
        capability_token,
        release_id,
    )


__all__ = [
    "ATTESTED_RELEASE_ACTION",
    "QUOTE_DOMAIN",
    "AttestedReleaseGate",
    "QuoteIssuer",
    "QuoteVerifier",
    "attested_release",
    "make_quote",
    "verify_quote",
]
