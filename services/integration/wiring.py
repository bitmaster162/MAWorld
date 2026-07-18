"""Integration wiring harness — verifies MAWorld adapter seams match the OWNER'S real code, so
plugging real clients in is a config change, not a rewrite. Uses AST inspection (no runtime deps
needed) to confirm the required methods exist on each real class, then (optionally) live-imports.

Seams:
  BinanceVenue  needs BinanceRESTClient.{place_order, cancel_order, open_orders}
                  (LIVE_TRADING/btcusdt_binance_futures_bot_v7 .../connectors/rest_client.py)
  money-forge   needs StripeWebhookVerifier.verify_webhook
                  (inner_circle_bot/access_control.py)
  dialectic     needs mind.dialectic.{collect_facts, devil, angel, synthesize}
                  (continuity_os/mind/dialectic.py)
"""
from __future__ import annotations
import ast, os
from dataclasses import dataclass


@dataclass
class Seam:
    name: str
    path: str
    cls: str | None
    required: list
    ok: bool
    missing: list


def _methods_of(path: str, cls: str | None):
    """Return the set of function/method names defined in `cls` (or module-level if cls is None)."""
    if not os.path.exists(path):
        return None
    tree = ast.parse(open(path, encoding="utf-8", errors="ignore").read())
    if cls is None:
        return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            return {b.name for b in node.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return set()


def check_seam(name, path, cls, required) -> Seam:
    have = _methods_of(path, cls)
    if have is None:
        return Seam(name, path, cls, required, False, ["<file not found>"])
    missing = [m for m in required if m not in have]
    return Seam(name, path, cls, required, len(missing) == 0, missing)


def all_seams(projects_root: str) -> list[Seam]:
    p = projects_root
    return [
        check_seam("binance", os.path.join(p, "LIVE_TRADING/btcusdt_binance_futures_bot_v7/src/btcusdt_bot/connectors/rest_client.py"),
                   "BinanceRESTClient", ["place_order", "cancel_order", "open_orders", "query_order"]),
        check_seam("stripe", os.path.join(p, "inner_circle_bot/access_control.py"),
                   "StripeWebhookVerifier", ["verify_webhook"]),
        check_seam("dialectic", os.path.join(p, "continuity_os/mind/dialectic.py"),
                   None, ["collect_facts", "devil", "angel", "synthesize"]),
        check_seam("continuityos_gate", os.path.join(p, "continuityos/continuityos/gate/engine.py"),
                   None, ["preflight"]),
        check_seam("continuityos_ledger", os.path.join(p, "continuityos/continuityos/gate/ledger.py"),
                   "Ledger", ["append", "verify"]),
    ]
