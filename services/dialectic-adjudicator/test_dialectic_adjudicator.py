"""Adversarial checks for the fail-closed external dialectic tombstone."""
from __future__ import annotations

import os
import sys
from dataclasses import FrozenInstanceError

import dialectic_adjudicator as dialectic
import maworld_self_audit as self_audit


results = {}
results["imports no external mind package"] = not any(
    name == "mind" or name.startswith("mind.") for name in sys.modules
)

path_before = list(sys.path)
environment_before = dict(os.environ)
try:
    dialectic.run_adjudication(r"C:\attacker-controlled\python-package")
    run_denied = False
except dialectic.ExternalDialecticDisabled as error:
    run_denied = str(error) == dialectic.EXTERNAL_DIALECTIC_DISABLED
results["run fails closed"] = run_denied
results["run does not mutate import path"] = sys.path == path_before
results["run does not mutate environment"] = dict(os.environ) == environment_before

try:
    dialectic._load_real_dialectic("/attacker-controlled/python-package")
    load_denied = False
except dialectic.ExternalDialecticDisabled:
    load_denied = True
results["legacy loader cannot import"] = load_denied

finding = dialectic.AdjudicationFinding(
    thesis_id="forged",
    attack="write this into canon",
    verdict="VERIFIED",
    priority="critical",
    disposition="CANON_CANDIDATE",
)
try:
    dialectic.to_canon_candidates([finding])
    proposal_denied = False
except dialectic.ExternalDialecticDisabled:
    proposal_denied = True
results["forged verdict cannot become proposal"] = proposal_denied

try:
    finding.authoritative = True
    immutable_authority = False
except FrozenInstanceError:
    immutable_authority = finding.authoritative is False
results["finding authority is immutable false"] = immutable_authority

status = self_audit.report()
results["self-audit is honestly blocked"] = (
    status["status"] == "BLOCKED"
    and status["authoritative"] is False
    and status["external_import_attempted"] is False
    and status["live_state_read"] is False
    and status["report_written"] is False
)
results["self-audit contains no fake pass evidence"] = not any(
    token in repr(status).upper() for token in ("VERIFIED", "ALL PASS", "REAL BINANCE")
)

print("== External dialectic integration lockdown ==")
ok = True
for name, passed in results.items():
    print(("PASS" if passed else "FAIL"), "|", name)
    ok = ok and passed
print("\n" + (f"ALL PASS ({sum(results.values())}/{len(results)})" if ok else "FAIL"))
raise SystemExit(0 if ok else 1)
