"""Hermes on cron — put the owner's cron agent to work: arena rounds on a schedule, and the ROUTINE
work that would otherwise burn expensive tokens.

Hermes is already a cron agent (31 of 59 sessions in 30 days, top tool `terminal` at 41%). So we do not
build a scheduler — we hand it declared jobs and govern what comes back.

THE DELEGATION RULE (this is the whole design, and it is not obvious):
    Delegation only saves anything if VERIFYING the result is cheaper than DOING the work.
For deterministic work — run the suite, collect a file, diff two things — verification is an exit code
or a hash: cheap, objective, done. For judgment work — "decide the architecture", "is this claim true" —
verification costs as much as the work, so delegating it saves nothing and adds an untrusted hop. So the
whitelist below contains ONLY cheaply-verifiable work, and it is fail-closed: an unlisted routine is
refused rather than guessed at.

And the invariant survives the trip: whatever Hermes returns is UNTRUSTED. He cannot mark his own work
done — every result comes back as a PROPOSAL carrying evidence the engine re-checks. That is the same
rule as everywhere else in the spine, applied to our own convenience.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from typing import Mapping
from maworld_core.hermes_control import HermesDriver, HermesIntent, HERMES
from maworld_core.arena_ledger import canon_bytes

# routine kind -> (tools it may use, how the ENGINE verifies the result cheaply)
DELEGATABLE = {
    "run_tests":     {"tools": ["terminal"],                "verify": "exit_code+tally", "risk": "MEDIUM"},
    "collect_data":  {"tools": ["terminal", "write_file"],  "verify": "artifact_hash",   "risk": "MEDIUM"},
    "scan_repo":     {"tools": ["search_files", "read_file"],"verify": "artifact_hash",  "risk": "LOW"},
    "fetch_guides":  {"tools": ["terminal", "write_file"],  "verify": "artifact_hash",   "risk": "MEDIUM"},
    "draft_report":  {"tools": ["read_file", "write_file"], "verify": "human_review",    "risk": "LOW"},
    "arena_round":   {"tools": ["execute_code"],            "verify": "engine_settle",   "risk": "MEDIUM"},
}
# never delegate: things where verification costs as much as doing it, or that carry authority
FORBIDDEN = {
    "decide_architecture": "judgment work — verification costs as much as doing it",
    "accept_evidence":     "an agent cannot accept its own work",
    "approve_action":      "authority stays with the spine",
    "spend_money":         "money never leaves the owner's hand",
    "promote_canon":       "canon promotion is separation-of-duties",
    "change_policy":       "policy is not delegable to a proposer",
}

@dataclass
class CronJob:
    name: str
    kind: str
    schedule: str                    # cron expression, e.g. "*/30 * * * *"
    payload: str = ""
    max_cost_usd: float = 0.05
    enabled: bool = True

@dataclass
class JobResult:
    """What Hermes hands back. UNTRUSTED until the engine verifies it."""
    job: str
    artifact: str = ""
    exit_code: int | None = None
    claimed_done: bool = True        # Hermes says it worked — meaningless on its own
    cost_usd: float = 0.0

class HermesCron:
    def __init__(self, driver: HermesDriver, budget_router=None, lane: str = "hermes-routines"):
        self.driver = driver
        self.router = budget_router
        self.lane = lane
        self.jobs: dict[str, CronJob] = {}
        self.results: list[dict] = []

    def schedule(self, job: CronJob) -> dict:
        if job.kind in FORBIDDEN:
            return {"ok": False, "reason": f"NOT DELEGABLE: {job.kind} — {FORBIDDEN[job.kind]}"}
        if job.kind not in DELEGATABLE:
            return {"ok": False, "reason": f"unknown routine '{job.kind}' — fail closed (whitelist only)"}
        self.jobs[job.name] = job
        spec = DELEGATABLE[job.kind]
        return {"ok": True, "job": job.name, "kind": job.kind, "schedule": job.schedule,
                "tools_allowed": spec["tools"], "verified_by": spec["verify"], "risk": spec["risk"],
                "cron_line": f"{job.schedule} hermes run {job.name}"}

    def plan(self, name: str) -> list[dict]:
        """Return exact tool specs for an external gate to authorize."""
        job = self.jobs.get(name)
        if not job or not job.enabled:
            return []
        job_spec = DELEGATABLE[job.kind]
        planned = []
        for tool in job_spec["tools"]:
            intent = HermesIntent(tool, job.payload, f"cron routine {job.kind}")
            action_spec = self.driver.spec_for(intent)
            planned.append({
                "tool": tool,
                "intent": intent,
                "spec": action_spec,
                "spec_hash": action_spec.hash(),
            })
        return planned

    def dispatch(self, name: str, grants: Mapping | None = None) -> dict:
        """Cross the boundary tool by tool using externally issued grants."""
        job = self.jobs.get(name)
        if not job: return {"ok": False, "reason": f"no job {name}"}
        if not job.enabled: return {"ok": False, "reason": f"job {name} disabled"}
        if self.router is not None:
            self.router.charge(self.lane, job.max_cost_usd)      # cap BEFORE the agent runs
        grants = grants or {}
        decisions = []
        for planned in self.plan(name):
            grant = grants.get(planned["spec_hash"])
            if isinstance(grant, tuple) and len(grant) == 2:
                decision, confirmation = grant
            else:
                decision, confirmation = None, None
            r = self.driver.propose(planned["intent"], decision, confirmation)
            decisions.append({
                "tool": planned["tool"],
                "spec_hash": planned["spec_hash"],
                "decision": r["decision"],
                "reason": r.get("reason"),
            })
        allowed = [d for d in decisions if d["decision"] == "ALLOW"]
        return {"ok": len(allowed) == len(decisions), "job": name, "decisions": decisions,
                "note": "tools the spine refused are simply not available to the routine"}

    def verify(self, job_name: str, result: JobResult, expected_hash: str | None = None) -> dict:
        """The engine re-checks. `claimed_done` is evidence, never acceptance."""
        job = self.jobs.get(job_name)
        if not job: return {"accepted": False, "reason": f"no job {job_name}"}
        how = DELEGATABLE[job.kind]["verify"]
        got = hashlib.sha256(canon_bytes({"a": result.artifact})).hexdigest()
        if how == "exit_code+tally":
            accepted = (result.exit_code == 0) and ("FAIL=0" in (result.artifact or ""))
            why = "exit 0 and a zero-fail tally" if accepted else "exit code or tally says otherwise"
        elif how == "artifact_hash":
            accepted = bool(expected_hash) and got == expected_hash
            why = "artifact hash matches the request" if accepted else "artifact hash absent or mismatched"
        elif how == "engine_settle":
            accepted = False; why = "arena results are only real after ArenaSession.settle() by the engine"
        else:  # human_review
            accepted = False; why = "draft requires human review before it means anything"
        rec = {"job": job_name, "kind": job.kind, "verify": how, "claimed_done": result.claimed_done,
               "accepted": accepted, "why": why, "artifact_hash": got, "cost_usd": result.cost_usd,
               "authoritative": False}
        self.results.append(rec)
        return rec

    def savings(self) -> dict:
        """Honest accounting. NOTE (Devil's Advocate, docs/42): the claim "delegation saves tokens" is
        UNPROVEN. The devil flagged it `evidence: assertion, not evidence` and `honesty: positive claim
        with no failure/limit mentioned` — and he was right. This function counts runs and dollars; it
        does NOT measure tokens, and there is no A/B against doing the work directly. Until someone
        measures (tokens to DO the task, vs tokens to VERIFY Hermes' artifact, over N tasks), delegation
        is a hypothesis. What IS proven is the bound: only cheaply-verifiable work is delegable at all."""
        cheap = [r for r in self.results if r["verify"] in ("exit_code+tally", "artifact_hash")]
        won = [r for r in cheap if r["accepted"]]
        return {"routines_run": len(self.results), "cheaply_verifiable": len(cheap),
                "verified_ok": len(won), "spent_usd": round(sum(r["cost_usd"] for r in self.results), 4),
                "token_savings": "UNMEASURED — claim not proven (docs/42, Devil's Advocate)",
                "note": "work whose verification is not cheap was NOT delegated — that saves nothing"}

def arena_cron(schedule: str = "0 */4 * * *", model: str = HERMES["model"], budget: float = 0.25) -> dict:
    """The arena round as a cron line for Hermes' own scheduler. Paper only, live models opt-in."""
    return {"schedule": schedule,
            "command": (f"ARENA_LIVE_MODELS=1 python3 tools/hermes_arena_run.py --live "
                        f"--model {model} --budget {budget} --rounds 3"),
            "arms": ["maworld", "continuityos", "bare"],
            "paper_only": True,
            "requires": "one-use externally signed broker capability + fixed trusted transport",
            "note": "each round emits a scoreboard; the engine settles PnL, never the model"}
