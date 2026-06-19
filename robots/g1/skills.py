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

import asyncio
from functools import partial

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.g1.controller import G1Controller


def _run_sync(fn, *args, **kwargs):
    """Run a blocking controller method in a thread pool so it does not block
    the asyncio event loop (prevents MCP -32001 Request timed out errors)."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


class BatteryState(BaseModel):
    soc_percent: int | None
    voltage_v: float
    current_a: float


class ImuState(BaseModel):
    roll_rad: float
    pitch_rad: float
    yaw_rad: float
    acc_x: float
    acc_y: float
    acc_z: float


class ActionResult(BaseModel):
    message: str


def register(mcp: FastMCP, controller: G1Controller) -> None:
    """Register selected G1 skills onto the MCP server."""

    @mcp.tool()
    async def connect() -> ActionResult:
        """Connect to the G1 humanoid robot over DDS."""
        msg = await _run_sync(controller.connect)
        return ActionResult(message=msg)

    @mcp.tool()
    async def disconnect() -> ActionResult:
        """Disconnect from the G1 humanoid robot."""
        await _run_sync(controller.disconnect)
        return ActionResult(message="Disconnected from G1")

    @mcp.tool()
    async def get_battery() -> BatteryState:
        """Get battery state: charge %, voltage, current."""
        result = await _run_sync(controller.get_battery)
        if isinstance(result, str):
            raise RuntimeError(result)
        return BatteryState(**result)

    @mcp.tool()
    async def stand_up() -> ActionResult:
        """Command the G1 to stand up from a sitting or lying position."""
        msg = await _run_sync(controller.stand_up)
        return ActionResult(message=msg)

    @mcp.tool()
    async def stand_down() -> ActionResult:
        """Command the G1 to sit / lie down from a standing position."""
        msg = await _run_sync(controller.stand_down)
        return ActionResult(message=msg)

    @mcp.tool()
    async def move(vx: float, vy: float, vyaw: float) -> ActionResult:
        """Send a continuous velocity command to the G1.

        Args:
            vx:   Forward (+) / backward (-) speed in m/s.
            vy:   Left (+) / right (-) lateral speed in m/s.
            vyaw: Counter-clockwise (+) yaw rate in rad/s.
        """
        msg = await _run_sync(controller.move, vx, vy, vyaw)
        return ActionResult(message=msg)

    @mcp.tool()
    async def stop() -> ActionResult:
        """Stop all G1 movement immediately."""
        msg = await _run_sync(controller.stop)
        return ActionResult(message=msg)

    @mcp.tool()
    async def balance_stand() -> ActionResult:
        """Switch G1 into a stable balanced standing posture."""
        msg = await _run_sync(controller.balance_stand)
        return ActionResult(message=msg)

    @mcp.tool()
    async def damp() -> ActionResult:
        """Put all G1 motors into damping (compliant / low-power) mode. Safe shutdown posture."""
        msg = await _run_sync(controller.damp)
        return ActionResult(message=msg)

    @mcp.tool()
    async def wave_hand() -> ActionResult:
        """Command the G1 to wave its hand."""
        msg = await _run_sync(controller.wave_hand)
        return ActionResult(message=msg)

    @mcp.tool()
    async def get_imu() -> ImuState:
        """Read IMU state: roll, pitch, yaw (radians) and linear accelerations (m/s²)."""
        result = await _run_sync(controller.get_imu)
        if isinstance(result, str):
            raise RuntimeError(result)
        return ImuState(**result)
