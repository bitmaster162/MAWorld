"""Unified VenueAdapter (Trading Cell). Normalizes an approved OrderIntent (already passed the
deterministic RiskService) into venue-specific submit/cancel/query/reconcile. Idempotency uses a
UUIDv7 client id mapped to each venue's native field (Binance newClientOrderId, Hyperliquid cloid,
Bitunix clientId). Every submit is mediated by the ExternalEffectRegistry (fire-once) so replay
after a crash never double-sends. Backends wrap the OWNER'S existing bots:
  Binance   -> LIVE_TRADING/btcusdt_binance_futures_bot_v7 (BinanceRESTClient/ExecutionGateway)
  Hyperliquid -> cloid-based on-chain order book
  Bitunix   -> continuity_os/04_OUTPUTS/bitunix_* (public WS + REST)
This legacy app adapter is hard-disabled to paper mode.  The canonical
``maworld_core.trading_safety.safe_submit`` is also proposal-only.  Production
venue access requires a separate signed ActionAuthority executor boundary that
is intentionally absent from this repository.
"""
from __future__ import annotations
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class OrderIntent:
    client_order_id: str            # UUIDv7 idempotency key
    instrument: str
    side: str                       # BUY | SELL
    order_type: str                 # MARKET | LIMIT
    quantity_fixed: int             # fixed-point (from RiskService.position_size_fixed)
    price_fixed: int                # 0 for MARKET
    reduce_only: bool = False
    post_only: bool = False


@dataclass
class VenueResult:
    ok: bool
    venue: str
    native_order_id: str | None
    status: str                     # ACCEPTED | REJECTED | DRY_RUN | REPLAYED
    detail: dict = field(default_factory=dict)


class LiveVenueDisabled(RuntimeError):
    pass


class VenueAdapter(ABC):
    name: str = "abstract"
    native_client_id_field: str = "clientOrderId"
    def __init__(self, dry_run: bool = True):
        if dry_run is not True:
            raise LiveVenueDisabled("legacy VenueAdapter live mode is disabled")
        self.dry_run = True

    @abstractmethod
    def _submit(self, intent: OrderIntent) -> VenueResult: ...
    @abstractmethod
    def reconcile(self) -> dict: ...

    def submit(self, intent: OrderIntent, effect_registry=None) -> VenueResult:
        """Idempotent paper submit through the canonical hardened registry."""
        if effect_registry is None:
            return self._submit(intent)
        eff_id = "order-" + intent.client_order_id
        out = effect_registry.execute_once(
            eff_id,
            lambda: self._submit(intent).__dict__,
            system=self.name,
            rev_class="IRREVERSIBLE",
            tenant="legacy-paper",
            action="trading.paper.submit",
            payload=asdict(intent),
        )
        if out["status"] not in {"FIRED", "REPLAYED_NO_REFIRE"}:
            return VenueResult(False, self.name, None, "HOLD", {"registry_status": out["status"]})
        r = out["result"]
        status = "REPLAYED" if out["status"] == "REPLAYED_NO_REFIRE" else r["status"]
        return VenueResult(r["ok"], r["venue"], r.get("native_order_id"), status, r.get("detail", {}))


class BinanceVenue(VenueAdapter):
    name = "binance"; native_client_id_field = "newClientOrderId"
    def __init__(self, client=None, dry_run=True): super().__init__(dry_run); self.client = client
    def _submit(self, intent):
        payload = {"symbol": intent.instrument, "side": intent.side, "type": intent.order_type,
                   "quantity": intent.quantity_fixed, self.native_client_id_field: intent.client_order_id,
                   "reduceOnly": intent.reduce_only}
        return VenueResult(True, self.name, None, "DRY_RUN", {"payload": payload})
    def reconcile(self):
        return {"reconciled": True, "mode": "dry_run"}


class HyperliquidVenue(VenueAdapter):
    name = "hyperliquid"; native_client_id_field = "cloid"
    def __init__(self, client=None, dry_run=True): super().__init__(dry_run); self.client = client
    def _submit(self, intent):
        # Hyperliquid cloid is a 128-bit hex client order id
        cloid = "0x" + uuid.UUID(intent.client_order_id).hex if _is_uuid(intent.client_order_id) else intent.client_order_id
        payload = {"coin": intent.instrument, "is_buy": intent.side == "BUY",
                   "sz": intent.quantity_fixed, "reduce_only": intent.reduce_only, "cloid": cloid}
        return VenueResult(True, self.name, cloid, "DRY_RUN", {"payload": payload})
    def reconcile(self):
        return {"reconciled": True, "mode": "dry_run"}


class BitunixVenue(VenueAdapter):
    name = "bitunix"; native_client_id_field = "clientId"
    def __init__(self, client=None, dry_run=True): super().__init__(dry_run); self.client = client
    def _submit(self, intent):
        payload = {"symbol": intent.instrument, "side": intent.side, "orderType": intent.order_type,
                   "qty": intent.quantity_fixed, self.native_client_id_field: intent.client_order_id,
                   "reduceOnly": intent.reduce_only}
        return VenueResult(True, self.name, None, "DRY_RUN", {"payload": payload})
    def reconcile(self):
        return {"reconciled": True, "mode": "dry_run"}


def _is_uuid(s):
    try: uuid.UUID(s); return True
    except Exception: return False


VENUES = {"binance": BinanceVenue, "hyperliquid": HyperliquidVenue, "bitunix": BitunixVenue}
def make_venue(name, client=None, dry_run=True):
    return VENUES[name](client=client, dry_run=dry_run)
