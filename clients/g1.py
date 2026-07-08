"""
clients/g1.py
-------------
G1 humanoid robot client.
"""

# Allow running directly: python clients/g1.py
# When imported normally __package__ == "clients"; when run directly it is None.
if __package__ is None or __package__ == "":
    import sys as _sys
    import os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)

from clients.base import RobotClient, RobotClientConfig


class G1Client(RobotClient):
    """MCP client for the Unitree G1 humanoid robot.

    Args:
        interface:  Network interface for DDS (e.g. "eth0").
                    Falls back to G1_NETWORK_INTERFACE env var, then auto-detects.
        transport:  "stdio" (subprocess) or "http" (HTTP MCP server).
        model:      Ollama model for agent_send() / run_agent().
        server_url: HTTP server base URL when transport="http"
                    (default: http://localhost:9991).

    Example — direct calls (stdio)::

        async with G1Client() as client:
            print(await client.connect())
            await client.stand_up()
            await client.move(0.2, 0.0, 0.0)
            await client.stop()

    Example — agent loop (HTTP)::

        async with G1Client(transport="http") as client:
            reply = await client.agent_send("stand up and wave")
            print(reply)
    """

    def __init__(
        self,
        interface: str | None = None,
        transport: str = "stdio",
        model: str = "llama3.2",
        server_url: str = "http://localhost:9991",
    ):
        super().__init__(
            RobotClientConfig(
                robot="g1",
                interface=interface,
                transport=transport,
                model=model,
                server_url=server_url,
            )
        )

    async def connect(self) -> str:
        """Connect to the G1 robot over DDS."""
        return await self.call("connect")

    async def disconnect(self) -> str:
        """Disconnect from the G1 robot."""
        return await self.call("disconnect")

    async def get_battery(self) -> str:
        """Read battery state (voltage proxy via motor state)."""
        return await self.call("get_battery")

    async def get_imu(self) -> str:
        """Read IMU: roll, pitch, yaw (rad) and accelerations (m/s²)."""
        return await self.call("get_imu")

    async def stand_up(self) -> str:
        """Stand up from a sitting or lying position."""
        return await self.call("stand_up")

    async def stand_down(self) -> str:
        """Sit / lie down from a standing position."""
        return await self.call("stand_down")

    async def balance_stand(self) -> str:
        """Enter stable balanced standing posture."""
        return await self.call("balance_stand")

    async def move(self, vx: float, vy: float, vyaw: float, duration: float = 2.0) -> str:
        """Send a velocity command.

        Args:
            vx:       Forward (+) / backward (-) in m/s.
            vy:       Left (+) / right (-) in m/s.
            vyaw:     Counter-clockwise (+) yaw rate in rad/s.
            duration: How long to move in seconds (default: 2.0).
        """
        return await self.call("move", {"vx": vx, "vy": vy, "vyaw": vyaw, "duration": duration})

    async def stop(self) -> str:
        """Stop all movement immediately."""
        return await self.call("stop")

    async def damp(self) -> str:
        """Put all motors into damping (compliant / low-power) mode."""
        return await self.call("damp")

    async def wave_hand(self) -> str:
        """High wave gesture."""
        return await self.call("wave_hand")

    async def shake_hand(self) -> str:
        """Handshake gesture."""
        return await self.call("shake_hand")

    async def clap(self) -> str:
        """Clap gesture."""
        return await self.call("clap")

    async def high_five(self) -> str:
        """High five gesture."""
        return await self.call("high_five")

    async def hug(self) -> str:
        """Hug gesture."""
        return await self.call("hug")

    async def hands_up(self) -> str:
        """Raise both hands gesture."""
        return await self.call("hands_up")

    async def cancel_action(self) -> str:
        """Cancel ongoing arm gesture and return to default position."""
        return await self.call("cancel_action")

    async def execute_arm_command(self, command_name: str) -> str:
        """Execute a named arm gesture.

        Valid names: high_wave, shake_hand, clap, high_five, hug, hands_up,
                     face_wave, arm_heart, right_heart, reject, right_hand_up,
                     x_ray, two_hand_kiss, left_kiss, right_kiss, cancel_action
        """
        return await self.call("execute_arm_command", {"command_name": command_name})

    async def execute_mode_command(self, mode_name: str) -> str:
        """Switch G1 locomotion FSM mode by name.

        Valid modes: walk, run, walk_waist, stand_up, stand_down, damp, sit, zero_torque
        """
        return await self.call("execute_mode_command", {"mode_name": mode_name})


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="G1 robot client")
    parser.add_argument("--interface", default=None, help="Network interface for DDS")
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="MCP transport (default: stdio)",
    )
    parser.add_argument("--agent", default=None, metavar="PROMPT",
                        help="Run Ollama agent with this prompt")
    parser.add_argument("--model", default="llama3.2",
                        help="Ollama model to use (default: llama3.2)")
    args = parser.parse_args()

    async def main() -> None:
        async with G1Client(
            interface=args.interface,
            transport=args.transport,
            model=args.model,
        ) as robot:
            if args.agent:
                await robot.run_agent(args.agent)
            else:
                print("Tools:", await robot.list_tools())
                print(await robot.connect())

    asyncio.run(main())
