"""Mandatory egress broker (control spine v1, HARDEN-FIRST from the broker research).

Closes the #1 gap all reports flag: today ContinuityOS is opt-in and bypassable. This makes
the gate PHYSICALLY unavoidable in miniature: the agent runs in a network-denied sandbox and
its ONLY channel to the outside is a unix socket to this broker, which calls the REAL
ContinuityOS preflight() before performing any egress. Prod target: gVisor + egress-deny
network namespace + veth-to-proxy (same fail-closed property; unix socket is the local stand-in).

Protocol (newline-delimited JSON on the unix socket):
  request : {"host": str, "method": str, "payload": str, "agent": str}
  response: {"decision": "ALLOW|DENY|...", "reasons": [...], "egress_performed": bool, "result": ...}
"""
from __future__ import annotations
import json, os, socket, sys, threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_bridge import ControlSpineGate

# allowlist of hosts the broker will ever reach (defense in depth on top of the gate)
EGRESS_ALLOWLIST = {"api.testnet.local", "hooks.stripe.test"}


class EgressBroker:
    def __init__(self, socket_path, ledger_path):
        self.socket_path = socket_path
        self.gate = ControlSpineGate(ledger_path)
        self._srv = None

    def _handle(self, conn):
        try:
            data = conn.recv(65536).decode().strip()
            req = json.loads(data)
            host = req.get("host", "")
            agent = req.get("agent", "unknown")
            # build the ActionSpec-equivalent and ask the REAL gate
            command = "egress %s %s" % (req.get("method", "GET"), host)
            gr = self.gate.check(tool="http", command=command, agent=agent)
            self.gate.audit("egress.request", {"host": host, "agent": agent, "decision": gr.decision})

            egress_performed = False
            result = None
            if gr.may_execute and host in EGRESS_ALLOWLIST:
                # broker performs the egress ON BEHALF of the agent (stubbed for the spike)
                egress_performed = True
                result = {"status": 200, "host": host, "echo": req.get("payload")}
                self.gate.audit("egress.performed", {"host": host, "agent": agent})
                decision = gr.decision
            elif gr.may_execute and host not in EGRESS_ALLOWLIST:
                decision = "DENY"
                gr.reasons = list(gr.reasons) + ["host not in egress allowlist: %s" % host]
                self.gate.audit("egress.denied_allowlist", {"host": host, "agent": agent})
            else:
                decision = gr.decision

            resp = {"decision": decision, "reasons": gr.reasons,
                    "egress_performed": egress_performed, "result": result}
            conn.sendall((json.dumps(resp) + "\n").encode())
        except Exception as e:
            conn.sendall((json.dumps({"decision": "DENY", "reasons": ["broker error: %s" % e],
                                      "egress_performed": False}) + "\n").encode())
        finally:
            conn.close()

    def serve_forever(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.socket_path)
        os.chmod(self.socket_path, 0o660)
        self._srv.listen(8)
        while True:
            conn, _ = self._srv.accept()
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    sp, lp = sys.argv[1], sys.argv[2]
    EgressBroker(sp, lp).serve_forever()
