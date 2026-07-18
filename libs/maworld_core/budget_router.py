"""Durable, atomic spend caps for external calls.

The policy digest is pinned in the database so reopening a ledger with inflated
caps cannot erase its authority.  Every reservation uses ``BEGIN IMMEDIATE``;
NaN, infinity, negative values and unknown lanes fail closed.  P0 never bypasses
the absolute cap.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3


class BudgetError(RuntimeError):
    pass


class BudgetRouter:
    def __init__(self, db_path, lane_caps: dict, absolute_cap: float):
        if not isinstance(db_path, str) or not db_path or not lane_caps:
            raise BudgetError("durable db_path and non-empty lane caps are required")
        try:
            self.absolute_cap = float(absolute_cap)
            self.lane_caps = {k: float(v) for k, v in lane_caps.items()}
        except (TypeError, ValueError) as exc:
            raise BudgetError("budget caps must be finite and non-negative") from exc
        if (
            not math.isfinite(self.absolute_cap)
            or self.absolute_cap < 0
            or any(not isinstance(k, str) or not k for k in self.lane_caps)
            or any(not math.isfinite(v) or v < 0 for v in self.lane_caps.values())
        ):
            raise BudgetError("budget caps must be finite and non-negative")
        self.con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=30000")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS spend("
            "lane TEXT PRIMARY KEY,total REAL NOT NULL DEFAULT 0 CHECK(total>=0))"
        )
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS budget_meta("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1),policy_digest TEXT NOT NULL)"
        )
        policy_digest = hashlib.sha256(
            json.dumps(
                {"lane_caps": self.lane_caps, "absolute_cap": self.absolute_cap},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        existing = self.con.execute(
            "SELECT policy_digest FROM budget_meta WHERE singleton=1"
        ).fetchone()
        if existing is None:
            self.con.execute(
                "INSERT INTO budget_meta(singleton,policy_digest) VALUES(1,?)",
                (policy_digest,),
            )
        elif existing[0] != policy_digest:
            self.con.close()
            raise BudgetError("budget policy mismatch for existing durable ledger")

    def _spent(self, lane):
        row = self.con.execute(
            "SELECT total FROM spend WHERE lane=?", (lane,)
        ).fetchone()
        return float(row[0]) if row else 0.0

    def total_spent(self):
        row = self.con.execute("SELECT COALESCE(SUM(total),0) FROM spend").fetchone()
        return round(float(row[0]), 6)

    def charge(self, lane, cost):
        if isinstance(cost, bool):
            raise BudgetError("cost must be a finite non-negative number")
        try:
            cost = float(cost)
        except (TypeError, ValueError) as exc:
            raise BudgetError("cost must be a finite non-negative number") from exc
        if not math.isfinite(cost) or cost < 0:
            raise BudgetError("cost must be finite and non-negative")
        if lane not in self.lane_caps:
            raise BudgetError(f"unknown lane {lane}")
        self.con.execute("BEGIN IMMEDIATE")
        try:
            lane_after = self._spent(lane) + cost
            row = self.con.execute("SELECT COALESCE(SUM(total),0) FROM spend").fetchone()
            total_after = float(row[0]) + cost
            if lane_after > self.lane_caps[lane]:
                raise BudgetError(
                    f"lane {lane} cap exceeded ({lane_after} > {self.lane_caps[lane]})"
                )
            if total_after > self.absolute_cap:
                raise BudgetError(
                    f"absolute hard cap exceeded ({total_after} > {self.absolute_cap})"
                )
            self.con.execute(
                "INSERT INTO spend(lane,total) VALUES(?,?) "
                "ON CONFLICT(lane) DO UPDATE SET total=total+?",
                (lane, cost, cost),
            )
            self.con.execute("COMMIT")
        except Exception:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        return {
            "lane": lane,
            "charged": cost,
            "lane_total": round(self._spent(lane), 6),
            "grand_total": self.total_spent(),
        }

    def close(self):
        self.con.close()
