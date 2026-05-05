"""
ml/embeddings.py — Node2Vec node embeddings via Neo4j GDS.

Locked parameters (Atlas architecture §8.3 — do NOT change):
  embeddingDimension: 128
  walkLength:        80
  walksPerNode:      10
  iterations:        5
  writeProperty:     'node2vec_embedding'

Uses a separate writeProperty ('node2vec_embedding') from Phase 2 Insight
embeddings ('embedding', 384-dim sentence-transformers) to avoid collision.

Entrypoint: python -m ml.embeddings
Also importable by ml/refresh.py: from ml.embeddings import run_embeddings
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

# ---------------------------------------------------------------------------
# Locked GDS parameters (architecture §8.3)
# ---------------------------------------------------------------------------
GRAPH_NAME = "cre-node2vec-projection"
EMBEDDING_DIM = 128
WALK_LENGTH = 80
WALKS_PER_NODE = 10
ITERATIONS = 5
WRITE_PROPERTY = "node2vec_embedding"

# Node labels to project (all business-entity nodes that benefit from structural embeddings)
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

# Relationship types to project (from data-model.md §2)
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
    """Drop existing projection to ensure idempotency."""
    try:
        gds.graph.drop(GRAPH_NAME)
        log.info("gds_projection_dropped", graph_name=GRAPH_NAME)
    except Exception:
        # Graph doesn't exist — that's fine
        pass


def _project_graph(gds) -> Any:
    """
    Project the in-memory GDS graph over all CRE entity labels and their
    relationships.  Idempotent: drops any existing projection first.
    """
    _drop_projection_if_exists(gds)

    # Build node projection dict: all labels projected with no properties
    node_projection = {label: {"label": label} for label in NODE_LABELS}

    # Build relationship projection dict: all types projected as UNDIRECTED
    # (Node2Vec performs random walks — undirected gives richer connectivity)
    rel_projection = {
        rel: {"type": rel, "orientation": "UNDIRECTED"}
        for rel in RELATIONSHIP_TYPES
    }

    G, stats = gds.graph.project(GRAPH_NAME, node_projection, rel_projection)
    log.info(
        "gds_projection_created",
        graph_name=GRAPH_NAME,
        node_count=stats["nodeCount"],
        relationship_count=stats["relationshipCount"],
    )
    return G


def run_embeddings(driver: Driver | None = None) -> dict[str, Any]:
    """
    Run Node2Vec and write 'node2vec_embedding' to all projected nodes.

    Returns a summary dict with nodeCount and writeMillis.
    Importable by ml.refresh — also works as __main__.
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

        log.info("embeddings_starting", graph_name=GRAPH_NAME)
        t0 = time.time()

        G = _project_graph(gds)

        # Run Node2Vec write — locked params per architecture §8.3
        result = gds.node2vec.write(
            G,
            embeddingDimension=EMBEDDING_DIM,
            walkLength=WALK_LENGTH,
            walksPerNode=WALKS_PER_NODE,
            iterations=ITERATIONS,
            writeProperty=WRITE_PROPERTY,
        )

        elapsed = time.time() - t0
        node_count = result.get("nodeCount", 0) if hasattr(result, "get") else 0
        write_millis = result.get("writeMillis", 0) if hasattr(result, "get") else 0

        log.info(
            "embeddings_complete",
            node_count=node_count,
            write_millis=write_millis,
            elapsed_s=round(elapsed, 1),
        )

        # Drop the projection to free GDS memory
        _drop_projection_if_exists(gds)
        gds.close()

        return {
            "status": "OK",
            "node_count": node_count,
            "write_millis": write_millis,
            "elapsed_s": round(elapsed, 1),
            "embedding_dim": EMBEDDING_DIM,
            "write_property": WRITE_PROPERTY,
        }

    except Exception as exc:
        log.error("embeddings_failed", error=str(exc))
        return {"status": "ERROR", "error": str(exc)}
    finally:
        if close_after and driver is not None:
            driver.close()


if __name__ == "__main__":
    result = run_embeddings()
    print(result)
    if result.get("status") != "OK":
        sys.exit(1)
