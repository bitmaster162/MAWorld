"""OpenRouter arena proposer using broker-owned secret dispatch.

Live calls are off by default.  A contestant holds one externally issued,
short-lived dispatch capability; it never receives an API key, an enclave key,
or a transport callback.  The capability is checked out once and the broker
dispatches through its fixed trusted transport registry.

Model output remains untrusted and must still pass ``ArenaSession.submit``.
"""
from __future__ import annotations

import json
import math
import os
import re

from maworld_core.arena_bridge import ArenaProposal, assert_paper_only
from maworld_core.budget_router import BudgetRouter
from maworld_core.secrets_broker import SecretScope, SecretsBroker


OPENROUTER_TRANSPORT_ID = "openrouter"
OPENROUTER_OPERATION_ID = "openrouter.chat.completions.create"
OPENROUTER_METHOD = "POST"
OPENROUTER_ENDPOINT_ID = "openrouter.api.v1.chat.completions"
MAX_OPENROUTER_MODEL_CHARS = 200
MAX_OPENROUTER_MESSAGES = 4
MAX_OPENROUTER_MESSAGE_CHARS = 12_000
MAX_OPENROUTER_CONTENT_CHARS = 16_384
MAX_RATIONALE_CHARS = 2_000

_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")


def prepare_openrouter_request(raw: object) -> dict:
    """Validate the only body schema accepted by the fixed chat operation.

    Routing, method, headers and authorization are deliberately absent.  A
    trusted broker-side transport owns those details and receives this bounded
    body inside the broker's reconstructed operation envelope.
    """
    if not isinstance(raw, dict) or set(raw) != {
        "model",
        "messages",
        "temperature",
        "max_tokens",
    }:
        raise ValueError("invalid OpenRouter request schema")
    model = raw.get("model")
    if (
        not isinstance(model, str)
        or len(model) > MAX_OPENROUTER_MODEL_CHARS
        or _MODEL_RE.fullmatch(model) is None
    ):
        raise ValueError("invalid OpenRouter model")
    messages = raw.get("messages")
    if (
        not isinstance(messages, list)
        or not 1 <= len(messages) <= MAX_OPENROUTER_MESSAGES
    ):
        raise ValueError("invalid OpenRouter messages")
    normalized_messages: list[dict[str, str]] = []
    total_chars = 0
    for message in messages:
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise ValueError("invalid OpenRouter message")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user"} or not isinstance(content, str):
            raise ValueError("invalid OpenRouter message")
        total_chars += len(content)
        if (
            len(content) > MAX_OPENROUTER_MESSAGE_CHARS
            or total_chars > MAX_OPENROUTER_MESSAGE_CHARS
        ):
            raise ValueError("OpenRouter prompt exceeds limit")
        normalized_messages.append({"role": role, "content": content})
    temperature = raw.get("temperature")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(float(temperature))
        or not 0 <= float(temperature) <= 2
    ):
        raise ValueError("invalid OpenRouter temperature")
    max_tokens = raw.get("max_tokens")
    if (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or not 1 <= max_tokens <= 1_024
    ):
        raise ValueError("invalid OpenRouter max_tokens")
    return {
        "model": model,
        "messages": normalized_messages,
        "temperature": float(temperature),
        "max_tokens": max_tokens,
    }


class LiveModelsDisabled(RuntimeError):
    pass


class ContestantError(RuntimeError):
    pass


def live_enabled() -> bool:
    """Live model calls require an exact, per-process opt-in."""
    return os.environ.get("ARENA_LIVE_MODELS", "0") == "1"


