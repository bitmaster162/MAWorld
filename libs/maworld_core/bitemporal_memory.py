"""Bitemporal facts with an explicit governed-promotion trust boundary.

Every fact carries valid time (``valid_from``/``valid_until``) and transaction
time.  Superseding a fact closes the previous interval instead of overwriting
history.

Ordinary writes are *always* ungoverned.  Governed truth can only be created by
``BitemporalStore.promote`` after a fixed ``GovernancePromotionVerifier`` has
validated a short-lived, signed claim for the exact stored fact.  This module
owns no signing key and reads no secret from the environment.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping


PROMOTION_DOMAIN = b"MAWORLD/BITEMPORAL/GOVERNANCE-PROMOTION/V1\x00"
PROMOTION_DECISION = "GOVERNED_PROMOTION"

_PROMOTION_VERSION = 1
_MAX_PROMOTION_TTL_S = 300
_MAX_FUTURE_SKEW_S = 5
_PROMOTION_FIELDS = frozenset(
    {
        "version",
        "issuer_id",
        "promotion_id",
        "fact_digest",
        "decision",
        "issued_at",
        "expires_at",
        "sig",
    }
)

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _ttl(value: object) -> int:
    if not _is_int(value) or not 0 < value <= _MAX_PROMOTION_TTL_S:
        raise ValueError(f"ttl_s must be in 1..{_MAX_PROMOTION_TTL_S}")
    return value


@dataclass(frozen=True, slots=True)
class BitemporalFact:
    subject: str
    predicate: str
    object_val: str
    trust_score: float
    transaction_time: float = field(default_factory=time.time)
    valid_from: float = field(default_factory=time.time)
    valid_until: float | None = None
    fact_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _governance_claim_id: str | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        _required("subject", self.subject)
        _required("predicate", self.predicate)
        if not isinstance(self.object_val, str):
            raise TypeError("object_val must be a string")
        trust = _finite_number("trust_score", self.trust_score)
        if not 0.0 <= trust <= 1.0:
            raise ValueError("trust_score must be in 0..1")
        transaction_time = _finite_number("transaction_time", self.transaction_time)
        valid_from = _finite_number("valid_from", self.valid_from)
        if self.valid_until is not None:
            valid_until = _finite_number("valid_until", self.valid_until)
            if valid_until < valid_from:
                raise ValueError("valid_until cannot precede valid_from")
        _required("fact_id", self.fact_id)
        object.__setattr__(self, "trust_score", trust)
        object.__setattr__(self, "transaction_time", transaction_time)
        object.__setattr__(self, "valid_from", valid_from)
        if self.valid_until is not None:
            object.__setattr__(self, "valid_until", float(self.valid_until))

    @property
    def is_governed_truth(self) -> bool:
        """Read-only projection; it is never accepted as constructor input."""

        return self._governance_claim_id is not None


def _clone_fact(
    fact: BitemporalFact,
    *,
    valid_until: float | None,
    governance_claim_id: str | None,
) -> BitemporalFact:
    """Create a store-owned frozen copy, discarding caller object state."""

    copied = BitemporalFact(
        subject=fact.subject,
        predicate=fact.predicate,
        object_val=fact.object_val,
        trust_score=fact.trust_score,
        transaction_time=fact.transaction_time,
        valid_from=fact.valid_from,
        valid_until=valid_until,
        fact_id=fact.fact_id,
    )
    if governance_claim_id is not None:
        object.__setattr__(copied, "_governance_claim_id", governance_claim_id)
    return copied


def fact_digest(fact: BitemporalFact) -> str:
    """Digest the complete non-governance identity and temporal payload."""

    if type(fact) is not BitemporalFact:
        raise TypeError("fact must be an exact BitemporalFact")
    payload = {
        "fact_id": fact.fact_id,
        "subject": fact.subject,
        "predicate": fact.predicate,
        "object_val": fact.object_val,
        "trust_score": fact.trust_score,
        "transaction_time": fact.transaction_time,
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _unsigned_promotion(claim: Mapping[str, object]) -> dict[str, object]:
    return {name: claim[name] for name in _PROMOTION_FIELDS if name != "sig"}


def _signature_ok(verify: VerifyFn, message: bytes, signature: object) -> bool:
    if not isinstance(signature, str) or not signature:
        return False
    try:
        return bool(verify(message, signature))
    except Exception:
        return False


class GovernancePromotionIssuer:
    """Sign-only role; it carries no relying-party trust policy."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self,
        fact: BitemporalFact,
        promotion_id: str,
        *,
        ttl_s: int = 60,
    ) -> dict[str, object]:
        promotion_id = _required("promotion_id", promotion_id)
        ttl_s = _ttl(ttl_s)
        issued_at = int(self._clock())
        unsigned: dict[str, object] = {
            "version": _PROMOTION_VERSION,
            "issuer_id": self.issuer_id,
            "promotion_id": promotion_id,
            "fact_digest": fact_digest(fact),
            "decision": PROMOTION_DECISION,
            "issued_at": issued_at,
            "expires_at": issued_at + ttl_s,
        }
        signature = self.__sign(PROMOTION_DOMAIN + _canonical(unsigned))
        if not isinstance(signature, str) or not signature:
            raise ValueError("promotion signer returned an invalid signature")
        return {**unsigned, "sig": signature}


