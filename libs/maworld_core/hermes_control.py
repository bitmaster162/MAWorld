"""Hermes control — govern the owner's REAL Hermes agent (observed live in Telegram, 2026-07-16).

This is not a guess. Config below was read off the running bot's /reset and /insights output:

  model      nvidia/nemotron-3-ultra-550b-a55b:free   (provider: openrouter, context 1.0M tokens)
  platforms  cron 31 sessions / telegram 22 / tool 4 / cli 2      <-- it is a CRON agent, not a chatbot
  tools      terminal 40.9% · read_file 32.3% · search_files 11.1% · patch 6.7% · execute_code 4.3%
             · write_file 3.2% · cronjob 0.9% · process 0.3%
  30d        59 sessions · 4,498 messages · 2,071 tool calls · ~2.06B tokens · 19-day streak
  commands   /help /new /stop /status /reset /resume /sessions /model /debug /restart /insights
  running    SCFT pipeline (collector+analyzer for BTCUSDT/ETHUSDT/SOLUSDT) — STALE at observation
             time (watchdog: last run 45-60 min vs 32 min threshold)

Why this matters: Hermes' #1 tool is `terminal` (40.9% of 2,071 calls) and it runs unattended on cron.
That is the highest-risk agent shape there is — an autonomous, scheduled, shell-capable LLM. It is
exactly the thing MAWorld exists to govern. So: Hermes PROPOSES, the spine decides.

Two control paths (both real):
  1. operator path  — Telegram bot commands (a human types them). Listed in COMMANDS.
  2. governed path  — we drive the same model over OpenRouter (openrouter_contestant) and route every
     tool-intent it emits through compliance_boundary. Nothing Hermes wants to do reaches a shell
     without a capability, a risk verdict, and (for HIGH) a human.

Live-effects OFF by default. This module never executes a Hermes tool-intent; it only classifies and
gates it, producing a signed receipt either way.
"""
from __future__ import annotations
from dataclasses import dataclass
from maworld_core.action_authority import ActionSpec, Decision, HumanConfirmation
from maworld_core.compliance_boundary import ComplianceBoundary, AgentAction

HERMES = {
    "name": "hermes",
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "provider": "openrouter",
    "context_tokens": 1_000_000,
    "gateway": "OpenClaw-style (session files, V4A patch format, background jobs)",
    "platforms": {"cron": 31, "telegram": 22, "tool": 4, "cli": 2},
    "tool_mix_pct": {"terminal": 40.9, "read_file": 32.3, "search_files": 11.1, "patch": 6.7,
                     "execute_code": 4.3, "write_file": 3.2, "cronjob": 0.9, "process": 0.3},
    "observed_at": "2026-07-16",
    "observed_via": "Telegram /reset + /insights (live)",
}

COMMANDS = {
    "/help": "show available commands", "/new": "new session (fresh id + history)",
    "/stop": "kill all running background processes", "/status": "session, model, token, context info",
    "/reset": "reset session", "/resume": "resume a named session", "/sessions": "browse sessions",
    "/model": "switch model (persists)", "/debug": "upload debug report + shareable links",
    "/restart": "gracefully restart the gateway after draining runs", "/insights": "30-day usage profile",
}
DESTRUCTIVE = {"/stop", "/restart", "/reset", "/new", "/model"}   # never fire without the owner

# Commands that travel THROUGH the gateway and ask it to restart or stop ITSELF. If the gateway does
# not come back, the control channel you used to send the command is gone with it.
#
# LEARNED THE HARD WAY (2026-07-16, docs/43): /status reported `Agent Running: No`, so the risk was
# re-scored as "low — nothing to drain" and /restart was sent. The gateway acknowledged, went down, and
# did not return. Three follow-up commands delivered, zero replies. The danger was never the running
# jobs — it was that the command ORPHANS ITS OWN CONTROL PATH. `Agent Running: No` is not a safety
# signal for these; if anything it means the daemon is already unhealthy and less likely to come back.
#
# Rule: a self-restart command is only safe when an OUT-OF-BAND recovery path exists (host shell,
# systemd, supervisor). Without one, sending it is a one-way door.
SELF_ORPHANING = {"/restart", "/stop"}

class OrphanedControlPath(RuntimeError): pass

# Hermes tool -> risk class in OUR spine. `terminal` is its most-used tool; it is also the classic
# confused-deputy surface, so it can never be LOW.
TOOL_RISK = {
    "terminal": "HIGH", "execute_code": "HIGH", "process": "HIGH", "cronjob": "HIGH",
    "write_file": "MEDIUM", "patch": "MEDIUM",
    "read_file": "LOW", "search_files": "LOW",
}
HIGH_IMPACT_TOOLS = {t for t, r in TOOL_RISK.items() if r == "HIGH"}

