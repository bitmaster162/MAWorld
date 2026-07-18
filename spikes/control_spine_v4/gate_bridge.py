from __future__ import annotations
import os, sys, sqlite3, threading
from dataclasses import dataclass
_COS = os.environ.get("CONTINUITYOS_PATH", r"C:\PROJECTS\continuityos")
if _COS not in sys.path: sys.path.insert(0, _COS)
try:
    from continuityos.gate.spec import ActionSpec
    from continuityos.gate.engine import preflight
    from continuityos.gate.ledger import Ledger
    REAL_GATE = True
except Exception as e:
    REAL_GATE = False; _IMPORT_ERR = e
_EXECUTABLE = ("ALLOW", "WARN", "REQUIRE_CONFIRMATION")
@dataclass
class GateResult:
    decision: str; may_execute: bool; reasons: list; ledger_hash: str | None
class ControlSpineGate:
    def __init__(self, ledger_path):
        if not REAL_GATE:
            raise RuntimeError("ContinuityOS not imported from %r: %r" % (_COS, _IMPORT_ERR))
        self.ledger = Ledger(ledger_path)
        # thread-portable connection: DBOS runs steps/recovery on different threads
        self.ledger.con = sqlite3.connect(ledger_path, timeout=30.0, check_same_thread=False)
        self.ledger.con.execute("PRAGMA busy_timeout=30000")
        self.ledger.con.execute("PRAGMA journal_mode=WAL")
        self.ledger.con.row_factory = sqlite3.Row
        self._lock = threading.Lock()
    def check(self, tool, command, agent, paths=None):
        spec = ActionSpec(tool=tool, command=command, args=command.split(), paths=paths or [], agent=agent)
        with self._lock:
            res = preflight(spec, ledger=self.ledger)
        d = res["decision"]
        return GateResult(d, d in _EXECUTABLE, res.get("reasons", []), res.get("ledger_hash"))
    def audit(self, kind, payload):
        with self._lock:
            return self.ledger.append(kind, payload)
    def verify_chain(self):
        with self._lock:
            return self.ledger.verify()
