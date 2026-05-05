.PHONY: bootstrap backfill mcp down test lint

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
