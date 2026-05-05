"""
CRE Knowledge Graph MCP Server — stdio transport.

Tool registration order follows api-contracts.md §11.
Each tool lives in its own module under mcp_server/tools/.
Phase 2 (ingester/) and Phase 3 (ml/) tools are registered by importing their
own register() functions here — no editing of existing tool files required.

Reserved module paths (do NOT create files here in Phase 1):
  mcp_server/tools/semantic_search.py      — Phase 2
  mcp_server/tools/traverse_graph.py       — Phase 3
  mcp_server/tools/list_communities.py     — Phase 3
  mcp_server/tools/predict_links.py        — Phase 3
  ingester/                                — Phase 2 streaming additions
  ml/                                      — Phase 3 ML enrichment
"""

from __future__ import annotations

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_server.neo4j_client import get_driver

load_dotenv()

log = structlog.get_logger()

mcp = FastMCP(
    name="cre-kg-mcp",
    instructions=(
        "You are connected to a Commercial Real Estate knowledge graph. "
        "Use health_check to verify the system before starting. "
        "Use the CRE-specific tools to answer questions about brokers, properties, "
        "leases, pursuits, and market insights grounded in real deal data."
    ),
)


def register_all_tools() -> None:
    """
    Import and register every tool module.

    Add new tool imports here as new phases land — never modify individual
    tool files to add registrations.
    """
    # Phase 1 tools (api-contracts.md §11 order, high-intent tools first)
    # Phase 2/3/4 high-intent tools will be prepended here
    from mcp_server.tools import health_check as hc_mod
    from mcp_server.tools import cypher_query as cq_mod

    # Registration order for Phase 1: health_check (pos 8) then cypher_query (pos 9)
    # Positions 1-7 will be filled by Phase 2/3/4 imports above this line
    hc_mod.register(mcp, get_driver)
    cq_mod.register(mcp, get_driver)


def main() -> None:
    log.info("mcp_server_starting", transport="stdio")
    register_all_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
