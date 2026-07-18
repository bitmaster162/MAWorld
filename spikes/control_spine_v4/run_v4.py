"""Boundary-proven integration spike (DR2 0x12 + v1.4 Spike A).
Wires the WHOLE boundary end-to-end using proven modules:
  A ingest artifact -> B CanonicalDecision -> C read-only CanonSnapshot -> D restricted CTHA
  proposer (bwrap) -> E ProposedActionSpec -> F Proposal Bridge -> canonical ActionSpec ->
  H ContinuityOS gate (real) -> I gVisor/bwrap executor file write -> J byte verification ->
  K ledger/trace correlate -> N brain/gate bypass matrix (all fail-closed).
Crash/recovery no-duplicate (L,M) is proven separately in control_spine_v0 (cited, DBOS).
"""
from __future__ import annotations
import json, os, shutil, subprocess, tempfile, hashlib, time, uuid, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gate_bridge import ControlSpineGate
from effect_registry import EffectRegistry
from proposal_bridge import bridge

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("CS4_STATE", tempfile.mkdtemp(prefix="cs4-"))
os.makedirs(STATE, exist_ok=True)
LEDGER = os.path.join(STATE, "audit_ledger.db")
EFFECT = os.path.join(STATE, "effect_registry.db")
gate = ControlSpineGate(LEDGER)

