"""Deprecated Stripe closure; run the scoped external-proof MoneyForge test."""
import os
import runpy
import sys

APP = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(APP, "..", ".."))
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(ROOT, "libs"))
runpy.run_path(os.path.join(APP, "test_money_forge_v2.py"), run_name="__main__")
