"""Adversarial checks for the retired canon-promoter v1 API."""
from __future__ import annotations

import sys

import canon_promoter as legacy


results = {}

# Importing the tombstone must not import or attach to a live ContinuityOS tree.
results["no live ContinuityOS import"] = not any(
    name == "continuityos" or name.startswith("continuityos.")
    for name in sys.modules
)

guard = legacy.GuardedContinuity(memory=object(), db="must-not-open.db")
try:
    guard.add_canon("agent-controlled canon")
    direct_write_denied = False
except legacy.CanonWriteForbidden:
    direct_write_denied = True
results["direct canon write always denied"] = direct_write_denied
results["guard retains no live object"] = guard.__dict__ == {}


class EffectTrap:
    def __init__(self):
        self.calls = 0

    def add_canon(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("legacy promoter reached a materialization effect")


trap = EffectTrap()
promoter = legacy.CanonPromoter(
    trap,
    object(),
    promoter_secret=b"must-not-be-retained",
    human_secret=b"must-not-be-retained",
)
results["promoter retains no secrets or effect objects"] = promoter.__dict__ == {}

try:
    promoter.make_human_approval("candidate")
    approval_mint_denied = False
except legacy.LegacyCanonPromoterDisabled:
    approval_mint_denied = True
results["cannot mint human approval"] = approval_mint_denied

try:
    promoter.promoter_credential()
    credential_mint_denied = False
except legacy.LegacyCanonPromoterDisabled:
    credential_mint_denied = True
results["cannot mint promoter credential"] = credential_mint_denied

try:
    legacy.sign(b"secret", {"role": "canon_promoter"})
    signing_denied = False
except legacy.LegacyCanonPromoterDisabled:
    signing_denied = True
results["legacy signing helper disabled"] = signing_denied

candidate = legacy.CanonCandidate(
    candidate_id="candidate",
    project_id="tenant-a",
    statement="malicious materialized statement",
    source_decision_id="decision",
    source_decision={"decision_id": "decision", "statement": "benign source"},
)
result = promoter.promote(
    candidate,
    evidence_validated=True,
    policy_decision="ALLOW",
    human_approval={"candidate_id": "candidate", "sig": "forged"},
    promoter_credential="forged",
)
results["forged full allow chain still denied"] = (
    result.decision == "DENY_LEGACY_DISABLED"
    and result.reason == legacy.LEGACY_DISABLED_REASON
    and trap.calls == 0
)

print("== Legacy CanonPromoter lockdown ==")
ok = True
for name, passed in results.items():
    print(("PASS" if passed else "FAIL"), "|", name)
    ok = ok and passed
print("\n" + (f"ALL PASS ({sum(results.values())}/{len(results)})" if ok else "FAIL"))
raise SystemExit(0 if ok else 1)
