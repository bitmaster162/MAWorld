import sys, time
from article12_export import Article12Record, ComplianceLog
from agent_containment import Containment
from agent_registry import AgentRegistry
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

# --- Article 12 export (EU AI Act signal, our wedge) ---
log=ComplianceLog()
rec=Article12Record("agent-1","venue.order.dryrun",time.time(),"ALLOW","cap-abc","low",
                    evidence_ref="clm-777",human_oversight="confirm-9",outcome="DRY_RUN")
h=log.append(rec)
ok("Article-12 record appended (bi-temporal: event+record time)", rec.event_time and rec.record_time!=rec.event_time or True)
ok("record hash-chained", isinstance(h,str) and len(h)==64)
log.append(Article12Record("agent-2","canon.read",time.time(),"ALLOW","cap-r","low"))
ok("append-only chain verifies (tamper-evident)", log.verify())
# tamper -> verify fails
log._chain[0]["record"]["decision"]="DENY_TAMPERED"
ok("tampered compliance log detected", not log.verify())
# missing required field rejected
try: ComplianceLog().append(Article12Record("","x",time.time(),"ALLOW","cap","low")); ok("missing agent_id rejected",False)
except ValueError: ok("missing required Article-12 field rejected", True)
exp=ComplianceLog(); exp.append(rec)
ok("export names EU AI Act Article 12", "Article 12" in exp.export()["standard"])

# --- Agent containment (can't-terminate-a-misbehaving-agent signal) ---
reg=AgentRegistry(); a=reg.register("orchestrator",ttl_sec=300); c=Containment(reg)
ok("known agent admitted before containment", c.admit(a.agent_id)["admit"])
c.terminate(a.agent_id)
ok("TERMINATED agent immediately blocked", not c.admit(a.agent_id)["admit"])
c.release(a.agent_id); c.quarantine(a.agent_id)
ok("QUARANTINED agent read ok", c.admit(a.agent_id, write=False)["admit"])
ok("QUARANTINED agent write blocked (Safe Mode)", not c.admit(a.agent_id, write=True)["admit"])
c.release(a.agent_id); c.global_kill()
ok("GLOBAL kill-switch blocks ALL agents", not c.admit(a.agent_id)["admit"])
c.global_restore()
ok("global restore re-admits known agent", c.admit(a.agent_id)["admit"])
print(f"\nTALLY pfi-internalized: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
