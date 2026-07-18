"""NautilusTrader risk seam: verified observations in, proposals only out.

This module does not submit orders and does not mint execution authority. A
strategy cannot assert healthy reconciliation or heartbeat flags on an order
call. Reconciliation, heartbeat, and daily-trade observations must arrive in a
short-lived signed snapshot verified against an issuer allowlist fixed when the
gate is constructed.

Even a valid snapshot only makes an order eligible as a proposal. A separate
Action Authority decision and hardened effect path remain mandatory for any
external venue effect.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Callable, Mapping


RISK_SNAPSHOT_DOMAIN = b"MAWORLD/NAUTILUS/RISK-SNAPSHOT/V1\x00"
MAX_SNAPSHOT_TTL_S = 30
MAX_FUTURE_SKEW_S = 5
RECONCILIATION_STATES = frozenset({"MATCH", "MISMATCH", "UNKNOWN"})
HEARTBEAT_STATES = frozenset({"HEALTHY", "LOST", "UNKNOWN"})

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


def _required(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class RiskCheck:
    max_risk_bps: int = 100
    max_trades_per_day: int = 20

    def __post_init__(self) -> None:
        if not _is_int(self.max_risk_bps) or self.max_risk_bps < 0:
            raise ValueError("max_risk_bps must be a non-negative integer")
        if not _is_int(self.max_trades_per_day) or self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be a positive integer")


@dataclass(frozen=True)
class RiskSnapshot:
    issuer_id: str
    snapshot_id: str
    reconciliation_state: str
    heartbeat_state: str
    trades_today: int
    observed_at: int
    expires_at: int
    sig: str = ""

    def _payload(self) -> bytes:
        return RISK_SNAPSHOT_DOMAIN + _canonical({
            "issuer_id": self.issuer_id,
            "snapshot_id": self.snapshot_id,
            "reconciliation_state": self.reconciliation_state,
            "heartbeat_state": self.heartbeat_state,
            "trades_today": self.trades_today,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
        })

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> "RiskSnapshot | None":
        if not isinstance(raw, dict) or set(raw) != {
            "issuer_id", "snapshot_id", "reconciliation_state",
            "heartbeat_state", "trades_today", "observed_at", "expires_at",
            "sig",
        }:
            return None
        try:
            snapshot = cls(**raw)
        except TypeError:
            return None
        return snapshot if _well_formed(snapshot) else None


def _well_formed(snapshot: RiskSnapshot) -> bool:
    return (
        all(
            isinstance(value, str) and bool(value.strip())
            for value in (snapshot.issuer_id, snapshot.snapshot_id, snapshot.sig)
        )
        and snapshot.reconciliation_state in RECONCILIATION_STATES
        and snapshot.heartbeat_state in HEARTBEAT_STATES
        and _is_int(snapshot.trades_today)
        and snapshot.trades_today >= 0
        and _is_int(snapshot.observed_at)
        and _is_int(snapshot.expires_at)
    )


class RiskSnapshotIssuer:
    """Sign-only observation service role; keep out of strategy processes."""

    def __init__(self, issuer_id: str, sign: SignFn, *, clock=time.time):
        self.issuer_id = _required("issuer_id", issuer_id)
        if not callable(sign):
            raise TypeError("sign must be callable")
        self.__sign = sign
        self._clock = clock

    def issue(
        self,
        *,
        reconciliation_state: str,
        heartbeat_state: str,
        trades_today: int,
        ttl_s: int = MAX_SNAPSHOT_TTL_S,
        now: int | None = None,
    ) -> RiskSnapshot:
        if reconciliation_state not in RECONCILIATION_STATES:
            raise ValueError("invalid reconciliation_state")
        if heartbeat_state not in HEARTBEAT_STATES:
            raise ValueError("invalid heartbeat_state")
        if not _is_int(trades_today) or trades_today < 0:
            raise ValueError("trades_today must be a non-negative integer")
        if not _is_int(ttl_s) or not 0 < ttl_s <= MAX_SNAPSHOT_TTL_S:
            raise ValueError(f"ttl_s must be in 1..{MAX_SNAPSHOT_TTL_S}")
        issued_at = int(self._clock()) if now is None else now
        if not _is_int(issued_at):
            raise ValueError("now must be an integer timestamp")
        unsigned = RiskSnapshot(
            issuer_id=self.issuer_id,
            snapshot_id=str(uuid.uuid4()),
            reconciliation_state=reconciliation_state,
            heartbeat_state=heartbeat_state,
            trades_today=trades_today,
            observed_at=issued_at,
            expires_at=issued_at + ttl_s,
            sig="pending",
        )
        signature = self.__sign(unsigned._payload())
        if not isinstance(signature, str) or not signature:
            raise ValueError("signer returned an invalid signature")
        return RiskSnapshot(**{**unsigned.to_dict(), "sig": signature})


@dataclass(frozen=True)
class SnapshotCheck:
    accepted: bool
    reason: str
    snapshot: RiskSnapshot | None = None


class RiskSnapshotVerifier:
    """Verifier-only role with a copied, fixed observation-issuer allowlist."""

    def __init__(self, trusted_issuers: Mapping[str, VerifyFn], *, clock=time.time):
        if not isinstance(trusted_issuers, Mapping) or not trusted_issuers:
            raise ValueError("a fixed risk snapshot issuer allowlist is required")
        copied = dict(trusted_issuers)
        if any(
            not isinstance(issuer_id, str)
            or not issuer_id.strip()
            or not callable(verify)
            for issuer_id, verify in copied.items()
        ):
            raise ValueError("risk snapshot issuer allowlist is invalid")
        self.__trusted_issuers = MappingProxyType(copied)
        self._clock = clock

    def verify(self, raw: object, *, now: int | None = None) -> SnapshotCheck:
        snapshot = raw if isinstance(raw, RiskSnapshot) else RiskSnapshot.from_dict(raw)
        if snapshot is None or not _well_formed(snapshot):
            return SnapshotCheck(False, "MALFORMED")
        verify = self.__trusted_issuers.get(snapshot.issuer_id)
        if verify is None:
            return SnapshotCheck(False, "UNTRUSTED_ISSUER")
        checked_at = int(self._clock()) if now is None else now
        if not _is_int(checked_at):
            return SnapshotCheck(False, "INVALID_CLOCK")
        if snapshot.observed_at > checked_at + MAX_FUTURE_SKEW_S:
            return SnapshotCheck(False, "FROM_FUTURE")
        if snapshot.expires_at <= snapshot.observed_at:
            return SnapshotCheck(False, "INVALID_TTL")
        if snapshot.expires_at - snapshot.observed_at > MAX_SNAPSHOT_TTL_S:
            return SnapshotCheck(False, "TTL_TOO_LONG")
        if checked_at >= snapshot.expires_at:
            return SnapshotCheck(False, "EXPIRED")
        try:
            signature_ok = bool(verify(snapshot._payload(), snapshot.sig))
        except Exception:
            signature_ok = False
        if not signature_ok:
            return SnapshotCheck(False, "BAD_SIGNATURE")
        return SnapshotCheck(True, "VERIFIED", snapshot)


class NautilusRiskGate:
    """Non-authoritative pre-trade filter that emits no external effects."""

    def __init__(self, snapshot_verifier: RiskSnapshotVerifier, *, cfg: RiskCheck | None = None):
        if not isinstance(snapshot_verifier, RiskSnapshotVerifier):
            raise TypeError("a fixed RiskSnapshotVerifier is required")
        self.__snapshot_verifier = snapshot_verifier
        self.__cfg = RiskCheck() if cfg is None else cfg
        if not isinstance(self.__cfg, RiskCheck):
            raise TypeError("cfg must be RiskCheck")

    @staticmethod
    def _result(gate: str, reason: str, *, intent: dict | None = None,
                snapshot_id: str | None = None) -> dict:
        return {
            "gate": gate,
            "reason": reason,
            "status": "PROPOSED",
            "submitted": False,
            "authoritative": False,
            "requires": "Action Authority decision + hardened effect handler",
            "snapshot_id": snapshot_id,
            "intent": intent,
        }

    def on_order(
        self,
        *,
        client_order_id: str,
        instrument: str,
        side: str,
        qty_fixed: int,
        proposed_risk_bps: int,
        snapshot: object = None,
        reduce_only: bool = False,
    ) -> dict:
        if (
            not isinstance(client_order_id, str)
            or not client_order_id.strip()
            or not isinstance(instrument, str)
            or not instrument.strip()
            or side not in {"BUY", "SELL"}
            or not _is_int(qty_fixed)
            or qty_fixed <= 0
            or not _is_int(proposed_risk_bps)
            or proposed_risk_bps < 0
            or not isinstance(reduce_only, bool)
        ):
            return self._result("INELIGIBLE_PROPOSAL", "INVALID_ORDER")

        checked = self.__snapshot_verifier.verify(snapshot)
        if not checked.accepted or checked.snapshot is None:
            return self._result(
                "INELIGIBLE_PROPOSAL",
                f"RISK_SNAPSHOT_{checked.reason}",
            )
        observed = checked.snapshot
        if observed.reconciliation_state != "MATCH":
            return self._result(
                "INELIGIBLE_PROPOSAL",
                "RECONCILIATION_NOT_VERIFIED",
                snapshot_id=observed.snapshot_id,
            )

        intent = {
            "client_order_id": client_order_id,
            "instrument": instrument,
            "side": side,
            "order_type": "MARKET",
            "qty_fixed": qty_fixed,
            "reduce_only": reduce_only,
        }
        if observed.heartbeat_state != "HEALTHY":
            if reduce_only:
                return self._result(
                    "REDUCE_ONLY_PROPOSAL",
                    "HEARTBEAT_NOT_HEALTHY",
                    intent=intent,
                    snapshot_id=observed.snapshot_id,
                )
            return self._result(
                "INELIGIBLE_PROPOSAL",
                "HEARTBEAT_NOT_HEALTHY",
                snapshot_id=observed.snapshot_id,
            )
        if observed.trades_today >= self.__cfg.max_trades_per_day:
            return self._result(
                "INELIGIBLE_PROPOSAL",
                "MAX_TRADES_PER_DAY",
                snapshot_id=observed.snapshot_id,
            )
        if proposed_risk_bps > self.__cfg.max_risk_bps:
            return self._result(
                "INELIGIBLE_PROPOSAL",
                "RISK_PER_TRADE_EXCEEDED",
                snapshot_id=observed.snapshot_id,
            )
        return self._result(
            "ELIGIBLE_PROPOSAL",
            "RISK_OBSERVATIONS_VERIFIED",
            intent=intent,
            snapshot_id=observed.snapshot_id,
        )
