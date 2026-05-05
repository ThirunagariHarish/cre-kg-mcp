"""
MCP tool: traverse_graph

Return the n-hop neighbourhood around a starting node, optionally filtered
by relationship types and target labels.

Caps: 200 nodes / 500 edges (Atlas locked).  Max 3 hops.
When cap hit, prunes by BFS order so closest-to-start nodes are kept.

Conforms to api-contracts.md §7.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Optional

import structlog

log = structlog.get_logger()

NODE_CAP = 200
EDGE_CAP = 500
MAX_HOPS = 3

# Labels that carry a stable ID we can surface
_MERGE_KEY_PROPS = [
    "broker_key",
    "property_key",
    "tenant_key",
    "landlord_key",
    "lease_key",
    "pursuit_id",
    "insight_id",
    "client_key",
    "name",
]


def _find_start_node(session, start_node_id: str, start_label: Optional[str]) -> Optional[dict]:
    """Locate start node by id across known merge key properties."""
    label_clause = f":{start_label}" if start_label else ""
    for prop in _MERGE_KEY_PROPS:
        query = f"""
        MATCH (n{label_clause})
        WHERE n.{prop} = $node_id
        RETURN id(n) AS internal_id,
               labels(n)[0] AS label,
               n.{prop} AS node_key,
               n
        LIMIT 1
        """
        try:
            result = session.run(query, node_id=start_node_id)
            row = result.single()
            if row:
                return {
                    "internal_id": row["internal_id"],
                    "label": row["label"],
                    "node_key": row["node_key"],
                    "props": dict(row["n"]),
                }
        except Exception:
            continue
    return None


def _extract_node_id(props: dict, labels_list: list) -> str:
    """Derive the stable id from node properties."""
    for key in _MERGE_KEY_PROPS:
        if key in props and props[key]:
            return str(props[key])
    return str(props.get("name", "unknown"))


def _node_display_name(props: dict) -> str:
    return (
        props.get("name")
        or props.get("address_line1")
        or props.get("broker_key", "")
        or "unknown"
    )


def _bfs_traverse(
    session,
    start_internal_id: int,
    max_hops: int,
    relationship_types: list[str],
    target_labels: list[str],
    node_cap: int,
    edge_cap: int,
) -> tuple[list[dict], list[dict], bool]:
    """
    BFS from start_internal_id up to max_hops.
    Returns (nodes, edges, truncated).
    Prunes by BFS order — closest nodes are kept when cap is hit.
    """
    # Build relationship type filter clause
    if relationship_types:
        rel_types = "|".join(relationship_types)
        rel_pattern = f"[r:{rel_types}]"
    else:
        rel_pattern = "[r]"

    visited_node_ids: set[int] = {start_internal_id}
    # Queue: (internal_id, hop_depth)
    queue: deque[tuple[int, int]] = deque([(start_internal_id, 0)])

    collected_nodes: list[dict] = []
    collected_edges: list[dict] = []
    seen_edges: set[tuple] = set()

    truncated = False

    # Fetch the start node itself
    start_result = session.run(
        "MATCH (n) WHERE id(n) = $iid RETURN n, labels(n) AS lbls",
        iid=start_internal_id,
    )
    start_row = start_result.single()
    if start_row:
        props = dict(start_row["n"])
        lbls = list(start_row["lbls"])
        label = lbls[0] if lbls else "Unknown"
        node_id = _extract_node_id(props, lbls)
        name = _node_display_name(props)
        collected_nodes.append({"id": node_id, "label": label, "name": name})

    while queue:
        current_iid, depth = queue.popleft()

        if depth >= max_hops:
            continue

        # Fetch neighbours
        neighbours_query = f"""
        MATCH (n)-{rel_pattern}-(m)
        WHERE id(n) = $iid
        RETURN id(m) AS m_iid, m, labels(m) AS m_lbls,
               type(r) AS rel_type,
               id(startNode(r)) AS from_iid,
               id(endNode(r)) AS to_iid,
               startNode(r) AS from_node,
               endNode(r) AS to_node
        """
        try:
            result = session.run(neighbours_query, iid=current_iid)
        except Exception as exc:
            log.warning("traverse_neighbour_query_failed", error=str(exc))
            continue

        for row in result:
            m_iid = row["m_iid"]
            m_props = dict(row["m"])
            m_lbls = list(row["m_lbls"])
            m_label = m_lbls[0] if m_lbls else "Unknown"

            # Apply target_labels filter
            if target_labels and m_label not in target_labels:
                continue

            # Check node cap
            if len(collected_nodes) >= node_cap:
                truncated = True
                continue

            # Add node if not visited
            if m_iid not in visited_node_ids:
                visited_node_ids.add(m_iid)
                m_node_id = _extract_node_id(m_props, m_lbls)
                m_name = _node_display_name(m_props)
                collected_nodes.append({"id": m_node_id, "label": m_label, "name": m_name})
                queue.append((m_iid, depth + 1))

            # Add edge if not seen
            from_iid = row["from_iid"]
            to_iid = row["to_iid"]
            rel_type = row["rel_type"]
            edge_key = (from_iid, to_iid, rel_type)

            if edge_key not in seen_edges:
                if len(collected_edges) >= edge_cap:
                    truncated = True
                    continue
                seen_edges.add(edge_key)

                from_props = dict(row["from_node"])
                to_props = dict(row["to_node"])
                from_id = _extract_node_id(from_props, [])
                to_id = _extract_node_id(to_props, [])
                collected_edges.append({"from": from_id, "to": to_id, "type": rel_type})

    return collected_nodes, collected_edges, truncated


async def run_traverse_graph(
    driver,
    *,
    start_node_id: str,
    start_label: Optional[str] = None,
    max_hops: int = 2,
    relationship_types: Optional[list[str]] = None,
    target_labels: Optional[list[str]] = None,
    node_cap: int = NODE_CAP,
    edge_cap: int = EDGE_CAP,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    # Enforce architectural caps
    node_cap = min(node_cap, NODE_CAP)
    edge_cap = min(edge_cap, EDGE_CAP)
    max_hops = min(max_hops, MAX_HOPS)

    rel_types = relationship_types or []
    tgt_labels = target_labels or []

    try:
        with driver.session() as session:
            start_node = _find_start_node(session, start_node_id, start_label)
            if start_node is None:
                return {
                    "status": "ERROR",
                    "error": f"Start node not found: {start_node_id}",
                    "nodes": [],
                    "edges": [],
                    "truncated": False,
                    "node_count": 0,
                    "edge_count": 0,
                }

            nodes, edges, truncated = _bfs_traverse(
                session,
                start_node["internal_id"],
                max_hops=max_hops,
                relationship_types=rel_types,
                target_labels=tgt_labels,
                node_cap=node_cap,
                edge_cap=edge_cap,
            )

        warnings = []
        if truncated:
            warnings.append(
                f"Result truncated at {node_cap} nodes / {edge_cap} edges. "
                "Narrow your start node or apply relationship_types / target_labels filters."
            )

        return {
            "status": "OK",
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "warnings": warnings,
        }

    except Exception as exc:
        log.error("traverse_graph_failed", error=str(exc))
        return {
            "status": "ERROR",
            "error": str(exc),
            "nodes": [],
            "edges": [],
            "truncated": False,
            "node_count": 0,
            "edge_count": 0,
        }


def register(mcp_server, driver_factory):
    """Register the traverse_graph tool on the MCP server instance."""

    @mcp_server.tool(
        name="traverse_graph",
        description=(
            "Return the n-hop neighbourhood around a starting node, optionally filtered "
            "by relationship types and target labels. Use this for exploratory questions "
            "the high-level tools do not cover, e.g. 'show all tenants connected to this "
            "landlord's portfolio' or 'show the subgraph around broker X'. "
            "Results are capped at 200 nodes / 500 edges; if hit you get truncated: true "
            "and should narrow your start node or apply filters. "
            "Required: start_node_id (merge key, e.g. broker_key or property_key). "
            "Optional: start_label, max_hops (1-3, default 2), relationship_types (list), "
            "target_labels (list), node_cap (≤200), edge_cap (≤500)."
        ),
    )
    async def traverse_graph(
        start_node_id: str,
        start_label: Optional[str] = None,
        max_hops: int = 2,
        relationship_types: Optional[list[str]] = None,
        target_labels: Optional[list[str]] = None,
        node_cap: int = NODE_CAP,
        edge_cap: int = EDGE_CAP,
    ) -> dict:
        driver = driver_factory()
        return await run_traverse_graph(
            driver,
            start_node_id=start_node_id,
            start_label=start_label,
            max_hops=max_hops,
            relationship_types=relationship_types,
            target_labels=target_labels,
            node_cap=node_cap,
            edge_cap=edge_cap,
        )
