"""
MCP tool: cypher_query — DEBUG ONLY, DANGEROUS.

Executes arbitrary Cypher. read_only=True runs in a READ transaction and
the Neo4j driver will reject write clauses at the server side.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_WRITE_KEYWORDS = frozenset(["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP"])


def _has_write_clause(query: str) -> bool:
    """
    Heuristic pre-check before submitting to Neo4j.
    Not a substitute for server-side read transaction enforcement.
    """
    upper = query.upper()
    return any(kw in upper for kw in _WRITE_KEYWORDS)


def register(mcp_server, driver_factory):
    """Register cypher_query on the MCP server."""

    @mcp_server.tool(
        name="cypher_query",
        description=(
            "Execute an arbitrary Cypher query against the knowledge graph. "
            "DESTRUCTIVE OPERATION: this can read or modify graph data. "
            "Only use this when the user explicitly asks for a raw graph query or when "
            "other tools cannot satisfy the request. Prefer traverse_graph or semantic_search "
            "for normal exploration. The result is returned as a list of records."
        ),
    )
    async def cypher_query(
        query: str,
        params: Optional[dict] = None,
        read_only: bool = True,
    ) -> dict[str, Any]:
        driver = driver_factory()
        params = params or {}

        if read_only and _has_write_clause(query):
            return {
                "status": "ERROR",
                "error": "Read-only mode rejected write clause",
                "records": [],
                "row_count": 0,
                "execution_ms": 0,
            }

        start = time.monotonic()
        try:
            if read_only:
                with driver.session() as session:
                    result = session.execute_read(
                        lambda tx: list(tx.run(query, **params))
                    )
            else:
                with driver.session() as session:
                    result = session.execute_write(
                        lambda tx: list(tx.run(query, **params))
                    )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            records = []
            for record in result:
                records.append(dict(record))

            return {
                "status": "OK",
                "records": records,
                "row_count": len(records),
                "execution_ms": elapsed_ms,
            }

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            err_str = str(exc)
            log.error("cypher_query_error", error=err_str, query=query[:200])

            if "SyntaxError" in err_str or "syntax" in err_str.lower():
                status_msg = f"Cypher syntax: {err_str}"
            elif elapsed_ms >= 10_000:
                status_msg = "Query exceeded 10s timeout"
            else:
                status_msg = err_str

            return {
                "status": "ERROR",
                "error": status_msg,
                "records": [],
                "row_count": 0,
                "execution_ms": elapsed_ms,
            }
