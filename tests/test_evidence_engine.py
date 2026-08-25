import copy
import hashlib
import hmac
import os
import shutil
import subprocess
import tempfile
import time

import evidence_engine as E
import maworld_core.evidence_engine as CORE_E
from evidence_engine import Claim, ClaimKind as K, Truth, Check, VerificationResult


P = F = 0


def ok(name, condition, detail=""):
    global P, F
    passed = bool(condition)
    P += passed
    F += not passed
    print(("  PASS " if passed else "  FAIL ") + name + ("" if passed else f" <- {detail}"))


NOW = int(time.time())
EVIDENCE_KEY = b"test-evidence-key"
APPROVAL_KEY = b"test-approval-key"
PAYMENT_KEY = b"test-payment-key"


def signer(key):
    return lambda message: hmac.new(key, message, hashlib.sha256).hexdigest()


def verifier(key):
    return lambda message, signature: hmac.compare_digest(
        hmac.new(key, message, hashlib.sha256).hexdigest(), signature
    )


approval_issuer = E.ApprovalProofIssuer("owner-approval", signer(APPROVAL_KEY), clock=lambda: NOW)
approval_verifier = E.ApprovalProofVerifier(
    {"owner-approval": verifier(APPROVAL_KEY)}, clock=lambda: NOW
)
payment_issuer = E.PaymentProofIssuer("stripe-webhook", signer(PAYMENT_KEY), clock=lambda: NOW)
payment_verifier = E.PaymentProofVerifier(
    {"stripe-webhook": verifier(PAYMENT_KEY)}, clock=lambda: NOW
)
acceptor = E.EvidenceAcceptor(
    {"evidence-service": verifier(EVIDENCE_KEY)}, clock=lambda: NOW
)


def evidence(*, registry=None, roots=(), issuer_id="evidence-service", key=EVIDENCE_KEY):
    return E.EvidenceIssuer(
        issuer_id,
        signer(key),
        registry=registry,
        file_roots=roots,
        approval_verifier=approval_verifier,
        payment_verifier=payment_verifier,
        clock=lambda: NOW,
    )


def accepted(claim, issuer=None):
    issuer = issuer or evidence()
    return acceptor.accept(claim, issuer.verify(claim))


class FakeReg:
    def __init__(self, count):
        self.count = count

    def fired_count(self, _key):
        return self.count


# Claim-selected code and paths are data, never execution authority.
tmp_root = tempfile.mkdtemp()
sentinel = os.path.join(tmp_root, "PWNED_%s" % os.getpid())
malicious = Claim(K.CODE_TESTS_PASS, {"test_path": "x; touch %s" % sentinel}, "attacker")
result = evidence(roots=(tmp_root,)).verify(malicious)
decision = acceptor.accept(malicious, result)
ok("RCE: shell-metachar test_path does not execute", not os.path.exists(sentinel))
ok("RCE: malicious test claim is refuted", not decision.accepted and result.truth == Truth.REFUTED)
ok(
    "RCE: arbitrary host path is rejected",
    not accepted(Claim(K.CODE_TESTS_PASS, {"test_path": "C:\\Windows\\win.ini"}, "attacker")).accepted,
)

marker = os.path.join(tmp_root, "EE_EXECUTED_%s" % os.getpid())
script = os.path.join(tmp_root, "test_claim.py")
with open(script, "w", encoding="utf-8") as handle:
    handle.write("open(%r,'w').write('bad')\n" % marker)
test_claim = Claim(K.CODE_TESTS_PASS, {"test_path": script}, "orch")
ok("claim-selected Python is refused", not accepted(test_claim).accepted)
ok("claim-selected Python is never executed", not os.path.exists(marker))

# File access is explicitly rooted and symlink/traversal escapes fail closed.
artifact_dir = tempfile.mkdtemp()
artifact = os.path.join(artifact_dir, "artifact.txt")
with open(artifact, "w", encoding="utf-8") as handle:
    handle.write("hello")
file_claim = Claim(K.FILE_CREATED, {"path": artifact, "sha256": hashlib.sha256(b"hello").hexdigest()}, "orch")
ok("file inside issuer root with recomputed hash is accepted", accepted(file_claim, evidence(roots=(artifact_dir,))).accepted)
ok("same file outside issuer roots is rejected", not accepted(file_claim, evidence(roots=(tmp_root,))).accepted)