class GovernancePromotionVerifier:
    """Verifier-only role with a copied, fixed issuer allowlist and TTL policy."""

    def __init__(
        self,
        issuer_verifiers: Mapping[str, VerifyFn],
        *,
        clock=time.time,
        max_ttl_s: int = 60,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not isinstance(issuer_verifiers, Mapping) or not issuer_verifiers:
            raise ValueError("a fixed promotion issuer allowlist is required")
        copied = dict(issuer_verifiers)
        if any(
            not isinstance(issuer_id, str)
            or not issuer_id.strip()
            or not callable(verify)
            for issuer_id, verify in copied.items()
        ):
            raise ValueError("promotion issuer allowlist is invalid")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not _is_int(max_ttl_s) or not 0 < max_ttl_s <= _MAX_PROMOTION_TTL_S:
            raise ValueError(f"max_ttl_s must be in 1..{_MAX_PROMOTION_TTL_S}")
        if not _is_int(max_future_skew_s) or max_future_skew_s < 0:
            raise ValueError("max_future_skew_s must be a non-negative integer")
        self._issuer_verifiers = MappingProxyType(copied)
        self._clock = clock
        self._max_ttl_s = max_ttl_s
        self._max_future_skew_s = max_future_skew_s

    def check(
        self, claim: object, fact: BitemporalFact
    ) -> tuple[bool, str, str | None]:
        if type(fact) is not BitemporalFact:
            return False, "invalid fact", None
        if not isinstance(claim, dict) or frozenset(claim) != _PROMOTION_FIELDS:
            return False, "malformed promotion claim", None
        if claim.get("version") != _PROMOTION_VERSION:
            return False, "unsupported promotion version", None
        issuer_id = claim.get("issuer_id")
        promotion_id = claim.get("promotion_id")
        claimed_digest = claim.get("fact_digest")
        decision = claim.get("decision")
        issued_at = claim.get("issued_at")
        expires_at = claim.get("expires_at")
        if (
            not isinstance(issuer_id, str)
            or not issuer_id
            or not isinstance(promotion_id, str)
            or not promotion_id
            or not isinstance(claimed_digest, str)
            or len(claimed_digest) != 64
            or decision != PROMOTION_DECISION
            or not _is_int(issued_at)
            or not _is_int(expires_at)
        ):
            return False, "malformed promotion payload", None

        verify_signature = self._issuer_verifiers.get(issuer_id)
        if verify_signature is None:
            return False, "untrusted promotion issuer", None
        if not _signature_ok(
            verify_signature,
            PROMOTION_DOMAIN + _canonical(_unsigned_promotion(claim)),
            claim.get("sig"),
        ):
            return False, "invalid promotion signature", None
        if claimed_digest != fact_digest(fact):
            return False, "promotion fact mismatch", None

        now = int(self._clock())
        if issued_at > now + self._max_future_skew_s:
            return False, "promotion issued in the future", None
        if expires_at <= issued_at:
            return False, "invalid promotion lifetime", None
        if expires_at - issued_at > self._max_ttl_s:
            return False, "promotion lifetime exceeds policy", None
        if now >= expires_at:
            return False, "promotion expired", None
        return True, "ok", promotion_id

    def verify(self, claim: object, fact: BitemporalFact) -> bool:
        return self.check(claim, fact)[0]


class BitemporalStore:
    """Race-safe in-memory bitemporal store with fail-closed promotion."""

    def __init__(
        self, promotion_verifier: GovernancePromotionVerifier | None = None
    ):
        if promotion_verifier is not None and not isinstance(
            promotion_verifier, GovernancePromotionVerifier
        ):
            raise TypeError("promotion_verifier must be a GovernancePromotionVerifier")
        self.__promotion_verifier = promotion_verifier
        self.__facts: list[BitemporalFact] = []
        self.__governed_promotions: dict[str, str] = {}
        self.__consumed_promotion_ids: set[str] = set()
        self.__lock = threading.RLock()

    def __snapshot(self, fact: BitemporalFact) -> BitemporalFact:
        return _clone_fact(
            fact,
            valid_until=fact.valid_until,
            governance_claim_id=self.__governed_promotions.get(fact.fact_id),
        )

    def __is_governed(self, fact: BitemporalFact) -> bool:
        promotion_id = self.__governed_promotions.get(fact.fact_id)
        return promotion_id is not None

    @property
    def facts(self) -> tuple[BitemporalFact, ...]:
        """Expose an immutable snapshot instead of the mutable backing list."""

        with self.__lock:
            return tuple(self.__snapshot(fact) for fact in self.__facts)

    def upsert(self, fact: BitemporalFact) -> BitemporalFact:
        """Store a fact as ungoverned, regardless of caller object state."""

        if type(fact) is not BitemporalFact:
            raise TypeError("fact must be an exact BitemporalFact")
        incoming = _clone_fact(
            fact, valid_until=fact.valid_until, governance_claim_id=None
        )
        with self.__lock:
            if any(item.fact_id == incoming.fact_id for item in self.__facts):
                raise ValueError("fact_id already exists")
            updated: list[BitemporalFact] = []
            for existing in self.__facts:
                if (
                    existing.subject == incoming.subject
                    and existing.predicate == incoming.predicate
                    and existing.valid_until is None
                ):
                    if incoming.valid_from < existing.valid_from:
                        raise ValueError("new valid_from precedes the current fact")
                    existing = _clone_fact(
                        existing,
                        valid_until=incoming.valid_from,
                        governance_claim_id=self.__governed_promotions.get(
                            existing.fact_id
                        ),
                    )
                updated.append(existing)
            updated.append(incoming)
            self.__facts = updated
            return self.__snapshot(incoming)

    def promote(self, fact: BitemporalFact, claim: object) -> bool:
        """Promote the exact open fact after fixed-policy signature verification."""

        if type(fact) is not BitemporalFact or self.__promotion_verifier is None:
            return False
        with self.__lock:
            index = next(
                (
                    index
                    for index, existing in enumerate(self.__facts)
                    if existing.fact_id == fact.fact_id
                    and existing.valid_until is None
                    and fact_digest(existing) == fact_digest(fact)
                ),
                None,
            )
            if index is None:
                return False
            stored = self.__facts[index]
            if self.__is_governed(stored):
                return False
            accepted, _, promotion_id = self.__promotion_verifier.check(claim, stored)
            if (
                not accepted
                or promotion_id is None
                or promotion_id in self.__consumed_promotion_ids
            ):
                return False
            self.__facts[index] = _clone_fact(
                stored,
                valid_until=stored.valid_until,
                governance_claim_id=promotion_id,
            )
            self.__governed_promotions[stored.fact_id] = promotion_id
            self.__consumed_promotion_ids.add(promotion_id)
            return True

    def current(
        self,
        subject: str,
        predicate: str,
        min_trust: float = 0.0,
        require_governed: bool = False,
    ) -> list[BitemporalFact]:
        min_trust = _finite_number("min_trust", min_trust)
        if not isinstance(require_governed, bool):
            raise TypeError("require_governed must be a boolean")
        with self.__lock:
            selected = [
                item
                for item in self.__facts
                if item.subject == subject
                and item.predicate == predicate
                and item.valid_until is None
                and item.trust_score >= min_trust
                and (self.__is_governed(item) or not require_governed)
            ]
            return [self.__snapshot(item) for item in selected]

    def history(
        self, subject: str, predicate: str | None = None
    ) -> list[BitemporalFact]:
        with self.__lock:
            selected = [
                item
                for item in self.__facts
                if item.subject == subject
                and (predicate is None or item.predicate == predicate)
            ]
            return [self.__snapshot(item) for item in selected]
