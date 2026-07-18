from dataclasses import fields

from money_forge_gate import LEGACY_PAYMENT_DISABLED, Evidence, advance


social = Evidence("social_buzz", "x")
ai_signal = Evidence("ai_sentiment", "model")


class ForgedPayment:
    kind = "payment_confirmed"
    verified = True
    source = "caller-controlled"


R = {}
R["legacy Evidence exposes no verified flag"] = "verified" not in {
    item.name for item in fields(Evidence)
}
R["DISCOVER->SCORE remains research-only"] = (
    advance("DISCOVER", "SCORE", [social]).decision == "ADVANCE"
)
R["SCORE->RESEARCH remains research-only"] = (
    advance("SCORE", "RESEARCH", [ai_signal]).decision == "ADVANCE"
)
R["research stage still needs a signal"] = (
    advance("DISCOVER", "SCORE", []).reason == "NEEDS_SOME_EVIDENCE"
)

for name, from_stage, to_stage, supplied in (
    ("soft signals cannot enter PAYMENT", "DISTRIBUTION_TEST", "PAYMENT_TEST", [social]),
    ("forged verified=True cannot enter PAYMENT", "DISTRIBUTION_TEST", "PAYMENT_TEST", [ForgedPayment()]),
    ("legacy input cannot enter RETENTION", "PAYMENT_TEST", "RETENTION_TEST", [ForgedPayment()]),
    ("legacy input cannot enter SCALE", "RETENTION_TEST", "SCALE", [ForgedPayment()]),
):
    result = advance(from_stage, to_stage, supplied)
    R[name] = result.decision == "DENY" and result.reason == LEGACY_PAYMENT_DISABLED

R["no stage skipping"] = advance("DISCOVER", "PAYMENT_TEST", [ForgedPayment()]).reason == "NON_SEQUENTIAL"
R["kill remains explicit"] = advance("PROTOTYPE", "KILL", []).decision == "KILLED"

print("== Money Forge legacy gate (research only) ==")
ok = True
for name, passed in R.items():
    print(("PASS" if passed else "FAIL"), "|", name)
    ok = ok and passed
print("\n" + (f"ALL PASS ({sum(R.values())}/{len(R)})" if ok else "FAIL"))

import sys

sys.exit(0 if ok else 1)
