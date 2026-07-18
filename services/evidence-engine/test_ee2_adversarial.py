"""Service entry point for the canonical Evidence Engine adversarial suite."""
import os
import runpy
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "libs"))
runpy.run_path(os.path.join(ROOT, "tests", "test_evidence_engine.py"), run_name="__main__")
