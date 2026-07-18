import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile

import evidence_engine as E
import lifeos_core as L
from evidence_engine import Claim, ClaimKind as K


_EE_KEY = b"lifeos-test-evidence"
_sign = lambda message: hmac.new(_EE_KEY, message, hashlib.sha256).hexdigest()
_verify = lambda message, signature: hmac.compare_digest(_sign(message), signature)
_issuer = E.EvidenceIssuer("lifeos-test-evidence", _sign)
_acceptor = E.EvidenceAcceptor({"lifeos-test-evidence": _verify})


def evidence_accept(claim):
    return _acceptor.accept(claim, _issuer.verify(claim))


P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def disk_store(db_name="life.db"):
    return L.LifeStore(tempfile.mkdtemp(prefix="lifeos-"), db_name)


# Fixed-root store and explicit in-memory helper.
store = disk_store()
ok("disk store resolves a fixed root", os.path.isabs(store.root) and store.db_path.startswith(store.root + os.sep))
ok("explicit in-memory helper has no filesystem path", L.LifeStore.in_memory().db_path is None)
for bad_name in ("../escape.db", "..\\escape.db", os.path.abspath("escape.db"), ":memory:"):
    try:
        L.LifeStore(tempfile.mkdtemp(prefix="lifeos-bad-"), bad_name)
        ok(f"unsafe db name rejected: {bad_name}", False)
    except L.StorePathViolation:
        ok(f"unsafe db name rejected: {bad_name}", True)
try:
    L.LifeStore(":memory:", "life.db")
    ok("raw :memory: root rejected", False)
except L.StorePathViolation:
    ok("raw :memory: root rejected", True)
try:
    L.LifeAgent("bad", os.path.join(tempfile.mkdtemp(), "life.db"))
    ok("LifeAgent rejects arbitrary path string", False)
except TypeError:
    ok("LifeAgent rejects arbitrary path string", True)

# Symlink database paths are rejected where the platform permits creating one.
symlink_root = tempfile.mkdtemp(prefix="lifeos-link-root-")
target_root = tempfile.mkdtemp(prefix="lifeos-link-target-")
target = os.path.join(target_root, "target.db")
sqlite3.connect(target).close()
link = os.path.join(symlink_root, "linked.db")
try:
    os.symlink(target, link)
except (OSError, NotImplementedError):
    ok("platform prevents unprivileged symlink database setup", True)
else:
    try:
        L.LifeStore(symlink_root, "linked.db")
        ok("symlink database path rejected", False)
    except L.StorePathViolation:
        ok("symlink database path rejected", True)

# Lifecycle.
a = L.LifeAgent("hermes", store)
try:
    a.transition("ACTIVE")
    ok("invalid skip rejected", False)
except L.LifecycleError:
    ok("invalid skip SEED->ACTIVE rejected", True)
a.transition("BOOTSTRAPPING")
a.transition("ACTIVE")
ok("valid path SEED->BOOT->ACTIVE", a.state == "ACTIVE")

# Hibernating state blocks memory and proposal creation; legacy execution is always denied.
a.remember("working", "draft plan")
a.transition("HIBERNATING")
ok("hibernating: model_calls=False", a.policy()["model_calls"] is False)
try:
    a.remember("working", "x")
    ok("hibernating memory write blocked", False)
except L.LifecycleError:
    ok("hibernating memory write blocked", True)
try:
    a.propose_external_action("send")
    ok("hibernating external proposal blocked", False)
except L.LifecycleError:
    ok("hibernating external proposal blocked", True)
try:
    a.act_externally("send", capability_token="tok", cap_key=b"caller-key")
    ok("legacy execution-shaped API denied", False)
except L.AuthorityViolation:
    ok("legacy execution-shaped API denied", True)

