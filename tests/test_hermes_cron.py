import hashlib
import hmac
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "libs"))

from maworld_core.action_authority import (
    ActionVerifier, DecisionIssuer, HumanApprovalIssuer, SQLiteNonceStore,
)
from maworld_core.hermes_cron import (
    DELEGATABLE, FORBIDDEN, CronJob, HermesCron, JobResult, arena_cron,
)
from maworld_core.hermes_control import HermesDriver
from maworld_core.compliance_boundary import (
    ComplianceBoundary, ReceiptIssuer, ReceiptVerifier,
)
from maworld_core.agent_registry import AgentRegistry
from maworld_core.agent_containment import Containment
from maworld_core.budget_router import BudgetRouter, BudgetError


P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


def sign(key):
    return lambda message: hmac.new(key, message, hashlib.sha256).hexdigest()


def verify(key):
    return lambda message, signature: hmac.compare_digest(
        hmac.new(key, message, hashlib.sha256).hexdigest(), signature
    )


gate_key = b"cron-gate"
owner_key = b"cron-owner"
receipt_key = b"cron-receipt"
registry = AgentRegistry()
containment = Containment(registry)
agent_id = registry.register("hermes").agent_id
gate = DecisionIssuer("cron-gate", sign(gate_key))
owner = HumanApprovalIssuer("cron-owner", sign(owner_key))
authority = ActionVerifier(
    {"cron-gate": verify(gate_key)}, {"cron-owner": verify(owner_key)}
)
boundary = ComplianceBoundary(
    containment,
    365,
    authority,
    SQLiteNonceStore(os.path.join(tempfile.mkdtemp(), "cron-nonces.db")),
    ReceiptIssuer("cron-receipts", sign(receipt_key)),
    ReceiptVerifier({"cron-receipts": verify(receipt_key)}),
)
driver = HermesDriver(boundary, agent_id, capability_ref="cap-cron")
router = BudgetRouter(
    os.path.join(tempfile.mkdtemp(), "budget.db"),
    {"hermes-routines": 0.30},
    absolute_cap=1.0,
)
cron = HermesCron(driver, budget_router=router)


def grants_for(name, *, confirm_high=True):
    grants = {}
    for planned in cron.plan(name):
        high = driver.classify(planned["intent"])["high_impact"]
        decision = gate.issue(
            planned["spec"], "REQUIRE_CONFIRMATION" if high else "ALLOW"
        )
        confirmation = owner.confirm(decision) if high and confirm_high else None
        grants[planned["spec_hash"]] = (decision, confirmation)
    return grants


# Delegation whitelist and scheduling.
scheduled = cron.schedule(CronJob(
    "nightly-tests", "run_tests", "0 3 * * *", "python3 tests/run_all.py"
))
ok("cheaply-verifiable routine schedules", scheduled["ok"] and scheduled["verified_by"] == "exit_code+tally", str(scheduled))
ok("schedule emits a real cron line", scheduled["cron_line"].startswith("0 3 * * *"))
for kind, why in FORBIDDEN.items():
    denied = cron.schedule(CronJob(f"j-{kind}", kind, "* * * * *"))
    ok(f"NOT delegable: {kind}", not denied["ok"] and "NOT DELEGABLE" in denied["reason"])
ok("accept_evidence is refused for separation-of-duties", "cannot accept its own work" in cron.schedule(CronJob("x", "accept_evidence", "* * * * *"))["reason"])
ok("unknown routine fails closed", not cron.schedule(CronJob("y", "invent_something", "* * * * *"))["ok"])
ok("judgment work is explicitly non-delegable", "verification costs as much" in FORBIDDEN["decide_architecture"])

# Dispatch requires one exact external grant per tool.
missing = cron.dispatch("nightly-tests")
ok("missing grants deny the terminal routine", any(item["decision"] == "DENY" for item in missing["decisions"]), str(missing["decisions"]))

no_owner = cron.dispatch("nightly-tests", grants_for("nightly-tests", confirm_high=False))
ok("gate decision without signed owner confirmation is denied", not no_owner["ok"] and "confirmation" in no_owner["decisions"][0]["reason"])

