import os, sys, subprocess, shutil, uuid
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("SPIKE_STATE", os.path.join(HERE, "_state"))
def _child(phase, idem):
    env = dict(os.environ, SPIKE_STATE=STATE)
    if phase == "crash": env["CRASH_AFTER_EFFECT"] = "1"
    return subprocess.call([sys.executable, os.path.join(HERE,"_kill_child.py"), phase, idem], env=env)
def main():
    shutil.rmtree(STATE, ignore_errors=True); os.makedirs(STATE, exist_ok=True)
    idem = "order-" + uuid.uuid4().hex[:8]
    print("="*60); print("KILLTEST: crash-recovery, no duplicate side effect"); print("="*60)
    print("\n[PHASE 1] run with crash injected right after external effect ...")
    rc1 = _child("crash", idem)
    print("  child exit code =", rc1, "(expect 137 = killed after effect)")
    from effect_registry import EffectRegistry
    reg = EffectRegistry(os.path.join(STATE,"effect_registry.db")); fired_before = reg.fired_count(idem); reg.close()
    print("  effect fired_count after crash =", fired_before, "(expect 1)")
    print("\n[PHASE 2] restart process -> DBOS recovery ...")
    rc2 = _child("recover", idem)
    print("  child exit code =", rc2, "(expect 0)")
    reg = EffectRegistry(os.path.join(STATE,"effect_registry.db")); fired_after = reg.fired_count(idem); reg.close()
    olog = os.path.join(STATE,"orders.log"); n_orders = sum(1 for _ in open(olog)) if os.path.exists(olog) else 0
    sys.path.insert(0, os.environ.get("CONTINUITYOS_PATH", r"C:\PROJECTS\continuityos"))
    from continuityos.gate.ledger import Ledger
    led = Ledger(os.path.join(STATE,"audit_ledger.db")); chain = led.verify()
    completed = any(e.get("kind")=="workflow.complete" for e in led.export(200)); led.close()
    print("\n--- RESULT ---")
    print("  external_effect fired_count :", fired_after, "  (must be 1)")
    print("  orders.log lines            :", n_orders, "  (must be 1)")
    print("  workflow.complete in audit  :", completed, "  (must be True)")
    print("  ledger.verify()             :", chain)
    ok = (fired_before==1 and fired_after==1 and n_orders==1 and completed and chain.get("ok",False))
    print("\n" + ("SPIKE PASSED -- crash did not duplicate the effect, workflow recovered, audit intact." if ok else "SPIKE FAILED -- see numbers above."))
    sys.exit(0 if ok else 1)
if __name__ == "__main__": main()
