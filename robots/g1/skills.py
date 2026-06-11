"""
robots/g1/skills.py
-------------------
G1 humanoid robot skills — minimal set.

Pattern mirrors DimOS's UnitreeG1SkillContainer (dimos/robot/unitree/g1/skill_container.py).
Only core skills:
  - connect/disconnect
  - get_battery

The register(mcp, controller) function is called from robots/g1/blueprint.py.
"""

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.g1.controller import G1Controller


class BatteryState(BaseModel):
    soc_percent: int | None
    voltage_v: float
    current_a: float


class ActionResult(BaseModel):
    message: str


def register(mcp: FastMCP, controller: G1Controller) -> None:
    """Register selected G1 skills onto the MCP server."""

    @mcp.tool()
    def connect() -> ActionResult:
        """Connect to the G1 humanoid robot over DDS."""
        return ActionResult(message=controller.connect())

    @mcp.tool()
    def disconnect() -> ActionResult:
        """Disconnect from the G1 humanoid robot."""
        controller.disconnect()
        return ActionResult(message="Disconnected from G1")

    @mcp.tool()
    def get_battery() -> BatteryState:
        """Get battery state: charge %, voltage, current."""
        result = controller.get_battery()
        if isinstance(result, str):
            raise RuntimeError(result)
        return BatteryState(**result)
