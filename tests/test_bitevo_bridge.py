import hashlib
import hmac
import os
import sys
import tempfile
import time

from bitevo_bridge import (
    BitEvoBridge, IsolatedCodeRunner, IsolationResult, admit_bitevo_code,
)
from capability import mint_capability, verify_capability
from policy_engine import Policy, PolicyEngine
from article12_export import ComplianceLog
from action_authority import (
    ActionVerifier, DecisionIssuer, HumanApprovalIssuer, SQLiteNonceStore,
)


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


class TrustedTestIsolationAdapter(IsolatedCodeRunner):
    """Control-flow test double; it does not claim to test OS isolation."""

    backend_id = "test-only-isolation-adapter"

    def __init__(self):
        self.calls = []

    def run(self, code):
        self.calls.append(code)
        if "while True" in code:
            return IsolationResult(False, "", "killed", 9)
        return IsolationResult(True, "hello from isolated adapter\n", "", 0)


CAPABILITY_KEY = b"bitevo-capability"
GATE_KEY = b"bitevo-gate"
OWNER_KEY = b"bitevo-owner"
agent = "bitevo_runner"
policy = PolicyEngine([
    Policy("PERMIT", agent, "execute_code", "sandbox")
])
compliance = ComplianceLog()
gate = DecisionIssuer("bitevo-gate", sign(GATE_KEY))
owner = HumanApprovalIssuer("bitevo-owner", sign(OWNER_KEY))
authority = ActionVerifier(
    {"bitevo-gate": verify(GATE_KEY)}, {"bitevo-owner": verify(OWNER_KEY)}
)


def capability_check(token, agent_id, action, resource):
    return verify_capability(
        CAPABILITY_KEY, token, agent_id, action, resource
    )


def passport(agent_id, action="execute_code", resource="sandbox"):
    return {
        "agent_id": agent_id,
        "token": mint_capability(
            CAPABILITY_KEY, agent_id, action, resource, time.time() + 300
        ),
    }


runner = TrustedTestIsolationAdapter()
bridge = BitEvoBridge(
    capability_check,
    policy,
    compliance,
    authority,
    SQLiteNonceStore(os.path.join(tempfile.mkdtemp(), "bitevo-nonces.db")),
    runner,
)


def grant(code, agent_id=agent, *, verdict="REQUIRE_CONFIRMATION", confirm=True):
    decision = gate.issue(bridge.action_spec(agent_id, code), verdict)
    confirmation = owner.confirm(decision) if confirm else None
    return decision, confirmation


# Exact capability + action decision + human proof + fixed isolation backend.
benign = "print('hello from bitevo')"
decision, confirmation = grant(benign)
result = bridge.admit(passport(agent), benign, decision, confirmation)
ok("exact externally authorized code reaches fixed isolation adapter", result["admitted"] and result["sandboxed"] and result["ok"] and not result["authoritative"])
ok("adapter receives the exact code bound into ActionSpec", runner.calls == [benign])

# Every authority layer fails closed.
unsigned = bridge.admit(passport(agent), "print(1)", None)
ok("missing action decision is denied", not unsigned["admitted"] and "signed action decision" in unsigned["reason"])

plain_allow_code = "print(2)"
plain_allow, _ = grant(plain_allow_code, verdict="ALLOW", confirm=False)
plain_allow_result = bridge.admit(passport(agent), plain_allow_code, plain_allow)
ok("arbitrary code cannot use plain ALLOW", not plain_allow_result["admitted"] and "REQUIRE_CONFIRMATION" in plain_allow_result["reason"])

no_owner_code = "print(3)"
no_owner, _ = grant(no_owner_code, confirm=False)
no_owner_result = bridge.admit(passport(agent), no_owner_code, no_owner)
ok("missing signed owner confirmation is denied", not no_owner_result["admitted"] and "confirmation" in no_owner_result["reason"])

forged_passport = {"agent_id": agent, "token": "forged"}
forged_code = "print(4)"
forged_decision, forged_confirmation = grant(forged_code)
ok("forged capability passport is rejected", not bridge.admit(forged_passport, forged_code, forged_decision, forged_confirmation)["admitted"])

stranger_code = "print(5)"
stranger_decision, stranger_confirmation = grant(stranger_code, "stranger")
ok("policy denies unlisted agent", not bridge.admit(passport("stranger"), stranger_code, stranger_decision, stranger_confirmation)["admitted"])

# Static guard still blocks obvious exfiltration before the isolation adapter.
env_code = "open('/repo/.env').read()"
env_decision, env_confirmation = grant(env_code)
ok("code reading .env is rejected", not bridge.admit(passport(agent), env_code, env_decision, env_confirmation)["admitted"])
socket_code = "import socket; socket.socket()"
socket_decision, socket_confirmation = grant(socket_code)
ok("code with socket is rejected", not bridge.admit(passport(agent), socket_code, socket_decision, socket_confirmation)["admitted"])

# Execution result may fail, while admission/isolation facts remain separate.
loop_code = "while True:\n x=1"
loop_decision, loop_confirmation = grant(loop_code)
loop = bridge.admit(passport(agent), loop_code, loop_decision, loop_confirmation)
ok("isolated runner failure is not reported as successful execution", loop["admitted"] and loop["sandboxed"] and not loop["ok"])

# Decisions are exact and single-use.
code_a = "print('A')"
code_b = "print('B')"
decision_a, confirmation_a = grant(code_a)
substitution = bridge.admit(passport(agent), code_b, decision_a, confirmation_a)
ok("decision for different code is rejected", not substitution["admitted"] and "bound" in substitution["reason"])

replay = bridge.admit(passport(agent), benign, decision, confirmation)
ok("decision nonce replay is rejected", not replay["admitted"] and "replay" in replay["reason"])

wrong_action_code = "print(6)"
wrong_action_decision, wrong_action_confirmation = grant(wrong_action_code)
ok("capability bound to wrong action is rejected", not bridge.admit(passport(agent, "read"), wrong_action_code, wrong_action_decision, wrong_action_confirmation)["admitted"])

# No isolation backend means no execution on any host.
closed_bridge = BitEvoBridge(
    capability_check,
    policy,
    compliance,
    authority,
    SQLiteNonceStore(os.path.join(tempfile.mkdtemp(), "closed-nonces.db")),
    None,
)
closed_code = "print('must not execute')"
closed_decision = gate.issue(closed_bridge.action_spec(agent, closed_code), "REQUIRE_CONFIRMATION")
closed_confirmation = owner.confirm(closed_decision)
closed = closed_bridge.admit(
    passport(agent), closed_code, closed_decision, closed_confirmation
)
ok("missing isolation backend denies before execution", not closed["admitted"] and "resource limits alone" in closed["reason"])

legacy = admit_bitevo_code(passport(agent), benign, CAPABILITY_KEY, policy, compliance)
ok("legacy self-authorizing API is permanently fail closed", not legacy["admitted"])
ok("Article-12 log is tamper-evident over all submissions", compliance.verify() and len(compliance.export()["records"]) >= 10)

print(f"\nTALLY bitevo-bridge: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
