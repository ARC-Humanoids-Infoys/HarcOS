"""
robots/base.py
--------------
Abstract base for all robot controllers in HarcOS.

Every robot controller (Go2, G1, H1, ...) must subclass RobotController
and implement these methods.  The blueprint layer and skill layer talk only
to this interface, so they are robot-agnostic.

Pattern mirrors DimOS:
  - Shared MCP infrastructure (FastMCP in blueprints/)
  - Per-robot skill registration (robots/<robot>/skills.py)
  - Per-robot controller implementation (robots/<robot>/controller.py)
"""

from abc import ABC, abstractmethod


class RobotController(ABC):
    """Minimal interface every robot controller must satisfy."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> str:
        """Establish connection to the robot. Returns status string."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully disconnect from the robot."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the connection is live."""
        ...

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    @abstractmethod
    def get_battery(self) -> dict | str:
        """
        Return battery state.
        Must include at minimum: {"soc_percent": float, "voltage_v": float}
        """
        ...