# Hibernate -> restore through the SAME store object with an externally held anchor.
continuity_store = disk_store("continuity.db")
result = L.model_swap_continuity_test(continuity_store)
ok("model-swap continuity: identity+memory survive", result["model_swap_test_passed"])
claim = Claim(K.CONTINUITY_PRESERVED, result, "lifeos")
ok("claim-supplied continuity boolean needs external attestation", not evidence_accept(claim).accepted)

anchor_store = disk_store("anchor.db")
anchored = L.LifeAgent("anchor", anchor_store)
anchored.transition("BOOTSTRAPPING")
anchored.transition("ACTIVE")
anchor_sha = anchored.hibernate()
try:
    L.LifeAgent.restore(anchor_store, anchored.agent_id, expect_sha="")
    ok("restore requires external manifest anchor", False)
except L.LifecycleError:
    ok("restore requires external manifest anchor", True)

tamper_store = disk_store("tamper.db")
b = L.LifeAgent("x", tamper_store)
b.transition("BOOTSTRAPPING")
b.transition("ACTIVE")
sha = b.hibernate()
connection = sqlite3.connect(tamper_store.db_path)
connection.execute("UPDATE hibernation SET blob=blob||' ' WHERE agent_id=?", (b.agent_id,))
connection.commit()
connection.close()
try:
    L.LifeAgent.restore(tamper_store, b.agent_id, expect_sha=sha)
    ok("tampered manifest rejected", False)
except L.LifecycleError:
    ok("tampered manifest rejected", True)

# LifeOS != Control Spine.
try:
    a.write_canon("truth")
    ok("canon write impossible", False)
except L.AuthorityViolation:
    ok("canon write impossible from life layer", True)

# Skill/trust can only contribute to a non-authoritative proposal.
d = L.LifeAgent("y", L.LifeStore.in_memory())
d.transition("BOOTSTRAPPING")
d.transition("ACTIVE")
d.learn_skill("trading", 0.99)
d.bond("owner", 1.0)
proposal = d.propose_external_action(
    "place_order", resource="BTCUSDT", payload={"side": "BUY", "qty": 1}
)
ok("external action is proposal-only", proposal["authoritative"] is False)
ok("proposal carries no capability token", "capability_token" not in proposal and "cap_key" not in proposal)
ok("proposal names canonical downstream checks", proposal["requires"] == ["ActionVerifier", "ActionExecutor"])

os.environ["LIFEOS_CAP_KEY"] = "must-not-be-read"
try:
    d.act_externally("place_order", capability_token="anything", cap_key=b"anything")
    ok("caller key and env cannot revive legacy action", False)
except L.AuthorityViolation:
    ok("caller key and env cannot revive legacy action", True)
finally:
    os.environ.pop("LIFEOS_CAP_KEY", None)

# Memory promotion remains proposal-only.
d.remember("episodic", "found alpha")
promotion = d.propose_promotion("episodic", 0)
ok("memory promotion = governed proposal", promotion["authoritative"] is False and "CanonPromoter" in promotion["requires"])
memory_claim = Claim(K.MEMORY_PROMOTED, {"promotion_state": "PROPOSED", "human_approval": None}, "lifeos")
ok("Evidence Engine rejects unapproved promotion", not evidence_accept(memory_claim).accepted)

# Fork gets a fresh identity and an explicit in-memory store, never authority.
child = d.fork("hermes-jr")
ok("fork -> new agent_id", child.agent_id != d.agent_id and child.parent_id == d.agent_id)
ok("fork copies memory but not authority", child.memory["episodic"][0]["item"] == "found alpha")
ok("fork uses explicit in-memory store", child.store.is_memory)
try:
    child.write_canon("x")
    ok("child also cannot write canon", False)
except L.AuthorityViolation:
    ok("child also cannot write canon", True)

# Terminal state remains final.
terminal = L.LifeAgent("z", L.LifeStore.in_memory())
terminal.transition("TERMINATED")
try:
    terminal.transition("BOOTSTRAPPING")
    ok("terminal final", False)
except L.LifecycleError:
    ok("terminal state cannot reopen", True)

print(f"\nTALLY lifeos: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
