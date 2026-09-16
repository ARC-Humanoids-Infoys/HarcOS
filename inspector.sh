#!/usr/bin/env bash
# inspector.sh — launch MCP Inspector, clearing stale port locks first
#
# Usage:
#   ./inspector.sh                         # stdio mode: g1 (default)
#   ./inspector.sh go2                     # stdio mode: go2
#   ./inspector.sh --http                  # HTTP mode: connect to localhost:9991
#   ./inspector.sh --http 9991             # HTTP mode: explicit port
#   ./inspector.sh --http 9990             # HTTP mode: go2 port
set -euo pipefail

# Free ports used by MCP Inspector
lsof -ti:6277 -ti:6274 | xargs kill -9 2>/dev/null || true
sleep 0.5

# Load nvm if available
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

if [[ "${1:-}" == "--http" ]]; then
    PORT="${2:-9991}"
    echo "Connecting inspector to http://localhost:${PORT}/mcp ..."
    exec npx @modelcontextprotocol/inspector --cli --server http://localhost:${PORT}/mcp
else
    ROBOT="${1:-g1}"
    exec npx @modelcontextprotocol/inspector python run.py "$ROBOT" "${@:2}"
fi
