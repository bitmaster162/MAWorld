"""Deterministic dry-run composition walk.

This exercises local adapters in sequence and proves fail-closed composition for the modeled path.
It is not a production E2E test and does not attest external venues, identity or human systems.
"""
from __future__ import annotations
import hashlib, os, time
from decimal import Decimal
from maworld_core.global_cycle import open_global, derive
from maworld_core.input_guard import admit_input
from maworld_core.policy_engine import Policy, PolicyEngine
from maworld_core.action_authority import (ActionSpec, ActionExecutor, ActionVerifier,
                                           SQLiteNonceStore, execute, ConfusedDeputy)
from maworld_core.trading_safety import RiskDecision, InstrumentSpec, fixed_to_qty
from maworld_core.hardened_effect_registry import HardenedEffectRegistry
from maworld_core.evidence_engine import (
    Claim, ClaimKind, EvidenceIssuer, EvidenceAcceptor,
)
from maworld_core.article12_export import Article12Record, ComplianceLog

BTC = InstrumentSpec("BINANCE:BTCUSDT",3,2,Decimal("0.001"),Decimal("0.01"),Decimal("0.001"),Decimal("100"))

def walk(intent: dict, policy: PolicyEngine, reg: HardenedEffectRegistry, compliance: ComplianceLog,
         decision_provider,
         authority_verifier: ActionVerifier, evidence_issuer: EvidenceIssuer,
         evidence_acceptor: EvidenceAcceptor, chaos=None):
    """intent: {agent_id, rationale, source, instrument, side, qty_fixed, risk_bps, cid}.
    ``decision_provider`` models an external gate/control plane and must return an
    exact signed ``(Decision, HumanConfirmation | None)`` pair.  This dry-run
    composition never turns a caller boolean into owner authority."""
    chaos = chaos or {}
    t = {}                                   # per-system verdict trace
    def fault(stage): return chaos.get(stage)

    # SYS: global-cycle (cycle starts from GLOBAL — worldview invariant)
    g = open_global(intent.get("objective","execute intent"), {"canon":"continuity_os"})
    t["global_cycle"] = {"ok": g.scope=="GLOBAL"}
    # SYS: input_guard (untrusted signal)
    adm = admit_input(intent.get("rationale",""), source=intent.get("source","internal"))
    if fault("input_guard")=="inject": adm={"admit":False,"reason":"chaos"}
    t["input_guard"] = {"ok": adm["admit"], "detail": adm.get("reason","")}
    if not adm["admit"]: return _halt(t,"input_guard", compliance, intent)
    # SYS: policy_engine (default-deny)
    pol = policy.evaluate(intent["agent_id"], "venue.order", intent.get("instrument","BTCUSDT"),
                          {"risk_bps": intent.get("risk_bps",50)})
    t["policy_engine"] = {"ok": pol.allow, "reason": pol.reason}
    if not pol.allow: return _halt(t,"policy_engine", compliance, intent)
    # SYS: risk + trading_safety (units)
    rb = intent.get("risk_bps",50); rd = RiskDecision("ALLOW",rb) if rb<=100 else RiskDecision("DENY",rb)
    if rd.kind!="ALLOW": t["risk"]={"ok":False}; return _halt(t,"risk", compliance, intent)
    try: qty = fixed_to_qty(int(intent.get("qty_fixed",0)), BTC)
    except Exception as e: t["trading_safety"]={"ok":False,"detail":str(e)[:40]}; return _halt(t,"trading_safety", compliance, intent)
    t["risk"]={"ok":True}; t["trading_safety"]={"ok":True,"qty":str(qty)}
    # SYS: action_authority (gate bound to exact spec hash) + control_plane confirm
    cid=intent.get("cid","cid-1"); spec=ActionSpec(
        "venue.order", intent.get("instrument","BTCUSDT"), (cid,str(qty)),
        handler_id="dryrun.venue.submit")
    decision, conf = decision_provider(spec)
    fired={"n":0}
    def do_effect():
        if fault("effect")=="crash": raise RuntimeError("chaos crash mid-effect")
        fired["n"]+=1; return {"venue":"binance","status":"DRY_RUN","cid":cid,"qty":str(qty)}
    effect_payload={"cid":cid,"instrument":intent.get("instrument","BTCUSDT"),
                    "qty":str(qty),"side":intent.get("side","")}
    def bound_handler(actual_spec):
        return reg.execute_once("order-"+cid, do_effect,
                      reconcile=lambda k:{"exists":False}, tenant="local-dryrun",
                      action=actual_spec.action_type, payload=effect_payload)
    effect_db=reg.con.execute("PRAGMA database_list").fetchone()[2]
    nonce_store=SQLiteNonceStore(effect_db+".authority")
    executor=ActionExecutor({"dryrun.venue.submit":bound_handler},authority_verifier,nonce_store)
    try:
        # SYS: hardened_effect_registry (exactly-once) wrapped by action_authority (hash-bound + confirm)
        out = execute(spec, decision, executor, confirmation=conf)
        t["action_authority"]={"ok":True}; t["control_plane"]={"ok":True,"confirmed":conf is not None}
        eff = out["result"]; t["effect_registry"]={"ok": eff.get("status") in ("FIRED","REPLAYED_NO_REFIRE","RECONCILED_CONFIRMED"), "status": eff.get("status")}
    except ConfusedDeputy as e:
        nonce_store.close()
        t["action_authority"]={"ok":False,"detail":str(e)[:40]}; return _halt(t,"action_authority", compliance, intent)
    except Exception as e:
        # chaos crash -> effect not confirmed -> registry holds (no double fire); safe degradation
        t["effect_registry"]={"ok": False, "status":"CRASH_HELD_no_refire", "detail":str(e)[:30]}
    nonce_store.close()
    # SYS: evidence_engine (engine-signed acceptance of the run's claim)
    fc = reg.fired_count("order-"+cid)
    cw=Claim(ClaimKind.WORKFLOW_RECOVERED,{"idem_key":"order-"+cid},intent["agent_id"])
    dec=evidence_acceptor.accept(cw, evidence_issuer.verify(cw))
    t["evidence_engine"]={"ok": dec.accepted, "fire_count": fc}
    # SYS: article12 (compliance record)
    compliance.append(Article12Record(intent["agent_id"],"venue.order.dryrun",time.time(),
                      "REQUIRE_CONFIRMATION","cap-trading","high",evidence_ref=spec.hash()[:12]))
    t["article12"]={"ok": compliance.verify()}
    verdict = "ACCEPTED" if all(v.get("ok") for v in t.values()) else "PARTIAL"
    return {"trace": t, "verdict": verdict, "fires": fired["n"], "authoritative": False}

def _halt(t, stage, compliance, intent):
    compliance.append(Article12Record(intent.get("agent_id","?"),"venue.order",time.time(),"DENY","cap-trading","high"))
    return {"trace": t, "verdict": "SAFE_HALT@"+stage, "fires": 0, "authoritative": False}

SYSTEMS = ["global_cycle","input_guard","policy_engine","risk","trading_safety","action_authority",
           "control_plane","effect_registry","evidence_engine","article12"]
