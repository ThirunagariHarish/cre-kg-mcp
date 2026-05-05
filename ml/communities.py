"""
ml/communities.py — Louvain community detection via Neo4j GDS.

Writes 'community_id' to all projected nodes.
Helper top_communities(n) returns top-N communities by size.

Entrypoint: python -m ml.communities
Also importable by ml/refresh.py.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import structlog
from dotenv import load_dotenv
from neo4j import GraphDatabase, Driver

load_dotenv()
log = structlog.get_logger()

try:
    from graphdatascience import GraphDataScience  # type: ignore
except ImportError:
    GraphDataScience = None  # type: ignore

GRAPH_NAME = "cre-louvain-projection"
COMMUNITY_WRITE_PROPERTY = "community_id"

NODE_LABELS = [
    "Broker",
    "Property",
    "Tenant",
    "Lease",
    "Pursuit",
    "Market",
    "Submarket",
    "AssetClass",
]

RELATIONSHIP_TYPES = [
    "COVERS",
    "SPECIALIZES_IN",
    "REPRESENTS",
    "SPOC_FOR",
    "BELONGS_TO",
    "LOCATED_IN",
    "PART_OF",
    "CLASSIFIED_AS",
    "OWNED_BY",
    "ON",
    "TENANT_IS",
    "LANDLORD_IS",
    "BROKERED_BY",
    "FOR",
    "ASSIGNED_TO",
    "HAS_SERVICE_LINE",
    "ABOUT",
]


def _get_driver() -> Driver:
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
    return GraphDatabase.driver(uri, auth=(user, password))


def _drop_projection_if_exists(gds) -> None:
    try:
        gds.graph.drop(GRAPH_NAME)
        log.info("gds_projection_dropped", graph_name=GRAPH_NAME)
    except Exception:
        pass


def run_communities(driver: Driver | None = None) -> dict[str, Any]:
    """
    Run Louvain and write 'community_id' to all projected nodes.
    Returns summary dict.
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    try:
        if GraphDataScience is None:
            raise ImportError("graphdatascience package not installed")

        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "hackathon_local_only")
        gds = GraphDataScience(uri, auth=(user, password))

        log.info("communities_starting")
        t0 = time.time()

        _drop_projection_if_exists(gds)

        node_projection = {label: {"label": label} for label in NODE_LABELS}
        rel_projection = {
            rel: {"type": rel, "orientation": "UNDIRECTED"}
            for rel in RELATIONSHIP_TYPES
        }
        G, proj_stats = gds.graph.project(GRAPH_NAME, node_projection, rel_projection)
        log.info("gds_projection_created", node_count=proj_stats["nodeCount"])

        # Run Louvain write
        result = gds.louvain.write(G, writeProperty=COMMUNITY_WRITE_PROPERTY)

        elapsed = time.time() - t0
        community_count = result.get("communityCount", 0) if hasattr(result, "get") else 0
        node_count = result.get("nodeCount", 0) if hasattr(result, "get") else 0

        log.info(
            "communities_complete",
            community_count=community_count,
            node_count=node_count,
            elapsed_s=round(elapsed, 1),
        )

        _drop_projection_if_exists(gds)
        gds.close()

        return {
            "status": "OK",
            "community_count": community_count,
            "node_count": node_count,
            "elapsed_s": round(elapsed, 1),
        }

    except Exception as exc:
        log.error("communities_failed", error=str(exc))
        return {"status": "ERROR", "error": str(exc)}
    finally:
        if close_after and driver is not None:
            driver.close()


def top_communities(n: int = 10, driver: Driver | None = None) -> list[dict[str, Any]]:
    """
    Return the top-N communities by member count.

    Each entry: {community_id, size, sample_member_ids, sample_member_labels}
    Queries the 'community_id' property written by run_communities().
    """
    close_after = driver is None
    if driver is None:
        driver = _get_driver()

    try:
        with driver.session() as session:
            # Aggregate community sizes across all labeled nodes
            result = session.run(
                """
                MATCH (n)
                WHERE n.community_id IS NOT NULL
                  AND (n:Broker OR n:Property OR n:Tenant OR n:Lease
                       OR n:Pursuit OR n:Market OR n:Submarket OR n:AssetClass)
                WITH n.community_id AS cid, count(n) AS sz,
                     collect({
                       id: coalesce(n.broker_key, n.property_key, n.tenant_key,
                                    n.lease_key, n.pursuit_id, n.name, 'unknown'),
                       label: labels(n)[0]
                     })[0..5] AS samples
                ORDER BY sz DESC
                LIMIT $n
                RETURN cid, sz, samples
                """,
                n=n,
            )
            communities = []
            for row in result:
                communities.append(
                    {
                        "community_id": row["cid"],
                        "size": row["sz"],
                        "sample_member_ids": [s["id"] for s in row["samples"]],
                        "sample_member_labels": [s["label"] for s in row["samples"]],
                    }
                )
            return communities
    except Exception as exc:
        log.error("top_communities_failed", error=str(exc))
        return []
    finally:
        if close_after and driver is not None:
            driver.close()


if __name__ == "__main__":
    result = run_communities()
    print(result)
    if result.get("status") != "OK":
        sys.exit(1)
    tops = top_communities(5)
    print(f"Top 5 communities: {tops}")
