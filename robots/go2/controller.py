"""
robots/go2/controller.py
------------------------
Go2 robot controller.

Thin adapter that wraps the core Go2 connection logic and satisfies the
RobotController base interface.  All hardware-specific details (WebRTC,
topic names, async loop) live here and nowhere else.

Ported from go2_agent/controllers/go2_controller.py.
"""

import asyncio
import math
import numbers
import os
import threading
import time

from robots.base import RobotController

from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
from unitree_webrtc_connect.webrtc_driver import (
    UnitreeWebRTCConnection as WebRTCConnection,
    WebRTCConnectionMethod,
)


class Go2Controller(RobotController):

    def __init__(self, ip: str | None = None):
        self.ip = ip or os.getenv("ROBOT_IP")

        self._conn = None
        self._loop = None
        self._thread = None
        self._task = None
        self._stop_timer = None
        self._cmd_vel_timeout = 0.2

        self._connection_ready = threading.Event()
        self._connection_error = None

        self._latest_low_state = None
        self._latest_odom = None
        self._latest_frame = None
        self._reference_pose = None

    # ------------------------------------------------------------------
    # RobotController interface
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._conn is not None

    def connect(self) -> str:
        if not self.ip:
            return "ROBOT_IP not set. Pass ip= or set the ROBOT_IP env var."

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

                if hasattr(self._conn, "video"):
                    self._conn.video.add_track_callback(self._video_callback)

                await connect_task

                self._conn.video.switchVideoChannel(True)
                await self._conn.datachannel.disableTrafficSaving(True)
                self._conn.datachannel.set_decoder(decoder_type="native")

                self._conn.datachannel.pub_sub.subscribe(
                    RTC_TOPIC["LOW_STATE"], self._on_low_state
                )
                self._conn.datachannel.pub_sub.subscribe(
                    RTC_TOPIC["ROBOTODOM"], self._on_odom
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

        connected = self._connection_ready.wait(timeout=5)

        if connected:
            if self._connection_error:
                return self._connection_error
            return "Connected to Go2"

        # Timed out — clean up
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
        return "Connection timeout"

    def disconnect(self) -> None:
        self.stop()
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
        self._latest_low_state = self._latest_odom = self._latest_frame = None
        self._connection_ready.clear()

    def move(
        self,
        x: float = 0.0,
        y: float = 0.0,
        yaw: float = 0.0,
        duration: float = 0.0,
    ) -> bool:
        if not self._conn:
            return False

        async def _send():
            self._conn.datachannel.pub_sub.publish_without_callback(
                RTC_TOPIC["WIRELESS_CONTROLLER"],
                data={"lx": -y, "ly": x, "rx": -yaw, "ry": 0},
            )

        async def _send_duration():
            start = time.time()
            while time.time() - start < duration:
                await _send()
                await asyncio.sleep(0.01)

        if self._stop_timer:
            self._stop_timer.cancel()
        self._stop_timer = threading.Timer(self._cmd_vel_timeout, self.stop)
        self._stop_timer.daemon = True
        self._stop_timer.start()

        try:
            coro = _send_duration() if duration > 0 else _send()
            asyncio.run_coroutine_threadsafe(coro, self._loop).result()
            return True
        except Exception:
            return False

    def stop(self) -> None:
        if not self._conn:
            return
        if self._stop_timer:
            self._stop_timer.cancel()
            self._stop_timer = None

        async def _zero():
            self._conn.datachannel.pub_sub.publish_without_callback(
                RTC_TOPIC["WIRELESS_CONTROLLER"],
                data={"lx": 0, "ly": 0, "rx": 0, "ry": 0},
            )

        asyncio.run_coroutine_threadsafe(_zero(), self._loop)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def get_battery(self) -> dict | str:
        state, err = self._require_low_state()
        if err:
            return err
        bms = state.get("bms_state", {})
        return {
            "soc_percent": bms.get("soc"),
            "voltage_v": round(state.get("power_v", 0), 3),
            "current_ma": bms.get("current"),
            "cycle_count": bms.get("cycle"),
            "bq_ntc_temp_c": bms.get("bq_ntc_temp"),
            "mcu_ntc_temp_c": bms.get("mcu_ntc_temp"),
        }

    def get_pose(self) -> dict | str:
        odom, err = self._require_odom_state()
        if err:
            return err
        return {
            "position": self._extract_position(odom),
            "orientation": self._extract_orientation(odom),
        }

    # ------------------------------------------------------------------
    # Go2-specific extras (not in base; registered as skills directly)
    # ------------------------------------------------------------------

    def get_imu(self) -> dict | str:
        state, err = self._require_low_state()
        if err:
            return err
        rpy = state.get("imu_state", {}).get("rpy", [])
        return {
            "roll":  round(rpy[0], 6) if len(rpy) > 0 else None,
            "pitch": round(rpy[1], 6) if len(rpy) > 1 else None,
            "yaw":   round(rpy[2], 6) if len(rpy) > 2 else None,
        }

    def execute_sport_command(self, command_name: str) -> str:
        if not self._conn:
            return "Not connected"
        api_id = SPORT_CMD.get(command_name)
        if api_id is None:
            return f"Unknown sport command: {command_name}"

        async def _exec():
            await self._conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["SPORT_MOD"],
                options={"api_id": api_id},
            )

        try:
            asyncio.run_coroutine_threadsafe(_exec(), self._loop).result()
            return f"Sport command sent: {command_name}"
        except Exception as e:
            return f"Sport command failed: {e}"

    def list_sport_commands(self) -> list[str]:
        return list(SPORT_CMD.keys())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_low_state(self, msg: dict):
        self._latest_low_state = msg.get("data", {})

    def _on_odom(self, msg: dict):
        self._latest_odom = msg.get("data", msg) if isinstance(msg, dict) else msg

    async def _video_callback(self, track):
        while True:
            self._latest_frame = await track.recv()

    def _require_low_state(self) -> tuple:
        if not self._conn:
            return None, "Not connected"
        deadline = time.time() + 2.0
        while self._latest_low_state is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_low_state is None:
            return None, "No LOW_STATE data received yet"
        return self._latest_low_state, None

    def _require_odom_state(self) -> tuple:
        if not self._conn:
            return None, "Not connected"
        deadline = time.time() + 2.0
        while self._latest_odom is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_odom is None:
            return None, "No ROBOTODOM data received yet"
        return self._latest_odom, None

    def _extract_position(self, odom: dict) -> dict:
        def _search(obj):
            if isinstance(obj, dict):
                if "x" in obj and "y" in obj:
                    return {"x": obj.get("x"), "y": obj.get("y"), "z": obj.get("z")}
                if "px" in obj and "py" in obj:
                    return {"x": obj.get("px"), "y": obj.get("py"), "z": obj.get("pz")}
                for key in ["position", "pose", "pos", "odom", "state", "body", "base", "data"]:
                    if key in obj:
                        found = _search(obj[key])
                        if found:
                            return found
                for v in obj.values():
                    found = _search(v)
                    if found:
                        return found
            if isinstance(obj, list):
                if (len(obj) >= 2 and isinstance(obj[0], numbers.Number)
                        and isinstance(obj[1], numbers.Number)):
                    return {"x": obj[0], "y": obj[1], "z": obj[2] if len(obj) >= 3 else None}
                for item in obj:
                    found = _search(item)
                    if found:
                        return found
            return None
        return _search(odom) or {"x": None, "y": None, "z": None}

    def _extract_orientation(self, odom: dict) -> dict:
        if not isinstance(odom, dict):
            return {"yaw_rad": None, "yaw_deg": None}
        yaw = odom.get("yaw") or odom.get("theta")
        if yaw is None and isinstance(odom.get("imu_state"), dict):
            rpy = odom["imu_state"].get("rpy", [])
            if len(rpy) >= 3:
                yaw = rpy[2]
        if not isinstance(yaw, numbers.Number):
            try:
                yaw = float(yaw)
            except Exception:
                yaw = None
        yaw_deg = round(math.degrees(float(yaw)), 3) if isinstance(yaw, numbers.Number) else None
        return {"yaw_rad": yaw, "yaw_deg": yaw_deg}
