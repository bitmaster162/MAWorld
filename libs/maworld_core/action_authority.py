"""Verifier-only action execution with explicit external issuers.

No module-level signing key exists here.  A trusted gate uses ``DecisionIssuer``;
an owner-control service uses ``HumanApprovalIssuer``; the executor receives only
an ``ActionVerifier`` with a fixed issuer allowlist.  Production deployments can
back the sign/verify callables with a remote service or asymmetric key.

The legacy ``gate_decide`` helper now creates an unsigned proposal only.  It is
kept so old proposal-producing modules import cleanly, but its result can never be
executed by ``ActionExecutor``.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


DECISION_DOMAIN = b"MAWORLD/ACTION-DECISION/V1\x00"
HUMAN_DOMAIN = b"MAWORLD/HUMAN-APPROVAL/V1\x00"
_EXECUTABLE = {"ALLOW"}
_VERDICTS = {"ALLOW", "DENY", "REQUIRE_CONFIRMATION"}
_MAX_DECISION_TTL_S = 300
_MAX_FUTURE_SKEW_S = 5

SignFn = Callable[[bytes], str]
VerifyFn = Callable[[bytes, str], bool]


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class ActionSpec:
    action_type: str
    target: str
    params: tuple = ()
    handler_id: str = ""

    def resolved_handler_id(self) -> str:
        return self.handler_id or self.action_type

    def payload_hash(self) -> str:
        return hashlib.sha256(_canonical(list(self.params)).encode()).hexdigest()

    def canonical(self) -> str:
        return _canonical({
            "action_type": self.action_type,
            "target": self.target,
            "params": list(self.params),
            "handler_id": self.resolved_handler_id(),
            "payload_hash": self.payload_hash(),
        })

    def hash(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


@dataclass(frozen=True)
class Decision:
    issuer_id: str
    spec_hash: str
    handler_id: str
    payload_hash: str
    verdict: str
    nonce: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "issuer_id": self.issuer_id,
            "spec_hash": self.spec_hash,
            "handler_id": self.handler_id,
            "payload_hash": self.payload_hash,
            "verdict": self.verdict,
            "nonce": self.nonce,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }).encode()

    def digest(self) -> str:
        return hashlib.sha256(self._payload() + b":" + self.sig.encode()).hexdigest()


@dataclass(frozen=True)
class HumanConfirmation:
    decision_digest: str
    approver_id: str
    issued_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return _canonical({
            "decision_digest": self.decision_digest,
            "approver_id": self.approver_id,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }).encode()


class ConfusedDeputy(RuntimeError):
    pass


class DecisionIssuer:
    """Gate-side signer. Keep this object outside the executor process in production."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self, spec: ActionSpec, verdict: str, *, ttl_s: int = 60,
        now: int | None = None, nonce: str | None = None,
    ) -> Decision:
        if verdict not in _VERDICTS:
            raise ValueError(f"unsupported verdict {verdict!r}")
        if not isinstance(ttl_s, int) or isinstance(ttl_s, bool) or not 0 < ttl_s <= _MAX_DECISION_TTL_S:
            raise ValueError(f"ttl_s must be in 1..{_MAX_DECISION_TTL_S}")
        issued_at = int(self._clock()) if now is None else int(now)
        unsigned = Decision(
            issuer_id=self.issuer_id,
            spec_hash=spec.hash(),
            handler_id=spec.resolved_handler_id(),
            payload_hash=spec.payload_hash(),
            verdict=verdict,
            nonce=nonce or uuid.uuid4().hex,
            issued_at=issued_at,
            expires_at=issued_at + ttl_s,
        )
        sig = self.__sign(DECISION_DOMAIN + unsigned._payload())
        if not isinstance(sig, str) or not sig:
            raise ConfusedDeputy("decision signer returned an invalid signature")
        return Decision(**{**unsigned.__dict__, "sig": sig})


