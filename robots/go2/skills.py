"""
robots/go2/skills.py
--------------------
Go2 robot skills — minimal set for connection, telemetry, and movement.

This mirrors DimOS's UnitreeSkillContainer. Only core skills:
  - connect/disconnect
  - get_battery

The register(mcp, controller) function is called from robots/go2/blueprint.py.
"""

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.go2.controller import Go2Controller


class BatteryState(BaseModel):
    soc_percent: int | None
    voltage_v: float
    current_ma: int | None
    cycle_count: int | None
    bq_ntc_temp_c: list[int] | None = None
    mcu_ntc_temp_c: list[int] | None = None


class ActionResult(BaseModel):
    message: str


def register(mcp: FastMCP, controller: Go2Controller) -> None:
    """Register selected Go2 skills onto the MCP server."""

    @mcp.tool()
    def connect() -> ActionResult:
        """Connect to the Go2 robot over WebRTC."""
        return ActionResult(message=controller.connect())

    @mcp.tool()
    def disconnect() -> ActionResult:
        """Disconnect from the Go2 robot."""
        controller.disconnect()
        return ActionResult(message="Disconnected from Go2")

    @mcp.tool()
    def get_battery() -> BatteryState:
        """Get battery state: charge %, voltage, current, cycle count."""
        result = controller.get_battery()
        if isinstance(result, str):
            raise RuntimeError(result)
        return BatteryState(**result)
