"""
mcp_server.py
-------------
Shared FastMCP server factory.

This mirrors DimOS's McpServer module — a single place to create
the MCP server that all robot blueprints use.

Pattern from DimOS:
    class McpServer(Module):
        def __init__(self, ...):
            ...

Here: simple factory function.
"""

from mcp.server.fastmcp import FastMCP


def create_server(name: str = "harcos") -> FastMCP:
    """
    Create a new FastMCP server instance.

    Args:
        name: Server name (appears in MCP metadata).

    Returns:
        FastMCP instance ready for tool registration.
    """
    return FastMCP(name)