class HumanApprovalIssuer:
    """Owner-control-side signer, separate from the gate and executor."""

    def __init__(self, approver_id: str, sign: SignFn, *, clock=time.time):
        self.approver_id = _required("approver_id", approver_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def confirm(self, decision: Decision, *, ttl_s: int = 60, now: int | None = None) -> HumanConfirmation:
        if not isinstance(ttl_s, int) or isinstance(ttl_s, bool) or ttl_s <= 0:
            raise ValueError("approval ttl_s must be a positive integer")
        issued_at = int(self._clock()) if now is None else int(now)
        expires_at = min(decision.expires_at, issued_at + ttl_s)
        if expires_at <= issued_at:
            raise ConfusedDeputy("cannot approve an expired decision")
        unsigned = HumanConfirmation(
            decision_digest=decision.digest(),
            approver_id=self.approver_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        sig = self.__sign(HUMAN_DOMAIN + unsigned._payload())
        if not isinstance(sig, str) or not sig:
            raise ConfusedDeputy("human approval signer returned an invalid signature")
        return HumanConfirmation(**{**unsigned.__dict__, "sig": sig})


class ActionVerifier:
    """Verifier-only trust map used by the executor."""

    def __init__(
        self,
        decision_verifiers: Mapping[str, VerifyFn],
        approval_verifiers: Mapping[str, VerifyFn] | None = None,
        *,
        clock=time.time,
        max_decision_ttl_s: int = _MAX_DECISION_TTL_S,
        max_future_skew_s: int = _MAX_FUTURE_SKEW_S,
    ):
        if not decision_verifiers or any(not callable(v) for v in decision_verifiers.values()):
            raise ValueError("a fixed decision issuer allowlist is required")
        self._decision_verifiers = MappingProxyType(dict(decision_verifiers))
        self._approval_verifiers = MappingProxyType(dict(approval_verifiers or {}))
        if any(not callable(v) for v in self._approval_verifiers.values()):
            raise ValueError("approval verifiers must be callable")
        self._clock = clock
        self._max_ttl = int(max_decision_ttl_s)
        self._future_skew = int(max_future_skew_s)

    @staticmethod
    def _verified(verify: VerifyFn, message: bytes, signature: str) -> bool:
        try:
            return bool(signature) and bool(verify(message, signature))
        except Exception:
            return False

    def authorize(
        self, spec: ActionSpec, decision: Decision,
        confirmation: HumanConfirmation | None = None,
    ) -> None:
        verify_decision = self._decision_verifiers.get(decision.issuer_id)
        if verify_decision is None or not self._verified(
            verify_decision, DECISION_DOMAIN + decision._payload(), decision.sig
        ):
            raise ConfusedDeputy("decision issuer/signature is not trusted")
        now = int(self._clock())
        if decision.spec_hash != spec.hash():
            raise ConfusedDeputy("decision is not bound to the action being executed")
        if decision.handler_id != spec.resolved_handler_id():
            raise ConfusedDeputy("decision handler binding mismatch")
        if decision.payload_hash != spec.payload_hash():
            raise ConfusedDeputy("decision payload binding mismatch")
        if decision.issued_at > now + self._future_skew:
            raise ConfusedDeputy("decision issued in the future")
        if now >= decision.expires_at:
            raise ConfusedDeputy("decision expired")
        if decision.expires_at - decision.issued_at > self._max_ttl:
            raise ConfusedDeputy("decision lifetime exceeds verifier policy")
        if decision.verdict == "DENY":
            raise ConfusedDeputy("DENY")
        if decision.verdict not in _EXECUTABLE | {"REQUIRE_CONFIRMATION"}:
            raise ConfusedDeputy(f"non-executable verdict {decision.verdict}")
        if decision.verdict == "REQUIRE_CONFIRMATION":
            self._verify_confirmation(decision, confirmation, now)

    def _verify_confirmation(
        self, decision: Decision, confirmation: HumanConfirmation | None, now: int
    ) -> None:
        if not isinstance(confirmation, HumanConfirmation):
            raise ConfusedDeputy("verified human confirmation required")
        verify_approval = self._approval_verifiers.get(confirmation.approver_id)
        if verify_approval is None or not self._verified(
            verify_approval, HUMAN_DOMAIN + confirmation._payload(), confirmation.sig
        ):
            raise ConfusedDeputy("human approver/signature is not trusted")
        if confirmation.decision_digest != decision.digest():
            raise ConfusedDeputy("human confirmation is for another decision")
        if confirmation.issued_at > now + self._future_skew:
            raise ConfusedDeputy("human confirmation issued in the future")
        if now >= confirmation.expires_at or confirmation.expires_at > decision.expires_at:
            raise ConfusedDeputy("human confirmation expired or outlives decision")


def gate_decide(
    spec: ActionSpec, verdict: str, *, ttl_s: int = 60,
    now: int | None = None, nonce: str | None = None,
) -> Decision:
    """Legacy proposal helper. Its unsigned result is deliberately non-executable."""
    if verdict not in _VERDICTS:
        raise ValueError(f"unsupported verdict {verdict!r}")
    issued_at = int(time.time()) if now is None else int(now)
    return Decision(
        issuer_id="legacy-untrusted",
        spec_hash=spec.hash(),
        handler_id=spec.resolved_handler_id(),
        payload_hash=spec.payload_hash(),
        verdict=verdict,
        nonce=nonce or uuid.uuid4().hex,
        issued_at=issued_at,
        expires_at=issued_at + ttl_s,
        sig="",
    )


def human_confirm(decision: Decision):
    """Removed insecure helper; callers must use an explicit HumanApprovalIssuer."""
    raise ConfusedDeputy("explicit HumanApprovalIssuer required")


class SQLiteNonceStore:
    """Durable, atomic replay barrier shared by all executor instances."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path:
            raise ValueError("nonce database path is required")
        self.con = sqlite3.connect(
            path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self._lock = threading.Lock()
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=30000")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute(
            """CREATE TABLE IF NOT EXISTS action_nonce(
                nonce TEXT PRIMARY KEY,
                decision_digest TEXT NOT NULL,
                consumed_at INTEGER NOT NULL
            )"""
        )

    def consume(self, decision: Decision) -> bool:
        with self._lock:
            cur = self.con.execute(
                "INSERT OR IGNORE INTO action_nonce(nonce,decision_digest,consumed_at) "
                "VALUES(?,?,?)",
                (decision.nonce, decision.digest(), int(time.time())),
            )
        return cur.rowcount == 1

    def close(self) -> None:
        self.con.close()


class ActionExecutor:
    """Resolve handlers from a registry fixed at construction, never from a call argument."""

    def __init__(
        self,
        handlers: Mapping[str, Callable[[ActionSpec], object]],
        verifier: ActionVerifier,
        nonce_store: SQLiteNonceStore,
    ):
        if not handlers or any(not callable(handler) for handler in handlers.values()):
            raise ValueError("a non-empty fixed handler registry is required")
        if not isinstance(verifier, ActionVerifier):
            raise ValueError("an explicit verifier-only ActionVerifier is required")
        if not callable(getattr(nonce_store, "consume", None)):
            raise ValueError("an explicit durable nonce store is required")
        self._handlers = MappingProxyType(dict(handlers))
        self._verifier = verifier
        self._nonce_store = nonce_store

    def execute(
        self, spec: ActionSpec, decision: Decision,
        *, confirmation: HumanConfirmation | None = None,
    ) -> dict:
        self._verifier.authorize(spec, decision, confirmation)
        handler = self._handlers.get(decision.handler_id)
        if handler is None:
            raise ConfusedDeputy(f"unregistered handler {decision.handler_id!r}")
        if not self._nonce_store.consume(decision):
            raise ConfusedDeputy("decision nonce replay")
        return {
            "executed": True,
            "spec_hash": spec.hash(),
            "handler_id": decision.handler_id,
            "result": handler(spec),
        }


def execute(
    spec: ActionSpec,
    decision: Decision,
    executor: ActionExecutor,
    confirmation: HumanConfirmation | None = None,
):
    """Compatibility entry point accepting only a fixed ``ActionExecutor``."""
    if not isinstance(executor, ActionExecutor):
        raise ConfusedDeputy("per-call effect callbacks are forbidden; use ActionExecutor")
    return executor.execute(spec, decision, confirmation=confirmation)