@dataclass
class HermesIntent:
    """What Hermes says it wants to do. UNTRUSTED — a model asserting 'I need shell' is not authority."""
    tool: str
    argument: str = ""
    rationale: str = ""
    session: str = "cron"

class HermesDriver:
    """Drive Hermes through the boundary. Every intent gets a signed receipt: ALLOW or DENY."""

    def __init__(self, boundary: ComplianceBoundary, agent_id: str, capability_ref: str = ""):
        self.boundary = boundary
        self.agent_id = agent_id
        self.capability_ref = capability_ref
        self.log: list[dict] = []

    def classify(self, intent: HermesIntent) -> dict:
        risk = TOOL_RISK.get(intent.tool, "HIGH")     # unknown tool -> fail closed at HIGH
        return {"tool": intent.tool, "risk_level": risk,
                "high_impact": intent.tool in HIGH_IMPACT_TOOLS or risk == "HIGH",
                "known_tool": intent.tool in TOOL_RISK}

    def prepare(self, intent: HermesIntent) -> AgentAction:
        """Translate an untrusted model intent into the exact boundary action."""
        if not isinstance(intent, HermesIntent):
            raise TypeError("intent must be HermesIntent")
        c = self.classify(intent)
        return AgentAction(
            agent_id=self.agent_id,
            action=f"hermes.{intent.tool}",
            capability_ref=self.capability_ref,
            risk_level=c["risk_level"],
            payload_text=f"{intent.rationale} {intent.argument}".strip(),
            source="external",                     # model output is untrusted input
            generates_content=False,
            high_impact=c["high_impact"],
        )

    def spec_for(self, intent: HermesIntent) -> ActionSpec:
        """Expose the deterministic spec so an external gate can decide it."""
        return self.boundary.action_spec(self.prepare(intent))

    def propose(
        self,
        intent: HermesIntent,
        decision: Decision | None,
        confirmation: HumanConfirmation | None = None,
    ) -> dict:
        """Hermes proposes; externally signed authority decides."""
        c = self.classify(intent)
        r = self.boundary.cross(self.prepare(intent), decision, confirmation)
        rec = {"intent": intent.tool, "risk": c["risk_level"], "decision": r["decision"],
               "reason": r.get("reason"), "receipt": r}
        self.log.append(rec)
        return rec

    def command_action(self, cmd: str) -> AgentAction:
        """Build the exact governed operator-command action."""
        if cmd not in COMMANDS:
            raise ValueError(f"unknown command {cmd}")
        destructive = cmd in DESTRUCTIVE
        return AgentAction(
            agent_id=self.agent_id,
            action=f"hermes.command.{cmd[1:]}",
            capability_ref=self.capability_ref,
            risk_level="HIGH" if destructive else "LOW",
            payload_text=cmd,
            source="owner",
            high_impact=destructive,
        )

    def command_spec(self, cmd: str) -> ActionSpec:
        return self.boundary.action_spec(self.command_action(cmd))

    def command(
        self,
        cmd: str,
        decision: Decision | None = None,
        confirmation: HumanConfirmation | None = None,
    ) -> dict:
        """Govern commands without trusting owner/recovery booleans.

        Self-orphaning commands stay disabled until a distinct signed recovery
        attestation and verifier exist.
        """
        if cmd not in COMMANDS:
            return {"ok": False, "reason": f"unknown command {cmd}"}
        if cmd in SELF_ORPHANING:
            return {"ok": False, "cmd": cmd,
                    "reason": f"{cmd} travels through the gateway and asks it to restart/stop itself. "
                              f"If it does not come back, this control channel dies with it. A distinct "
                              f"signed OUT-OF-BAND recovery attestation is required but not implemented. "
                              f"'Agent Running: No' does NOT make this safe — it makes it likelier to "
                              f"stay down (docs/43)."}
        receipt = self.boundary.cross(self.command_action(cmd), decision, confirmation)
        return {
            "ok": receipt["decision"] == "ALLOW",
            "cmd": cmd,
            "note": COMMANDS[cmd] if receipt["decision"] == "ALLOW" else None,
            "reason": receipt.get("reason"),
            "receipt": receipt,
        }

    def summary(self) -> dict:
        allowed = [r for r in self.log if r["decision"] == "ALLOW"]
        denied = [r for r in self.log if r["decision"] == "DENY"]
        return {"model": HERMES["model"], "intents": len(self.log),
                "allowed": len(allowed), "denied": len(denied),
                "denied_tools": sorted({r["intent"] for r in denied}),
                "invariant": "Hermes proposes; the deterministic spine decides"}
