"""
MCP tool: list_communities

Returns Louvain communities discovered in the graph with size and sample members.
Reads the 'community_id' property written by ml/communities.py.

Conforms to api-contracts.md §8.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

log = structlog.get_logger()


# Cypher to pull community sizes and per-community sample members with names
_COMMUNITIES_QUERY = """
MATCH (n)
WHERE n.community_id IS NOT NULL
  AND (n:Broker OR n:Property OR n:Tenant)
WITH n.community_id AS cid, count(n) AS sz,
     collect(n)[0..5] AS sample_nodes
WHERE sz >= $min_size
ORDER BY sz DESC
LIMIT $limit
RETURN cid, sz, sample_nodes
"""

_LAST_RUN_QUERY = """
MATCH (m:MLRunMeta {key: 'global'})
RETURN m.last_run_at AS last_run_at
"""


def _node_ref(n) -> dict[str, str]:
    """Extract id/label/name triple from a Neo4j node."""
    props = dict(n)
    label = list(n.labels)[0] if n.labels else "Unknown"

    # ID: prefer merge key, then source PK, then name
    node_id = (
        props.get("broker_key")
        or props.get("property_key")
        or props.get("tenant_key")
        or props.get("name")
        or str(n.id)
    )
    # Name: broker name, property address, tenant name
    name = (
        props.get("name")
        or props.get("address_line1")
        or props.get("broker_key", "")
    )
    return {"id": node_id, "label": label, "name": name}


async def run_list_communities(
    driver,
    *,
    min_size: int = 5,
    limit: int = 20,
    include_members_sample: bool = False,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    try:
        with driver.session() as session:
            # Fetch last ML run time
            computed_at: Optional[str] = None
            try:
                meta_row = session.run(_LAST_RUN_QUERY).single()
                if meta_row and meta_row["last_run_at"]:
                    val = meta_row["last_run_at"]
                    computed_at = str(val)
            except Exception:
                pass

            result = session.run(
                _COMMUNITIES_QUERY,
                min_size=min_size,
                limit=limit,
            )
            rows = list(result)

        if not rows:
            return {
                "status": "DEGRADED",
                "error": "Louvain has not yet run or no communities meet min_size",
                "communities": [],
                "computed_at": computed_at,
                "truncated": False,
            }

        communities = []
        for row in rows:
            entry: dict[str, Any] = {
                "community_id": row["cid"],
                "size": row["sz"],
            }
            if include_members_sample:
                sample = [_node_ref(n) for n in row["sample_nodes"]]
                entry["members_sample"] = sample
            communities.append(entry)

        return {
            "status": "OK",
            "computed_at": computed_at,
            "communities": communities,
            "truncated": len(communities) >= limit,
        }

    except Exception as exc:
        log.error("list_communities_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "communities": [],
            "truncated": False,
        }


def register(mcp_server, driver_factory):
    """Register the list_communities tool on the MCP server instance."""

    @mcp_server.tool(
        name="list_communities",
        description=(
            "List Louvain communities discovered in the CRE knowledge graph with their "
            "size and dominant attributes. Use this to answer 'what natural market clusters "
            "exist?' or 'list the top communities and their members'. "
            "Parameters: min_size (default 5), limit (default 20), "
            "include_members_sample (bool, default false — set true to see node samples). "
            "Returns DEGRADED if community detection has not yet run."
        ),
    )
    async def list_communities(
        min_size: int = 5,
        limit: int = 20,
        include_members_sample: bool = False,
    ) -> dict:
        driver = driver_factory()
        return await run_list_communities(
            driver,
            min_size=min_size,
            limit=limit,
            include_members_sample=include_members_sample,
        )
