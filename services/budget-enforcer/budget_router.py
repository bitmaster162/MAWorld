"""Fail-closed, durable routing-budget planner.

This service emits only ``ELIGIBLE_PROPOSAL``.  It never authorizes or invokes a
provider.  Policies, prices and provider identities are fixed at construction;
cost is derived from token counts and catalog rates rather than trusted from a
caller estimate; every eligible proposal reserves budget atomically in SQLite.
"""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


PRIORITIES = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
SENSITIVE = {"CONFIDENTIAL", "FINANCIAL_SENSITIVE", "SECRET", "CREDENTIAL"}


@dataclass(frozen=True)
class PriceCatalog:
    rates: Mapping  # {(provider, model): {input, cached, output}} per million tokens
    source: str = "manual_override"
    fetched_at: float = 0.0
    freshness_sla_h: int = 24

    def __post_init__(self):
        if not self.fetched_at:
            object.__setattr__(self, "fetched_at", time.time())


@dataclass(frozen=True)
class RolePolicy:
    role: str
    primary: str
    secondary: str
    monthly_cap_usd: float
    p0_reserve_usd: float
    p1_reserve_usd: float
    prompt_cache: bool = True
    batch_allowed: bool = False
    direct_api_required: bool = False


@dataclass(frozen=True)
class UsageEstimate:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class RouteDecision:
    decision: str  # ELIGIBLE_PROPOSAL | HOLD | DENY
    provider: str | None
    lane: str | None
    use_cache: bool
    use_batch: bool
    reason: str
    reserved_usd: float = 0.0
    authoritative: bool = False


class BudgetRouter:
    def __init__(self, catalog: PriceCatalog, policies: Mapping[str, RolePolicy], db_path: str):
        if not policies or not isinstance(db_path, str) or not db_path:
            raise ValueError("fixed role policies and durable db_path are required")
        rates = {}
        for key, raw in catalog.rates.items():
            if not isinstance(key, tuple) or len(key) != 2 or set(raw) != {"input", "cached", "output"}:
                raise ValueError("catalog rates must be exact provider/model triples")
            converted = {name: float(raw[name]) for name in ("input", "cached", "output")}
            if any(not math.isfinite(v) or v < 0 for v in converted.values()):
                raise ValueError("catalog rates must be finite and non-negative")
            rates[key] = MappingProxyType(converted)
        if not rates:
            raise ValueError("non-empty price catalog required")
        self.catalog = PriceCatalog(
            MappingProxyType(rates), catalog.source, float(catalog.fetched_at), int(catalog.freshness_sla_h)
        )
        fixed = {}
        for role, policy in policies.items():
            if role != policy.role or not role:
                raise ValueError("role policy identity mismatch")
            values = (policy.monthly_cap_usd, policy.p0_reserve_usd, policy.p1_reserve_usd)
            if any(not math.isfinite(float(v)) or float(v) < 0 for v in values):
                raise ValueError("policy budgets must be finite and non-negative")
            if policy.p0_reserve_usd + policy.p1_reserve_usd > policy.monthly_cap_usd:
                raise ValueError("reserves exceed monthly cap")
            self._provider_key(policy.primary)  # validate syntax now
            fixed[role] = policy
        self._policies = MappingProxyType(fixed)
        self.con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS route_reservation("
            "reservation_id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL, "
            "cost REAL NOT NULL, created_at INTEGER NOT NULL)"
        )

    @staticmethod
    def _provider_key(provider: str) -> tuple[str, str]:
        if not isinstance(provider, str) or "/" not in provider:
            raise ValueError("provider must be provider/model")
        namespace, model = provider.split("/", 1)
        if not namespace or not model:
            raise ValueError("provider must be provider/model")
        return namespace, model

    def _is_stale(self, now: float) -> bool:
        return now < self.catalog.fetched_at or (
            now - self.catalog.fetched_at > self.catalog.freshness_sla_h * 3600
        )

    def _cost(self, provider: str, usage: UsageEstimate) -> float:
        if not isinstance(usage, UsageEstimate):
            raise ValueError("typed UsageEstimate required")
        counts = (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in counts):
            raise ValueError("token counts must be non-negative integers")
        if usage.cached_input_tokens > usage.input_tokens:
            raise ValueError("cached input cannot exceed total input")
        rates = self.catalog.rates.get(self._provider_key(provider))
        if rates is None:
            raise ValueError("provider/model price is not pinned")
        uncached = usage.input_tokens - usage.cached_input_tokens
        return (
            uncached * rates["input"]
            + usage.cached_input_tokens * rates["cached"]
            + usage.output_tokens * rates["output"]
        ) / 1_000_000

    def _spent(self, role: str) -> float:
        row = self.con.execute(
            "SELECT COALESCE(SUM(cost),0) FROM route_reservation WHERE role=?", (role,)
        ).fetchone()
        return float(row[0])

    def route(self, role: str, priority: str, data_class: str, usage: UsageEstimate,
              *, now: float | None = None) -> RouteDecision:
        policy = self._policies.get(role)
        if policy is None or priority not in PRIORITIES:
            return RouteDecision("DENY", None, None, False, False, "UNKNOWN_ROLE_OR_PRIORITY")
        current = time.time() if now is None else float(now)
        if not math.isfinite(current) or self._is_stale(current):
            return RouteDecision("HOLD", None, None, False, False, "PRICE_CATALOG_STALE")
        try:
            cost = self._cost(policy.primary, usage)
        except ValueError as exc:
            return RouteDecision("DENY", None, None, False, False, str(exc))
        pr = PRIORITIES[priority]
        self.con.execute("BEGIN IMMEDIATE")
        try:
            spent = self._spent(role)
            if spent + cost > policy.monthly_cap_usd:
                self.con.execute("ROLLBACK")
                return RouteDecision("DENY", None, None, False, False, "OVER_CAP")
            reserve = policy.p0_reserve_usd + policy.p1_reserve_usd
            if pr >= 2 and spent + cost > policy.monthly_cap_usd - reserve:
                self.con.execute("ROLLBACK")
                return RouteDecision("DENY", None, None, False, False, "WOULD_TOUCH_RESERVE")
            self.con.execute(
                "INSERT INTO route_reservation(role,cost,created_at) VALUES(?,?,?)",
                (role, cost, int(current)),
            )
            self.con.execute("COMMIT")
        except Exception:
            if self.con.in_transaction:
                self.con.execute("ROLLBACK")
            raise
        sensitive = data_class in SENSITIVE
        lane = "direct" if policy.direct_api_required or sensitive else "router"
        use_batch = policy.batch_allowed and pr >= 3
        return RouteDecision(
            "ELIGIBLE_PROPOSAL", policy.primary, lane,
            policy.prompt_cache and not use_batch, use_batch, "BUDGET_RESERVED",
            round(cost, 9), False,
        )

    def observe_cost(self, *args, **kwargs):
        raise RuntimeError("caller-reported actual cost is not trusted; ingest signed provider billing evidence")

    def fallback(self, *args, **kwargs) -> RouteDecision:
        return RouteDecision("HOLD", None, None, False, False, "FALLBACK_REQUIRES_NEW_BUDGET_PROPOSAL")

    def close(self):
        self.con.close()
