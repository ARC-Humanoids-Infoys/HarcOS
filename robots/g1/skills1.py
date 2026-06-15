"""
robots/g1/skills1.py
--------------------
G1 humanoid robot skills (extended set).

Registers MCP tools backed by G1Controller1:
- connect
- disconnect
- get_battery
- move_velocity
- stand_up
- lie_down
- get_state
- execute_arm_command
- execute_mode_command
- list_arm_command
- list_mode_command
"""

from __future__ import annotations

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.g1.controller1 import G1Controller


class BatteryState(BaseModel):
    soc_percent: int | None
    voltage_v: float
    current_a: float


class ActionResult(BaseModel):
    message: str


class CommandListResult(BaseModel):
    commands: list[str]


def register(mcp: FastMCP, controller: G1Controller) -> None:
    """Register extended G1 skills onto the MCP server."""

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

    @mcp.tool()
    def move_velocity(
        x: float, y: float = 0.0, yaw: float = 0.0, duration: float = 0.0
    ) -> ActionResult:
        """Move robot with velocity setpoints (x, y, yaw) for duration seconds."""
        return ActionResult(
            message=controller.move_velocity(x=x, y=y, yaw=yaw, duration=duration)
        )

    @mcp.tool()
    def stand_up() -> ActionResult:
        """Command robot to stand up."""
        return ActionResult(message=controller.stand_up())

    @mcp.tool()
    def lie_down() -> ActionResult:
        """Command robot to lie down / return to damp posture."""
        return ActionResult(message=controller.lie_down())

    @mcp.tool()
    def get_state() -> ActionResult:
        """Get robot FSM state."""
        return ActionResult(message=controller.get_state())

    @mcp.tool()
    def execute_arm_command(command_name: str) -> ActionResult:
        """Execute a predefined G1 arm command by name."""
        return ActionResult(message=controller.execute_arm_command(command_name=command_name))

    @mcp.tool()
    def execute_mode_command(command_name: str) -> ActionResult:
        """Execute a predefined G1 locomotion mode command by name."""
        return ActionResult(message=controller.execute_mode_command(command_name=command_name))

    @mcp.tool()
    def list_arm_command() -> CommandListResult:
        """List available predefined G1 arm commands."""
        return CommandListResult(commands=controller.list_arm_command())

    @mcp.tool()
    def list_mode_command() -> CommandListResult:
        """List available predefined G1 locomotion mode commands."""
        return CommandListResult(commands=controller.list_mode_command())
