"""
MCP tool: list_communities

Returns Louvain communities discovered in the graph with size and sample members.
Reads the 'community_id' property written by ml/communities.py.

M-P3-4 FIX: Computes dominant_market and dominant_asset_class per community.
M-P3-6 FIX: _node_ref always returns {id, label, name} shape (not raw Neo4j nodes).

Conforms to api-contracts.md §8.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

log = structlog.get_logger()


# Cypher to pull community sizes, dominant market/asset_class, and per-community sample members.
# M-P3-4: Uses OPTIONAL MATCH to find Market and AssetClass nodes connected to community members.
_COMMUNITIES_QUERY = """
MATCH (n)
WHERE n.community_id IS NOT NULL
  AND (n:Broker OR n:Property OR n:Tenant)
WITH n.community_id AS cid, count(n) AS sz,
     collect(n)[0..5] AS sample_nodes
WHERE sz >= $min_size

// Compute dominant_market: highest-frequency Market connected to any community member
CALL {
  WITH cid
  MATCH (m2)
  WHERE m2.community_id = cid
    AND (m2:Broker OR m2:Property OR m2:Tenant)
  OPTIONAL MATCH (m2)-[:COVERS|LOCATED_IN|CLASSIFIED_AS*1..2]->(mkt:Market)
  WITH mkt.name AS mkt_name, count(*) AS mkt_cnt
  WHERE mkt_name IS NOT NULL
  ORDER BY mkt_cnt DESC
  LIMIT 1
  RETURN mkt_name AS dominant_market
}

// Compute dominant_asset_class: highest-frequency AssetClass connected to any community member
CALL {
  WITH cid
  MATCH (m3)
  WHERE m3.community_id = cid
    AND (m3:Broker OR m3:Property OR m3:Tenant)
  OPTIONAL MATCH (m3)-[:SPECIALIZES_IN|CLASSIFIED_AS]->(ac:AssetClass)
  WITH ac.name AS ac_name, count(*) AS ac_cnt
  WHERE ac_name IS NOT NULL
  ORDER BY ac_cnt DESC
  LIMIT 1
  RETURN ac_name AS dominant_asset_class
}

ORDER BY sz DESC
LIMIT $limit
RETURN cid, sz, sample_nodes, dominant_market, dominant_asset_class
"""

_LAST_RUN_QUERY = """
MATCH (m:MLRunMeta {key: 'global'})
RETURN m.last_run_at AS last_run_at
"""


def _node_ref(n) -> dict[str, str]:
    """
    M-P3-6 FIX: Extract id/label/name triple from a Neo4j node.
    Always returns consistent {id: str, label: str, name: str} shape.
    """
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
    return {"id": str(node_id), "label": str(label), "name": str(name)}


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
                # M-P3-4: dominant market and asset class
                "dominant_market": row["dominant_market"],
                "dominant_asset_class": row["dominant_asset_class"],
            }
            if include_members_sample:
                # M-P3-6: always use _node_ref for consistent {id, label, name} shape
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
