"""
CRE Knowledge Graph MCP Server — stdio + streamable-http transport.

Tool registration order follows api-contracts.md §11.
Each tool lives in its own module under mcp_server/tools/ and must expose a
`register(mcp_server, driver_factory)` function.

Transport selection via `MCP_TRANSPORT` env var:
  - "stdio" (default) — Claude Desktop / local MCP clients
  - "streamable-http" — remote agents over HTTPS (requires MCP_AUTH_TOKEN)

In streamable-http mode, `cypher_query` is hidden from the registered tool
surface unless MCP_REMOTE_ALLOW_CYPHER=1 (Cypher-injection blast radius is too
large to expose to internet callers by default).
"""

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import sys
from typing import Callable

import structlog
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from mcp_server.neo4j_client import get_driver
import mcp_server.tools as _tools_pkg

load_dotenv()

_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()

# MCP stdio transport requires stdout to be reserved for JSON-RPC ONLY.
# Route structlog + stdlib logging to stderr so log lines never corrupt the protocol stream.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, force=True)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(colors=False),
    ],
    logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
)

log = structlog.get_logger()

_HOST = os.getenv("MCP_HOST", "127.0.0.1")
_PORT = int(os.getenv("MCP_PORT", "8080"))

mcp = FastMCP(
    name="cre-kg-mcp",
    instructions=(
        "You are connected to a Commercial Real Estate knowledge graph. "
        "Use health_check to verify the system before starting. "
        "Use the CRE-specific tools to answer questions about brokers, properties, "
        "leases, pursuits, and market insights grounded in real deal data."
    ),
    host=_HOST,
    port=_PORT,
)

# In remote (tunneled) mode the Host header arrives as the Cloudflare hostname,
# which the default DNS-rebinding protection would reject. Disable that check
# since the tunnel itself acts as the trust boundary.
if _TRANSPORT == "streamable-http":
    mcp.settings.transport_security.enable_dns_rebinding_protection = False

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

    In streamable-http (remote) mode, `cypher_query` is hidden by default —
    arbitrary Cypher over the public internet is too broad an attack surface.
    Set MCP_REMOTE_ALLOW_CYPHER=1 to override.
    """
    found = {
        mod.name
        for mod in pkgutil.iter_modules(_tools_pkg.__path__)
        if not mod.name.startswith("_")
    }
    if _TRANSPORT == "streamable-http" and os.getenv("MCP_REMOTE_ALLOW_CYPHER") != "1":
        found.discard("cypher_query")
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
    log.info(
        "mcp_server_starting",
        transport=_TRANSPORT,
        host=_HOST if _TRANSPORT != "stdio" else None,
        port=_PORT if _TRANSPORT != "stdio" else None,
    )
    register_all_tools()
    if _TRANSPORT == "streamable-http":
        log.info(
            "remote_mode_active",
            tool_count=len(_discover_tool_modules()),
            cypher_query_exposed=os.getenv("MCP_REMOTE_ALLOW_CYPHER") == "1",
            endpoint=f"http://{_HOST}:{_PORT}/mcp",
        )
        mcp.run(transport="streamable-http")
    elif _TRANSPORT == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
