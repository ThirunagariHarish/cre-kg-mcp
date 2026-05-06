.PHONY: bootstrap backfill mcp down test lint ml-refresh \
	mcp-remote mcp-tunnel mcp-up mcp-down mcp-url mcp-test mcp-logs

# Override on the command line, e.g. `make mcp-up MCP_PORT=9876`
MCP_HOST ?= 127.0.0.1
MCP_PORT ?= 8080
MCP_LOG  := /tmp/cre_mcp_remote.log
TUN_LOG  := /tmp/cloudflared.log
MCP_PID  := /tmp/cre_mcp_remote.pid
TUN_PID  := /tmp/cloudflared.pid

# -----------------------------------------------------------------------
# bootstrap: install Python deps, bring Neo4j up, wait for healthy
# -----------------------------------------------------------------------
bootstrap:
	@echo "==> Installing Python dependencies via uv..."
	uv sync
	@echo "==> Starting Neo4j (docker compose)..."
	docker compose up -d neo4j
	@echo "==> Waiting for Neo4j + GDS healthcheck (up to 3 min)..."
	@for i in $$(seq 1 36); do \
	  STATUS=$$(docker inspect --format='{{.State.Health.Status}}' cre-neo4j 2>/dev/null || echo "missing"); \
	  echo "  [$${i}/36] Neo4j health: $$STATUS"; \
	  [ "$$STATUS" = "healthy" ] && echo "Neo4j is healthy!" && break; \
	  [ $$i -eq 36 ] && echo "ERROR: Neo4j did not become healthy in time" && exit 1; \
	  sleep 5; \
	done

# -----------------------------------------------------------------------
# backfill: run the full Snowflake → Neo4j backfill
# -----------------------------------------------------------------------
backfill:
	uv run python -m ingester.backfill

# -----------------------------------------------------------------------
# mcp: start the MCP server on stdio (for testing outside Claude Desktop)
# -----------------------------------------------------------------------
mcp:
	uv run python -m mcp_server.server

# -----------------------------------------------------------------------
# down: stop and remove containers; -v destroys Neo4j data volume
# -----------------------------------------------------------------------
down:
	docker compose down

down-v:
	docker compose down -v

# -----------------------------------------------------------------------
# test: run all unit tests (skip integration tests requiring Docker)
# -----------------------------------------------------------------------
test:
	uv run pytest tests/ -v -m "not integration"

# -----------------------------------------------------------------------
# test-integration: run integration tests (requires Docker + Neo4j)
# -----------------------------------------------------------------------
test-integration:
	uv run pytest tests/ -v

# -----------------------------------------------------------------------
# lint / typecheck
# -----------------------------------------------------------------------
lint:
	uv run ruff check ingester/ mcp_server/ tests/ || true

# -----------------------------------------------------------------------
# ml-refresh: run ML pipeline once (embeddings → communities → link prediction)
# M-P3-1: --once flag exits after a single run (no scheduler)
# -----------------------------------------------------------------------
ml-refresh:
	uv run python -m ml.refresh --once

# -----------------------------------------------------------------------
# Remote MCP (streamable-http + Cloudflare Tunnel)
# -----------------------------------------------------------------------
# mcp-remote : foreground HTTP server (Ctrl-C to stop)
# mcp-tunnel : foreground cloudflared tunnel
# mcp-up     : detached server + tunnel, prints public URL
# mcp-down   : stops detached server + tunnel
# mcp-url    : prints current public URL
# mcp-test   : initialize handshake + tools/list + health_check
# mcp-logs   : tail server + tunnel logs
# -----------------------------------------------------------------------
mcp-remote:
	MCP_TRANSPORT=streamable-http MCP_HOST=$(MCP_HOST) MCP_PORT=$(MCP_PORT) \
		bash scripts/run_remote_mcp.sh

mcp-tunnel:
	cloudflared tunnel --url http://$(MCP_HOST):$(MCP_PORT)

