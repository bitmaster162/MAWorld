"""AsyncTaskRegistry — orphan-poll ban + full canonical state machine (v1.4 §5.2, DR2 0x0E).

Binds every MCP task to (action_spec_id, delegation_grant_id, trace_id, task_external_id) at
creation and denies any poll/result whose binding does not match. Enforces the canonical task
lifecycle so a task cannot skip verification or re-open a terminal state.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

# canonical states (v1.4 §5.2)
STATES = ["CREATED","RUNNING","INPUT_REQUIRED","RESULT_READY","RESULT_FETCHED","VERIFIED",
          "COMPLETED","FAILED","EXPIRED","CANCELLED"]
TERMINAL = {"COMPLETED","FAILED","EXPIRED","CANCELLED"}
# allowed forward transitions
_ALLOWED = {
    "CREATED": {"RUNNING","FAILED","CANCELLED","EXPIRED"},
    "RUNNING": {"INPUT_REQUIRED","RESULT_READY","FAILED","CANCELLED","EXPIRED"},
    "INPUT_REQUIRED": {"RUNNING","FAILED","CANCELLED","EXPIRED"},
    "RESULT_READY": {"RESULT_FETCHED","FAILED","CANCELLED","EXPIRED"},
    "RESULT_FETCHED": {"VERIFIED","FAILED","CANCELLED"},
    "VERIFIED": {"COMPLETED","FAILED"},
}


@dataclass(frozen=True)
class TaskBinding:
    action_spec_id: str
    delegation_grant_id: str
    trace_id: str
    task_external_id: str


@dataclass
class _Rec:
    binding: TaskBinding
    state: str = "CREATED"
    created_at: float = field(default_factory=time.time)


class AsyncTaskRegistry:
    def __init__(self):
        self._t: dict[str, _Rec] = {}

    def register(self, b: TaskBinding) -> None:
        if b.task_external_id in self._t:
            raise ValueError("task already registered")
        self._t[b.task_external_id] = _Rec(binding=b)

    def _match(self, p: TaskBinding):
        r = self._t.get(p.task_external_id)
        if r is None:
            return None, "ORPHAN_TASK_UNKNOWN_HANDLE"
        b = r.binding
        if (p.action_spec_id != b.action_spec_id or p.delegation_grant_id != b.delegation_grant_id
                or p.trace_id != b.trace_id):
            return None, "AUTHORITY_BINDING_MISMATCH"
        return r, "OK"

    def poll(self, p: TaskBinding):
        r, reason = self._match(p)
        return ("ALLOW", "OK") if r else ("DENY", reason)

    def transition(self, p: TaskBinding, new_state: str):
        """Advance a task's state ONLY if binding matches and the transition is legal."""
        r, reason = self._match(p)
        if r is None:
            return "DENY", reason
        if new_state not in STATES:
            return "DENY", "UNKNOWN_STATE"
        if r.state in TERMINAL:
            return "DENY", "TERMINAL_STATE_%s" % r.state
        if new_state not in _ALLOWED.get(r.state, set()):
            return "DENY", "ILLEGAL_TRANSITION_%s_TO_%s" % (r.state, new_state)
        r.state = new_state
        return "ALLOW", r.state

    def state(self, task_external_id: str):
        r = self._t.get(task_external_id)
        return r.state if r else None
