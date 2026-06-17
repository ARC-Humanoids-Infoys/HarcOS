"""
run.py
------
HarcOS entry point — start an MCP server for a given robot.

Usage:
    python run.py go2                     # Go2 on stdio (Claude Desktop)
    python run.py go2 --ip 192.168.1.100 # Go2 with specific IP
    python run.py go2 --transport sse --port 9990  # HTTP SSE server

    python run.py g1                      # G1 on stdio
    python run.py g1 --interface eth0     # G1 with specific network interface
    python run.py g1 --transport sse --port 9991   # G1 on port 9991

Pattern mirrors `dimos run <blueprint>`.
"""

import argparse
import sys

from registry import BLUEPRINTS

# Per-robot default SSE ports.  Must match the server_url defaults in each client.
ROBOT_DEFAULT_PORTS: dict[str, int] = {
    "go2": 9990,
    "g1": 9991,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="HarcOS — Start a robot MCP server",
    )
    parser.add_argument(
        "robot",
        choices=list(BLUEPRINTS.keys()),
        help="Robot blueprint to run: go2, g1, etc.",
    )
    parser.add_argument(
        "--ip",
        default=None,
        help="Robot IP address (overrides ROBOT_IP / G1_ROBOT_IP env var)",
    )
    parser.add_argument(
        "--interface",
        default=None,
        dest="network_interface",
        help="Network interface for G1 DDS (overrides G1_NETWORK_INTERFACE env var)",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport: stdio (Claude Desktop) or sse (HTTP server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HTTP port when --transport sse (default: 9990 for go2, 9991 for g1)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    build_fn = BLUEPRINTS[args.robot]

    # Prepare kwargs for the blueprint builder
    build_kwargs = {}
    if args.ip:
        build_kwargs["ip"] = args.ip
    if args.network_interface:
        build_kwargs["network_interface"] = args.network_interface

    print(f"[HarcOS] Starting blueprint: {args.robot}", file=sys.stderr)

    try:
        mcp, _controller = build_fn(**build_kwargs)
    except Exception as e:
        print(f"[HarcOS] Failed to build blueprint: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[HarcOS] Blueprint built. Starting MCP server...", file=sys.stderr)

    if args.transport == "sse":
        port = args.port if args.port is not None else ROBOT_DEFAULT_PORTS.get(args.robot, 9990)
        # host/port live on mcp.settings, not on run().
        # stateless_http=True: each POST is independent, no session tokens needed.
        # Use streamable-http so the client can POST to /mcp (DimOS pattern).
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = port
        print(
            f"[HarcOS] HTTP server listening on http://localhost:{port}/sse",
            file=sys.stderr,
        )
        mcp.run(transport="sse")
    else:
        print(f"[HarcOS] Stdio mode (Claude Desktop compatible)", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