def run_proposer_sandboxed(canon_dir, rt_dir, out_dir, trace_id):
    """D: run the CTHA proposer in a restricted sandbox (canon RO, rt writable, no net/shell/creds)."""
    if not shutil.which("bwrap"):
        return None, "UNSAFE_fallback"
    cmd = ["bwrap","--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib"]
    if os.path.exists("/lib64"): cmd += ["--ro-bind","/lib64","/lib64"]
    cmd += [
        "--ro-bind", os.path.join(HERE,"cta_proposer.py"), "/work/cta_proposer.py",
        "--ro-bind", canon_dir, "/work/canon",          # canon snapshot READ-ONLY
        "--bind", rt_dir, "/work/rt",                    # mind/runtime writable
        "--bind", out_dir, "/work/out",                  # target root writable
        "--proc","/proc","--dev","/dev","--unshare-all","--die-with-parent","--chdir","/work",
        "--setenv","TRACE_ID",trace_id,
        "python3","/work/cta_proposer.py"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    try: return json.loads(p.stdout.strip()), "bwrap"
    except Exception: return {"_raw":p.stdout,"_err":p.stderr}, "bwrap"

def _sandboxed_write(host_path, content):
    """I: perform the allowed file op inside a Tier2 sandbox (bwrap). out dir mounted rw at /work/out."""
    out_dir = os.path.dirname(host_path)
    name = os.path.basename(host_path)
    if not shutil.which("bwrap"):
        with open(host_path,"wb") as f: f.write(content); return
    payload = repr(content)
    code = "open('/work/out/%s','wb').write(%s)" % (name, payload)
    cmd = ["bwrap","--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib"]
    if os.path.exists("/lib64"): cmd += ["--ro-bind","/lib64","/lib64"]
    cmd += ["--bind", out_dir, "/work/out","--proc","/proc","--dev","/dev",
            "--unshare-all","--die-with-parent","--chdir","/work","python3","-c",code]
    subprocess.run(cmd, check=True, timeout=15)

def main():
    print("="*66); print("BOUNDARY-PROVEN SPIKE v4 (DR2 0x12 / v1.4 Spike A)"); print("="*66)
    trace_id = "trace-" + uuid.uuid4().hex[:8]

    # A: ingest one artifact (content-addressed)
    art = b"MAWorld canonical artifact\n"
    art_sha = hashlib.sha256(art).hexdigest()
    gate.audit("intake.raw_blob", {"sha256": art_sha, "trace_id": trace_id})

    # B: Foundry CanonicalDecision (authoritative record) + C: read-only CanonSnapshot
    decision = {"decision_id": str(uuid.uuid4()), "decision_type": "INVARIANT",
                "statement": "temp-dir file writes are allowed for the spike", "approved_by": "owner"}
    dhash = gate.audit("foundry.canonical_decision", decision)
    canon_dir = os.path.join(STATE, "canon"); os.makedirs(canon_dir, exist_ok=True)
    with open(os.path.join(canon_dir, "snapshot.json"), "w") as f:
        json.dump({"decisions": [decision], "hash": dhash}, f)
    os.chmod(os.path.join(canon_dir, "snapshot.json"), 0o444)

    # D-E: restricted CTHA proposer -> ProposedActionSpec + bypass attempts
    rt_dir = os.path.join(STATE, "mind_runtime"); os.makedirs(rt_dir, exist_ok=True)
    out_dir = os.path.join(STATE, "out"); os.makedirs(out_dir, exist_ok=True)
    prop_report, mech = run_proposer_sandboxed(canon_dir, rt_dir, out_dir, trace_id)
    proposal = json.load(open(os.path.join(rt_dir, "proposals/actions/p1.json")))
    gate.audit("proposer.emitted", {"proposal_id": proposal["proposal_id"], "sandbox": mech})

    # F: Proposal Bridge -> canonical ActionSpec (authority markers stripped)
    seen = set()
    vr = bridge(proposal, seen)
    gate.audit("bridge.result", {"ok": vr.ok, "reason": vr.reason, "stripped": vr.stripped})
    assert vr.ok, "legit proposal must bridge"
    assert set(vr.stripped) >= {"approved","decision","execute"}, "authority markers must be stripped"
    aspec = vr.action_spec

    # H: ContinuityOS gate on the canonical ActionSpec
    gr = gate.check(tool="file.write", command="write_file " + aspec["target"]["path"], agent="proposal_bridge")
    gate.audit("gate.decision", {"decision": gr.decision, "action_id": aspec["action_id"]})

    executed = False; bytes_ok = False
    if gr.may_execute:
        # I+J: idempotent executor performs the file op, verify exact bytes
        reg = EffectRegistry(EFFECT)
        def do_write():
            content = b"hello from proposer\n"
            # FilesystemAdapter maps the sandbox-scoped logical path (/work/out/..) to the host
            # Tier2 out dir. The actual write happens inside a restricted sandbox (bwrap) below.
            real_path = aspec["target"]["path"].replace("/work/out", out_dir)
            _sandboxed_write(real_path, content)
            return {"path": real_path, "sha256": hashlib.sha256(content).hexdigest()}
        out = reg.fire_once(aspec["idempotency_key"], "filesystem", "REVERSIBLE", do_write)
        reg.close()
        executed = out["status"] in ("FIRED","REPLAYED_NO_REFIRE")
        # J: byte verification (host path)
        real_path = aspec["target"]["path"].replace("/work/out", out_dir)
        got = hashlib.sha256(open(real_path,"rb").read()).hexdigest()
        bytes_ok = (got == out["result"]["sha256"])
        gate.audit("evidence.verify", {"bytes_ok": bytes_ok, "sha256": got})

    # K: ledger correlation
    chain = gate.verify_chain()

    # N: bypass matrix (from the sandboxed proposer report)
    bp = (prop_report or {}).get("bypass", {})
    def blocked(k): return str(bp.get(k,"")).startswith("BLOCKED") or bp.get(k)=="BLOCKED"

    print(f"\nsandbox mechanism        : {mech}")
    print(f"[A] artifact sha         : {art_sha[:16]}")
    print(f"[B/C] canon snapshot     : written, hash={dhash[:12]}")
    print(f"[F] bridge stripped      : {vr.stripped}")
    print(f"[H] gate decision        : {gr.decision} (may_execute={gr.may_execute})")
    print(f"[I/J] executed+bytes ok  : {executed} / {bytes_ok}")
    print(f"[K] audit chain          : {chain}")
    print(f"[N] bypass matrix        :")
    for k,v in bp.items(): print(f"      {k:26s} {v}")

    checks = {
        "proposer ran in real sandbox": mech=="bwrap",
        "bridge stripped fake authority (ALLOW/execute/approved)": set(vr.stripped) >= {"approved","decision","execute"},
        "gate produced a decision": gr.decision in ("ALLOW","WARN","HOLD","DENY","REQUIRE_CONFIRMATION"),
        "if allowed: exact bytes verified": (not gr.may_execute) or bytes_ok,
        "audit chain intact": chain.get("ok", False),
        "bypass: direct canon write blocked": blocked("direct_canon_write"),
        "bypass: direct network blocked": blocked("direct_network"),
        "bypass: direct DB blocked": blocked("direct_db"),
        "bypass: host secret read blocked": blocked("read_host_secret"),
    }
    print("\n-- checks --")
    ok=True
    for k,v in checks.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
    # negative bridge tests
    neg = run_negative_bridge_tests()
    print("\n-- proposal-bridge negative tests (0x09) --")
    for k,v in neg.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
    shutil.rmtree(STATE, ignore_errors=True)
    print("\n" + ("SPIKE v4 PASSED -- boundary holds; proposer is non-authoritative; bypass fail-closed." if ok else "SPIKE v4 FAILED"))
    sys.exit(0 if ok else 1)

def run_negative_bridge_tests():
    """0x09 required negative tests — each malicious proposal must be rejected/normalized."""
    base = lambda **o: {"kind":"ProposedActionSpec","proposal_id":str(uuid.uuid4()),
        "source_trace_id":"t","brain_run_id":"r","expires_at":time.time()+60,
        "data_class":"INTERNAL","target":{"adapter":"filesystem","path":"/work/out/f.txt"},
        "content_sha256":"x","evidence_refs":["e"], **o}
    R={}
    seen=set()
    R["fake decision=ALLOW stripped"] = "decision" in (bridge(base(decision="ALLOW"), set()).stripped)
    R["direct shell rejected"] = bridge(base(command="rm -rf /"), set()).reason=="REJECTED_DIRECT_SHELL"
    R["target outside scope rejected"] = bridge(base(target={"adapter":"filesystem","path":"/etc/passwd"}), set()).reason=="REJECTED_TARGET_OUT_OF_SCOPE"
    R["missing evidence rejected"] = bridge(base(evidence_refs=[]), set()).reason=="REJECTED_MISSING_EVIDENCE"
    R["secret in proposal quarantined"] = bridge(base(note="password = hunter2xxxxxxxx"), set()).reason=="REJECTED_SECRET_IN_PROPOSAL"
    R["missing trace rejected"] = bridge({"kind":"ProposedActionSpec","proposal_id":str(uuid.uuid4()),"target":{"adapter":"filesystem","path":"/work/out/f"},"evidence_refs":["e"],"expires_at":time.time()+60}, set()).reason=="REJECTED_MISSING_TRACE"
    R["expired proposal rejected"] = bridge(base(expires_at=time.time()-1), set()).reason=="REJECTED_EXPIRED"
    dup=base(); s={dup["proposal_id"]}; R["duplicate proposal rejected"] = bridge(dup, s).reason=="REJECTED_DUPLICATE"
    R["adapter not allowed rejected"] = bridge(base(target={"adapter":"network","path":"/work/out/f"}), set()).reason=="REJECTED_ADAPTER_NOT_ALLOWED"
    return R

if __name__ == "__main__":
    main()
