import sys, os
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT,"libs"))
from maworld_core.arena_ledger import (merkle_root, canon_bytes, canon_from_json_text, CanonError,
    minor_units, Manifest, NullAnchor, ExternalAnchor, AnchorError, anchored_commit, verify_manifest,
    RoundSchedule, ForcedRevealRound, ThresholdCommittee, NonRevealForfeit)
P=F=0
def ok(n,c,d=""):
    global P,F; b=bool(c); P+=b; F+=(not b); print(("  PASS " if b else "  FAIL ")+n+("" if b else f" <- {d}"))

a={"id":1,"pnl_minor":1000}; b={"id":2,"pnl_minor":2000}; c={"id":3,"pnl_minor":-9900}

# ===== REFUTATION A: duplicate-last Merkle (CVE-2012-2459 class) =====
ok("A: merkle([a,b,c]) != merkle([a,b,c,c])  (v1 gave the SAME root)",
   merkle_root([a,b,c]) != merkle_root([a,b,c,c]))
ok("A: order matters (list, not multiset)", merkle_root([a,b,c]) != merkle_root([c,b,a]))
ok("A: empty tree = SHA256('') per RFC 6962",
   merkle_root([]) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
import hashlib
ok("A: single leaf = H(0x00||leaf) (domain-separated)",
   merkle_root([a]) == hashlib.sha256(b"\x00"+canon_bytes(a)).hexdigest())
ok("A: leaf and internal nodes live in different hash domains (0x00 vs 0x01)",
   merkle_root([a,b]) == hashlib.sha256(b"\x01"+hashlib.sha256(b"\x00"+canon_bytes(a)).digest()
                                        +hashlib.sha256(b"\x00"+canon_bytes(b)).digest()).hexdigest())
ok("A: tail-truncation still detected via count+root", merkle_root([a,b,c]) != merkle_root([a,b]))

# ===== REFUTATION C: RFC 8785 is not hash-stability on its own =====
for bad,label in [({"pnl":0.3},"float"), ({"q":2**53+1},"IEEE-754-unsafe int"),
                  ({"s":"é"},"non-NFC string"), ({"é":"v"},"non-NFC key"),
                  ({"x":{1,2}},"non-I-JSON type")]:
    try: canon_bytes(bad); ok(f"C: {label} rejected", False, "accepted!")
    except CanonError: ok(f"C: {label} rejected at the input contract", True)
try: canon_from_json_text('{"a":1,"a":2}'); ok("C: duplicate keys rejected", False, "accepted!")
except CanonError: ok("C: duplicate JSON keys rejected (json.loads silently keeps the last)", True)
ok("C: money as int minor units is stable", minor_units("12.34", 2) == 1234)
ok("C: canonical bytes are sorted + tight", canon_bytes({"b":1,"a":2}) == b'{"a":2,"b":1}')

# ===== REFUTATION B: self-published commitment proves nothing about time =====
m = Manifest(round_id="r1", ruleset_hash="rs", snapshot_hash="sn", root=merkle_root([a,b,c]), count=3)
try: anchored_commit(m, [NullAnchor()]); ok("B: unanchored refused", False, "no raise")
except AnchorError as e: ok("B: NO external anchor -> refuse to call it proof", "does not prove WHEN" in str(e))
try: anchored_commit(m, []); ok("B: empty anchors refused", False, "no raise")
except AnchorError: ok("B: publishing an unanchored commitment as proof is refused", True)

stamped=[]
tsa = ExternalAnchor("rfc3161-tsa", lambda d: (stamped.append(d), {"time":"2026-07-16T00:00:00Z","tsa":"sig"})[1])
pub = anchored_commit(m, [tsa])
ok("B: with a real anchor the manifest is stamped externally", pub["anchored"] and stamped==[m.digest()])
v = verify_manifest(pub, [a,b,c])
ok("B: third party verifies root+count+digest+anchor", v["ok"], str(v))
ok("B: dropping the losing trade is detected", not verify_manifest(pub,[a,b])["ok"])
tampered=dict(pub); tampered["manifest"]=dict(pub["manifest"], count=2)
ok("B: editing the manifest breaks its digest", not verify_manifest(tampered,[a,b])["digest_ok"])
bad_anchor = ExternalAnchor("broken", lambda d: {"no_time":1})
try: anchored_commit(m,[bad_anchor]); ok("B: anchor without time refused", False, "no raise")
except AnchorError: ok("B: an anchor that returns no verifiable time is refused", True)

# ===== REFUTATION B (2nd half): OMISSION — never publishing an inconvenient round =====
sch = RoundSchedule(["r1","r2","r3"])
sch.publish("r1", m.digest())
ok("OMISSION: schedule audit flags rounds never published", sch.audit()["missing"]==["r2","r3"])
sch.publish_null("r2", "venue outage")
ok("OMISSION: an explicit NULL-MANIFEST closes a skipped round", "r2" not in sch.audit()["missing"])
try: sch.publish_null("r3",""); ok("OMISSION: null needs a reason", False, "no raise")
except AnchorError: ok("OMISSION: a NULL-MANIFEST demands a public reason", True)
try: sch.publish("r9","x"); ok("OMISSION: unscheduled round rejected", False, "no raise")
except AnchorError: ok("OMISSION: publishing an unregistered round is rejected", True)
sch.publish("r3", m.digest())
ok("OMISSION: complete only when every pre-registered round is accounted for", sch.audit()["complete"])

# ===== REFUTATION D: selective abort / last-revealer =====
class XorOpener:
    K=b"committee-key-material-xxxxxxxxxx"
    def seal(s,x): return bytes(v ^ s.K[i%len(s.K)] for i,v in enumerate(x))
    def open(s,x): return bytes(v ^ s.K[i%len(s.K)] for i,v in enumerate(x))
r=ForcedRevealRound(ThresholdCommittee(XorOpener(), threshold=2))
r.commit("honest",{"side":"BUY","qty_minor":1000},"salt-a")
r.commit("chicken",{"side":"SELL","qty_minor":9000},"salt-b")
r.reveal("honest",{"side":"BUY","qty_minor":1000},"salt-a")
s3=r.settle(shares_present=3)
ok("D: voluntary reveal recorded", s3["honest"]["status"]=="REVEALED")
ok("D: a hidden losing commit is FORCE-OPENED by the committee", s3["chicken"]["status"]=="FORCE_OPENED")
ok("D: non-reveal does NOT become 'did not participate'", s3["chicken"]["payload"]["qty_minor"]==9000)
ok("D: below threshold -> FORFEIT, not a free pass", r.settle(shares_present=1)["chicken"]["status"]=="FORFEIT")
try: r.reveal("honest",{"side":"SELL","qty_minor":1},"salt-a"); ok("D: mismatched reveal rejected", False, "no raise")
except NonRevealForfeit: ok("D: a reveal that does not match the commitment is rejected", True)

print(f"\nTALLY arena-ledger: PASS={P} FAIL={F}"); sys.exit(1 if F else 0)
