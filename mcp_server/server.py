"""
CRE Knowledge Graph MCP Server — stdio transport.

Tool registration order follows api-contracts.md §11.
Each tool lives in its own module under mcp_server/tools/ and must expose a
`register(mcp_server, driver_factory)` function.

M7: Tools are discovered automatically via pkgutil.iter_modules so that
    Phase 3 can add list_communities, predict_links, traverse_graph by
    dropping module files — no editing of this file required and no
    merge-collision risk across parallel branches.

Registration order is controlled by the ORDER list below.  Modules found by
auto-discovery that are NOT in ORDER are appended alphabetically after the
ordered set (safe default for new phases).

Reserved module paths (do NOT create files here in Phase 1):
  mcp_server/tools/semantic_search.py      — Phase 2 (already present)
  mcp_server/tools/traverse_graph.py       — Phase 3
  mcp_server/tools/list_communities.py     — Phase 3
  mcp_server/tools/predict_links.py        — Phase 3
  ingester/                                — Phase 2 streaming additions
  ml/                                      — Phase 3 ML enrichment
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Callable

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_server.neo4j_client import get_driver
import mcp_server.tools as _tools_pkg

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

# api-contracts.md §11 registration order.
# Modules present on disk but absent from this list are appended alphabetically.
_TOOL_ORDER = [
    "find_matching_properties_for_insight",   # 1  — Phase 4
    "suggest_next_best_actions_for_deal",     # 2  — Phase 4
    "recommend_broker_for_deal",              # 3  — Phase 4
    "semantic_search",                         # 4  — Phase 2
    "traverse_graph",                          # 5  — Phase 3
    "list_communities",                        # 6  — Phase 3
    "predict_links",                           # 7  — Phase 3
    "health_check",                            # 8
    "cypher_query",                            # 9  — always last (destructive)
]


def _discover_tool_modules() -> list[str]:
    """
    Return module base-names found under mcp_server/tools/, ordered per
    _TOOL_ORDER with unknowns appended alphabetically.
    """
    found = {
        mod.name
        for mod in pkgutil.iter_modules(_tools_pkg.__path__)
        if not mod.name.startswith("_")
    }
    ordered = [name for name in _TOOL_ORDER if name in found]
    extras = sorted(found - set(_TOOL_ORDER))
    return ordered + extras


def register_all_tools() -> None:
    """
    Auto-discover and register every tool module under mcp_server/tools/.

    Each module must expose register(mcp_server, driver_factory).
    Missing register() is logged and skipped — it does not abort startup.
    """
    for mod_name in _discover_tool_modules():
        full_name = f"mcp_server.tools.{mod_name}"
        try:
            module = importlib.import_module(full_name)
        except ImportError as exc:
            log.warning("tool_module_import_failed", module=full_name, error=str(exc))
            continue

        register_fn: Callable | None = getattr(module, "register", None)
        if register_fn is None:
            log.warning("tool_module_no_register", module=full_name)
            continue

        try:
            register_fn(mcp, get_driver)
            log.debug("tool_registered", module=mod_name)
        except Exception as exc:
            log.error("tool_register_failed", module=full_name, error=str(exc))


def main() -> None:
    log.info("mcp_server_starting", transport="stdio")
    register_all_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
