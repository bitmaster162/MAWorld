"""Service compatibility entry point for the canonical adversarial suite."""
from __future__ import annotations

import os
import runpy

runpy.run_path(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../tests/test_effect_registry.py")),
    run_name="__main__",
)
