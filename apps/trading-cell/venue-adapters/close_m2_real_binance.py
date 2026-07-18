"""Live Binance closure is disabled; run the deterministic dry-run M6 v2 instead."""
import os
import runpy
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "libs"))
runpy.run_path(
    os.path.join(ROOT, "services", "integration", "m6_e2e_v2.py"),
    run_name="__main__",
)
