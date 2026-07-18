"""Canon promotion with explicit separation of duties and durable policy binding.

The approver is sign-only and belongs to a separate trust domain.  The
promoter receives an :class:`ApprovalVerifier` with a fixed issuer allowlist;
it never receives an approval signing function.  Approval signatures cover the
complete, domain-separated payload and are bound to one canonical candidate,
one policy, one issuer, one nonce, and a bounded validity interval.

Nonce consumption and canon materialization happen in one ``BEGIN IMMEDIATE``
SQLite transaction.  A database is permanently pinned to the verifier policy
that created it.  Legacy v2 databases and callable-only verifier APIs are
rejected rather than silently losing replay history.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


APPROVAL_DOMAIN = "maworld.canon.approval.v3"
APPROVAL_VERSION = 3
_MESSAGE_PREFIX = b"MAWORLD_CANON_APPROVAL_V3\x00"
_PAYLOAD_FIELDS = frozenset(
    {
        "domain",
        "version",
        "issuer_id",
        "policy_id",
        "candidate_hash",
        "nonce",
        "issued_at",
        "expires_at",
    }
)
_APPROVAL_FIELDS = _PAYLOAD_FIELDS | {"signature"}


class CanonSODError(RuntimeError):
    pass


class CandidateEncodingError(ValueError):
    pass


class LegacyVerifierAPIRejected(TypeError):
    pass


class PolicyBindingError(CanonSODError):
    pass


class LegacyDatabaseRejected(CanonSODError):
    pass


def _required_text(name: str, value: object, *, max_length: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty, trimmed string")
    if len(value) > max_length:
        raise ValueError(f"{name} is too long")
    return value


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 128:
        raise CandidateEncodingError("canonical JSON is too deeply nested")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise CandidateEncodingError("canonical JSON rejects NaN and infinity")
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise CandidateEncodingError("canonical JSON object keys must be strings")
            _validate_json_value(item, depth=depth + 1)
        return
    raise CandidateEncodingError("canonical JSON contains an unsupported value")


def _canonical_json_bytes(value: object, *, label: str) -> bytes:
    if type(value) is not dict:
        raise CandidateEncodingError(f"{label} must be a plain dict")
    _validate_json_value(value)
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise CandidateEncodingError(f"{label} must be canonical JSON") from error
    return encoded


def _candidate_material(candidate: dict) -> tuple[bytes, str]:
    encoded = _canonical_json_bytes(candidate, label="candidate")
    return encoded, hashlib.sha256(encoded).hexdigest()


def candidate_hash(candidate: dict) -> str:
    """Hash canonical JSON; NaN, infinity, custom mappings, and objects reject."""
    return _candidate_material(candidate)[1]


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _approval_message(payload: dict) -> bytes:
    if type(payload) is not dict or frozenset(payload) != _PAYLOAD_FIELDS:
        raise ValueError("approval payload has unexpected fields")
    return _MESSAGE_PREFIX + _canonical_json_bytes(payload, label="approval payload")


class Approver:
    """Sign-only approval issuer; it has no verification or promotion method."""

    __slots__ = ("_issuer_id", "_sign")

    def __init__(self, issuer_id: str, sign_fn: Callable[[bytes], str]):
        self._issuer_id = _required_text("issuer_id", issuer_id, max_length=128)
        if not callable(sign_fn):
            raise TypeError("Approver requires a sign-only callable")
        self._sign = sign_fn

    @property
    def issuer_id(self) -> str:
        return self._issuer_id

    def approve(
        self,
        candidate_hash_value: str,
        nonce: str,
        *,
        policy_id: str,
        ttl_s: int = 300,
        issued_at: int | None = None,
    ) -> dict:
        if not _valid_sha256(candidate_hash_value):
            raise ValueError("candidate_hash must be a lowercase SHA-256 digest")
        nonce = _required_text("nonce", nonce, max_length=256)
        policy_id = _required_text("policy_id", policy_id, max_length=128)
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, int) or ttl_s <= 0:
            raise ValueError("ttl_s must be a positive integer")
        if issued_at is None:
            issued_at = int(time.time())
        if isinstance(issued_at, bool) or not isinstance(issued_at, int):
            raise ValueError("issued_at must be an integer timestamp")
        payload = {
            "domain": APPROVAL_DOMAIN,
            "version": APPROVAL_VERSION,
            "issuer_id": self._issuer_id,
            "policy_id": policy_id,
            "candidate_hash": candidate_hash_value,
            "nonce": nonce,
            "issued_at": issued_at,
            "expires_at": issued_at + ttl_s,
        }
        signature = self._sign(_approval_message(payload))
        if not isinstance(signature, str) or not signature or len(signature) > 4096:
            raise TypeError("sign_fn must return a non-empty bounded string")
        return {**payload, "signature": signature}


@dataclass(frozen=True, slots=True)
class AcceptedApproval:
    issuer_id: str
    policy_id: str
    candidate_hash: str
    nonce: str
    issued_at: int
    expires_at: int
    approval_digest: str


@dataclass(frozen=True, slots=True)
class ApprovalVerification:
    accepted: bool
    reason: str
    approval: AcceptedApproval | None = None


class ApprovalVerifier:
    """Verify-only boundary with immutable issuer and policy configuration."""

    __slots__ = (
        "_issuer_verifiers",
        "_policy_id",
        "_max_ttl_s",
        "_future_skew_s",
        "_policy_fingerprint",
    )

    def __init__(
        self,
        issuer_verifiers: Mapping[str, Callable[[bytes, str], bool]],
        *,
        policy_id: str,
        max_ttl_s: int = 300,
        max_future_skew_s: int = 30,
    ):
        policy_id = _required_text("policy_id", policy_id, max_length=128)
        if isinstance(max_ttl_s, bool) or not isinstance(max_ttl_s, int) or max_ttl_s <= 0:
            raise ValueError("max_ttl_s must be a positive integer")
        if (
            isinstance(max_future_skew_s, bool)
            or not isinstance(max_future_skew_s, int)
            or max_future_skew_s < 0
        ):
            raise ValueError("max_future_skew_s must be a non-negative integer")
        copied: dict[str, Callable[[bytes, str], bool]] = {}
        for issuer_id, verify_fn in dict(issuer_verifiers).items():
            issuer_id = _required_text("issuer_id", issuer_id, max_length=128)
            if not callable(verify_fn):
                raise TypeError("every issuer verifier must be callable")
            copied[issuer_id] = verify_fn
        if not copied:
            raise ValueError("at least one approval issuer is required")
        self._issuer_verifiers = MappingProxyType(copied)
        self._policy_id = policy_id
        self._max_ttl_s = max_ttl_s
        self._future_skew_s = max_future_skew_s
        policy_material = {
            "domain": APPROVAL_DOMAIN,
            "version": APPROVAL_VERSION,
            "policy_id": policy_id,
            "allowed_issuers": sorted(copied),
            "max_ttl_s": max_ttl_s,
            "max_future_skew_s": max_future_skew_s,
        }
        self._policy_fingerprint = hashlib.sha256(
            _canonical_json_bytes(policy_material, label="approval policy")
        ).hexdigest()

    @property
    def policy_id(self) -> str:
        return self._policy_id

    @property
    def allowed_issuers(self) -> frozenset[str]:
        return frozenset(self._issuer_verifiers)

    @property
    def policy_fingerprint(self) -> str:
        return self._policy_fingerprint

    def verify(self, candidate_hash_value: str, approval: object) -> ApprovalVerification:
        def reject(reason: str) -> ApprovalVerification:
            return ApprovalVerification(False, reason)

        if not _valid_sha256(candidate_hash_value):
            return reject("INVALID_CANDIDATE_HASH")
        if type(approval) is not dict:
            return reject("MALFORMED_APPROVAL")
        if frozenset(approval) != _APPROVAL_FIELDS:
            return reject("UNEXPECTED_APPROVAL_FIELDS")
        try:
            domain = approval["domain"]
            version = approval["version"]
            issuer_id = approval["issuer_id"]
            policy_id = approval["policy_id"]
            approved_hash = approval["candidate_hash"]
            nonce = approval["nonce"]
            issued_at = approval["issued_at"]
            expires_at = approval["expires_at"]
            signature = approval["signature"]
            issuer_id = _required_text("issuer_id", issuer_id, max_length=128)
            policy_id = _required_text("policy_id", policy_id, max_length=128)
            nonce = _required_text("nonce", nonce, max_length=256)
        except (KeyError, TypeError, ValueError):
            return reject("MALFORMED_APPROVAL")
        if domain != APPROVAL_DOMAIN or version != APPROVAL_VERSION:
            return reject("WRONG_APPROVAL_DOMAIN")
        if policy_id != self._policy_id:
            return reject("WRONG_POLICY")
        verify_fn = self._issuer_verifiers.get(issuer_id)
        if verify_fn is None:
            return reject("UNTRUSTED_ISSUER")
        if approved_hash != candidate_hash_value or not _valid_sha256(approved_hash):
            return reject("CANDIDATE_MISMATCH")
        if (
            isinstance(issued_at, bool)
            or not isinstance(issued_at, int)
            or isinstance(expires_at, bool)
            or not isinstance(expires_at, int)
        ):
            return reject("INVALID_APPROVAL_TIME")
        ttl = expires_at - issued_at
        if ttl <= 0 or ttl > self._max_ttl_s:
            return reject("INVALID_APPROVAL_TTL")
        now = int(time.time())
        if issued_at > now + self._future_skew_s:
            return reject("APPROVAL_FROM_FUTURE")
        if expires_at <= now:
            return reject("APPROVAL_EXPIRED")
        if not isinstance(signature, str) or not signature or len(signature) > 4096:
            return reject("MALFORMED_SIGNATURE")
        payload = {field: approval[field] for field in _PAYLOAD_FIELDS}
        try:
            message = _approval_message(payload)
            signature_ok = verify_fn(message, signature) is True
        except Exception:
            signature_ok = False
        if not signature_ok:
            return reject("INVALID_APPROVAL_SIGNATURE")
        accepted = AcceptedApproval(
            issuer_id=issuer_id,
            policy_id=policy_id,
            candidate_hash=approved_hash,
            nonce=nonce,
            issued_at=issued_at,
            expires_at=expires_at,
            approval_digest=hashlib.sha256(message).hexdigest(),
        )
        return ApprovalVerification(True, "ACCEPTED", accepted)


class CanonPromoter:
    """Verify approvals and atomically consume nonce + materialize candidate."""

    def __init__(self, db_path, verifier: ApprovalVerifier):
        if type(verifier) is not ApprovalVerifier:
            raise LegacyVerifierAPIRejected(
                "CanonPromoter requires an ApprovalVerifier; callable legacy API is disabled"
            )
        self._verifier = verifier
        self.con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        try:
            # Configure contention handling before WAL negotiation. Two service
            # instances may open a fresh database concurrently; journal_mode
            # itself can need the database lock.
            self.con.execute("PRAGMA busy_timeout=30000")
            self.con.execute("PRAGMA foreign_keys=ON")
            self._enable_wal()
            self.con.execute("PRAGMA synchronous=FULL")
            self._initialize_database()
        except BaseException:
            self.con.close()
            raise

    def _enable_wal(self) -> None:
        """Negotiate WAL with a bounded retry for simultaneous first opens.

        SQLite can return ``database is locked`` immediately from
        ``PRAGMA journal_mode=WAL`` even when a busy timeout is configured.
        Only that transient lock class is retried; every other error remains
        fail-closed.
        """
        deadline = time.monotonic() + 5.0
        while True:
            try:
                row = self.con.execute("PRAGMA journal_mode=WAL").fetchone()
            except sqlite3.OperationalError as error:
                code = getattr(error, "sqlite_errorcode", None)
                busy = (
                    isinstance(code, int)
                    and (code & 0xFF) == sqlite3.SQLITE_BUSY
                ) or (
                    code is None
                    and str(error).casefold() == "database is locked"
                )
                if not busy or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
                continue
            if row is None or str(row[0]).casefold() != "wal":
                raise sqlite3.OperationalError("WAL journal mode was not established")
            return

    @property
    def policy_id(self) -> str:
        return self._verifier.policy_id

    def _initialize_database(self) -> None:
        self.con.execute("BEGIN IMMEDIATE")
        try:
            tables = {
                row[0]
                for row in self.con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if {"used_nonce", "canon"} & tables:
                raise LegacyDatabaseRejected(
                    "legacy canon database has unbound replay state; explicit migration required"
                )
            self.con.execute(
                """CREATE TABLE IF NOT EXISTS canon_policy_v3(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    policy_id TEXT NOT NULL,
                    policy_fingerprint TEXT NOT NULL)"""
            )
            self.con.execute(
                """CREATE TABLE IF NOT EXISTS canon_nonce_v3(
                    policy_id TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    candidate_hash TEXT NOT NULL,
                    used_at INTEGER NOT NULL,
                    PRIMARY KEY(policy_id,issuer_id,nonce))"""
            )
            self.con.execute(
                """CREATE TABLE IF NOT EXISTS canon_promotion_v3(
                    candidate_hash TEXT PRIMARY KEY,
                    candidate_json TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    approval_digest TEXT NOT NULL,
                    promoted_at INTEGER NOT NULL,
                    FOREIGN KEY(policy_id,issuer_id,nonce)
                        REFERENCES canon_nonce_v3(policy_id,issuer_id,nonce))"""
            )
            row = self.con.execute(
                "SELECT policy_id,policy_fingerprint FROM canon_policy_v3 WHERE singleton=1"
            ).fetchone()
            if row is None:
                self.con.execute(
                    "INSERT INTO canon_policy_v3"
                    "(singleton,policy_id,policy_fingerprint) VALUES(1,?,?)",
                    (self._verifier.policy_id, self._verifier.policy_fingerprint),
                )
            elif row != (
                self._verifier.policy_id,
                self._verifier.policy_fingerprint,
            ):
                raise PolicyBindingError(
                    "canon database is pinned to a different approval policy configuration"
                )
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise

    @staticmethod
    def _deny(reason: str) -> dict:
        return {"ok": False, "reason": reason}

    def promote(self, candidate: object, approval: object) -> dict:
        try:
            candidate_json_bytes, candidate_hash_value = _candidate_material(candidate)  # type: ignore[arg-type]
        except CandidateEncodingError:
            return self._deny("INVALID_CANDIDATE")
        verification = self._verifier.verify(candidate_hash_value, approval)
        if not verification.accepted or verification.approval is None:
            return self._deny(verification.reason)
        accepted = verification.approval

        try:
            self.con.execute("BEGIN IMMEDIATE")
            policy_row = self.con.execute(
                "SELECT policy_id,policy_fingerprint "
                "FROM canon_policy_v3 WHERE singleton=1"
            ).fetchone()
            if policy_row != (
                accepted.policy_id,
                self._verifier.policy_fingerprint,
            ):
                self.con.execute("ROLLBACK")
                return self._deny("DATABASE_POLICY_MISMATCH")
            now = int(time.time())
            if accepted.expires_at <= now:
                self.con.execute("ROLLBACK")
                return self._deny("APPROVAL_EXPIRED")
            nonce_exists = self.con.execute(
                "SELECT 1 FROM canon_nonce_v3 "
                "WHERE policy_id=? AND issuer_id=? AND nonce=?",
                (accepted.policy_id, accepted.issuer_id, accepted.nonce),
            ).fetchone()
            if nonce_exists is not None:
                self.con.execute("ROLLBACK")
                return self._deny("NONCE_REPLAY")
            canon_exists = self.con.execute(
                "SELECT 1 FROM canon_promotion_v3 WHERE candidate_hash=?",
                (candidate_hash_value,),
            ).fetchone()
            if canon_exists is not None:
                self.con.execute("ROLLBACK")
                return self._deny("ALREADY_PROMOTED")
            self.con.execute(
                "INSERT INTO canon_nonce_v3"
                "(policy_id,issuer_id,nonce,candidate_hash,used_at) VALUES(?,?,?,?,?)",
                (
                    accepted.policy_id,
                    accepted.issuer_id,
                    accepted.nonce,
                    candidate_hash_value,
                    now,
                ),
            )
            self.con.execute(
                "INSERT INTO canon_promotion_v3"
                "(candidate_hash,candidate_json,policy_id,issuer_id,nonce,issued_at,"
                "expires_at,approval_digest,promoted_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    candidate_hash_value,
                    candidate_json_bytes.decode("utf-8"),
                    accepted.policy_id,
                    accepted.issuer_id,
                    accepted.nonce,
                    accepted.issued_at,
                    accepted.expires_at,
                    accepted.approval_digest,
                    now,
                ),
            )
            self.con.execute("COMMIT")
        except sqlite3.Error:
            try:
                self.con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return self._deny("DURABLE_COMMIT_FAILED")
        return {
            "ok": True,
            "candidate_hash": candidate_hash_value,
            "policy_id": accepted.policy_id,
            "issuer_id": accepted.issuer_id,
        }

    def close(self) -> None:
        self.con.close()


__all__ = [
    "APPROVAL_DOMAIN",
    "APPROVAL_VERSION",
    "AcceptedApproval",
    "ApprovalVerification",
    "ApprovalVerifier",
    "Approver",
    "CandidateEncodingError",
    "CanonPromoter",
    "CanonSODError",
    "LegacyDatabaseRejected",
    "LegacyVerifierAPIRejected",
    "PolicyBindingError",
    "candidate_hash",
]
