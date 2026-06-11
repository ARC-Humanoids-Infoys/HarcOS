"""
robots/go2/blueprint.py
-----------------------
Go2 blueprint — compose the MCP server with the Go2 controller and skills.

Pattern mirrors DimOS:
    unitree_go2_agentic = autoconnect(
        unitree_go2_spatial,
        McpServer.blueprint(),
        McpClient.blueprint(),
        _common_agentic,
    )

Here:
    go2_blueprint = build_go2(ip=...)
    returns (mcp, controller)
"""

from mcp.server.fastmcp import FastMCP

from mcp_server import create_server
from robots.go2.controller import Go2Controller
import robots.go2.skills as go2_skills


def build_go2(ip: str | None = None) -> tuple[FastMCP, Go2Controller]:
    """
    Build the Go2 blueprint.

    Args:
        ip: Robot IP. Falls back to ROBOT_IP env var if not provided.

    Returns:
        (mcp, controller) tuple — pass mcp to mcp.run() in run.py.
    """
    mcp = create_server("harcos-go2")
    controller = Go2Controller(ip=ip)
    go2_skills.register(mcp, controller)
    return mcp, controller
