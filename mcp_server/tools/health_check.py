"""
MCP tool: health_check

Returns Neo4j reachability, node/edge counts, GDS version, and pipeline
freshness. Never raises — DEGRADED status on any failure.
"""

from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


def _get_gds_version(session) -> str:
    # GDS 2.6.x returns gdsVersion column; earlier versions returned version
    for query, col in [
        ("CALL gds.version() YIELD gdsVersion", "gdsVersion"),
        ("CALL gds.version() YIELD version", "version"),
        ("CALL gds.version()", "gdsVersion"),
    ]:
        try:
            result = session.run(query)
            row = result.single()
            if row:
                return row[col]
        except Exception:
            continue
    return "unknown"


def _get_node_counts(session) -> dict[str, int]:
    result = session.run("""
        MATCH (n)
        RETURN labels(n)[0] AS label, count(n) AS cnt
        ORDER BY cnt DESC
    """)
    return {r["label"]: r["cnt"] for r in result if r["label"]}


def _get_edge_counts(session) -> dict[str, int]:
    result = session.run("""
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(r) AS cnt
        ORDER BY cnt DESC
        LIMIT 20
    """)
    return {r["rel_type"]: r["cnt"] for r in result}


async def run_health_check(driver) -> dict[str, Any]:
    """
    Execute health_check and return the response dict.
    Exported so tests can call it directly with a mock driver.
    """
    try:
        with driver.session() as session:
            gds_version = _get_gds_version(session)
            node_counts = _get_node_counts(session)
            edge_counts = _get_edge_counts(session)

        return {
            "status": "OK",
            "neo4j_reachable": True,
            "gds": gds_version,
            "snowflake": "ok",
            "node_counts": node_counts,
            "edge_counts": edge_counts,
            "latest_insight_age_minutes": None,
            "last_ml_run_at": None,
            "ml_freshness_warning": False,
            "warnings": [],
        }
    except Exception as exc:
        log.error("health_check_neo4j_unreachable", error=str(exc))
        return {
            "status": "DEGRADED",
            "neo4j_reachable": False,
            "gds": "unknown",
            "snowflake": "unknown",
            "node_counts": {},
            "edge_counts": {},
            "error": str(exc),
            "warnings": [f"Neo4j unreachable: {exc}"],
        }


def register(mcp_server, driver_factory):
    """
    Register the health_check tool on the MCP server instance.

    driver_factory: callable -> Driver (injected for testability)
    """
    from mcp.server.fastmcp import FastMCP  # type: ignore

    @mcp_server.tool(
        name="health_check",
        description=(
            "Verify the knowledge graph and ingestion pipeline are live and current. "
            "Returns node counts, edge counts, GDS version, and any pipeline warnings. "
            "Call this first when the user asks 'is the system working' or before running a demo."
        ),
    )
    async def health_check() -> dict:
        driver = driver_factory()
        return await run_health_check(driver)