nightly_grants = grants_for("nightly-tests", confirm_high=True)
allowed = cron.dispatch("nightly-tests", nightly_grants)
ok("exact gate+owner grants allow the routine", allowed["ok"], str(allowed["decisions"]))

replayed = cron.dispatch("nightly-tests", nightly_grants)
ok("reusing the same tool grant is rejected as replay", not replayed["ok"] and "replay" in replayed["decisions"][0]["reason"])

try:
    cron.dispatch("nightly-tests", human_confirmed=True)
    bool_api_removed = False
except TypeError:
    bool_api_removed = True
ok("human_confirmed boolean dispatch API is removed", bool_api_removed)

cron.schedule(CronJob("scan", "scan_repo", "0 * * * *", "libs/"))
scan_plan = cron.plan("scan")
ok("plan exposes one exact spec per declared tool", len(scan_plan) == len(DELEGATABLE["scan_repo"]["tools"]) and all(item["spec_hash"] == item["spec"].hash() for item in scan_plan))
scan = cron.dispatch("scan", grants_for("scan"))
ok("read-only scan succeeds with exact low-risk grants", scan["ok"])

# Swapping decisions between tool hashes triggers ActionSpec binding.
swapped_grants = grants_for("scan")
hashes = list(swapped_grants)
swapped_grants[hashes[0]], swapped_grants[hashes[1]] = swapped_grants[hashes[1]], swapped_grants[hashes[0]]
swapped = cron.dispatch("scan", swapped_grants)
ok("cross-tool grant substitution is denied", not swapped["ok"] and all(item["decision"] == "DENY" for item in swapped["decisions"]))

# Budget is charged before an agent invocation/boundary crossing.
try:
    for _ in range(20):
        cron.dispatch("scan")
    ok("budget cap enforced", False, "no raise")
except BudgetError:
    ok("routine budget cap raises before another agent run", True)

# Result verification remains objective and non-authoritative.
verified = cron.verify(
    "nightly-tests",
    JobResult("nightly-tests", artifact="== 46/46 suites green ==\nFAIL=0", exit_code=0),
)
ok("green suite + exit 0 -> accepted", verified["accepted"] and verified["verify"] == "exit_code+tally")
verified = cron.verify(
    "nightly-tests",
    JobResult("nightly-tests", artifact="FAIL=3", exit_code=1, claimed_done=True),
)
ok("Hermes self-claim on red suite is rejected", not verified["accepted"] and verified["claimed_done"])
ok("verification result is not authoritative by itself", verified["authoritative"] is False)

cron.schedule(CronJob("draft", "draft_report", "0 6 * * *"))
verified = cron.verify("draft", JobResult("draft", artifact="a lovely draft"))
ok("draft requires human review", not verified["accepted"] and "human review" in verified["why"])

cron.schedule(CronJob("round", "arena_round", "0 */4 * * *"))
verified = cron.verify("round", JobResult("round", artifact="I made +9999", claimed_done=True))
ok("arena result is real only after engine settle", not verified["accepted"] and "settle()" in verified["why"])
verified = cron.verify("scan", JobResult("scan", artifact="X"), expected_hash="deadbeef")
ok("artifact-hash routine rejects mismatch", not verified["accepted"])

savings = cron.savings()
ok("savings accounting states its verification bound", savings["routines_run"] >= 4 and "saves nothing" in savings["note"], str(savings))
ok("token-savings claim remains UNMEASURED", "UNMEASURED" in savings["token_savings"], str(savings))

arena = arena_cron()
ok("arena cron drives all three paper arms", arena["paper_only"] and set(arena["arms"]) == {"maworld", "continuityos", "bare"})
ok("arena cron uses confirmed model slug", "nemotron-3-ultra-550b-a55b:free" in arena["command"])
ok("arena cron says engine settles", "never the model" in arena["note"])

print(f"\n  SAVINGS: {savings}")
print(f"\nTALLY hermes-cron: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
