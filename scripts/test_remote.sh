#!/usr/bin/env bash
# scripts/test_remote.sh — exercise the public MCP endpoint end-to-end.
#
# Usage:
#   bash scripts/test_remote.sh
#   bash scripts/test_remote.sh https://your-other-tunnel.trycloudflare.com/mcp
#
# Does the full MCP handshake (initialize → notifications/initialized → tools/list
# → tools/call), parses the SSE responses, and prints what the server returned.

set -euo pipefail

URL="${1:-https://lounge-instances-lanka-compression.trycloudflare.com/mcp}"

echo "Endpoint: $URL"
echo ""

HDR_CT='Content-Type: application/json'
HDR_AC='Accept: application/json, text/event-stream'

echo "=== STEP 1: initialize ==="
INIT_RESP=$(curl -s -i -X POST "$URL" \
  -H "$HDR_CT" -H "$HDR_AC" \
  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test_remote.sh","version":"1.0"}}}')

SESSION=$(echo "$INIT_RESP" | grep -i "^mcp-session-id:" | awk '{print $2}' | tr -d '\r')
HTTP_STATUS=$(echo "$INIT_RESP" | head -1)

if [ -z "$SESSION" ]; then
    echo "FAILED: no session id in response"
    echo "$INIT_RESP" | head -20
    exit 1
fi

echo "  $HTTP_STATUS"
echo "  Session: $SESSION"
echo ""

echo "=== STEP 2: notifications/initialized ==="
curl -s -X POST "$URL" -H "$HDR_CT" -H "$HDR_AC" -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null
echo "  ok"
echo ""

echo "=== STEP 3: tools/list ==="
curl -s -X POST "$URL" -H "$HDR_CT" -H "$HDR_AC" -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}' \
  | grep "^data:" | sed 's/^data: //' | python3 - <<'PY'
import sys, json
d = json.loads(sys.stdin.read())
tools = d.get("result", {}).get("tools", [])
print("  " + str(len(tools)) + " tools available:")
for t in tools:
    print("    - " + t["name"])
PY
echo ""

echo "=== STEP 4: tools/call → health_check ==="
curl -s -X POST "$URL" -H "$HDR_CT" -H "$HDR_AC" -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":3,"params":{"name":"health_check","arguments":{}}}' \
  | grep "^data:" | sed 's/^data: //' | python3 - <<'PY'
import sys, json
d = json.loads(sys.stdin.read())
text = d["result"]["content"][0]["text"]
parsed = json.loads(text)
print("  Status:           " + parsed.get("status", "?"))
print("  Neo4j reachable:  " + str(parsed.get("neo4j_reachable", "?")))
print("  GDS version:      " + str(parsed.get("gds", "?")))
print("  Last ML run:      " + str(parsed.get("last_ml_run_at", "?")))
print("  ML stale warning: " + str(parsed.get("ml_freshness_warning", "?")))
counts = parsed.get("node_counts", {})
top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
print("  Top node labels:")
for label, n in top:
    print("    " + label.ljust(15) + " " + str(n))
PY
echo ""

echo "=== STEP 5: tools/call → recommend_broker_for_deal (Manhattan office leasing) ==="
curl -s -X POST "$URL" -H "$HDR_CT" -H "$HDR_AC" -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":4,"params":{"name":"recommend_broker_for_deal","arguments":{"market":"manhattan","asset_class":"office","service_line":"leasing"}}}' \
  | grep "^data:" | sed 's/^data: //' | python3 - <<'PY'
import sys, json
d = json.loads(sys.stdin.read())
parsed = json.loads(d["result"]["content"][0]["text"])
print("  Status:  " + parsed.get("status", "?"))
print("  Brokers: " + str(len(parsed.get("brokers", []))))
for b in parsed.get("brokers", [])[:5]:
    name  = b["broker"]["name"]
    firm  = b["broker"].get("firm", "?") or "?"
    score = b.get("score", 0)
    tier  = b.get("components", {}).get("production_tier", "?")
    print("    " + name.ljust(25) + " | " + firm.ljust(22) + " | score=" + ("%.3f" % score) + " | " + tier)
PY
echo ""
echo "All 5 steps passed."
