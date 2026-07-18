"""Unit-safe trading proposal builder.

The Rust RiskService returns quantity in fixed-point (scale 1_000_000). Passing that integer straight
to an exchange means ordering 1,000,000x the intended size. This layer:
  * converts fixed-point -> Decimal -> venue-legal quantity/price honoring lot_size, tick_size, min/max
    (round DOWN to lot multiple; reject below-min; reject non-finite);
  * treats the caller's risk result as untrusted proposal metadata, never as execution authority;
  * never invokes a venue, registry, reconcile callback, or any other effect boundary.

``safe_submit`` is retained as a compatibility name, but it is deliberately proposal-only.  A
production executor must be a separate boundary that verifies an exact signed ActionAuthority
decision with a fixed verifier, consumes a durable nonce, and uses the canonical hardened effect
registry.  That executor is intentionally not implemented here, so caller-constructible values can
never become venue authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, InvalidOperation, localcontext

SCALE = Decimal(1_000_000)   # matches Rust risk-service SCALE
I64_MIN = -(2**63)
I64_MAX = 2**63 - 1
MAX_PRECISION = 18


class UnitError(ValueError):
    pass


class RiskBlocked(RuntimeError):
    pass


def _require_precision(value: object, name: str) -> int:
    # bool is an int subclass and must not silently become precision 0/1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnitError(f"{name} must be an integer")
    if not 0 <= value <= MAX_PRECISION:
        raise UnitError(f"{name} must be between 0 and {MAX_PRECISION}")
    return value


def _require_positive_decimal(value: object, name: str) -> Decimal:
    # Refuse float/string coercion: the venue contract must supply exact Decimal values.
    if not isinstance(value, Decimal):
        raise UnitError(f"{name} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise UnitError(f"{name} must be positive and finite")
    if len(value.as_tuple().digits) > 64:
        raise UnitError(f"{name} has excessive precision")
    return value


def _quantum(precision: int) -> Decimal:
    return Decimal(1).scaleb(-precision)


def _require_precision_fit(value: Decimal, precision: int, name: str) -> None:
    """Require an exact representation at the declared venue precision."""
    try:
        with localcontext() as ctx:
            ctx.prec = 80
            quantized = value.quantize(_quantum(precision), rounding=ROUND_DOWN)
    except InvalidOperation as exc:
        raise UnitError(f"{name} is incompatible with precision {precision}") from exc
    if quantized != value:
        raise UnitError(f"{name} is incompatible with precision {precision}")


def _require_step_multiple(value: Decimal, step: Decimal, name: str) -> None:
    try:
        with localcontext() as ctx:
            ctx.prec = 80
            remainder = value % step
    except InvalidOperation as exc:
        raise UnitError(f"{name} is incompatible with lot_size") from exc
    if remainder != 0:
        raise UnitError(f"{name} must be an exact multiple of lot_size")


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    qty_precision: int
    price_precision: int
    lot_size: Decimal        # min increment of quantity
    tick_size: Decimal       # min increment of price
    min_qty: Decimal
    max_qty: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip() or len(self.symbol) > 128:
            raise UnitError("symbol must be a non-empty string of at most 128 characters")

        qty_precision = _require_precision(self.qty_precision, "qty_precision")
        price_precision = _require_precision(self.price_precision, "price_precision")
        lot_size = _require_positive_decimal(self.lot_size, "lot_size")
        tick_size = _require_positive_decimal(self.tick_size, "tick_size")
        min_qty = _require_positive_decimal(self.min_qty, "min_qty")
        max_qty = _require_positive_decimal(self.max_qty, "max_qty")

        _require_precision_fit(lot_size, qty_precision, "lot_size")
        _require_precision_fit(tick_size, price_precision, "tick_size")
        _require_precision_fit(min_qty, qty_precision, "min_qty")
        _require_precision_fit(max_qty, qty_precision, "max_qty")
        _require_step_multiple(min_qty, lot_size, "min_qty")
        _require_step_multiple(max_qty, lot_size, "max_qty")
        if min_qty > max_qty:
            raise UnitError("min_qty must not exceed max_qty")


@dataclass(frozen=True)
class RiskDecision:
    """Untrusted risk assessment supplied by a proposer; never execution authority."""
    kind: str                # ALLOW | REDUCE_ONLY | DENY (proposal classification only)
    risk_bps: int = 0
    reason: str = ""


def _require_fixed(value: object, name: str, *, allow_zero: bool) -> int:
    # The upstream ABI is a Rust i64.  Reject bool, arbitrary precision Python ints,
    # floats and Decimal values before doing any arithmetic.
    if isinstance(value, bool) or not isinstance(value, int):
        raise UnitError(f"{name} must be an i64 fixed-point integer")
    if value < I64_MIN or value > I64_MAX:
        raise UnitError(f"{name} is outside the signed i64 range")
    if value < 0 or (value == 0 and not allow_zero):
        qualifier = "negative" if allow_zero else "non-positive"
        raise UnitError(f"{qualifier} {name}")
    return value


def _round_down_to_step(raw: Decimal, step: Decimal, precision: int, name: str) -> Decimal:
    """Floor a positive value to a venue step without ever increasing it."""
    quantum = _quantum(precision)
    try:
        with localcontext() as ctx:
            # i64/SCALE plus an 18-place venue step needs fewer than 40 digits;
            # leave ample room so the division itself cannot round the quotient up.
            ctx.prec = 80
            units = (raw / step).to_integral_value(rounding=ROUND_DOWN)
            rounded = (units * step).quantize(quantum, rounding=ROUND_DOWN)
            remainder = rounded % step
    except InvalidOperation as exc:
        raise UnitError(f"invalid {name} normalization") from exc
    if not rounded.is_finite() or rounded < 0 or rounded > raw:
        raise UnitError(f"unsafe {name} normalization")
    if remainder != 0:
        raise UnitError(f"{name} normalization violates the venue step")
    return rounded


def fixed_to_qty(qty_fixed: int, spec: InstrumentSpec) -> Decimal:
    """i64 fixed-point (scale 1e6) -> venue-legal Decimal quantity. Rounds DOWN to lot_size."""
    if not isinstance(spec, InstrumentSpec):
        raise UnitError("spec must be an InstrumentSpec")
    fixed = _require_fixed(qty_fixed, "quantity", allow_zero=False)
    raw = Decimal(fixed) / SCALE
    q = _round_down_to_step(raw, spec.lot_size, spec.qty_precision, "quantity")
    if q <= 0:
        raise UnitError("quantity rounds to zero")
    if q < spec.min_qty:
        raise UnitError(f"quantity {q} below min_qty {spec.min_qty}")
    if q > spec.max_qty:
        raise UnitError(f"quantity {q} above max_qty {spec.max_qty}")
    return q


def fixed_to_price(price_fixed: int, spec: InstrumentSpec) -> Decimal:
    if not isinstance(spec, InstrumentSpec):
        raise UnitError("spec must be an InstrumentSpec")
    fixed = _require_fixed(price_fixed, "price", allow_zero=True)
    if fixed == 0:
        return Decimal(0)  # MARKET
    raw = Decimal(fixed) / SCALE
    price = _round_down_to_step(raw, spec.tick_size, spec.price_precision, "price")
    if price <= 0:
        # Never let a positive limit price silently become the MARKET sentinel.
        raise UnitError("positive price rounds to zero")
    return price


def safe_submit(venue, intent, risk: RiskDecision, spec: InstrumentSpec,
                effect_registry=None, reconcile=None, *, tenant=None):
    """Build a unit-safe order proposal and perform no external effect.

    The legacy arguments ``venue``, ``effect_registry``, ``reconcile`` and ``tenant`` remain accepted
    so old paper/demo callers fail safe during migration.  They are intentionally never inspected or
    invoked.  In particular, a caller-created ``RiskDecision("ALLOW")`` can at most produce this
    non-authoritative proposal.
    """
    if not isinstance(risk, RiskDecision) or risk.kind != "ALLOW":
        raise RiskBlocked(
            "proposal requires an ALLOW risk assessment, got "
            f"{getattr(risk, 'kind', risk)}"
        )
    qty = fixed_to_qty(intent.quantity_fixed, spec)          # <-- the fix: real units, not raw int
    price = fixed_to_price(getattr(intent, "price_fixed", 0), spec)
    payload = {"symbol": spec.symbol, "qty": str(qty), "price": str(price),
               "cid": intent.client_order_id, "risk_bps": risk.risk_bps}
    return {
        "status": "PROPOSED",
        "submitted": False,
        "authoritative": False,
        "payload": payload,
        "qty_decimal": str(qty),
        "requires": "separate signed ActionAuthority executor boundary",
    }
