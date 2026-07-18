"""Runs INSIDE the network-denied sandbox. Proves: (1) no direct egress possible,
(2) the only channel out is the broker unix socket. Prints JSON results for the demo."""
import json, socket, sys

BROKER_SOCK = "/work/broker.sock"  # bind-mounted into the sandbox; the ONLY outward path

def try_direct_network():
    try:
        s = socket.create_connection(("1.1.1.1", 53), timeout=2)
        s.close()
        return {"direct_net": "REACHABLE_BAD"}
    except Exception as e:
        return {"direct_net": "BLOCKED_GOOD", "err": type(e).__name__}

def via_broker(host, method="GET", payload="hi"):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(BROKER_SOCK)
        s.sendall((json.dumps({"host": host, "method": method, "payload": payload,
                               "agent": "sandboxed_agent"}) + "\n").encode())
        resp = s.recv(65536).decode().strip()
        s.close()
        return json.loads(resp)
    except Exception as e:
        return {"decision": "NO_BROKER", "reasons": [type(e).__name__ + ": " + str(e)],
                "egress_performed": False}

if __name__ == "__main__":
    out = {"direct": try_direct_network()}
    out["broker_allowed_host"] = via_broker("api.testnet.local")
    out["broker_denied_host"] = via_broker("evil.example.com")
    print(json.dumps(out))
