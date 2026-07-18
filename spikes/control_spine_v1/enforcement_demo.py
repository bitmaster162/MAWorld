"""Orchestrates the mandatory-enforcement proof:
  1. start the broker (holds the only egress capability + real ContinuityOS gate),
  2. run the agent inside bwrap: no network, ONLY the broker socket bind-mounted,
  3. assert: direct net blocked, broker egress to allowlisted host works, denied host blocked,
  4. broker-down case: agent gets NO_BROKER (fail-closed = no egress)."""
import json, os, shutil, socket, subprocess, sys, tempfile, time, threading

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("CS1_STATE", tempfile.mkdtemp(prefix="cs1-"))
SOCK = os.path.join(STATE, "broker.sock")
LEDGER = os.path.join(STATE, "audit_ledger.db")

def start_broker():
    import egress_broker
    b = egress_broker.EgressBroker(SOCK, LEDGER)
    threading.Thread(target=b.serve_forever, daemon=True).start()
    for _ in range(50):
        if os.path.exists(SOCK): return True
        time.sleep(0.05)
    return False

def run_agent_sandboxed():
    have_bwrap = shutil.which("bwrap") is not None
    if not have_bwrap:
        return {"_mechanism": "UNSAFE_fallback"}, "UNSAFE_fallback"
    cmd = ["bwrap","--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib"]
    if os.path.exists("/lib64"): cmd += ["--ro-bind","/lib64","/lib64"]
    cmd += ["--ro-bind", os.path.join(HERE,"sandboxed_agent.py"), "/work/sandboxed_agent.py",
            "--bind", SOCK, "/work/broker.sock",     # ONLY outward channel bind-mounted in
            "--proc","/proc","--dev","/dev","--unshare-all","--die-with-parent","--chdir","/work",
            "python3","/work/sandboxed_agent.py"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try:
        return json.loads(p.stdout.strip()), "bwrap"
    except Exception:
        return {"_raw": p.stdout, "_err": p.stderr}, "bwrap"

def main():
    sys.path.insert(0, HERE)
    print("="*64); print("ENFORCEMENT DEMO: mandatory egress broker (HARDEN-FIRST)"); print("="*64)
    assert start_broker(), "broker did not start"
    res, mech = run_agent_sandboxed()
    print("sandbox mechanism        :", mech)
    print("direct network from agent:", res.get("direct"))
    print("broker allowlisted host  :", {k: res.get("broker_allowed_host",{}).get(k) for k in ("decision","egress_performed")})
    print("broker denied host       :", {k: res.get("broker_denied_host",{}).get(k) for k in ("decision","egress_performed")})

    # broker-down / fail-closed case: replace live socket with a DEAD one (bound, not listening)
    # so connect() is refused -> agent gets no egress. This is a faithful "broker crashed" sim.
    os.unlink(SOCK)
    dead = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); dead.bind(SOCK); dead.close()
    downres, _ = run_agent_sandboxed()
    fail_closed = downres.get("broker_allowed_host",{}).get("decision") == "NO_BROKER"
    print("broker DOWN -> egress     :", downres.get("broker_allowed_host",{}).get("decision"), "(fail-closed)")

    checks = {
        "sandbox isolates network (no direct egress)": res.get("direct",{}).get("direct_net")=="BLOCKED_GOOD",
        "allowlisted egress goes through gate + performed": res.get("broker_allowed_host",{}).get("egress_performed") is True,
        "denied host blocked by gate/allowlist": res.get("broker_denied_host",{}).get("decision")=="DENY"
            and res.get("broker_denied_host",{}).get("egress_performed") is False,
        "broker down => no egress (fail-closed)": fail_closed,
    }
    print("\n-- checks --")
    for k,v in checks.items(): print(("PASS" if v else "FAIL"), "|", k)
    # audit chain
    sys.path.insert(0, os.environ.get("CONTINUITYOS_PATH", r"C:\PROJECTS\continuityos"))
    from continuityos.gate.ledger import Ledger
    L = Ledger(LEDGER); chain = L.verify(); L.close()
    print("audit chain              :", chain)
    ok = all(checks.values()) and chain.get("ok", False)
    shutil.rmtree(STATE, ignore_errors=True)
    print("\n" + ("ENFORCEMENT DEMO PASSED" if ok else "ENFORCEMENT DEMO FAILED"))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
