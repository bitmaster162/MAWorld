from __future__ import annotations
import sqlite3, json, time
class EffectRegistry:
    def __init__(self, path):
        self.con = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS external_effect(
            idempotency_key TEXT PRIMARY KEY, external_system TEXT, reversibility_class TEXT,
            execution_status TEXT, result_json TEXT, fired_count INTEGER NOT NULL DEFAULT 0, executed_at REAL)""")
        self.con.commit()
    def fire_once(self, key, system, rev_class, do_effect):
        cur = self.con.execute("SELECT execution_status,result_json FROM external_effect WHERE idempotency_key=?",(key,)).fetchone()
        if cur and cur[0]=="CONFIRMED":
            return {"status":"REPLAYED_NO_REFIRE","result":json.loads(cur[1])}
        self.con.execute("INSERT OR IGNORE INTO external_effect(idempotency_key,external_system,reversibility_class,execution_status,fired_count) VALUES(?,?,?,?,0)",(key,system,rev_class,"PENDING"))
        self.con.commit()
        result = do_effect()
        self.con.execute("UPDATE external_effect SET execution_status='CONFIRMED',result_json=?,fired_count=fired_count+1,executed_at=? WHERE idempotency_key=?",(json.dumps(result),time.time(),key))
        self.con.commit()
        return {"status":"FIRED","result":result}
    def fired_count(self, key):
        r = self.con.execute("SELECT fired_count FROM external_effect WHERE idempotency_key=?",(key,)).fetchone()
        return r[0] if r else 0
    def close(self): self.con.close()
