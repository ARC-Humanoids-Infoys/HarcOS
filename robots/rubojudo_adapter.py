"""RoboJuDo integration for HarcOS.

RoboJuDo (https://github.com/HansZ8/RoboJuDo) is a plug-and-play RL policy
deployment framework for Unitree robots. This adapter lets HarcOS launch and
control RoboJuDo pipelines alongside its existing MCP skill layer.

Installed from source::

    git clone https://github.com/HansZ8/RoboJuDo.git ~/RoboJuDo
    cd ~/RoboJuDo
    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install -e .

Architecture::

    HarcOS MCP tools           RoboJuDo
    ─────────────────          ──────────────────────────────────────
    start_policy(cfg)  ──────► ConfigManager(cfg) → RlPipeline.prepare()
    stop_policy()      ──────► pipeline thread shutdown
    list_configs()     ──────► cfg_registry keys

RoboJuDo handles trained RL locomotion policies (BeyondMimic, ASAP, …).
HarcOS handles natural-language commands, MCP tool exposure and AI agents.
The two layers are complementary and can run concurrently.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class RoboJuDoAdapter:
    """Run a RoboJuDo pipeline in a background thread.

    Usage::

        adapter = RoboJuDoAdapter()
        adapter.start(config_name="g1")          # sim2sim (MuJoCo)
        adapter.start(config_name="g1_real")     # real robot
        adapter.stop()
        print(adapter.list_configs())            # all available cfg names
    """

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._current_config: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when robojudo is importable."""
        try:
            import robojudo  # noqa: F401
            return True
        except Exception:
            return False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, config_name: str = "g1") -> str:
        """Build and start a RoboJuDo pipeline in a background thread.

        Args:
            config_name: Name of a registered config, e.g. ``"g1"`` (sim),
                         ``"g1_real"`` (real robot), ``"g1_beyondmimic"``.

        Returns:
            Status string.
        """
        if self.is_running():
            return f"Pipeline '{self._current_config}' already running. Call stop() first."

        if not self.is_available():
            return (
                "robojudo is not installed. Run:\n"
                "  git clone https://github.com/HansZ8/RoboJuDo.git ~/RoboJuDo\n"
                "  cd ~/RoboJuDo && pip install torch --index-url "
                "https://download.pytorch.org/whl/cpu && pip install -e ."
            )

        try:
            import robojudo.pipeline
            from robojudo.config.config_manager import ConfigManager

            config_manager = ConfigManager(config_name=config_name)
            cfg = config_manager.get_cfg()
            pipeline_class = getattr(robojudo.pipeline, cfg.pipeline_type)
            self._pipeline = pipeline_class(cfg=cfg)
        except Exception as exc:
            return f"Failed to build pipeline '{config_name}': {exc}"

        self._current_config = config_name
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"robojudo-{config_name}",
        )
        self._thread.start()
        return f"RoboJuDo pipeline '{config_name}' started (dt={getattr(self._pipeline, 'dt', '?')}s)."

    def stop(self) -> str:
        """Stop the running pipeline."""
        if not self.is_running():
            return "No pipeline is currently running."
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._pipeline = None
        self._thread = None
        config = self._current_config
        self._current_config = None
        return f"RoboJuDo pipeline '{config}' stopped."

    def list_configs(self) -> list[str]:
        """Return all registered RoboJuDo config names."""
        if not self.is_available():
            return []
        try:
            import robojudo  # noqa: F401 — triggers all @cfg_registry.register decorators
            from robojudo.config import cfg_registry
            return list(cfg_registry.registered_modules.keys())
        except Exception:
            return []

    def status(self) -> dict:
        """Return a status dict suitable for an MCP tool response."""
        return {
            "robojudo_available": self.is_available(),
            "pipeline_running": self.is_running(),
            "current_config": self._current_config,
        }

    def send_velocity(self, vx: float, vy: float, vyaw: float) -> str:
        """Push a velocity command into the running HarcOS-controlled pipeline.

        Only works when the pipeline was started with a ``g1_harcos*`` config
        that uses ``HarcOSCtrl`` as its controller.

        Args:
            vx:   Forward (+) / backward (-) speed in m/s.
            vy:   Left (+) / right (-) lateral speed in m/s.
            vyaw: Counter-clockwise (+) / clockwise (-) yaw rate in rad/s.
        """
        ctrl = self._harcos_ctrl()
        if ctrl is None:
            return (
                "send_velocity requires a pipeline started with a g1_harcos* config. "
                f"Current config: {self._current_config}. "
                "Restart with start_policy('g1_harcos') first."
            )
        ctrl.push_velocity(vx, vy, vyaw)
        return f"Velocity set: vx={vx}, vy={vy}, vyaw={vyaw}"

    def send_trigger(self, trigger: str) -> str:
        """Send a RoboJuDo trigger to the running pipeline.

        Common triggers:
            [SHUTDOWN]         — emergency stop
            [MOTION_FADE_IN]   — start motion-mimic sequence
            [MOTION_FADE_OUT]  — fade out motion-mimic, return to loco
            [MOTION_RESET]     — reset current motion
            [MOTION_LOAD_NEXT] — load next motion in playlist
            [MOTION_LOAD_PREV] — load previous motion in playlist
        """
        ctrl = self._harcos_ctrl()
        if ctrl is None:
            return (
                "send_trigger requires a pipeline started with a g1_harcos* config. "
                f"Current config: {self._current_config}."
            )
        ctrl.push_trigger(trigger)
        return f"Trigger sent: {trigger}"

    def _harcos_ctrl(self) -> Any | None:
        """Return the HarcOSCtrl instance from the running pipeline, or None."""
        if not self.is_running() or self._pipeline is None:
            return None
        try:
            from robojudo.controller.harcos_ctrl import HarcOSCtrl
            ctrl_manager = self._pipeline.ctrl_manager
            for ctrl in ctrl_manager.controllers:
                if isinstance(ctrl, HarcOSCtrl):
                    return ctrl
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        pipeline = self._pipeline
        try:
            if not pipeline.cfg.env.is_sim:
                pipeline.prepare()
            while not self._stop_event.is_set():
                t0 = time.time()
                pipeline.step()
                elapsed = time.time() - t0
                if not pipeline.cfg.run_fullspeed:
                    sleep_for = pipeline.dt - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
        except Exception as exc:
            logger.error("RoboJuDo pipeline error: %s", exc)


# Module-level singleton so all HarcOS skills share one adapter instance.
_adapter: RoboJuDoAdapter | None = None


def get_adapter() -> RoboJuDoAdapter:
    global _adapter
    if _adapter is None:
        _adapter = RoboJuDoAdapter()
    return _adapter


# ---------------------------------------------------------------------------
# Backwards-compat shim: old code used RubojudoAdapter (generic fallback).
# Keep the name so existing tests still pass.
# ---------------------------------------------------------------------------

class RubojudoAdapter:
    """Compatibility shim — prefer RoboJuDoAdapter for new code."""

    def __init__(self, backend: Any | None = None, enabled: bool = True):
        self.enabled = enabled
        self._real = RoboJuDoAdapter() if enabled else None

    def is_available(self) -> bool:
        return bool(self._real and self._real.is_available())

    def execute(self, action: str, **kwargs: Any) -> Any:
        if not self.is_available():
            return {
                "status": "skipped",
                "backend": "robojudo",
                "action": action,
                "message": "RoboJuDo is not available; using fallback path.",
            }
        return self._real.start(config_name=kwargs.get("config_name", "g1"))
