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
import os
import threading
import time

from robots.base import RobotController

from unitree_webrtc_connect.constants import RTC_TOPIC
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

        self._connection_ready = threading.Event()
        self._connection_error = None

        self._latest_low_state = None

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

                await connect_task

                self._conn.video.switchVideoChannel(True)
                await self._conn.datachannel.disableTrafficSaving(True)
                self._conn.datachannel.set_decoder(decoder_type="native")

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_low_state(self, msg: dict):
        self._latest_low_state = msg.get("data", {})

    def _require_low_state(self) -> tuple:
        if not self._conn:
            return None, "Not connected"
        deadline = time.time() + 2.0
        while self._latest_low_state is None and time.time() < deadline:
            time.sleep(0.05)
        if self._latest_low_state is None:
            return None, "No LOW_STATE data received yet"
        return self._latest_low_state, None