outside_dir = tempfile.mkdtemp()
outside_artifact = os.path.join(outside_dir, "outside.txt")
with open(outside_artifact, "wb") as handle:
    handle.write(b"outside-secret")
outside_digest = hashlib.sha256(b"outside-secret").hexdigest()

link_path = os.path.join(artifact_dir, "outside-link.txt")
try:
    os.symlink(outside_artifact, link_path)
    outside_link_rejected = not accepted(
        Claim(K.FILE_CREATED, {"path": link_path, "sha256": outside_digest}, "attacker"),
        evidence(roots=(artifact_dir,)),
    ).accepted
except (OSError, NotImplementedError):
    outside_link_rejected = True
ok("file symlink escaping the trusted root is rejected", outside_link_rejected)

inside_target = os.path.join(artifact_dir, "inside-target.txt")
inside_link = os.path.join(artifact_dir, "inside-link.txt")
with open(inside_target, "wb") as handle:
    handle.write(b"inside-target")
try:
    os.symlink(inside_target, inside_link)
    inside_link_rejected = not accepted(
        Claim(K.FILE_CREATED, {
            "path": inside_link,
            "sha256": hashlib.sha256(b"inside-target").hexdigest(),
        }, "attacker"),
        evidence(roots=(artifact_dir,)),
    ).accepted
except (OSError, NotImplementedError):
    inside_link_rejected = True
ok("file symlink inside the trusted root is still rejected", inside_link_rejected)

oversized = os.path.join(artifact_dir, "oversized.bin")
with open(oversized, "wb") as handle:
    handle.truncate(CORE_E._MAX_FILE_BYTES + 1)
oversized_claim = Claim(K.FILE_CREATED, {
    "path": oversized,
    "sha256": hashlib.sha256(b"").hexdigest(),
}, "attacker")
ok("oversized file evidence fails closed", not accepted(
    oversized_claim, evidence(roots=(artifact_dir,))
).accepted)

# Deterministically swap the leaf after path validation but before descriptor open.
swap_victim = os.path.join(artifact_dir, "swap-victim.txt")
with open(swap_victim, "wb") as handle:
    handle.write(b"safe")
real_os_open = os.open
swap_triggered = False


def swapping_open(path, flags, *args, **kwargs):
    global swap_triggered
    if not swap_triggered and os.path.basename(os.fspath(path)) == os.path.basename(swap_victim):
        swap_triggered = True
        os.unlink(swap_victim)
        os.symlink(outside_artifact, swap_victim)
    return real_os_open(path, flags, *args, **kwargs)


CORE_E.os.open = swapping_open
try:
    swap_claim = Claim(K.FILE_CREATED, {
        "path": swap_victim, "sha256": outside_digest,
    }, "attacker")
    swap_rejected = not accepted(
        swap_claim, evidence(roots=(artifact_dir,))
    ).accepted
finally:
    CORE_E.os.open = real_os_open
ok("check/open symlink swap cannot redirect the descriptor", swap_triggered and swap_rejected)


# Git evidence accepts only a full OID from a direct, link-free .git directory.
GIT = shutil.which("git")


