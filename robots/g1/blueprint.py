"""
robots/g1/blueprint.py
----------------------
G1 blueprint — compose the MCP server with the G1 controller and skills.

Pattern mirrors DimOS:
    unitree_g1_agentic = autoconnect(
        unitree_g1,
        _agentic_skills,
    )
    where _agentic_skills = autoconnect(
        McpServer.blueprint(),
        McpClient.blueprint(system_prompt=G1_SYSTEM_PROMPT),
        UnitreeG1SkillContainer.blueprint(),
    )

Here: just the core MCP + controller + skills (no LLM agent client).
"""

from mcp.server.fastmcp import FastMCP

from mcp_server import create_server
from robots.g1.controller import G1Controller
import robots.g1.skills as g1_skills


def build_g1(
    ip: str | None = None,
    network_interface: str | None = None,  # accepted but unused (WebRTC uses IP)
    **kwargs,
) -> tuple[FastMCP, G1Controller]:
    """
    Build the G1 blueprint.

    Args:
        ip: Main controller IP (default: 192.168.123.161).
            Override via G1_ROBOT_IP or ROBOT_IP env var.

    Returns:
        (mcp, controller) tuple — pass mcp to mcp.run() in run.py.
    """
    mcp = create_server("harcos-g1")
    controller = G1Controller(ip=ip)
    g1_skills.register(mcp, controller)
    return mcp, controller
