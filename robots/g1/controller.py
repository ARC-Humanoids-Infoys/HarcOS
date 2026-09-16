"""
robots/g1/controller.py
-----------------------
G1 humanoid robot controller — WebRTC transport.

Connects to the G1's main controller board at 192.168.123.161 using the
unitree_webrtc_connect library (unitree-webrtc-connect-leshy on PyPI),
the same transport used by the Go2 controller.

Connection sequence (DimOS pattern):
  1. WebRTC connect to 192.168.123.161 port 8081
  2. disableTrafficSaving(True)
  3. publish_request_new("rt/api/motion_switcher/request",
                         {"api_id": 1002, "parameter": {"name": "ai"}})
     REQUIRED: switches from Developer mode → AI mode.
     Without this, ALL motion commands are silently ignored.

Motion commands:
  Movement  : "rt/wirelesscontroller"  {"lx": -vy, "ly": vx, "rx": -vyaw, "ry": 0}
              published every 0.05 s for the requested duration, then zeros.
  Arm       : "rt/api/arm/request"     {"api_id": 7106, "parameter": {"data": action_id}}
  Posture   : "rt/api/sport/request"   {"api_id": 7101, "parameter": {"data": fsm_id}}
  Balance   : "rt/api/sport/request"   {"api_id": 7102, "parameter": {"data": balance_mode}}

Network:
  192.168.123.161  Main controller — WebRTC signaling, motion commands
  192.168.123.164  PC4 / Jetson    — SSH only, no motion

Environment:
    G1_ROBOT_IP : Main controller IP (default: 192.168.123.161)
    ROBOT_IP    : Fallback IP env var
"""

import asyncio
import os
import threading
import time

from robots.base import RobotController

from unitree_webrtc_connect.constants import RTC_TOPIC
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection as WebRTCConnection,
    WebRTCConnectionMethod,
)

# ------------------------------------------------------------------
# Arm gesture name → action ID  (DimOS / G1 SDK arm action map)
# ------------------------------------------------------------------
ARM_GESTURES: dict[str, int] = {
    "two_hand_kiss": 11,
    "left_kiss":     12,
    "right_kiss":    13,
    "hands_up":      15,
    "clap":          17,
    "high_five":     18,
    "hug":           19,
    "arm_heart":     20,
    "right_heart":   21,
    "reject":        22,
    "right_hand_up": 23,
    "x_ray":         24,
    "face_wave":     25,
    "high_wave":     26,
    "shake_hand":    27,
    "cancel_action": 99,
    "release_arm":   99,
}

# ------------------------------------------------------------------
# Sport API IDs for rt/api/sport/request
# ------------------------------------------------------------------
_SPORT_SET_FSM = 7101   # set FSM state (posture / locomotion mode)
_SPORT_SET_BAL = 7102   # set balance mode
_ARM_EXECUTE   = 7106   # rt/api/arm/request — execute arm action
_MODE_SWITCH   = 1002   # rt/api/motion_switcher/request — select mode

# FSM state IDs for _SPORT_SET_FSM
_FSM_DAMP     = 1
_FSM_SIT      = 3
_FSM_STAND_UP = 706   # Squat → StandUp
_FSM_WALK     = 500
_FSM_RUN      = 801


