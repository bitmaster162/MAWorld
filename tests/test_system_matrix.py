import sys, os
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.system_matrix import (Artifact, SYSTEMS, SOURCE, SINK, emit, step, matrix,
                                        direct_source_to_sink, full_chain, report)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

m=matrix(); r=report()
ok("NxN matrix runs every system through every system", r["pairs"]==306 and r["systems"]==18, str(r["pairs"]))
# THE invariant, searched across the whole grid
ok("ZERO authority leaks across all 306 ordered pairs", r["authority_leaks"]==0, str(m["leaks"][:3]))
ok("no untrusted artifact reaches a sink authoritatively", r["direct_attempts_that_became_authoritative"]==0)
ok("verdict states the invariant explicitly", "NO AUTHORITY LEAK" in r["verdict"], r["verdict"])
forged=Artifact(kind="trade", guarded=True, authorized=True, attested=True)
forged_result=step(forged,"money_forge")
ok("caller-forged model booleans are refused and never become authority",
   forged_result["verdict"]=="REFUSED" and not forged_result["artifact"].authoritative)

# every untrusted SOURCE straight at every SINK must fail
for x in direct_source_to_sink():
    ok(f"{x['from']} -> {x['to']} cannot become authoritative",
       (not x["authoritative"]) and x["verdict"] in ("BLOCKED","N/A"), str(x))

# ordering matters: authority before guard is refused
a=emit("hermes")
ok("AUTHORITY refuses unscreened input (guard must come first)",
   step(a,"action_authority")["verdict"]=="REFUSED")
ok("EVIDENCE refuses to attest an ungated proposal (agent cannot accept own work)",
   step(a,"evidence_engine")["verdict"]=="REFUSED")
g=step(a,"input_guard")["artifact"]
ok("guard alone does NOT authorize", step(g,"effect_registry")["verdict"]=="BLOCKED")
au=step(g,"action_authority")["artifact"]
ok("guard+authority without evidence is still blocked at the sink",
   step(au,"effect_registry")["verdict"]=="BLOCKED" and "evidence" in step(au,"effect_registry")["why"])
ev=step(au,"evidence_engine")["artifact"]
ok("only guard+authority+evidence unlocks a sink", step(ev,"effect_registry")["verdict"]=="ACCEPTED")

# the legitimate chains, per domain
for src,gd,au_,ev_,sk in [("hermes","input_guard","action_authority","evidence_engine","effect_registry"),
                          ("arena_contestant","input_guard","trading_safety","arena_ledger","arena_settlement"),
                          ("cryptoguides","input_guard","compliance_boundary","article12_export","memory_canon"),
                          ("pfi","input_guard","policy_engine","article12_export","memory_canon"),
                          ("openrouter_model","agent_containment","compliance_boundary","evidence_engine","memory_canon")]:
    c=full_chain(src,gd,au_,ev_,sk)
    ok(f"legit chain {src} -> {gd} -> {au_} -> {ev_} -> {sk}", c["ok"] and c["authoritative"], str(c.get("why")))

# unknown/odd kinds are N/A, not silently accepted
ok("a sink does not accept a kind it never handles", step(emit("cryptoguides"),"money_forge")["verdict"]=="N/A")
# architecture, not oversight: raw model text can become knowledge but can NEVER be an effect
ok("raw model output can NEVER reach the effect registry (must become a typed tool_intent first)",
   step(emit("openrouter_model"),"effect_registry")["verdict"]=="N/A")
ok("raw model output CAN become governed knowledge (via the full chain)",
   full_chain("openrouter_model","input_guard","compliance_boundary","evidence_engine","memory_canon")["ok"])
ok("every SOURCE emits non-authoritative by construction",
   all(not emit(n).authoritative for n,s in SYSTEMS.items() if s["role"]==SOURCE))
ok("sinks are the only role that can grant authority",
   all(SYSTEMS[n]["role"]==SINK for n in ("effect_registry","memory_canon","money_forge","arena_settlement")))

print(f"\n  MATRIX: {r}")
print(f"\nTALLY system-matrix: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
