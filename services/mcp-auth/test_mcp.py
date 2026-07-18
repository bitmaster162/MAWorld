"""Run the canonical MCP-auth adversarial test against this service shim."""
from pathlib import Path
import runpy


runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "tests" / "test_mcp_auth.py"),
    run_name="__main__",
)