class G1Controller(RobotController):
    """G1 humanoid controller via WebRTC (unitree_webrtc_connect_leshy)."""

    def __init__(
        self,
        ip: str | None = None,
        network_interface: str | None = None,  # accepted but unused (WebRTC uses IP)
        **_kwargs,
    ):
        self.ip = ip or os.getenv("G1_ROBOT_IP") or os.getenv("ROBOT_IP", "192.168.123.161")

        self._conn = None
        self._loop = None
        self._thread = None
        self._task = None

        self._connection_ready = threading.Event()
        self._connection_error: str | None = None

        self._latest_low_state: dict | None = None


    # ------------------------------------------------------------------
    # RobotController interface
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> str:
        """Connect to G1 via WebRTC and activate AI mode."""
        self._conn = WebRTCConnection(
            WebRTCConnectionMethod.LocalSTA,
            ip=self.ip,
        )
        self._connection_ready.clear()
        self._connection_error = None
        self._loop = asyncio.new_event_loop()

        async def _async_connect():
            try:
                connect_task = asyncio.create_task(self._conn.connect())
                while not hasattr(self._conn, "video"):
                    if connect_task.done():
                        break
                    await asyncio.sleep(0.01)
                await connect_task

                self._conn.video.switchVideoChannel(True)
                await self._conn.datachannel.disableTrafficSaving(True)
                self._conn.datachannel.set_decoder(decoder_type="native")

                # CRITICAL: switch from Developer → AI mode.
                # Without this, all motion commands are silently ignored.
                await self._conn.datachannel.pub_sub.publish_request_new(
                    "rt/api/motion_switcher/request",
                    {"api_id": _MODE_SWITCH, "parameter": {"name": "ai"}},
                )

                # Subscribe to LOW_STATE for battery / IMU telemetry.
                self._conn.datachannel.pub_sub.subscribe(
                    RTC_TOPIC["LOW_STATE"], self._on_low_state
                )

                self._connection_ready.set()
                while True:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise
            except BaseException as e:
                self._connection_error = f"Connect failed: {e}"
                self._connection_ready.set()
                self._conn = None

        def _start_loop():
            asyncio.set_event_loop(self._loop)
            self._task = self._loop.create_task(_async_connect())
            self._loop.run_forever()

        self._thread = threading.Thread(target=_start_loop, daemon=True)
        self._thread.start()

        connected = self._connection_ready.wait(timeout=15)  # WebRTC takes a few seconds

        if connected:
            if self._connection_error:
                return self._connection_error
            return f"Connected to G1 at {self.ip} (AI mode active)"

        # Timed out — clean up.
        if self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._conn:
            async def _cleanup():
                await self._conn.disconnect()
            try:
                asyncio.run_coroutine_threadsafe(_cleanup(), self._loop).result(timeout=2)
            except Exception:
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._conn = self._loop = self._thread = self._task = None
        return (
            f"Connection timeout to G1 at {self.ip}. "
            "Check: Ethernet cable connected, "
            "IP 192.168.123.100/24 set on enp2s0, "
            "WebRTC port 8081 reachable (robot must be in Sport mode)."
        )


    def disconnect(self) -> None:
        """Cleanly disconnect from G1."""
        if not self._loop or not self._thread:
            self._conn = None
            self._connection_ready.clear()
            return

        if self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)

        if self._conn:
            async def _async_disconnect():
                await self._conn.disconnect()
            try:
                asyncio.run_coroutine_threadsafe(
                    _async_disconnect(), self._loop
                ).result(timeout=3)
            except Exception:
                pass

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

        self._conn = self._loop = self._thread = self._task = None
        self._latest_low_state = None
        self._connection_ready.clear()

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def get_battery(self) -> dict | str:
        """Read battery state from LOW_STATE."""
        state, err = self._require_low_state()
        if err:
            return err
        bms = state.get("bms_state", {})
        return {
            "soc_percent": bms.get("soc"),
            "voltage_v":   round(state.get("power_v", 0.0), 3),
            "current_a":   bms.get("current"),
            "cycle_count": bms.get("cycle"),
        }

    def get_imu(self) -> dict | str:
        """Read IMU state (roll, pitch, yaw, accelerations) from LOW_STATE."""
        state, err = self._require_low_state()
        if err:
            return err
        imu = state.get("imu_state", {})
        rpy = imu.get("rpy", [0.0, 0.0, 0.0])
        acc = imu.get("accelerometer", [0.0, 0.0, 0.0])
        return {
            "roll_rad":  round(rpy[0], 5) if len(rpy) > 0 else 0.0,
            "pitch_rad": round(rpy[1], 5) if len(rpy) > 1 else 0.0,
            "yaw_rad":   round(rpy[2], 5) if len(rpy) > 2 else 0.0,
            "acc_x": round(acc[0], 5) if len(acc) > 0 else 0.0,
            "acc_y": round(acc[1], 5) if len(acc) > 1 else 0.0,
            "acc_z": round(acc[2], 5) if len(acc) > 2 else 0.0,
        }

    # ------------------------------------------------------------------
    # Posture & locomotion
    # ------------------------------------------------------------------

    def _publish_sport(self, api_id: int, data: int) -> str | None:
        """Send a sport API request; returns error string on failure, None on success."""
        err = self._require_connected()
        if err:
            return err

        async def _coro():
            await self._conn.datachannel.pub_sub.publish_request_new(
                "rt/api/sport/request",
                {"api_id": api_id, "parameter": {"data": data}},
            )

        try:
            asyncio.run_coroutine_threadsafe(_coro(), self._loop).result(timeout=5)
            return None
        except Exception as e:
            return f"sport api_id={api_id} data={data} failed: {e}"

    def stand_up(self) -> str:
        return self._publish_sport(_SPORT_SET_FSM, _FSM_STAND_UP) or "Standing up"

    def stand_down(self) -> str:
        return self._publish_sport(_SPORT_SET_FSM, _FSM_SIT) or "Sitting down"

    def balance_stand(self) -> str:
        return self._publish_sport(_SPORT_SET_BAL, 1) or "Balance stand activated"

    def damp(self) -> str:
        return self._publish_sport(_SPORT_SET_FSM, _FSM_DAMP) or "Damping mode activated"

    def move(self, vx: float, vy: float, vyaw: float, duration: float = 2.0) -> str:
        """Send continuous velocity for `duration` seconds via the virtual joystick.

        DimOS coordinate mapping:
            lx = -vy   (strafe: right is negative)
            ly =  vx   (forward: positive)
            rx = -vyaw (yaw: clockwise is negative)
        """
        err = self._require_connected()
        if err:
            return err

        async def _coro():
            t_end = self._loop.time() + duration
            while self._loop.time() < t_end:
                self._conn.datachannel.pub_sub.publish_without_callback(
                    "rt/wirelesscontroller",
                    data={"lx": -vy, "ly": vx, "rx": -vyaw, "ry": 0.0},
                )
                await asyncio.sleep(0.05)
            # Send zeros to stop.
            self._conn.datachannel.pub_sub.publish_without_callback(
                "rt/wirelesscontroller",
                data={"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            )

        try:
            asyncio.run_coroutine_threadsafe(_coro(), self._loop).result(
                timeout=duration + 5
            )
            return f"Moved: vx={vx} vy={vy} vyaw={vyaw} for {duration}s"
        except Exception as e:
            return f"move failed: {e}"

    def stop(self) -> str:
        """Send zero velocity to halt movement."""
        err = self._require_connected()
        if err:
            return err

        async def _coro():
            self._conn.datachannel.pub_sub.publish_without_callback(
                "rt/wirelesscontroller",
                data={"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0},
            )

        try:
            asyncio.run_coroutine_threadsafe(_coro(), self._loop).result(timeout=3)
            return "Stopped"
        except Exception as e:
            return f"stop failed: {e}"

    # ------------------------------------------------------------------
    # Arm gestures  (rt/api/arm/request  api_id=7106)
    # ------------------------------------------------------------------

    def execute_arm_command(self, command_name: str) -> str:
        """Execute a named arm gesture.

        Valid names: high_wave, shake_hand, clap, high_five, hug, hands_up,
                     face_wave, arm_heart, right_heart, reject, right_hand_up,
                     x_ray, two_hand_kiss, left_kiss, right_kiss, cancel_action
        """
        key = command_name.lower().replace(" ", "_").replace("-", "_")
        if key not in ARM_GESTURES:
            return f"Unknown gesture '{command_name}'. Valid: {', '.join(sorted(ARM_GESTURES))}"
        return self._execute_arm_action(ARM_GESTURES[key])

    def _execute_arm_action(self, action_id: int) -> str:
        err = self._require_connected()
        if err:
            return err

        async def _coro():
            await self._conn.datachannel.pub_sub.publish_request_new(
                "rt/api/arm/request",
                {"api_id": _ARM_EXECUTE, "parameter": {"data": action_id}},
            )

        try:
            asyncio.run_coroutine_threadsafe(_coro(), self._loop).result(timeout=5)
            return f"Arm action {action_id} started"
        except Exception as e:
            return f"arm action {action_id} failed: {e}"

    def wave_hand(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["high_wave"])

    def shake_hand(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["shake_hand"])

    def clap(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["clap"])

    def high_five(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["high_five"])

    def hug(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["hug"])

    def hands_up(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["hands_up"])

    def cancel_action(self) -> str:
        return self._execute_arm_action(ARM_GESTURES["cancel_action"])

    # ------------------------------------------------------------------
    # Mode commands  (generic, rt/api/sport/request api_id=7101)
    # ------------------------------------------------------------------

    def execute_mode_command(self, mode_name: str) -> str:
        """Switch locomotion FSM mode by name.

        Valid modes: walk, run, walk_waist, stand_up, stand_down, damp, sit, zero_torque
        """
        modes = {
            "zero_torque": 0,
            "damp":        _FSM_DAMP,
            "sit":         _FSM_SIT,
            "stand_up":    _FSM_STAND_UP,
            "stand_down":  _FSM_SIT,
            "walk":        _FSM_WALK,
            "walk_waist":  501,
            "run":         _FSM_RUN,
        }
        key = mode_name.lower().replace(" ", "_").replace("-", "_")
        if key not in modes:
            return f"Unknown mode '{mode_name}'. Valid: {', '.join(sorted(modes))}"
        return self._publish_sport(_SPORT_SET_FSM, modes[key]) or f"Mode '{mode_name}' activated"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_low_state(self, msg: dict) -> None:
        self._latest_low_state = msg.get("data", {})

    def _require_connected(self) -> str | None:
        if not self._conn:
            return "Not connected. Call connect() first."
        return None

    def _require_low_state(self) -> tuple:
        if not self._conn:
            return None, "Not connected"
        deadline = time.time() + 2.0
        while self._latest_low_state is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_low_state is None:
            return None, "No LOW_STATE data received (check robot is powered on)"
        return self._latest_low_state, None
