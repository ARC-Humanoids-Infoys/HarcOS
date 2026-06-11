"""
robots/g1/controller.py
-----------------------
G1 humanoid robot controller.

Pattern inspired by DimOS's G1 DDS path:
  - Uses Unitree SDK2 Python (unitree_sdk2py) over DDS
  - Requires network interface (e.g. "eth0") rather than IP for DDS transport
    - MotionSwitcherClient + LocoClient for movement and posture commands
  - LowState subscription for battery/IMU/motor states

Install: pip install unitree_sdk2py

Environment:
    G1_ROBOT_IP       : Robot identifier (optional, not used by DDS)
    G1_NETWORK_INTERFACE : Network interface name (default: eth0)
"""

import os
import socket
import threading
import time
import traceback

from robots.base import RobotController


class G1Controller(RobotController):
    """G1 humanoid controller via Unitree SDK2 DDS."""

    def __init__(
        self,
        ip: str | None = None,
        network_interface: str | None = None,
    ):
        self.ip = ip or os.getenv("G1_ROBOT_IP")
        self.network_interface = network_interface or os.getenv("G1_NETWORK_INTERFACE")

        self._connected = False
        self._lock = threading.Lock()
        self._loco_client = None
        self._motion_switcher = None
        self._low_state_sub = None
        self._latest_low_state = None

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

        # Prefer common wired interface names first.
        for preferred in ("eth0", "enp0s31f6", "enp0s25", "eno1"):
            if preferred in available:
                return preferred

        # Otherwise choose the first non-loopback interface.
        for name in available:
            if name != "lo":
                return name

        return None

    # ------------------------------------------------------------------
    # RobotController interface (from robots/base.py)
    # ------------------------------------------------------------------

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

            # Initialize DDS transport layer (DimOS-style: with iface + fallback).
            # IMPORTANT: do not silently swallow failures here — otherwise
            # downstream SDK calls fail with opaque errors like NoneType._ref.
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
                    # If already initialized, proceed.
                    if "already" in msg or "init" in msg and "once" in msg:
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
                    if "already" in msg or "init" in msg and "once" in msg:
                        dds_ok = True
                        used_nic = "default"
                    else:
                        dds_errors.append(f"iface=default: {type(e).__name__}: {e}")

            if not dds_ok:
                return (
                    "G1 connect failed at ChannelFactoryInitialize: "
                    + " | ".join(dds_errors)
                )

            # Motion switcher is helpful but treated as optional because some SDK
            # builds throw opaque C-extension errors (e.g. NoneType _ref) here.
            try:
                self._motion_switcher = MotionSwitcherClient()
                self._motion_switcher.SetTimeout(5.0)
                self._motion_switcher.Init()

                status, result = self._motion_switcher.CheckMode()
                while status == 0 and result and result.get("name"):
                    self._motion_switcher.ReleaseMode()
                    status, result = self._motion_switcher.CheckMode()
                    time.sleep(1.0)
            except Exception:
                # Non-fatal; locomotion may still work without explicit release.
                self._motion_switcher = None

            # Create G1 locomotion client (not Go2 SportClient)
            try:
                self._loco_client = LocoClient()
                self._loco_client.SetTimeout(10.0)
                self._loco_client.Init()
            except Exception as e:
                return (
                    "G1 connect failed at LocoClient.Init: "
                    f"{type(e).__name__}: {e} (dds_interface={used_nic})"
                )

            # Subscribe to low state. Try unitree_hg first (DimOS wholebody path),
            # then fallback to unitree_go for SDK variants.
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

            self._connected = True
            return f"Connected to G1 via DDS interface={used_nic}"

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
        self._low_state_sub = None
        self._latest_low_state = None

    def move(
        self, x: float = 0.0, y: float = 0.0, yaw: float = 0.0, duration: float = 0.0
    ) -> bool:
        """Send velocity command via G1 LocoClient."""
        if not self._connected or self._loco_client is None:
            return False
        try:
            if duration > 0:
                code = self._loco_client.SetVelocity(x, y, yaw, duration)
                if code != 0:
                    return False
            else:
                self._loco_client.Move(x, y, yaw, continous_move=True)
            return True
        except Exception:
            return False

    def stop(self) -> None:
        """Stop G1 movement."""
        if not self._connected or self._loco_client is None:
            return
        try:
            self._loco_client.StopMove()
        except Exception:
            pass

    def get_battery(self) -> dict | str:
        """Get G1 battery state.
        
        NOTE: G1 humanoid uses unitree_hg IDL which does NOT include battery fields
        in rt/lowstate. Battery telemetry would require a separate BMS topic subscription.
        For now, return placeholder values based on motor voltages (averaged motor supply voltage).
        """
        state = self._require_low_state()
        if isinstance(state, str):
            return state
        try:
            # unitree_hg.LowState_ does NOT have bms_state, power_v, power_a fields.
            # Instead, use motor voltages as proxy for system power status.
            if hasattr(state, 'motor_state') and state.motor_state:
                voltages = [m.vol for m in state.motor_state if hasattr(m, 'vol') and m.vol > 0]
                avg_v = sum(voltages) / len(voltages) if voltages else 0.0
            else:
                avg_v = 0.0
            
            return {
                "soc_percent": 85,  # Placeholder (would need separate BMS topic)
                "voltage_v": round(avg_v, 3),
                "current_a": 0.0,  # Placeholder (would need separate BMS topic)
            }
        except Exception as e:
            return f"Failed to read G1 battery: {e}"

    def get_pose(self) -> dict | str:
        """Get G1 pose estimate from low-state IMU (minimal)."""
        if not self._connected:
            return "Not connected"

        state = self._require_low_state()
        if isinstance(state, str):
            return state

        try:
            imu = state.imu_state
            yaw = imu.rpy[2] if len(imu.rpy) >= 3 else None
            return {
                "position": {
                    "x": None,
                    "y": None,
                    "z": None,
                },
                "orientation": {
                    "yaw_rad": round(yaw, 6) if yaw is not None else None,
                    "yaw_deg": round(yaw * 57.2958, 3) if yaw is not None else None,
                },
            }
        except Exception as e:
            return f"Failed to read G1 pose: {e}"

    # ------------------------------------------------------------------
    # G1-specific posture commands (mirroring DimOS execute_*_command)
    # ------------------------------------------------------------------

    def stand_up(self) -> str:
        """Command G1 to stand up."""
        if not self._connected or self._loco_client is None:
            return "Not connected"
        try:
            # DimOS uses SQUAT_STANDUP_TOGGLE FSM (706) in high-level DDS control.
            self._loco_client.SetFsmId(706)
            return "G1 standing up"
        except Exception as e:
            return f"StandUp failed: {e}"

    def stand_down(self) -> str:
        """Command G1 to stand down (sit)."""
        if not self._connected or self._loco_client is None:
            return "Not connected"
        try:
            # Sit FSM
            self._loco_client.SetFsmId(3)
            return "G1 standing down"
        except Exception as e:
            return f"StandDown failed: {e}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_low_state(self, msg) -> None:
        """LowState subscriber callback."""
        with self._lock:
            self._latest_low_state = msg

    def _require_low_state(self):
        """Wait for and return the latest low state message."""
        if not self._connected:
            return "Not connected"
        deadline = time.time() + 2.0
        while self._latest_low_state is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_low_state is None:
            return "No low state data received yet"
        with self._lock:
            return self._latest_low_state