mcp-up:
	@echo "==> Stopping any prior detached server/tunnel..."
	@-[ -f $(MCP_PID) ] && kill $$(cat $(MCP_PID)) 2>/dev/null && rm -f $(MCP_PID) || true
	@-[ -f $(TUN_PID) ] && kill $$(cat $(TUN_PID)) 2>/dev/null && rm -f $(TUN_PID) || true
	@echo "==> Booting MCP server on $(MCP_HOST):$(MCP_PORT) (log: $(MCP_LOG))..."
	@MCP_TRANSPORT=streamable-http MCP_HOST=$(MCP_HOST) MCP_PORT=$(MCP_PORT) \
		nohup bash scripts/run_remote_mcp.sh > $(MCP_LOG) 2>&1 & echo $$! > $(MCP_PID)
	@for i in $$(seq 1 30); do \
	  curl -sS -o /dev/null --max-time 1 http://$(MCP_HOST):$(MCP_PORT)/mcp -X POST \
	    -H 'Accept: application/json, text/event-stream' && break; \
	  [ $$i -eq 30 ] && echo "ERROR: MCP server did not come up — see $(MCP_LOG)" && exit 1; \
	  sleep 1; \
	done
	@echo "==> Booting Cloudflare Tunnel (log: $(TUN_LOG))..."
	@rm -f $(TUN_LOG)
	@nohup cloudflared tunnel --url http://$(MCP_HOST):$(MCP_PORT) > $(TUN_LOG) 2>&1 & echo $$! > $(TUN_PID)
	@for i in $$(seq 1 30); do \
	  URL=$$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' $(TUN_LOG) | head -1); \
	  [ -n "$$URL" ] && echo "" && echo "MCP URL: $$URL/mcp" && exit 0; \
	  [ $$i -eq 30 ] && echo "ERROR: tunnel URL not found in $(TUN_LOG)" && exit 1; \
	  sleep 1; \
	done

mcp-down:
	@-[ -f $(TUN_PID) ] && kill $$(cat $(TUN_PID)) 2>/dev/null && rm -f $(TUN_PID) && echo "tunnel stopped" || echo "tunnel: no pid file"
	@-[ -f $(MCP_PID) ] && kill $$(cat $(MCP_PID)) 2>/dev/null && rm -f $(MCP_PID) && echo "server stopped" || echo "server: no pid file"

mcp-url:
	@URL=$$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' $(TUN_LOG) 2>/dev/null | head -1); \
	if [ -n "$$URL" ]; then echo "$$URL/mcp"; else echo "no tunnel URL — run 'make mcp-up'"; exit 1; fi

mcp-test:
	@URL=$$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' $(TUN_LOG) 2>/dev/null | head -1)/mcp; \
	[ "$$URL" = "/mcp" ] && echo "no tunnel URL — run 'make mcp-up' first" && exit 1; \
	echo "Testing $$URL ..."; \
	SID=$$(curl -sS -i -X POST "$$URL" \
	  -H 'Content-Type: application/json' \
	  -H 'Accept: application/json, text/event-stream' \
	  -d '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"make-test","version":"1"}}}' \
	  | awk -v IGNORECASE=1 '/^mcp-session-id:/ {gsub("\r",""); print $$2}'); \
	[ -z "$$SID" ] && echo "FAIL: no session id" && exit 1; \
	echo "  session_id=$$SID"; \
	curl -sS -o /dev/null -X POST "$$URL" \
	  -H 'Content-Type: application/json' \
	  -H 'Accept: application/json, text/event-stream' \
	  -H "mcp-session-id: $$SID" \
	  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'; \
	curl -sS -X POST "$$URL" \
	  -H 'Content-Type: application/json' \
	  -H 'Accept: application/json, text/event-stream' \
	  -H "mcp-session-id: $$SID" \
	  -d '{"jsonrpc":"2.0","method":"tools/list","id":100}' \
	  | grep '^data: ' | sed 's/^data: //' \
	  | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'  tools: {len(d[\"result\"][\"tools\"])}')"; \
	curl -sS -X POST "$$URL" \
	  -H 'Content-Type: application/json' \
	  -H 'Accept: application/json, text/event-stream' \
	  -H "mcp-session-id: $$SID" \
	  -d '{"jsonrpc":"2.0","method":"tools/call","id":101,"params":{"name":"health_check","arguments":{}}}' \
	  | grep '^data: ' | sed 's/^data: //' \
	  | python3 -c "import sys,json; e=json.loads(sys.stdin.read()); h=json.loads(e['result']['content'][0]['text']); print(f'  health: {h[\"status\"]} | neo4j={h[\"neo4j_reachable\"]} | gds={h[\"gds\"]}')"

mcp-logs:
	@echo "=== $(MCP_LOG) ==="; tail -n 30 $(MCP_LOG) 2>/dev/null || echo "(no server log)"
	@echo ""; echo "=== $(TUN_LOG) ==="; tail -n 30 $(TUN_LOG) 2>/dev/null || echo "(no tunnel log)"
