"""
registry.py
-----------
Blueprint name → build function mapping.

This mirrors DimOS's all_blueprints.py.
Maps CLI robot names to their blueprint build functions.

Usage (from run.py):
    from registry import BLUEPRINTS
    build_fn = BLUEPRINTS["go2"]
    mcp, controller = build_fn()
"""

from robots.go2.blueprint import build_go2
from robots.g1.blueprint import build_g1

# Maps CLI robot name → blueprint build function.
# Each function returns (FastMCP, RobotController).
BLUEPRINTS = {
    "go2": build_go2,
    "g1": build_g1,
}
