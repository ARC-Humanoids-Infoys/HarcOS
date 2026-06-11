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
    # Motion
    # ------------------------------------------------------------------

    @abstractmethod
    def move(
        self,
        x: float = 0.0,
        y: float = 0.0,
        yaw: float = 0.0,
        duration: float = 0.0,
    ) -> bool:
        """
        Send a velocity command.

        Args:
            x:        forward (+) / backward (-) velocity in m/s
            y:        left (+) / right (-) velocity in m/s
            yaw:      counter-clockwise (+) angular velocity in rad/s
            duration: seconds to hold the command (0 = single shot)
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Immediately zero all velocity commands."""
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

    @abstractmethod
    def get_pose(self) -> dict | str:
        """
        Return current robot pose.
        Must include at minimum:
          {"position": {"x": float, "y": float}, "orientation": {"yaw_rad": float}}
        """
        ...
