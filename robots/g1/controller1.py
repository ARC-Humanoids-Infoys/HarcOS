"""
robots/g1/controller1.py
------------------------
G1 humanoid robot controller (extended tool surface).

This module mirrors the existing robots/g1/controller.py style but adds
higher-level control methods inspired by DimOS G1 DDS SDK modules:
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

import difflib
from enum import IntEnum
import json
import os
import socket
import threading
import time
import traceback
from typing import Any

from robots.base import RobotController


class FsmState(IntEnum):
    ZERO_TORQUE = 0
    DAMP = 1
    SIT = 3
    AI_MODE = 200
    LIE_TO_STANDUP = 702
    SQUAT_STANDUP_TOGGLE = 706


LOCO_API_IDS: dict[str, int] = {
    "GET_FSM_ID": 7100,
    "GET_FSM_MODE": 7101,
    "GET_BALANCE_MODE": 7102,
}

ARM_API_ID = 7106
MODE_API_ID = 7101
ARM_TOPIC = "rt/api/arm/request"
MODE_TOPIC = "rt/api/sport/request"

ARM_COMMANDS: dict[str, tuple[int, str]] = {
    "Handshake": (27, "Perform a handshake gesture with the right hand."),
    "HighFive": (18, "Give a high five with the right hand."),
    "Hug": (19, "Perform a hugging gesture with both arms."),
    "HighWave": (26, "Wave with the hand raised high."),
    "Clap": (17, "Clap hands together."),
    "FaceWave": (25, "Wave near the face level."),
    "LeftKiss": (12, "Blow a kiss with the left hand."),
    "ArmHeart": (20, "Make a heart shape with both arms overhead."),
    "RightHeart": (21, "Make a heart gesture with the right hand."),
    "HandsUp": (15, "Raise both hands up in the air."),
    "XRay": (24, "Hold arms in an X-ray pose position."),
    "RightHandUp": (23, "Raise only the right hand up."),
    "Reject": (22, "Make a rejection or 'no' gesture."),
    "CancelAction": (99, "Cancel any current arm action and return neutral."),
}

MODE_COMMANDS: dict[str, tuple[int, str]] = {
    "WalkMode": (500, "Switch to normal walking mode."),
    "WalkControlWaist": (501, "Switch to walking mode with waist control."),
    "RunMode": (801, "Switch to running mode."),
}


class G1Controller(RobotController):
    """G1 humanoid controller via Unitree SDK2 DDS with extended controls."""

    def __init__(
        self,
        ip: str | None = None,
        network_interface: str | None = None,
    ):
        self.ip = ip or os.getenv("G1_ROBOT_IP")
        self.network_interface = network_interface or os.getenv("G1_NETWORK_INTERFACE")

        self._connected = False
        self._lock = threading.Lock()
        self._loco_client: Any | None = None
        self._motion_switcher: Any | None = None
        self._low_state_sub: Any | None = None
        self._latest_low_state: Any | None = None
        # Mirrors DimOS wholebody_connection.py: mode_machine is read from every
        # LowState and must be echoed back in LowCmd so the G1 firmware accepts it.
        # LocoClient handles its own LowCmd publishing, but we still capture this
        # so get_state() and FSM introspection reflect the live hardware value.
        self._mode_machine: int | None = None

    def _available_interfaces(self) -> list[str]:
        try:
            names = [name for _, name in socket.if_nameindex()]
        except Exception:
            names = []
        return sorted(names)

    def _resolve_network_interface(self) -> str | None:
        available = self._available_interfaces()

        if self.network_interface:
            return self.network_interface if self.network_interface in available else None

        for preferred in ("eth0", "enp0s31f6", "enp0s25", "eno1"):
            if preferred in available:
                return preferred

        for name in available:
            if name != "lo":
                return name

        return None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> str:
        """Initialize DDS and connect to G1."""
        self._connected = False
        self._loco_client = None
        self._motion_switcher = None
        self._low_state_sub = None

        try:
            import unitree_sdk2py.core.channel as channel_mod
            from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import (
                MotionSwitcherClient,
            )
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

            requested_nic = (self.network_interface or "").strip()
            nic = self._resolve_network_interface()
            dds_errors: list[str] = []

            if requested_nic and nic is None:
                return (
                    f"G1 connect failed: network interface '{requested_nic}' not found. "
                    f"Available: {', '.join(self._available_interfaces()) or '(none)'}"
                )

            dds_ok = False
            used_nic = "default"

            if nic:
                try:
                    channel_mod.ChannelFactoryInitialize(0, nic)
                    dds_ok = True
                    used_nic = nic
                except Exception as e:
                    msg = str(e).lower()
                    if "already" in msg or ("init" in msg and "once" in msg):
                        dds_ok = True
                        used_nic = nic
                    else:
                        dds_errors.append(f"iface={nic}: {type(e).__name__}: {e}")

            if not dds_ok:
                try:
                    channel_mod.ChannelFactoryInitialize(0)
                    dds_ok = True
                    used_nic = "default"
                except Exception as e:
                    msg = str(e).lower()
                    if "already" in msg or ("init" in msg and "once" in msg):
                        dds_ok = True
                        used_nic = "default"
                    else:
                        dds_errors.append(f"iface=default: {type(e).__name__}: {e}")

            if not dds_ok:
                return (
                    "G1 connect failed at ChannelFactoryInitialize: "
                    + " | ".join(dds_errors)
                )

            # Release sport mode if active — mirrors DimOS wholebody_connection.py
            # _release_sport_mode().  Non-fatal: locomotion may still work even if
            # the switcher is unavailable on some SDK builds.
            try:
                self._motion_switcher = MotionSwitcherClient()
                self._motion_switcher.SetTimeout(5.0)
                self._motion_switcher.Init()
                self._release_sport_mode(self._motion_switcher)
            except Exception:
                self._motion_switcher = None

            try:
                self._loco_client = LocoClient()
                self._loco_client.SetTimeout(10.0)
                self._loco_client.Init()
                self._loco_client._RegistApi(LOCO_API_IDS["GET_FSM_ID"], 0)
                self._loco_client._RegistApi(LOCO_API_IDS["GET_FSM_MODE"], 0)
                self._loco_client._RegistApi(LOCO_API_IDS["GET_BALANCE_MODE"], 0)
            except Exception as e:
                return (
                    "G1 connect failed at LocoClient.Init: "
                    f"{type(e).__name__}: {e} (dds_interface={used_nic})"
                )

            lowstate_error = None
            for import_path in (
                "unitree_sdk2py.idl.unitree_hg.msg.dds_",
                "unitree_sdk2py.idl.unitree_go.msg.dds_",
            ):
                try:
                    module = __import__(import_path, fromlist=["LowState_"])
                    LowState_ = getattr(module, "LowState_")
                    self._low_state_sub = channel_mod.ChannelSubscriber("rt/lowstate", LowState_)
                    self._low_state_sub.Init(self._on_low_state, 10)
                    lowstate_error = None
                    break
                except Exception as e:
                    lowstate_error = f"{import_path}: {type(e).__name__}: {e}"

            if lowstate_error is not None:
                return f"G1 connect failed at lowstate subscription: {lowstate_error}"

            # Wait for first LowState to capture mode_machine — mirrors DimOS
            # wholebody_connection.py start() which blocks up to _MODE_MACHINE_WAIT_S.
            # Without this, any FSM call made immediately after connect() would race
            # against the first DDS message arriving.
            _LOWSTATE_WAIT_S = 5.0
            deadline = time.time() + _LOWSTATE_WAIT_S
            while self._mode_machine is None and time.time() < deadline:
                time.sleep(0.05)
            if self._mode_machine is None:
                # Non-fatal for LocoClient path (mode_machine is only needed for
                # raw LowCmd publishing which we don't do here), but warn clearly.
                print(
                    f"[G1Controller] Warning: no LowState received within "
                    f"{_LOWSTATE_WAIT_S:.1f}s — mode_machine unknown. "
                    "FSM state reads may be unreliable until data arrives.",
                    file=__import__('sys').stderr,
                )

            self._connected = True
            return f"Connected to G1 via DDS interface={used_nic} (mode_machine={self._mode_machine})"

        except ImportError:
            return "unitree_sdk2py not installed. Run: pip install unitree_sdk2py"
        except Exception as e:
            self._connected = False
            return (
                f"G1 connect failed: {type(e).__name__}: {e}. "
                f"Trace: {traceback.format_exc(limit=1).strip()}"
            )

    def disconnect(self) -> None:
        """Cleanly disconnect from G1."""
        self._connected = False
        self._loco_client = None
        self._motion_switcher = None
        # Explicitly close the DDS subscriber before releasing the reference —
        # mirrors DimOS wholebody_connection.py stop() which calls subscriber.Close()
        # to avoid GC-race segfaults on process exit with the C-extension callbacks.
        if self._low_state_sub is not None:
            try:
                self._low_state_sub.Close()
            except (OSError, RuntimeError):
                pass
        self._low_state_sub = None
        self._latest_low_state = None
        self._mode_machine = None

    def get_battery(self) -> dict[str, Any] | str:
        """Get G1 battery state from LowState when available.

        G1 unitree_hg LowState often does not expose full BMS fields (soc/current)
        in all SDK variants. This method extracts real values when present and
        falls back to motor-voltage proxy plus safe defaults.
        """
        state = self._require_low_state()
        if isinstance(state, str):
            return state

        def _read(obj: Any, key: str, default: Any = None) -> Any:
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        try:
            motor_state = _read(state, "motor_state", []) or []
            voltages = [
                _read(m, "vol", 0.0) for m in motor_state if float(_read(m, "vol", 0.0) or 0.0) > 0
            ]
            avg_motor_v = sum(voltages) / len(voltages) if voltages else 0.0

            # Try direct power fields first; fallback to motor-voltage proxy.
            power_v = _read(state, "power_v", None)
            voltage_v = float(power_v) if power_v is not None else float(avg_motor_v)

            # Try BMS-backed SOC/current if present in this SDK/IDL flavor.
            bms_state = _read(state, "bms_state", None)
            soc_raw = _read(bms_state, "soc", None)
            soc_percent = int(soc_raw) if soc_raw is not None else None

            current_raw = _read(bms_state, "current", None)
            # Common Unitree convention is mA for BMS current; convert if numeric.
            current_a = float(current_raw) / 1000.0 if current_raw is not None else 0.0

            return {
                "soc_percent": soc_percent,
                "voltage_v": round(voltage_v, 3),
                "current_a": round(current_a, 3),
            }
        except Exception as e:
            return f"Failed to read G1 battery: {e}"

    def move_velocity(self, x: float, y: float = 0.0, yaw: float = 0.0, duration: float = 0.0) -> str:
        """Move the robot in velocity space."""
        if not self._connected or self._loco_client is None:
            return "Not connected"
        try:
            if duration > 0:
                code = self._loco_client.SetVelocity(x, y, yaw, duration)
            else:
                self._loco_client.Move(x, y, yaw, continous_move=True)
                code = 0
            if code != 0:
                return f"Move failed: code={code}"
            return f"Started moving with velocity=({x}, {y}, {yaw}) for {duration} seconds"
        except Exception as e:
            return f"Move failed: {type(e).__name__}: {e}"

    def stand_up(self) -> str:
        """Transition robot into standing posture."""
        if not self._connected or self._loco_client is None:
            return "Not connected"

        try:
            fsm_id = self._get_fsm_id()
            if fsm_id is None:
                return "Stand up aborted: unable to read FSM state"

            if fsm_id == FsmState.ZERO_TORQUE:
                self._loco_client.SetFsmId(FsmState.DAMP)
                time.sleep(1.0)
                fsm_id = self._get_fsm_id() or FsmState.DAMP

            if fsm_id != FsmState.AI_MODE:
                self._loco_client.SetFsmId(FsmState.AI_MODE)
                time.sleep(1.5)

            self._loco_client.SetFsmId(FsmState.SQUAT_STANDUP_TOGGLE)
            time.sleep(3.0)
            return f"Stand up command sent. Current state: {self.get_state()}"
        except Exception as e:
            return f"Stand up failed: {type(e).__name__}: {e}"

    def lie_down(self) -> str:
        """Transition robot into squat/damp state."""
        if not self._connected or self._loco_client is None:
            return "Not connected"
        try:
            self._loco_client.StandUp2Squat()
            time.sleep(1.0)
            self._loco_client.Damp()
            return "Lie down command sent"
        except Exception as e:
            return f"Lie down failed: {type(e).__name__}: {e}"

    def get_state(self) -> str:
        """Get current FSM state name."""
        if not self._connected or self._loco_client is None:
            return "Not connected"
        fsm_id = self._get_fsm_id()
        if fsm_id is None:
            return "Unknown (query failed)"
        try:
            return FsmState(fsm_id).name
        except ValueError:
            return f"UNKNOWN_{fsm_id}"

    def execute_arm_command(self, command_name: str) -> str:
        """Execute named arm command on rt/api/arm/request."""
        return self._execute_named_command(ARM_COMMANDS, ARM_API_ID, ARM_TOPIC, command_name)

    def execute_mode_command(self, command_name: str) -> str:
        """Execute named mode command on rt/api/sport/request."""
        return self._execute_named_command(MODE_COMMANDS, MODE_API_ID, MODE_TOPIC, command_name)

    def list_arm_command(self) -> list[str]:
        """List available arm command names."""
        return sorted(ARM_COMMANDS.keys())

    def list_mode_command(self) -> list[str]:
        """List available mode command names."""
        return sorted(MODE_COMMANDS.keys())

    def publish_request(self, topic: str, data: dict[str, Any]) -> dict[str, Any]:
        """Publish high-level API request through LocoClient."""
        if not self._connected or self._loco_client is None:
            return {"code": -1, "error": "Not connected"}

        api_id = data.get("api_id")
        parameter = data.get("parameter", {})

        try:
            if api_id == MODE_API_ID:
                fsm_id = parameter.get("data", 0)
                code = self._loco_client.SetFsmId(fsm_id)
                return {"code": code}

            if api_id == 7105:
                velocity = parameter.get("velocity", [0.0, 0.0, 0.0])
                duration = parameter.get("duration", 1.0)
                code = self._loco_client.SetVelocity(
                    float(velocity[0]),
                    float(velocity[1]),
                    float(velocity[2]),
                    float(duration),
                )
                return {"code": code}

            payload = json.dumps(parameter)
            code, result = self._loco_client._Call(int(api_id), payload)
            return {"code": code, "result": result}
        except Exception as e:
            return {"code": -1, "error": f"{type(e).__name__}: {e}"}

    def _execute_named_command(
        self,
        command_dict: dict[str, tuple[int, str]],
        api_id: int,
        topic: str,
        command_name: str,
    ) -> str:
        if command_name not in command_dict:
            suggestions = difflib.get_close_matches(command_name, command_dict.keys(), n=3, cutoff=0.6)
            return f"There's no '{command_name}' command. Did you mean: {suggestions}"

        command_id, _ = command_dict[command_name]
        response = self.publish_request(topic, {"api_id": api_id, "parameter": {"data": command_id}})
        code = response.get("code", -1)
        if code != 0:
            return f"Failed to execute '{command_name}': {response}"
        return f"'{command_name}' command executed successfully."

    def _on_low_state(self, msg: Any) -> None:
        """rt/lowstate DDS callback — mirrors DimOS wholebody_connection._on_low_state.
        Captures mode_machine on first message (required by G1 firmware to echo back
        in LowCmd) and keeps the latest snapshot for telemetry reads."""
        with self._lock:
            self._latest_low_state = msg
            # Capture mode_machine on first arrival, like DimOS does in
            # wholebody_connection.py: `if self._mode_machine is None: self._mode_machine = msg.mode_machine`
            if self._mode_machine is None and hasattr(msg, "mode_machine"):
                self._mode_machine = msg.mode_machine

    def _require_low_state(self) -> Any | str:
        if not self._connected:
            return "Not connected"
        deadline = time.time() + 2.0
        while self._latest_low_state is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_low_state is None:
            return "No low state data received yet"
        with self._lock:
            return self._latest_low_state

    @staticmethod
    def _release_sport_mode(msc: Any) -> None:
        """Loop ReleaseMode until MotionSwitcher reports no active controller.

        Mirrors DimOS wholebody_connection.py _release_sport_mode() exactly:
        CheckMode returns (status, None) once nothing is active.
        """
        _status, result = msc.CheckMode()
        while result and result.get("name"):
            msc.ReleaseMode()
            time.sleep(1.0)
            _status, result = msc.CheckMode()

    def _get_fsm_id(self) -> int | None:
        if self._loco_client is None:
            return None
        try:
            code, data = self._loco_client._Call(LOCO_API_IDS["GET_FSM_ID"], "{}")
            if code != 0:
                return None
            decoded = json.loads(data) if isinstance(data, str) else data
            if isinstance(decoded, dict):
                value = decoded.get("data")
                return int(value) if value is not None else None
            if isinstance(decoded, int):
                return decoded
            return None
        except Exception:
            return None
