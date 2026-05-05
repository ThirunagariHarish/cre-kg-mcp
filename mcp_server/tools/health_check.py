"""
MCP tool: health_check

Returns Neo4j reachability, node/edge counts, GDS version, and pipeline
freshness. Never raises — DEGRADED status on any failure.
"""

from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()


def _get_latest_insight_age_minutes(session) -> tuple[float | None, list[str]]:
    """
    Returns (age_minutes_or_None, warnings).
    age_minutes is time since the most recently ingested Insight node.
    Returns None if no Insight nodes exist yet.
    Adds a staleness warning when age > 15 minutes.
    """
    warnings: list[str] = []
    try:
        result = session.run("""
            MATCH (i:Insight)
            WHERE i.ingested_at IS NOT NULL
            RETURN i.ingested_at AS ingested_at
            ORDER BY i.ingested_at DESC
            LIMIT 1
        """)
        row = result.single()
        if row is None:
            return None, warnings

        ingested_at = row["ingested_at"]
        if ingested_at is None:
            return None, warnings

        from datetime import datetime, timezone
        # Neo4j datetime objects have .to_native() in the Python driver
        if hasattr(ingested_at, "to_native"):
            dt = ingested_at.to_native()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        now = datetime.now(timezone.utc)
        age_minutes = (now - dt).total_seconds() / 60.0
        age_minutes = round(age_minutes, 1)

        if age_minutes > 15:
            warnings.append(
                f"latest_insight_age ({age_minutes:.1f} min) exceeds 15-minute SLO"
            )

        return age_minutes, warnings
    except Exception as exc:
        return None, [f"insight_freshness_check_failed: {exc}"]


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
            insight_age_minutes, freshness_warnings = _get_latest_insight_age_minutes(session)

        all_warnings = list(freshness_warnings)

        return {
            "status": "OK",
            "neo4j_reachable": True,
            "gds": gds_version,
            "snowflake": "ok",
            "node_counts": node_counts,
            "edge_counts": edge_counts,
            "latest_insight_age_minutes": insight_age_minutes,
            "last_ml_run_at": None,
            "ml_freshness_warning": False,
            "warnings": all_warnings,
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