def git_env():
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def git_run(repo, *arguments):
    return subprocess.run(
        [GIT, *arguments], cwd=repo, env=git_env(), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.decode("ascii", "strict").strip()


def make_repo(parent, name, filename="tracked.txt", content=b"tracked"):
    repo = os.path.join(parent, name)
    os.makedirs(repo)
    git_run(repo, "init", "-q")
    git_run(repo, "config", "user.email", "evidence@example.invalid")
    git_run(repo, "config", "user.name", "Evidence Test")
    with open(os.path.join(repo, filename), "wb") as handle:
        handle.write(content)
    git_run(repo, "add", "--", filename)
    git_run(repo, "commit", "-q", "-m", "fixture")
    return repo, git_run(repo, "rev-parse", "HEAD")


if GIT:
    git_root = tempfile.mkdtemp()
    clean_repo, clean_oid = make_repo(git_root, "clean")
    commit_claim = Claim(K.COMMIT_MADE, {
        "repo": clean_repo,
        "sha": clean_oid,
        "expected_paths": ["tracked.txt"],
    }, "orch")
    ok("full commit OID in a direct trusted repository is accepted", accepted(
        commit_claim, evidence(roots=(git_root,))
    ).accepted)

    mutable_ref_claim = Claim(K.COMMIT_MADE, {
        "repo": clean_repo, "sha": "HEAD",
    }, "attacker")
    ok("mutable Git ref is rejected instead of being resolved twice", not accepted(
        mutable_ref_claim, evidence(roots=(git_root,))
    ).accepted)

    outside_git_root = tempfile.mkdtemp()
    outside_repo, outside_oid = make_repo(outside_git_root, "outside")

    gitfile_repo = os.path.join(git_root, "gitfile")
    os.makedirs(gitfile_repo)
    with open(os.path.join(gitfile_repo, ".git"), "w", encoding="utf-8") as handle:
        handle.write("gitdir: " + os.path.join(outside_repo, ".git") + "\n")
    gitfile_claim = Claim(K.COMMIT_MADE, {
        "repo": gitfile_repo, "sha": outside_oid,
    }, "attacker")
    ok("in-root .git file cannot redirect to an outside repository", not accepted(
        gitfile_claim, evidence(roots=(git_root,))
    ).accepted)

    gitlink_repo = os.path.join(git_root, "gitlink")
    os.makedirs(gitlink_repo)
    try:
        os.symlink(
            os.path.join(outside_repo, ".git"),
            os.path.join(gitlink_repo, ".git"),
            target_is_directory=True,
        )
        gitlink_rejected = not accepted(
            Claim(K.COMMIT_MADE, {
                "repo": gitlink_repo, "sha": outside_oid,
            }, "attacker"),
            evidence(roots=(git_root,)),
        ).accepted
    except (OSError, NotImplementedError):
        gitlink_rejected = True
    ok("in-root .git symlink cannot redirect Git evidence", gitlink_rejected)

    alternate_repo, _alternate_oid = make_repo(git_root, "alternate")
    alternates_file = os.path.join(
        alternate_repo, ".git", "objects", "info", "alternates"
    )
    with open(alternates_file, "w", encoding="utf-8") as handle:
        handle.write(os.path.join(outside_repo, ".git", "objects") + "\n")
    alternate_claim = Claim(K.COMMIT_MADE, {
        "repo": alternate_repo, "sha": outside_oid,
    }, "attacker")
    ok("Git objects/info/alternates indirection is rejected", not accepted(
        alternate_claim, evidence(roots=(git_root,))
    ).accepted)

    inherited_repo, _inherited_oid = make_repo(git_root, "inherited", content=b"inherited")
    previous_git_dir = os.environ.get("GIT_DIR")
    os.environ["GIT_DIR"] = os.path.join(outside_repo, ".git")
    try:
        inherited_claim = Claim(K.COMMIT_MADE, {
            "repo": inherited_repo, "sha": outside_oid,
        }, "attacker")
        inherited_rejected = not accepted(
            inherited_claim, evidence(roots=(git_root,))
        ).accepted
    finally:
        if previous_git_dir is None:
            os.environ.pop("GIT_DIR", None)
        else:
            os.environ["GIT_DIR"] = previous_git_dir
    ok("inherited GIT_DIR cannot replace the pinned repository", inherited_rejected)

    prior_stdout_limit = CORE_E._MAX_GIT_STDOUT_BYTES
    CORE_E._MAX_GIT_STDOUT_BYTES = 8
    try:
        overflow_rejected = not accepted(
            commit_claim, evidence(roots=(git_root,))
        ).accepted
    finally:
        CORE_E._MAX_GIT_STDOUT_BYTES = prior_stdout_limit
    ok("oversized Git stdout is killed and fails closed", overflow_rejected)
else:
    ok("Git unavailable: commit evidence remains fail closed", not accepted(
        Claim(K.COMMIT_MADE, {"repo": artifact_dir, "sha": "0" * 40}, "orch"),
        evidence(roots=(artifact_dir,)),
    ).accepted)

# Unsigned, untrusted, forged, stale, and mutated results never cross the acceptor.
forged = VerificationResult(
    "clm-x", K.FILE_CREATED, Truth.VERIFIED, [Check("file_exists", True)],
    claim_digest="x", issuer_id="evidence-service",
)
ok("forgery: unsigned VERIFIED rejected", not acceptor.accept(
    Claim(K.FILE_CREATED, {}, "attacker", claim_id="clm-x"), forged
).accepted)

forged.sig = "deadbeef"
ok("forgery: guessed signature rejected", not acceptor.accept(
    Claim(K.FILE_CREATED, {}, "attacker", claim_id="clm-x"), forged
).accepted)

attacker_issuer = evidence(key=b"attacker-key")
attacker_claim = Claim(K.WORKFLOW_RECOVERED, {"idem_key": "o1"}, "attacker")
ok("same issuer id with wrong key is rejected", not acceptor.accept(
    attacker_claim, attacker_issuer.verify(attacker_claim)
).accepted)

unknown_issuer = evidence(issuer_id="unknown-evidence")
ok("unknown evidence issuer is rejected", not acceptor.accept(
    attacker_claim, unknown_issuer.verify(attacker_claim)
).accepted)

bad_hash_claim = Claim(K.FILE_CREATED, {"path": artifact, "sha256": "WRONG"}, "orch")
tampered = evidence(roots=(artifact_dir,)).verify(bad_hash_claim)
for check in tampered.checks:
    check.passed = True
tampered.truth = Truth.VERIFIED
ok("tampered truth/checks break the result signature", not acceptor.accept(bad_hash_claim, tampered).accepted)

shared = "clm-shared"
source = Claim(K.FILE_CREATED, {"path": artifact, "contains": "hello"}, "orch", claim_id=shared)
source_result = evidence(roots=(artifact_dir,)).verify(source)
target = Claim(
    K.PRODUCT_SUCCESS,
    {"event_type": "payment_intent.succeeded", "amount_cents": 999999},
    "attacker",
    claim_id=shared,
)
ok("result cannot move to another kind/subject", acceptor.accept(source, source_result).accepted and not acceptor.accept(target, source_result).accepted)

changed_assertor = copy.deepcopy(source)
changed_assertor.asserted_by = "attacker"
ok("result binds asserted_by as well as subject", not acceptor.accept(changed_assertor, source_result).accepted)

expired = evidence().verify(attacker_claim, now=NOW - 100, ttl_s=1)
future = evidence().verify(attacker_claim, now=NOW + 10, ttl_s=60)
ok("expired evidence result rejected", not acceptor.accept(attacker_claim, expired).accepted)
ok("future evidence result rejected", not acceptor.accept(attacker_claim, future).accepted)

legacy = E.verify(attacker_claim, registry=FakeReg(1))
ok("legacy unsigned verify result cannot be accepted", not E.accept(attacker_claim, legacy).accepted)
for helper, args in (
    (E.sign_approval, ("statement",)),
    (E.sign_payment, ("pi", 100, "payment_intent.succeeded")),
):
    try:
        helper(*args)
        removed = False
    except RuntimeError:
        removed = True
    ok(f"public {helper.__name__} cannot mint authority", removed)

# Workflow evidence is re-derived only from the registry fixed on the issuer.
workflow = Claim(K.WORKFLOW_RECOVERED, {"idem_key": "o1"}, "orch")
ok("workflow: fixed registry count=1 accepted", accepted(workflow, evidence(registry=FakeReg(1))).accepted)
ok("workflow: fixed registry count=2 rejected", not accepted(workflow, evidence(registry=FakeReg(2))).accepted)
ok("workflow: no registry cannot self-assert", not accepted(workflow).accepted)

# Payment authority is distinct, short-lived, and bound to the exact event body.
payment_id = "pi_123"
amount = 19900
payment_scope = {
    "tenant_id": "tenant-a",
    "merchant_account": "acct-main",
    "customer_id": "pilot-1",
    "currency": "USD",
    "provider": "stripe",
}
payment_token = payment_issuer.issue(
    payment_id, amount, "payment_intent.succeeded", **payment_scope
)
payment_claim = Claim(K.PRODUCT_SUCCESS, {
    "event_type": "payment_intent.succeeded",
    "payment_id": payment_id,
    "amount_cents": amount,
    "payment_token": payment_token,
    **payment_scope,
}, "orch")
ok("trusted payment proof is accepted", accepted(payment_claim).accepted)

for field, value in (
    ("payment_id", "pi_other"), ("amount_cents", amount + 1),
    ("event_type", "charge.succeeded"), ("tenant_id", "tenant-b"),
    ("merchant_account", "acct-evil"), ("customer_id", "pilot-2"),
    ("currency", "EUR"), ("provider", "other-provider"),
):
    changed = copy.deepcopy(payment_claim)
    changed.subject[field] = value
    ok(f"payment proof binds {field}", not accepted(changed).accepted)

for event_type in (
    "checkout.session.completed", "customer.subscription.created",
    "customer.subscription.updated",
):
    claim = Claim(K.PRODUCT_SUCCESS, {
        "event_type": event_type,
        "payment_id": payment_id,
        "amount_cents": amount,
        "payment_token": payment_issuer.issue(
            payment_id, amount, event_type, **payment_scope
        ),
        **payment_scope,
    }, "orch")
    ok(f"'{event_type}' does not prove money", not accepted(claim).accepted)

malformed_amount = Claim(K.PRODUCT_SUCCESS, {
    "event_type": "payment_intent.succeeded", "payment_id": payment_id,
    "amount_cents": "19900", "payment_token": payment_token,
}, "attacker")
ok("malformed payment amount refutes instead of raising", not accepted(malformed_amount).accepted)

expired_payment = payment_issuer.issue(
    payment_id, amount, "payment_intent.succeeded", **payment_scope,
    now=NOW - 100, ttl_s=1
)
expired_claim = copy.deepcopy(payment_claim)
expired_claim.subject["payment_token"] = expired_payment
ok("expired payment proof is rejected", not accepted(expired_claim).accepted)

# Pilot scale gate consumes accepted, scoped, unique customer/payment evidence only.
pilot_ids = [f"pilot-{index}" for index in range(1, 6)]
attestations = []
for index in range(1, 4):
    scoped = {**payment_scope, "customer_id": f"pilot-{index}"}
    pid = f"pi-pilot-{index}"
    token = payment_issuer.issue(pid, amount, "payment_intent.succeeded", **scoped)
    claim = Claim(K.PRODUCT_SUCCESS, {
        "event_type": "payment_intent.succeeded", "payment_id": pid,
        "amount_cents": amount, "payment_token": token, **scoped,
    }, "money-forge")
    attestations.append((claim, evidence().verify(claim)))
pilot_result = E.pilot_gate(
    pilot_ids, attestations, tenant_id="tenant-a", merchant_account="acct-main",
    currency="USD", acceptor=acceptor,
)
ok("pilot gate scales on 5 unique pilots and 3 accepted payments", pilot_result["decision"] == "SCALE")
duplicate_result = E.pilot_gate(
    pilot_ids, [attestations[0]] * 3, tenant_id="tenant-a",
    merchant_account="acct-main", currency="USD", acceptor=acceptor,
)
ok("pilot gate deduplicates customer and payment replay", duplicate_result["decision"] == "HOLD" and duplicate_result["paying"] == 1)
wrong_tenant_result = E.pilot_gate(
    pilot_ids, attestations, tenant_id="tenant-b", merchant_account="acct-main",
    currency="USD", acceptor=acceptor,
)
ok("pilot gate cannot mix tenant payment proofs", wrong_tenant_result["decision"] == "HOLD")

# Approval authority cannot be confused with payment authority.
statement = hashlib.sha256(b"promote fact 42").hexdigest()
approval_token = approval_issuer.issue(statement)
memory_claim = Claim(K.MEMORY_PROMOTED, {
    "promotion_state": "ACTIVE",
    "statement_hash": statement,
    "approval_token": approval_token,
}, "orch")
ok("trusted exact-statement approval is accepted", accepted(memory_claim).accepted)

wrong_statement = copy.deepcopy(memory_claim)
wrong_statement.subject["statement_hash"] = hashlib.sha256(b"other").hexdigest()
ok("approval proof binds exact statement", not accepted(wrong_statement).accepted)

wrong_role = copy.deepcopy(memory_claim)
wrong_role.subject["approval_token"] = payment_token
ok("payment proof cannot serve as approval proof", not accepted(wrong_role).accepted)

continuity = Claim(K.CONTINUITY_PRESERVED, {"model_swap_test_passed": True}, "agent")
ok("claim-supplied continuity boolean is not evidence", not accepted(continuity).accepted)

import sys
print(f"\nTALLY evidence adversarial: PASS={P} FAIL={F}")
sys.exit(1 if F else 0)
