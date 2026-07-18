"""ExternalEffectRegistry (DR2 0x0C) — makes replay safe across runtimes.

Every external side effect gets an effect_id, idempotency state, reversibility class and
reconciliation status. Replay NEVER re-fires a CONFIRMED effect. After a crash between SENT and
CONFIRMED, reconciliation probes the external world: confirmed-externally -> mark CONFIRMED (no
re-fire); absent -> safe retry; ambiguous -> HOLD (never auto-retry into a side effect).
COMPENSATABLE effects can be compensated; IRREVERSIBLE effects cannot -> HOLD for human.
"""
from __future__ import annotations
import sqlite3, json, time

REVERSIBILITY = ("REVERSIBLE", "COMPENSATABLE", "IRREVERSIBLE", "UNKNOWN")


class ExternalEffectRegistry:
    def __init__(self, path):
        self.con = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS external_effect(
            effect_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, external_system TEXT,
            reversibility_class TEXT, execution_status TEXT, result_json TEXT,
            compensation_action TEXT, compensation_status TEXT,
            reconciliation_status TEXT, fired_count INTEGER NOT NULL DEFAULT 0,
            executed_at REAL, reconciled_at REAL)""")
        self.con.commit()

    def register_intent(self, effect_id, idempotency_key, external_system, reversibility_class,
                        compensation_action=None):
        assert reversibility_class in REVERSIBILITY
        self.con.execute(
            "INSERT OR IGNORE INTO external_effect(effect_id,idempotency_key,external_system,"
            "reversibility_class,execution_status,compensation_action,compensation_status,"
            "reconciliation_status,fired_count) VALUES(?,?,?,?,?,?,?,?,0)",
            (effect_id, idempotency_key, external_system, reversibility_class, "PENDING",
             compensation_action, "NOT_REQUIRED", "NONE"))
        self.con.commit()

    def _row(self, effect_id):
        return self.con.execute("SELECT execution_status,result_json,fired_count,reversibility_class,"
                                "reconciliation_status FROM external_effect WHERE effect_id=?",
                                (effect_id,)).fetchone()

    def execute_once(self, effect_id, do_effect):
        """Fire the effect at most once. Returns {status, result}."""
        r = self._row(effect_id)
        if r and r[0] == "CONFIRMED":
            # result may be absent if the effect was adopted via reconciliation (crash before record)
            res = json.loads(r[1]) if r[1] else {"reconciled": True}
            return {"status": "REPLAYED_NO_REFIRE", "result": res}
        self.con.execute("UPDATE external_effect SET execution_status='SENT' WHERE effect_id=?", (effect_id,))
        self.con.commit()
        result = do_effect()
        self.con.execute("UPDATE external_effect SET execution_status='CONFIRMED',result_json=?,"
                         "fired_count=fired_count+1,executed_at=? WHERE effect_id=?",
                         (json.dumps(result), time.time(), effect_id))
        self.con.commit()
        return {"status": "FIRED", "result": result}

    def reconcile(self, effect_id, external_probe):
        """external_probe() -> 'CONFIRMED'|'ABSENT'|'AMBIGUOUS'. Called after a crash to decide
        whether the effect already happened externally. Returns a decision string."""
        r = self._row(effect_id)
        if not r:
            return "UNKNOWN_EFFECT"
        if r[0] == "CONFIRMED":
            return "ALREADY_CONFIRMED"
        probe = external_probe()
        ts = time.time()
        if probe == "CONFIRMED":
            # external world already has it -> adopt as CONFIRMED, do NOT re-fire
            self.con.execute("UPDATE external_effect SET execution_status='CONFIRMED',"
                             "reconciliation_status='RECONCILED_CONFIRMED',reconciled_at=? WHERE effect_id=?",
                             (ts, effect_id)); self.con.commit()
            return "RECONCILED_CONFIRMED_NO_REFIRE"
        if probe == "ABSENT":
            self.con.execute("UPDATE external_effect SET reconciliation_status='RECONCILED_ABSENT',"
                             "reconciled_at=? WHERE effect_id=?", (ts, effect_id)); self.con.commit()
            return "SAFE_TO_RETRY"
        # ambiguous -> HOLD, never auto-retry into a side effect
        self.con.execute("UPDATE external_effect SET reconciliation_status='HOLD_AMBIGUOUS',"
                         "reconciled_at=? WHERE effect_id=?", (ts, effect_id)); self.con.commit()
        return "HOLD_AMBIGUOUS"

    def compensate(self, effect_id, do_compensation):
        """Roll back a COMPENSATABLE effect. IRREVERSIBLE -> HOLD for human."""
        r = self._row(effect_id)
        if not r:
            return "UNKNOWN_EFFECT"
        rev = r[3]
        if rev == "IRREVERSIBLE":
            self.con.execute("UPDATE external_effect SET compensation_status='HOLD' WHERE effect_id=?", (effect_id,))
            self.con.commit()
            return "HOLD_IRREVERSIBLE"
        if rev == "REVERSIBLE" or rev == "COMPENSATABLE":
            do_compensation()
            self.con.execute("UPDATE external_effect SET compensation_status='EXECUTED' WHERE effect_id=?", (effect_id,))
            self.con.commit()
            return "COMPENSATED"
        return "HOLD_UNKNOWN_REVERSIBILITY"

    def status(self, effect_id):
        r = self._row(effect_id)
        return {"execution_status": r[0], "fired_count": r[2], "reversibility": r[3],
                "reconciliation_status": r[4]} if r else None

    def close(self): self.con.close()
