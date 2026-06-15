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
from robots.g1.controller1 import G1Controller
import robots.g1.skills1 as g1_skills


def build_g1(
    ip: str | None = None,
    network_interface: str | None = None,
) -> tuple[FastMCP, G1Controller]:
    """
    Build the G1 blueprint.

    Args:
        ip: Robot identifier (optional, for logging).
        network_interface: Network interface for DDS (e.g. "eth0").

    Returns:
        (mcp, controller) tuple — pass mcp to mcp.run() in run.py.
    """
    mcp = create_server("harcos-g1")
    controller = G1Controller(ip=ip, network_interface=network_interface)
    g1_skills.register(mcp, controller)
    return mcp, controller
