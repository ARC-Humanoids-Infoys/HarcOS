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
from typing import List

from pydantic import BaseModel

from mcp.server.fastmcp import FastMCP

from robots.g1.controller import G1Controller
from robots.rubojudo_adapter import get_adapter


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

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # RoboJuDo policy pipeline tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def start_policy(config_name: str = "g1_harcos") -> ActionResult:
        """Start a trained locomotion or motion policy on the G1.

        This activates RoboJuDo, which runs a learned AI policy at 50 Hz to
        control the robot's walking, running, or expressive motion — much
        smoother and more natural than raw velocity commands.

        Configs for sim (no robot needed):
          g1_harcos        — default walking policy in MuJoCo simulation
          g1_harcos_mimic  — expressive BeyondMimic motion in simulation
          g1_beyondmimic   — BeyondMimic with keyboard control in sim
          g1_asap          — ASAP policy in simulation

        Configs for the real G1 robot:
          g1_harcos_real   — walking policy on the real robot (HarcOS-controlled)
          g1_real          — walking policy on the real robot (joystick-controlled)

        Use list_policies() to see all available configs.

        Args:
            config_name: Which policy config to run (default: g1_harcos for sim).
        """
        adapter = get_adapter()
        msg = await _run_sync(adapter.start, config_name)
        return ActionResult(message=str(msg))

    @mcp.tool()
    async def stop_policy() -> ActionResult:
        """Stop the currently running locomotion or motion policy.

        Call this before switching to a different policy, or when you want
        to return to direct robot commands (stand_up, move, wave, etc.).
        """
        adapter = get_adapter()
        msg = await _run_sync(adapter.stop)
        return ActionResult(message=str(msg))

    @mcp.tool()
    async def policy_status() -> ActionResult:
        """Check whether a locomotion policy is currently running on the G1.

        Returns whether RoboJuDo is available, whether a policy is active,
        and which config (policy name) is running.
        """
        adapter = get_adapter()
        status = adapter.status()
        parts = [
            f"policy_available: {status['robojudo_available']}",
            f"policy_running: {status['pipeline_running']}",
            f"active_policy: {status['current_config'] or 'none'}",
        ]
        return ActionResult(message=", ".join(parts))

    @mcp.tool()
    async def list_policies() -> ActionResult:
        """List all locomotion and motion policies available on this machine.

        Policies starting with g1_ are for the Unitree G1.
        Policies starting with h1_ are for the Unitree H1.
        Policies ending in _real run on the physical robot.
        Others run in MuJoCo simulation (no robot needed).
        """
        adapter = get_adapter()
        configs = await _run_sync(adapter.list_configs)
        if not configs:
            return ActionResult(message="No policies found — is RoboJuDo installed at ~/RoboJuDo?")
        return ActionResult(message="Available policies: " + ", ".join(sorted(configs)))

    @mcp.tool()
    async def walk(forward_speed: float, sideways_speed: float = 0.0, turn_speed: float = 0.0) -> ActionResult:
        """Make the G1 walk using the active locomotion policy.

        Must call start_policy() first (use config g1_harcos for sim,
        g1_harcos_real for the physical robot).

        The policy translates these speed values into smooth, natural
        whole-body walking motion — much more stable than raw motor commands.

        Args:
            forward_speed:  Forward (+) or backward (-) in m/s. Max ±1.0.
                            Example: 0.3 = walk forward, -0.3 = walk backward.
            sideways_speed: Strafe left (+) or right (-) in m/s. Max ±0.5.
                            Example: 0.2 = step left, -0.2 = step right.
            turn_speed:     Rotate left (+) or right (-) in rad/s. Max ±1.0.
                            Example: 0.5 = turn left, -0.5 = turn right.
        """
        adapter = get_adapter()
        msg = await _run_sync(adapter.send_velocity, forward_speed, sideways_speed, turn_speed)
        return ActionResult(message=str(msg))

    @mcp.tool()
    async def policy_command(command: str) -> ActionResult:
        """Send a high-level command to the active locomotion policy.

        Use this to control motion modes, switch between walking and
        expressive motion, or trigger an emergency stop.

        Available commands:
            emergency_stop     — cut power to all motors immediately (SAFETY)
            start_motion       — begin a pre-learned expressive motion sequence
            stop_motion        — fade out the motion and return to normal walking
            reset_motion       — restart the current motion from the beginning
            next_motion        — switch to the next motion in the playlist
            previous_motion    — switch to the previous motion in the playlist

        Args:
            command: One of the command names listed above.
        """
        command_map = {
            "emergency_stop":  "[SHUTDOWN]",
            "start_motion":    "[MOTION_FADE_IN]",
            "stop_motion":     "[MOTION_FADE_OUT]",
            "reset_motion":    "[MOTION_RESET]",
            "next_motion":     "[MOTION_LOAD_NEXT]",
            "previous_motion": "[MOTION_LOAD_PREV]",
        }
        trigger = command_map.get(command)
        if trigger is None:
            valid = ", ".join(command_map.keys())
            return ActionResult(message=f"Unknown command '{command}'. Valid commands: {valid}")
        adapter = get_adapter()
        msg = await _run_sync(adapter.send_trigger, trigger)
        return ActionResult(message=f"Command '{command}' sent. {msg}")

    @mcp.tool()
    async def hold_pose() -> ActionResult:
        """Tell the active locomotion policy to stop moving and hold its current pose.

        Sends zero velocity to the policy — the robot stays exactly where it
        is and the RL policy keeps it balanced without walking anywhere.

        Call this before doing arm gestures while a policy is running, so the
        robot stays still while the gesture plays.

        Requires start_policy() to have been called first.
        """
        adapter = get_adapter()
        msg = await _run_sync(adapter.send_velocity, 0.0, 0.0, 0.0)
        return ActionResult(message="Holding pose — robot stopped. " + str(msg))

    @mcp.tool()
    async def do_gesture(gesture_name: str) -> ActionResult:
        """Safely perform an arm gesture while pausing any active locomotion policy.

        This is the SAFE way to combine arm gestures with RoboJuDo:
          1. Sends zero velocity so the robot holds still
          2. Performs the arm gesture via the G1's built-in gesture API
          3. The policy stays active for balance — just movement is paused

        Available gestures:
            wave          — high wave with one hand
            shake_hand    — handshake gesture
            clap          — clap both hands
            high_five     — high five
            hug           — hug arms open
            hands_up      — raise both hands
            heart         — arm heart shape
            reject        — rejection gesture
            x_ray         — X-ray pose

        Args:
            gesture_name: Name of the gesture from the list above.
        """
        gesture_map = {
            "wave":        controller.wave_hand,
            "shake_hand":  controller.shake_hand,
            "clap":        controller.clap,
            "high_five":   controller.high_five,
            "hug":         controller.hug,
            "hands_up":    controller.hands_up,
            "heart":       lambda: controller.execute_arm_command("arm_heart"),
            "reject":      lambda: controller.execute_arm_command("reject"),
            "x_ray":       lambda: controller.execute_arm_command("x_ray"),
        }
        fn = gesture_map.get(gesture_name)
        if fn is None:
            valid = ", ".join(gesture_map.keys())
            return ActionResult(message=f"Unknown gesture '{gesture_name}'. Valid: {valid}")

        # First send zero velocity so the robot holds still during the gesture
        adapter = get_adapter()
        if adapter.is_running():
            await _run_sync(adapter.send_velocity, 0.0, 0.0, 0.0)

        # Execute the arm gesture via the G1's built-in gesture API
        msg = await _run_sync(fn)
        return ActionResult(message=f"Gesture '{gesture_name}' executed. {msg}")
