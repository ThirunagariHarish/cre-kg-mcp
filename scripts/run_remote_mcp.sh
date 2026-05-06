#!/usr/bin/env bash
# scripts/run_remote_mcp.sh — boot the MCP server in streamable-http mode for remote agents.
#
# Usage:
#   bash scripts/run_remote_mcp.sh                    # foreground, stdout+stderr to terminal
#   nohup bash scripts/run_remote_mcp.sh > /tmp/cre_mcp_remote.log 2>&1 &   # detached
#
# After this is running, start a Cloudflare Tunnel to expose it:
#   cloudflared tunnel --url http://localhost:8080
#
# The tunnel will print a public *.trycloudflare.com URL — that's what the remote agent uses.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f ".env" ]; then
    set -a; source .env; set +a
fi

export MCP_TRANSPORT="${MCP_TRANSPORT:-streamable-http}"
export MCP_HOST="${MCP_HOST:-127.0.0.1}"
export MCP_PORT="${MCP_PORT:-8080}"

echo "[remote-mcp] starting MCP server: ${MCP_TRANSPORT} on ${MCP_HOST}:${MCP_PORT}"
echo "[remote-mcp] cypher_query exposed: ${MCP_REMOTE_ALLOW_CYPHER:-0}"
echo "[remote-mcp] endpoint will be: http://${MCP_HOST}:${MCP_PORT}/mcp"
echo ""

exec uv run python -m mcp_server.server
