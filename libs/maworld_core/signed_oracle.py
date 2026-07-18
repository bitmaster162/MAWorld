"""Verifier-only, proposal-only external price quote boundary."""
from __future__ import annotations

import json
import hashlib
import math
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Callable, Mapping


QUOTE_DOMAIN = b"MAWORLD/ORACLE-QUOTE/V2\x00"
VerifyFn = Callable[[bytes, str], bool]
SignFn = Callable[[bytes], str]


def _required_text(name: str, value: object, limit: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be bounded non-empty text")
    return value


def _price(value: object) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid price") from error
    if not price.is_finite() or price <= 0:
        raise ValueError("price must be finite and positive")
    return price


def _body(feed: str, price: Decimal, observed_at: int, update_id: str) -> bytes:
    body = {
        "feed": _required_text("feed", feed),
        "observed_at": observed_at,
        "price": format(price, "f"),
        "update_id": _required_text("update_id", update_id, 128),
        "version": 2,
    }
    return QUOTE_DOMAIN + json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


class OracleIssuer:
    """Sign-only quote issuer; custody belongs outside the verifier process."""

    def __init__(self, issuer_id: str, sign: SignFn):
        self.issuer_id = _required_text("issuer_id", issuer_id, 128)
        if not callable(sign):
            raise TypeError("sign callback required")
        self.__sign = sign

    def sign_quote(self, feed: str, price: object, observed_at: int, update_id: str) -> tuple[str, str]:
        if not isinstance(observed_at, int) or isinstance(observed_at, bool):
            raise ValueError("observed_at must be integer epoch seconds")
        signature = self.__sign(_body(feed, _price(price), observed_at, update_id))
        if not isinstance(signature, str) or not signature or len(signature) > 4096:
            raise ValueError("invalid oracle signature")
        return self.issuer_id, signature


class OracleReplayStore:
    """Durable, atomic quote-id consumption store.

    The database path is fixed by the composition root.  Production deployments
    must place it on storage writable only by the verifier identity.
    """

    def __init__(self, path: str):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("explicit durable oracle replay database path required")
        self._connection = sqlite3.connect(
            path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self._lock = threading.Lock()
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS oracle_quote_replay(
                update_id TEXT PRIMARY KEY,
                quote_digest TEXT NOT NULL,
                consumed_at INTEGER NOT NULL
            )"""
        )

    def consume(self, update_id: str, quote_digest: str, consumed_at: int) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO oracle_quote_replay"
                "(update_id,quote_digest,consumed_at) VALUES(?,?,?)",
                (update_id, quote_digest, consumed_at),
            )
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class OracleVerifier:
    """Fixed trust/policy verifier that emits no execution authority."""

    def __init__(
        self,
        issuer_verifiers: Mapping[str, VerifyFn],
        replay_store: OracleReplayStore,
        *,
        max_deviation: Decimal = Decimal("0.20"),
        min_sources: int = 2,
        max_age_seconds: int = 120,
        max_future_skew_seconds: int = 5,
        clock=time.time,
    ):
        if not issuer_verifiers or any(
            not isinstance(issuer, str) or not issuer or not callable(verify)
            for issuer, verify in issuer_verifiers.items()
        ):
            raise ValueError("fixed non-empty oracle issuer allowlist required")
        if not isinstance(replay_store, OracleReplayStore):
            raise TypeError("durable OracleReplayStore required")
        deviation = Decimal(str(max_deviation))
        if not deviation.is_finite() or not Decimal("0") <= deviation <= Decimal("1"):
            raise ValueError("max_deviation must be finite and in [0,1]")
        if isinstance(min_sources, bool) or not 2 <= min_sources <= len(issuer_verifiers):
            raise ValueError("min_sources must be at least two and fit the allowlist")
        if not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 3600:
            raise ValueError("bounded max_age_seconds required")
        if not isinstance(max_future_skew_seconds, int) or not 0 <= max_future_skew_seconds <= 60:
            raise ValueError("bounded max_future_skew_seconds required")
        if not callable(clock):
            raise TypeError("clock must be fixed and callable")
        self._verifiers = MappingProxyType(dict(issuer_verifiers))
        self._replay = replay_store
        self._max_deviation = deviation
        self._min_sources = min_sources
        self._max_age = max_age_seconds
        self._future_skew = max_future_skew_seconds
        self._clock = clock

    def verify_quote(
        self,
        feed: str,
        price: object,
        signatures: object,
        *,
        prev_price: object,
        observed_at: int,
        update_id: str,
    ) -> dict:
        try:
            feed = _required_text("feed", feed)
            update_id = _required_text("update_id", update_id, 128)
            value = _price(price)
            previous = _price(prev_price)
            if not isinstance(observed_at, int) or isinstance(observed_at, bool):
                raise ValueError("observed_at must be integer epoch seconds")
            now = float(self._clock())
            if not math.isfinite(now):
                raise ValueError("clock is non-finite")
            if observed_at > now + self._future_skew or now - observed_at > self._max_age:
                raise ValueError("quote is stale or from the future")
            if not isinstance(signatures, (list, tuple)) or len(signatures) > 64:
                raise ValueError("bounded signature list required")
            message = _body(feed, value, observed_at, update_id)
            valid: set[str] = set()
            for entry in signatures:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    continue
                issuer, signature = entry
                verify = self._verifiers.get(issuer) if isinstance(issuer, str) else None
                if verify is None or not isinstance(signature, str) or len(signature) > 4096:
                    continue
                try:
                    if bool(verify(message, signature)):
                        valid.add(issuer)
                except Exception:
                    continue
            if len(valid) < self._min_sources:
                raise ValueError("insufficient independent trusted sources")
            deviation = abs(value - previous) / previous
            if deviation > self._max_deviation:
                raise ValueError("price deviation exceeds fixed circuit breaker")
            quote_digest = hashlib.sha256(message).hexdigest()
            if not self._replay.consume(update_id, quote_digest, int(now)):
                raise ValueError("quote replay")
            return {
                "status": "ELIGIBLE_PROPOSAL",
                "verified": True,
                "authoritative": False,
                "sources": sorted(valid),
                "price": format(value, "f"),
                "update_id": update_id,
                "requires": ["action_authority"],
            }
        except (TypeError, ValueError, InvalidOperation, sqlite3.Error) as error:
            return {
                "status": "REJECTED",
                "verified": False,
                "authoritative": False,
                "reason": str(error),
            }


def sign_price(*_args, **_kwargs):
    raise TypeError("per-call oracle signing is disabled; use a sign-only OracleIssuer")


def admit_price_update(*_args, **_kwargs):
    raise TypeError("per-call oracle trust policy is disabled; use a fixed OracleVerifier")


__all__ = [
    "OracleIssuer", "OracleReplayStore", "OracleVerifier",
    "sign_price", "admit_price_update",
]
