"""
clients/go2.py
--------------
Go2 quadruped robot client.
"""

from clients.base import RobotClient, RobotClientConfig


class Go2Client(RobotClient):
    """MCP client for the Unitree Go2 quadruped robot.

    Args:
        ip:         Robot IP address. Falls back to ROBOT_IP env var if not provided.
        transport:  "stdio" (subprocess) or "http" (HTTP MCP server).
        model:      Ollama model for agent_send() / run_agent().
        server_url: HTTP server base URL when transport="http"
                    (default: http://localhost:9990).

    Example — direct calls (stdio)::

        async with Go2Client(ip="192.168.123.161") as client:
            print(await client.connect())
            print(await client.get_battery())

    Example — agent loop (HTTP)::

        async with Go2Client(transport="http") as client:
            reply = await client.agent_send("go forward 2 meters then stop")
            print(reply)
    """

    def __init__(
        self,
        ip: str | None = None,
        transport: str = "stdio",
        model: str = "llama3.2",
        server_url: str = "http://localhost:9990",
    ):
        super().__init__(
            RobotClientConfig(
                robot="go2",
                ip=ip,
                transport=transport,
                model=model,
                server_url=server_url,
            )
        )

    async def connect(self) -> str:
        """Connect to the Go2 robot over WebRTC."""
        return await self.call("connect")

    async def disconnect(self) -> str:
        """Disconnect from the Go2 robot."""
        return await self.call("disconnect")

    async def get_battery(self) -> str:
        """Read battery state: charge %, voltage, current, cycle count."""
        return await self.call("get_battery")


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Go2 robot client")
    parser.add_argument("--ip", default=None, help="Robot IP address")
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
        async with Go2Client(ip=args.ip, transport=args.transport, model=args.model) as robot:
            if args.agent:
                await robot.run_agent(args.agent)
            else:
                print("Tools:", await robot.list_tools())
                print(await robot.connect())

    asyncio.run(main())