class OpenRouterContestant:
    """Single-capability external proposer.  It has no transport/key API."""

    LANE = "arena-inference"
    TRANSPORT_ID = OPENROUTER_TRANSPORT_ID
    OPERATION_ID = OPENROUTER_OPERATION_ID
    METHOD = OPENROUTER_METHOD
    ENDPOINT_ID = OPENROUTER_ENDPOINT_ID

    def __init__(
        self,
        agent_id: str,
        model: str,
        broker: SecretsBroker,
        capability: object,
        secret_id: str = "OPENROUTER_API_KEY",
        role: str = "arena-contestant",
        data_class: str = "api_key",
        router: BudgetRouter | None = None,
        est_cost_usd: float = 0.01,
    ):
        if not isinstance(agent_id, str) or not agent_id:
            raise ContestantError("explicit agent_id required")
        if (
            not isinstance(model, str)
            or len(model) > MAX_OPENROUTER_MODEL_CHARS
            or _MODEL_RE.fullmatch(model) is None
        ):
            raise ContestantError("explicit OpenRouter model slug required (no guessing)")
        if not isinstance(broker, SecretsBroker):
            raise ContestantError("explicit configured SecretsBroker required")
        if not isinstance(router, BudgetRouter):
            raise ContestantError("explicit durable BudgetRouter required for external calls")
        self._agent_id = agent_id
        self._model = model
        self._broker = broker
        self._capability = capability
        self._scope = SecretScope(
            subject_id=agent_id,
            secret_id=secret_id,
            role=role,
            data_class=data_class,
            transport_id=self.TRANSPORT_ID,
            operation_id=self.OPERATION_ID,
            method=self.METHOD,
            endpoint_id=self.ENDPOINT_ID,
        )
        self._router = router
        self._est_cost = float(est_cost_usd)
        if not math.isfinite(self._est_cost) or self._est_cost < 0:
            raise ContestantError("estimated cost must be finite and non-negative")

    def __repr__(self) -> str:
        return (
            f"<OpenRouterContestant agent={self._agent_id} "
            f"model={self._model} key=REDACTED>"
        )

    __str__ = __repr__

    def build_prompt(self, snapshot) -> list:
        """Only anonymized OHLCV crosses the external-model boundary."""
        ohlcv = snapshot.ohlcv
        user = (
            "You are a contestant in a PAPER trading arena. No real money moves.\n"
            f"Asset: {snapshot.asset_id}\n"
            f"OHLCV: open={ohlcv[0]} high={ohlcv[1]} low={ohlcv[2]} "
            f"close={ohlcv[3]} volume={ohlcv[4]}\n"
            "Rules: risk_bps must be <= 100 (1%). Reason only from the data above; "
            "you must not name any real ticker or date.\n"
            'Respond ONLY with JSON: {"side":"BUY|SELL|HOLD","qty_fixed":int,'
            '"risk_bps":int,"rationale":"...","claimed_pnl":float}'
        )
        return [
            {"role": "system", "content": "Anonymized paper-trading arena contestant."},
            {"role": "user", "content": user},
        ]

    def propose(self, snapshot) -> ArenaProposal:
        """Use one capability through broker dispatch and parse untrusted output."""
        assert_paper_only()
        if not live_enabled():
            raise LiveModelsDisabled("live model calls are OFF")
        if self._capability is None:
            raise ContestantError("single-use model capability is unavailable")
        capability = self._capability
        self._capability = None
        request_body = {
            "model": self._model,
            "messages": self.build_prompt(snapshot),
            "temperature": 0.7,
            "max_tokens": 400,
        }
        checkout = self._broker.checkout(self._scope, capability, request_body)
        if not checkout.get("ok"):
            raise ContestantError("secret checkout refused")
        # A forged capability cannot burn the caller's budget.  The valid token
        # is consumed before charging; budget still gates the external dispatch.
        self._router.charge(self.LANE, self._est_cost)

        dispatch_failed = False
        try:
            raw = self._broker.dispatch(checkout["reference"])
        except Exception:
            dispatch_failed = True
            raw = None
        if dispatch_failed:
            # Raise outside the handler so no broker exception remains reachable
            # through ``ContestantError.__context__``.
            raise ContestantError("OpenRouter dispatch failed")
        return self._parse(raw)

    def _parse(self, raw: object) -> ArenaProposal:
        """Malformed/missing fields fail closed; model values grant no authority."""
        try:
            content = raw["choices"][0]["message"]["content"]  # type: ignore[index]
        except Exception:
            raise ContestantError("malformed OpenRouter response") from None
        if not isinstance(content, str):
            raise ContestantError("malformed OpenRouter response")
        if (
            len(content) > MAX_OPENROUTER_CONTENT_CHARS
            or len(content.encode("utf-8")) > MAX_OPENROUTER_CONTENT_CHARS
        ):
            raise ContestantError("OpenRouter response content exceeds limit")
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ContestantError("model returned no JSON proposal")
        try:
            data = json.loads(
                match.group(0),
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"invalid constant {value}")
                ),
            )
        except Exception:
            raise ContestantError("model returned invalid JSON") from None
        if not isinstance(data, dict):
            raise ContestantError("model returned invalid proposal")
        allowed_fields = {"side", "qty_fixed", "risk_bps", "rationale", "claimed_pnl"}
        if not set(data).issubset(allowed_fields):
            raise ContestantError("model returned invalid proposal")
        try:
            side_raw = data.get("side", "HOLD")
            quantity_raw = data.get("qty_fixed", 0)
            risk_raw = data.get("risk_bps", 10_000)
            rationale_raw = data.get("rationale", "")
            claimed_raw = data.get("claimed_pnl", 0.0)
            if not isinstance(side_raw, str) or not 1 <= len(side_raw) <= 8:
                raise ValueError
            if (
                isinstance(quantity_raw, bool)
                or not isinstance(quantity_raw, int)
                or abs(quantity_raw) > 9_007_199_254_740_991
            ):
                raise ValueError
            if isinstance(risk_raw, bool) or not isinstance(risk_raw, int):
                raise ValueError
            if (
                not isinstance(rationale_raw, str)
                or len(rationale_raw) > MAX_RATIONALE_CHARS
            ):
                raise ValueError
            if (
                isinstance(claimed_raw, bool)
                or not isinstance(claimed_raw, (int, float))
                or not math.isfinite(float(claimed_raw))
            ):
                raise ValueError
            side = side_raw.upper()
            quantity = quantity_raw
            risk_bps = risk_raw
            rationale = rationale_raw
            claimed_pnl = float(claimed_raw)
        except (TypeError, ValueError, OverflowError):
            raise ContestantError("model returned invalid proposal fields") from None
        return ArenaProposal(
            agent_id=self._agent_id,
            side=side,
            qty_fixed=quantity,
            risk_bps=risk_bps,
            rationale=rationale,
            claimed_pnl=claimed_pnl,
        )
