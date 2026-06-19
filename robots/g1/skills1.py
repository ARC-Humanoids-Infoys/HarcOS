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

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import time

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.g1.controller1 import G1Controller


_SKILL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="g1-skill")
_DEFAULT_SKILL_TIMEOUT_S = 4.0


def _run_with_timeout(
    call_name: str,
    fn,
    timeout_s: float = _DEFAULT_SKILL_TIMEOUT_S,
) -> str:
    """Run potentially blocking controller calls without exceeding MCP client deadlines."""
    started = time.monotonic()
    future = _SKILL_EXECUTOR.submit(fn)
    try:
        result = future.result(timeout=timeout_s)
        elapsed = time.monotonic() - started
        return f"{result} (took {elapsed:.2f}s)"
    except FuturesTimeoutError:
        return (
            f"{call_name} is taking longer than {timeout_s:.1f}s and continues in background. "
            "Use get_state to verify robot status."
        )
    except Exception as e:
        return f"{call_name} failed: {type(e).__name__}: {e}"


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
        return ActionResult(
            message=_run_with_timeout("connect", controller.connect, timeout_s=4.0)
        )

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
        return ActionResult(message=_run_with_timeout(
            "move_velocity",
            lambda: controller.move_velocity(x=x, y=y, yaw=yaw, duration=duration),
        )
        )

    @mcp.tool()
    def stand_up() -> ActionResult:
        """Command robot to stand up."""
        return ActionResult(message=_run_with_timeout("stand_up", controller.stand_up, timeout_s=4.0))

    @mcp.tool()
    def lie_down() -> ActionResult:
        """Command robot to lie down / return to damp posture."""
        return ActionResult(message=_run_with_timeout("lie_down", controller.lie_down))

    @mcp.tool()
    def get_state() -> ActionResult:
        """Get robot FSM state."""
        return ActionResult(message=_run_with_timeout("get_state", controller.get_state, timeout_s=2.0))

    @mcp.tool()
    def execute_arm_command(command_name: str) -> ActionResult:
        """Execute a predefined G1 arm command by name."""
        return ActionResult(message=_run_with_timeout(
            "execute_arm_command",
            lambda: controller.execute_arm_command(command_name=command_name),
        ))

    @mcp.tool()
    def execute_mode_command(command_name: str) -> ActionResult:
        """Execute a predefined G1 locomotion mode command by name."""
        return ActionResult(message=_run_with_timeout(
            "execute_mode_command",
            lambda: controller.execute_mode_command(command_name=command_name),
        ))

    @mcp.tool()
    def list_arm_command() -> CommandListResult:
        """List available predefined G1 arm commands."""
        return CommandListResult(commands=controller.list_arm_command())

    @mcp.tool()
    def list_mode_command() -> CommandListResult:
        """List available predefined G1 locomotion mode commands."""
        return CommandListResult(commands=controller.list_mode_command())
