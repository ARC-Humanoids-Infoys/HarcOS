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
    loop = asyncio.get_running_loop()  # get_event_loop() is broken in Python 3.12+
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


class BatteryState(BaseModel):
    soc_percent: int | None
    voltage_v: float
    current_a: float | None
    cycle_count: int | None = None


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
    async def move(vx: float, vy: float, vyaw: float, duration: float = 2.0) -> ActionResult:
        """Send a continuous velocity command to the G1.

        Args:
            vx:       Forward (+) / backward (-) speed in m/s.
            vy:       Left (+) / right (-) lateral speed in m/s.
            vyaw:     Counter-clockwise (+) yaw rate in rad/s.
            duration: How long to move in seconds (default: 2.0).
        """
        msg = await _run_sync(controller.move, vx, vy, vyaw, duration)
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
        """Command the G1 to perform a high wave gesture."""
        msg = await _run_sync(controller.wave_hand)
        return ActionResult(message=msg)

    @mcp.tool()
    async def shake_hand() -> ActionResult:
        """Command the G1 to offer a handshake."""
        msg = await _run_sync(controller.shake_hand)
        return ActionResult(message=msg)

    @mcp.tool()
    async def clap() -> ActionResult:
        """Command the G1 to clap its hands."""
        msg = await _run_sync(controller.clap)
        return ActionResult(message=msg)

    @mcp.tool()
    async def high_five() -> ActionResult:
        """Command the G1 to give a high five."""
        msg = await _run_sync(controller.high_five)
        return ActionResult(message=msg)

    @mcp.tool()
    async def hug() -> ActionResult:
        """Command the G1 to give a hug."""
        msg = await _run_sync(controller.hug)
        return ActionResult(message=msg)

    @mcp.tool()
    async def hands_up() -> ActionResult:
        """Command the G1 to raise both hands."""
        msg = await _run_sync(controller.hands_up)
        return ActionResult(message=msg)

    @mcp.tool()
    async def cancel_action() -> ActionResult:
        """Cancel any ongoing arm gesture and return arms to default position."""
        msg = await _run_sync(controller.cancel_action)
        return ActionResult(message=msg)

    @mcp.tool()
    async def execute_arm_command(command_name: str) -> ActionResult:
        """Execute a named arm gesture.

        Valid names: high_wave, shake_hand, clap, high_five, hug, hands_up,
                     face_wave, arm_heart, right_heart, reject, right_hand_up,
                     x_ray, two_hand_kiss, left_kiss, right_kiss, cancel_action
        """
        msg = await _run_sync(controller.execute_arm_command, command_name)
        return ActionResult(message=msg)

    @mcp.tool()
    async def execute_mode_command(mode_name: str) -> ActionResult:
        """Switch G1 locomotion FSM mode by name.

        Valid modes: walk, run, walk_waist, stand_up, stand_down, damp, sit, zero_torque
        """
        msg = await _run_sync(controller.execute_mode_command, mode_name)
        return ActionResult(message=msg)

    @mcp.tool()
    async def get_imu() -> ImuState:
        """Read IMU state: roll, pitch, yaw (radians) and linear accelerations (m/s²)."""
        result = await _run_sync(controller.get_imu)
        if isinstance(result, str):
            raise RuntimeError(result)
        return ImuState(**result)
