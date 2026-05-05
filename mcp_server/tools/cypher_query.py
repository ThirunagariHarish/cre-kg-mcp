"""
MCP tool: cypher_query — DEBUG ONLY, DANGEROUS.

Executes arbitrary Cypher. read_only=True runs in a READ transaction and
the Neo4j driver will reject write clauses at the server side.

Write mode is gated behind ALLOW_WRITE_CYPHER=1 environment variable.
When unset, any call with read_only=False is rejected before hitting Neo4j.

Audit: every call emits an INFO log line with query hash, read_only flag,
and (if available) caller context.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional

import structlog

log = structlog.get_logger()

_WRITE_KEYWORDS = frozenset(["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP"])

# 10-second transaction timeout in milliseconds (api-contracts.md §2)
_TX_TIMEOUT_MS = 10_000


def _has_write_clause(query: str) -> bool:
    """
    Heuristic pre-check before submitting to Neo4j.
    Not a substitute for server-side read transaction enforcement.
    """
    upper = query.upper()
    return any(kw in upper for kw in _WRITE_KEYWORDS)


def _query_hash(query: str) -> str:
    return hashlib.sha256(query.encode()).hexdigest()[:12]


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

        q_hash = _query_hash(query)

        # --- B1: gate write mode behind env var ---
        if not read_only:
            allow_write = os.environ.get("ALLOW_WRITE_CYPHER", "").strip() == "1"
            if not allow_write:
                log.info(
                    "cypher_query_write_blocked",
                    query_hash=q_hash,
                    read_only=read_only,
                )
                return {
                    "status": "error",
                    "error": "Write Cypher disabled — set ALLOW_WRITE_CYPHER=1 to enable",
                    "records": [],
                    "row_count": 0,
                    "execution_ms": 0,
                }

        # --- Audit log: every call ---
        log.info(
            "cypher_query_called",
            query_hash=q_hash,
            read_only=read_only,
            query_preview=query[:120],
        )

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
            # M5: enforce real 10s timeout via neo4j driver transaction timeout.
            # execute_read / execute_write accept timeout in seconds.
            timeout_s = _TX_TIMEOUT_MS / 1000.0
            if read_only:
                with driver.session() as session:
                    result = session.execute_read(
                        lambda tx: list(tx.run(query, **params)),
                        timeout=timeout_s,
                    )
            else:
                with driver.session() as session:
                    result = session.execute_write(
                        lambda tx: list(tx.run(query, **params)),
                        timeout=timeout_s,
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
            log.error("cypher_query_error", error=err_str, query_hash=q_hash)

            if "SyntaxError" in err_str or "syntax" in err_str.lower():
                status_msg = f"Cypher syntax: {err_str}"
            elif "timeout" in err_str.lower() or elapsed_ms >= _TX_TIMEOUT_MS:
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
