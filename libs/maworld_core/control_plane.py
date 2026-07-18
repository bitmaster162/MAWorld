"""Fixed owner-approval boundary for exact high-impact actions."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass

from maworld_core.action_authority import (
    ActionExecutor,
    ActionSpec,
    ConfusedDeputy,
    DecisionIssuer,
    HumanApprovalIssuer,
    execute,
)


MAX_UPDATE_BYTES = 16 * 1024
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


@dataclass(frozen=True)
class OwnerBinding:
    owner_chat_id: int
    webhook_secret: str
    nonce_ttl_sec: int = 120
    max_future_skew_sec: int = 5

    def __post_init__(self):
        if isinstance(self.owner_chat_id, bool) or not isinstance(self.owner_chat_id, int):
            raise ValueError("owner_chat_id must be an integer")
        if not isinstance(self.webhook_secret, str) or len(self.webhook_secret) < 16:
            raise ValueError("fixed webhook secret must be at least 16 characters")
        if not isinstance(self.nonce_ttl_sec, int) or not 1 <= self.nonce_ttl_sec <= 300:
            raise ValueError("nonce_ttl_sec must be in 1..300")
        if not isinstance(self.max_future_skew_sec, int) or not 0 <= self.max_future_skew_sec <= 30:
            raise ValueError("max_future_skew_sec must be in 0..30")


class WebhookReplayStore:
    """Durable atomic nonce store; production should place it in a protected service."""

    def __init__(self, path: str):
        if not isinstance(path, str) or not path or path == ":memory:":
            raise ValueError("explicit durable replay database path required")
        self._connection = sqlite3.connect(
            path, timeout=30, isolation_level=None, check_same_thread=False
        )
        self._lock = threading.Lock()
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA busy_timeout=30000")
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS owner_webhook_nonce(
                nonce TEXT PRIMARY KEY,
                update_digest TEXT NOT NULL,
                consumed_at INTEGER NOT NULL
            )"""
        )

    def consume(self, nonce: str, update_digest: str, consumed_at: int) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "INSERT OR IGNORE INTO owner_webhook_nonce(nonce,update_digest,consumed_at) VALUES(?,?,?)",
                (nonce, update_digest, consumed_at),
            )
        return cursor.rowcount == 1

    def close(self) -> None:
        self._connection.close()


class OwnerApprovalBoundary:
    """Composition-root object; callers cannot replace trust, time, or replay policy."""

    def __init__(
        self,
        binding: OwnerBinding,
        replay_store: WebhookReplayStore,
        executor: ActionExecutor,
        decision_issuer: DecisionIssuer,
        approval_issuer: HumanApprovalIssuer,
        *,
        clock=time.time,
    ):
        if not isinstance(binding, OwnerBinding):
            raise TypeError("fixed OwnerBinding required")
        if not isinstance(replay_store, WebhookReplayStore):
            raise TypeError("durable WebhookReplayStore required")
        if not isinstance(executor, ActionExecutor):
            raise TypeError("fixed ActionExecutor required")
        if not isinstance(decision_issuer, DecisionIssuer):
            raise TypeError("fixed DecisionIssuer required")
        if not isinstance(approval_issuer, HumanApprovalIssuer):
            raise TypeError("fixed HumanApprovalIssuer required")
        if not callable(clock):
            raise TypeError("fixed clock required")
        self._binding = binding
        self._replay = replay_store
        self._executor = executor
        self._decision_issuer = decision_issuer
        self._approval_issuer = approval_issuer
        self._clock = clock

    def execute(self, spec: ActionSpec, update: object, header_secret: object) -> dict:
        if not isinstance(spec, ActionSpec):
            return {"executed": False, "reason": "INVALID_ACTION_SPEC"}
        parsed = self._parse_update(update, header_secret, spec)
        if isinstance(parsed, str):
            return {"executed": False, "reason": parsed}
        nonce, update_digest, now = parsed
        if not self._replay.consume(nonce, update_digest, int(now)):
            return {"executed": False, "reason": "REPLAY_OR_NO_NONCE"}
        try:
            decision = self._decision_issuer.issue(
                spec, "REQUIRE_CONFIRMATION", now=int(now)
            )
            confirmation = self._approval_issuer.confirm(decision, now=int(now))
            result = execute(spec, decision, self._executor, confirmation=confirmation)
            return {"executed": True, "result": result["result"]}
        except (ConfusedDeputy, TypeError, ValueError) as error:
            return {"executed": False, "reason": str(error)[:100]}

    def _parse_update(self, update: object, header_secret: object, spec: ActionSpec):
        if not isinstance(header_secret, str) or len(header_secret) > 4096:
            return "BAD_SECRET_TOKEN"
        if not hmac.compare_digest(header_secret, self._binding.webhook_secret):
            return "BAD_SECRET_TOKEN"
        if not isinstance(update, dict):
            return "MALFORMED_UPDATE"
        try:
            encoded = json.dumps(
                update, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, OverflowError):
            return "MALFORMED_UPDATE"
        if len(encoded) > MAX_UPDATE_BYTES:
            return "UPDATE_TOO_LARGE"
        message = update.get("message")
        if not isinstance(message, dict):
            return "MALFORMED_UPDATE"
        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("id") != self._binding.owner_chat_id:
            return "NOT_OWNER"
        date = message.get("date")
        if isinstance(date, bool) or not isinstance(date, (int, float)) or not math.isfinite(float(date)):
            return "MALFORMED_DATE"
        now = float(self._clock())
        if not math.isfinite(now):
            return "CLOCK_FAILURE"
        age = now - float(date)
        if age < -self._binding.max_future_skew_sec:
            return "FUTURE"
        if age > self._binding.nonce_ttl_sec:
            return "STALE"
        nonce = message.get("nonce")
        if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
            return "REPLAY_OR_NO_NONCE"
        expected = "APPROVE:" + spec.hash()
        if message.get("text") != expected:
            return "APPROVAL_NOT_FOR_THIS_ACTION"
        digest = hashlib.sha256(encoded + b"\x00" + spec.hash().encode("ascii")).hexdigest()
        return nonce, digest, now


def verify_owner(*_args, **_kwargs):
    raise TypeError("legacy per-call owner verification is disabled; use OwnerApprovalBoundary")


def owner_confirm_for(*_args, **_kwargs):
    raise TypeError("legacy per-call approval composition is disabled; use OwnerApprovalBoundary")


def high_impact_execute(*_args, **_kwargs):
    raise TypeError("legacy per-call execution composition is disabled; use OwnerApprovalBoundary")


ReplayGuard = WebhookReplayStore

__all__ = [
    "OwnerBinding", "WebhookReplayStore", "OwnerApprovalBoundary", "ReplayGuard",
    "verify_owner", "owner_confirm_for", "high_impact_execute",
]
