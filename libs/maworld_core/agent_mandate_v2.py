"""Proposal-only AP2 payment mandate verifier.

The verifier fixes user and merchant trust at construction, checks every
signature and exact cart field, and never performs a charge.  Durable payment
idempotency and settlement remain an external Action Authority responsibility.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import threading
import time
from types import MappingProxyType


DOMAIN = b"MAWORLD/AP2/V3\x00"
MAX_CART_BYTES = 64 * 1024
MAX_CART_DEPTH = 8
MAX_CART_NODES = 512
MAX_CART_CONTAINER_ITEMS = 64
MAX_CART_STRING = 4096


def _key(value, name="key"):
    if not isinstance(value, bytes) or len(value) < 16:
        raise ValueError(f"{name} must be at least 16 bytes")
    return value


def _text(value, name, limit=256):
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be bounded non-empty text")
    return value


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _sig(key, kind, body):
    return hmac.new(_key(key), DOMAIN + kind.encode() + b"\x00" + _canonical(body), hashlib.sha256).hexdigest()


def _digest(kind, body):
    return hashlib.sha256(DOMAIN + kind.encode() + b"\x00" + _canonical(body)).hexdigest()


def _validated_cart(cart):
    """Return a detached bounded JSON cart with an explicit payment action."""
    if type(cart) is not dict or not cart:
        raise ValueError("cart must be a non-empty plain object")
    nodes = 0

    def visit(value, depth):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_CART_NODES:
            raise ValueError("cart exceeds node limit")
        if depth > MAX_CART_DEPTH:
            raise ValueError("cart exceeds depth limit")
        if type(value) is dict:
            if len(value) > MAX_CART_CONTAINER_ITEMS:
                raise ValueError("cart object has too many fields")
            for key, child in value.items():
                _text(key, "cart field", 128)
                visit(child, depth + 1)
            return
        if type(value) is list:
            if len(value) > MAX_CART_CONTAINER_ITEMS:
                raise ValueError("cart list has too many items")
            for child in value:
                visit(child, depth + 1)
            return
        if isinstance(value, str):
            if len(value) > MAX_CART_STRING or "\x00" in value:
                raise ValueError("cart string is invalid or too large")
            return
        if value is None or type(value) is bool:
            return
        if type(value) is int:
            if not -(2**63) <= value <= 2**63 - 1:
                raise ValueError("cart integer is outside signed i64 range")
            return
        # Floats are deliberately excluded from a payment contract.  Monetary
        # values and quantities need an explicit integer/fixed-point schema.
        raise ValueError("cart contains a non-canonical JSON value")

    visit(cart, 0)
    action = _text(cart.get("action"), "cart action")
    amount = cart.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("cart amount_cents must be a positive integer")
    encoded = _canonical(cart)
    if len(encoded) > MAX_CART_BYTES:
        raise ValueError("cart exceeds encoded size limit")
    detached = json.loads(encoded)
    # Keep the local names live as explicit schema assertions.
    if detached.get("action") != action or detached.get("amount_cents") != amount:
        raise ValueError("cart canonicalization changed security fields")
    return detached


def _intent_body(intent):
    if not isinstance(intent, dict):
        raise ValueError("signed intent required")
    body = {
        "user": _text(intent.get("user"), "user"),
        "merchant_did": _text(intent.get("merchant_did"), "merchant_did"),
        "allowed_action": _text(intent.get("allowed_action"), "allowed_action"),
        "max_amount_cents": intent.get("max_amount_cents"),
        "exp": intent.get("exp"),
    }
    if (
        isinstance(body["max_amount_cents"], bool)
        or not isinstance(body["max_amount_cents"], int)
        or body["max_amount_cents"] <= 0
        or isinstance(body["exp"], bool)
        or not isinstance(body["exp"], int)
    ):
        raise ValueError("invalid intent bounds")
    return body


def _payment_identifier(intent_digest, cart_digest_value, merchant_did, merchant_nonce):
    return _digest("PAYMENT_IDENTIFIER", {
        "intent_digest": intent_digest,
        "cart_digest": cart_digest_value,
        "merchant_did": merchant_did,
        "merchant_nonce": merchant_nonce,
    })


def canonical_cart(cart: dict) -> str:
    return _canonical(_validated_cart(cart)).decode("utf-8")


def cart_digest(cart: dict) -> str:
    return hashlib.sha256(canonical_cart(cart).encode("utf-8")).hexdigest()


def sign_intent(user_key, user, merchant_did, allowed_action, max_cents, exp):
    if isinstance(max_cents, bool) or not isinstance(max_cents, int) or max_cents <= 0:
        raise ValueError("max_cents must be a positive integer")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(float(exp)):
        raise ValueError("exp must be finite")
    body = {
        "user": _text(user, "user"),
        "merchant_did": _text(merchant_did, "merchant_did"),
        "allowed_action": _text(allowed_action, "allowed_action"),
        "max_amount_cents": max_cents,
        "exp": int(exp),
    }
    return {**body, "sig": _sig(user_key, "INTENT", body)}


def sign_cart(merchant_key, merchant_did, cart: dict, merchant_nonce):
    detached_cart = _validated_cart(cart)
    digest = hashlib.sha256(_canonical(detached_cart)).hexdigest()
    nonce = _text(merchant_nonce, "merchant_nonce", 128)
    body = {
        "merchant_did": _text(merchant_did, "merchant_did"),
        "cart_digest": digest,
        "merchant_nonce": nonce,
    }
    return {
        "merchant_did": body["merchant_did"],
        "cart": detached_cart,
        "cart_digest": digest,
        "merchant_nonce": nonce,
        "sig": _sig(merchant_key, "CART", body),
    }


def make_payment_mandate(user_key, intent, cart_signed, merchant_nonce):
    if type(intent) is not dict or type(cart_signed) is not dict:
        raise ValueError("signed intent and cart required")
    intent = dict(intent)
    cart_signed = dict(cart_signed)
    nonce = _text(merchant_nonce, "merchant_nonce", 128)
    signed_nonce = _text(cart_signed.get("merchant_nonce"), "cart merchant_nonce", 128)
    if not hmac.compare_digest(nonce, signed_nonce):
        raise ValueError("merchant_nonce is not authenticated by signed cart")
    intent_body = _intent_body(intent)
    if not hmac.compare_digest(str(intent.get("sig", "")), _sig(user_key, "INTENT", intent_body)):
        raise ValueError("user intent signature invalid")
    merchant = _text(cart_signed.get("merchant_did"), "merchant_did")
    if merchant != intent_body["merchant_did"]:
        raise ValueError("payee substitution")
    detached_cart = _validated_cart(cart_signed.get("cart"))
    actual_cart_digest = hashlib.sha256(_canonical(detached_cart)).hexdigest()
    if actual_cart_digest != cart_signed.get("cart_digest"):
        raise ValueError("cart payload digest mismatch")
    amount = detached_cart.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise ValueError("cart amount_cents must be a positive integer")
    allowed_action = _text(detached_cart.get("action"), "cart action")
    if allowed_action != intent_body["allowed_action"]:
        raise ValueError("cart action is outside signed user intent")
    intent_digest = _digest("INTENT_LINEAGE", intent_body)
    pid = _payment_identifier(intent_digest, actual_cart_digest, merchant, nonce)
    body = {
        "user": intent_body["user"],
        "merchant_did": merchant,
        "intent_digest": intent_digest,
        "cart_digest": actual_cart_digest,
        "merchant_nonce": nonce,
        "allowed_action": allowed_action,
        "payment_identifier": pid,
        "amount_cents": amount,
    }
    return {**body, "sig": _sig(user_key, "PAYMENT", body)}


class MoneyForgeV2:
    """Fixed verifier that emits an eligible payment proposal, never a charge."""

    def __init__(self, user_key, merchant_keys, *, clock=time.time):
        self.__user_key = _key(user_key, "user_key")
        if not merchant_keys or any(
            not isinstance(merchant, str) or not merchant or not isinstance(key, bytes) or len(key) < 16
            for merchant, key in merchant_keys.items()
        ):
            raise ValueError("fixed merchant verifier map with strong keys required")
        self.__merchant_keys = MappingProxyType(dict(merchant_keys))
        if not callable(clock):
            raise TypeError("fixed clock required")
        self.__clock = clock
        self.__used: set[tuple[str, str, str]] = set()
        self.__lock = threading.Lock()

    def verify(self, intent, cart_signed, pm):
        try:
            if not all(type(value) is dict for value in (intent, cart_signed, pm)):
                raise ValueError("signed mandate objects required")
            intent = dict(intent)
            cart_signed = dict(cart_signed)
            pm = dict(pm)
            merchant = _text(cart_signed.get("merchant_did"), "merchant_did")
            merchant_key = self.__merchant_keys.get(merchant)
            if merchant_key is None:
                raise ValueError("merchant not trusted")
            detached_cart = _validated_cart(cart_signed.get("cart"))
            actual_cart_digest = hashlib.sha256(_canonical(detached_cart)).hexdigest()
            if actual_cart_digest != cart_signed.get("cart_digest"):
                raise ValueError("cart payload digest mismatch")
            merchant_nonce = _text(cart_signed.get("merchant_nonce"), "merchant_nonce", 128)
            cart_body = {
                "merchant_did": merchant,
                "cart_digest": actual_cart_digest,
                "merchant_nonce": merchant_nonce,
            }
            if not hmac.compare_digest(str(cart_signed.get("sig", "")), _sig(merchant_key, "CART", cart_body)):
                raise ValueError("merchant cart signature invalid")

            intent_body = _intent_body(intent)
            if not hmac.compare_digest(str(intent.get("sig", "")), _sig(self.__user_key, "INTENT", intent_body)):
                raise ValueError("user intent signature invalid")
            now = float(self.__clock())
            if not math.isfinite(now) or now >= intent_body["exp"]:
                raise ValueError("intent expired")

            if not (intent_body["merchant_did"] == merchant == pm.get("merchant_did")):
                raise ValueError("payee substitution")
            cart_action = _text(detached_cart.get("action"), "cart action")
            if cart_action != intent_body["allowed_action"]:
                raise ValueError("cart action is outside signed user intent")
            intent_digest = _digest("INTENT_LINEAGE", intent_body)
            if (
                pm.get("user") != intent_body["user"]
                or pm.get("intent_digest") != intent_digest
                or pm.get("cart_digest") != actual_cart_digest
                or pm.get("merchant_nonce") != merchant_nonce
                or pm.get("allowed_action") != cart_action
            ):
                raise ValueError("payment mandate lineage mismatch")
            amount = detached_cart.get("amount_cents")
            if (
                isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0
                or pm.get("amount_cents") != amount
                or amount > intent_body["max_amount_cents"]
            ):
                raise ValueError("amount invalid or exceeds intent cap")
            expected_pid = _payment_identifier(intent_digest, actual_cart_digest, merchant, merchant_nonce)
            payment_identifier = _text(pm.get("payment_identifier"), "payment_identifier", 128)
            if not hmac.compare_digest(payment_identifier, expected_pid):
                raise ValueError("payment_identifier does not match authenticated lineage")
            payment_body = {
                "user": pm.get("user"),
                "merchant_did": pm.get("merchant_did"),
                "intent_digest": pm.get("intent_digest"),
                "cart_digest": pm.get("cart_digest"),
                "merchant_nonce": pm.get("merchant_nonce"),
                "allowed_action": pm.get("allowed_action"),
                "payment_identifier": payment_identifier,
                "amount_cents": pm.get("amount_cents"),
            }
            if not hmac.compare_digest(str(pm.get("sig", "")), _sig(self.__user_key, "PAYMENT", payment_body)):
                raise ValueError("payment mandate signature invalid")
            return {
                "accepted": True,
                "authoritative": False,
                "reason": "verified proposal",
                "merchant_did": merchant,
                "intent_digest": intent_digest,
                "cart_digest": actual_cart_digest,
                "payment_identifier": payment_identifier,
                "allowed_action": cart_action,
            }
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            return {"accepted": False, "authoritative": False, "reason": str(error)}

    def evaluate_payment_proposal(self, intent, cart_signed, pm):
        result = self.verify(intent, cart_signed, pm)
        if not result["accepted"]:
            return result
        # A merchant cannot mint multiple proposals for one authorized intent/cart
        # merely by re-signing the same cart with fresh nonces.
        replay_key = (
            result["merchant_did"], result["intent_digest"], result["cart_digest"]
        )
        with self.__lock:
            if replay_key in self.__used:
                return {"accepted": False, "authoritative": False, "reason": "duplicate_payment_lineage"}
            self.__used.add(replay_key)
        return {
            "accepted": True,
            "status": "ELIGIBLE_PROPOSAL",
            "payment_identifier": result["payment_identifier"],
            "allowed_action": result["allowed_action"],
            "authoritative": False,
            "requires": ["action_authority", "durable_payment_idempotency", "settlement_evidence"],
        }

    def charge(self, *_args, **_kwargs):
        raise TypeError("charge is disabled; use proposal verification plus external Action Authority")
