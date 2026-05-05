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
    from mcp_server.tools import health_check as hc_mod
    from mcp_server.tools import cypher_query as cq_mod
    # Phase 2 tools (api-contracts.md §11 order: semantic_search at position 4)
    from mcp_server.tools import semantic_search as ss_mod

    # Registration order per api-contracts.md §11:
    # 1-3: find_matching_properties_for_insight, suggest_next_best_actions_for_deal,
    #       recommend_broker_for_deal  (Phase 4 — registered when those modules land)
    # 4: semantic_search
    ss_mod.register(mcp, get_driver)
    # 5-7: traverse_graph, list_communities, predict_links  (Phase 3)
    # 8: health_check
    hc_mod.register(mcp, get_driver)
    # 9: cypher_query (destructive escape hatch — always last)
    cq_mod.register(mcp, get_driver)


def main() -> None:
    log.info("mcp_server_starting", transport="stdio")
    register_all_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
