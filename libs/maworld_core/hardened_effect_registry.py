"""Durable at-most-once registry with tenant/action/payload-bound idempotency.

The idempotency key is not authority by itself.  Every claim is also bound to a
canonical digest of ``tenant + action + system + reversibility + payload``.
Reusing a key for different work fails closed before replay or reconciliation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time


class IdempotencyBindingConflict(RuntimeError):
    pass


def _required(name, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def binding_digest(*, tenant, action, payload, system, rev_class):
    _required("tenant", tenant); _required("action", action)
    _required("system", system); _required("rev_class", rev_class)
    try:
        body = json.dumps(
            {"tenant": tenant, "action": action, "system": system,
             "rev_class": rev_class, "payload": payload},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("effect payload must be canonical JSON") from exc
    return hashlib.sha256(body).hexdigest()


class HardenedEffectRegistry:
    def __init__(self, path):
        self.con = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA busy_timeout=30000")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS effect(
            idem TEXT PRIMARY KEY, binding_digest TEXT, system TEXT, rev_class TEXT,
            status TEXT NOT NULL, result_json TEXT,
            fired_count INTEGER NOT NULL DEFAULT 0, ts REAL)""")
        # Fail closed for rows created by v2: they have NULL binding and cannot be replayed as new work.
        cols = {row[1] for row in self.con.execute("PRAGMA table_info(effect)")}
        if "binding_digest" not in cols:
            self.con.execute("ALTER TABLE effect ADD COLUMN binding_digest TEXT")

    def _claim(self, idem, digest, system, rev_class):
        cur = self.con.execute(
            "INSERT OR IGNORE INTO effect"
            "(idem,binding_digest,system,rev_class,status,fired_count,ts) "
            "VALUES(?,?,?,?, 'PENDING',0,?)",
            (idem, digest, system, rev_class, time.time()),
        )
        return cur.rowcount == 1

    def _row(self, idem):
        return self.con.execute(
            "SELECT binding_digest,status,result_json FROM effect WHERE idem=?", (idem,)
        ).fetchone()

    def _confirmed_replay_or_fail(self, idem, digest):
        """Resolve a lost state-transition race without reopening terminal work."""
        row = self._row(idem)
        if row is None or not row[0] or row[0] != digest:
            raise IdempotencyBindingConflict(
                "effect binding changed during concurrent state transition"
            )
        if row[1] == "CONFIRMED":
            return {
                "status": "REPLAYED_NO_REFIRE",
                "result": json.loads(row[2]) if row[2] else None,
            }
        raise RuntimeError(f"effect state changed concurrently to {row[1]!r}")

    def status(self, idem):
        r = self.con.execute("SELECT status FROM effect WHERE idem=?", (idem,)).fetchone()
        return r[0] if r else None

    def fired_count(self, idem):
        r = self.con.execute("SELECT fired_count FROM effect WHERE idem=?", (idem,)).fetchone()
        return r[0] if r else 0

    def execute_once(
        self,
        idem,
        do_effect,
        system="venue",
        rev_class="IRREVERSIBLE",
        reconcile=None,
        *,
        tenant,
        action,
        payload,
    ):
        _required("idempotency key", idem)
        digest = binding_digest(
            tenant=tenant, action=action, payload=payload,
            system=system, rev_class=rev_class,
        )
        won = self._claim(idem, digest, system, rev_class)
        if not won:
            row = self._row(idem)
            if row is None or not row[0] or row[0] != digest:
                raise IdempotencyBindingConflict(
                    "idempotency key already belongs to different or unbound work"
                )
            st, result_json = row[1], row[2]
            if st == "CONFIRMED":
                return {"status": "REPLAYED_NO_REFIRE",
                        "result": json.loads(result_json) if result_json else None}
            if st in {"PENDING", "SENT", "HOLD"}:
                if reconcile is not None:
                    probe = reconcile(idem)
                    if not isinstance(probe, dict):
                        raise TypeError("reconcile must return a dict")
                    if probe.get("exists"):
                        encoded = json.dumps(probe.get("result"), sort_keys=True, allow_nan=False)
                        cur = self.con.execute(
                            "UPDATE effect SET status='CONFIRMED',result_json=?,ts=? "
                            "WHERE idem=? AND binding_digest=? "
                            "AND status IN ('PENDING','SENT','HOLD')",
                            (encoded, time.time(), idem, digest),
                        )
                        if cur.rowcount != 1:
                            return self._confirmed_replay_or_fail(idem, digest)
                        return {"status": "RECONCILED_CONFIRMED", "result": probe.get("result")}
                    cur = self.con.execute(
                        "UPDATE effect SET status='HOLD',ts=? "
                        "WHERE idem=? AND binding_digest=? "
                        "AND status IN ('PENDING','SENT','HOLD')",
                        (time.time(), idem, digest),
                    )
                    if cur.rowcount != 1:
                        return self._confirmed_replay_or_fail(idem, digest)
                    return {"status": "RECONCILE_ABSENT_HOLD", "result": None}
                cur = self.con.execute(
                    "UPDATE effect SET status='HOLD',ts=? "
                    "WHERE idem=? AND binding_digest=? "
                    "AND status IN ('PENDING','SENT','HOLD')",
                    (time.time(), idem, digest),
                )
                if cur.rowcount != 1:
                    return self._confirmed_replay_or_fail(idem, digest)
                return {"status": "IN_FLIGHT_HOLD", "result": None}
            raise RuntimeError(f"unknown effect status {st!r}")

        cur = self.con.execute(
            "UPDATE effect SET status='SENT',ts=? "
            "WHERE idem=? AND binding_digest=? AND status IN ('PENDING','HOLD')",
            (time.time(), idem, digest),
        )
        if cur.rowcount != 1:
            return self._confirmed_replay_or_fail(idem, digest)
        result = do_effect()
        encoded = json.dumps(result, sort_keys=True, allow_nan=False)
        cur = self.con.execute(
            "UPDATE effect SET status='CONFIRMED',result_json=?,"
            "fired_count=fired_count+1,ts=? WHERE idem=? AND binding_digest=?",
            (encoded, time.time(), idem, digest),
        )
        if cur.rowcount != 1:
            raise IdempotencyBindingConflict("effect binding changed during execution")
        return {"status": "FIRED", "result": result}

    def simulate_crash_after_send(
        self, idem, system="venue", rev_class="IRREVERSIBLE", *, tenant, action, payload
    ):
        digest = binding_digest(
            tenant=tenant, action=action, payload=payload,
            system=system, rev_class=rev_class,
        )
        won = self._claim(idem, digest, system, rev_class)
        if not won:
            row = self._row(idem)
            if row is None or row[0] != digest:
                raise IdempotencyBindingConflict("crash simulation binding conflict")
            return
        cur = self.con.execute(
            "UPDATE effect SET status='SENT',fired_count=fired_count+1,ts=? "
            "WHERE idem=? AND binding_digest=? AND status IN ('PENDING','HOLD')",
            (time.time(), idem, digest),
        )
        if cur.rowcount != 1:
            self._confirmed_replay_or_fail(idem, digest)

    def close(self):
        self.con.close()
