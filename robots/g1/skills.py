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
    def stand_up() -> ActionResult:
        """Command the G1 to stand up from a sitting or lying position."""
        return ActionResult(message=controller.stand_up())

    @mcp.tool()
    def stand_down() -> ActionResult:
        """Command the G1 to sit / lie down from a standing position."""
        return ActionResult(message=controller.stand_down())

    @mcp.tool()
    def move(vx: float, vy: float, vyaw: float) -> ActionResult:
        """Send a continuous velocity command to the G1.

        Args:
            vx:   Forward (+) / backward (-) speed in m/s.
            vy:   Left (+) / right (-) lateral speed in m/s.
            vyaw: Counter-clockwise (+) yaw rate in rad/s.
        """
        return ActionResult(message=controller.move(vx, vy, vyaw))

    @mcp.tool()
    def stop() -> ActionResult:
        """Stop all G1 movement immediately."""
        return ActionResult(message=controller.stop())

    @mcp.tool()
    def balance_stand() -> ActionResult:
        """Switch G1 into a stable balanced standing posture."""
        return ActionResult(message=controller.balance_stand())

    @mcp.tool()
    def damp() -> ActionResult:
        """Put all G1 motors into damping (compliant / low-power) mode. Safe shutdown posture."""
        return ActionResult(message=controller.damp())

    @mcp.tool()
    def wave_hand() -> ActionResult:
        """Command the G1 to wave its hand."""
        return ActionResult(message=controller.wave_hand())

    @mcp.tool()
    def get_imu() -> ImuState:
        """Read IMU state: roll, pitch, yaw (radians) and linear accelerations (m/s²)."""
        result = controller.get_imu()
        if isinstance(result, str):
            raise RuntimeError(result)
        return ImuState(**result)
