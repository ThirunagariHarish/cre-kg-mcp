"""
MCP tool: semantic_search

Find graph nodes semantically similar to a text query or anchor node, using
stored embedding vectors. Supports label=Insight with 384-dim text embeddings
(all-MiniLM-L6-v2), and label=Broker/Property/Tenant with 128-dim Node2Vec
embeddings (Phase 3 — gracefully degrades when not yet computed).

Cosine similarity is computed in Python over the stored embedding lists because
Neo4j 5.x vector index approximate-nearest-neighbour queries require the query
vector to match the index dimension exactly — and Phase 2 only populates Insight
embeddings (384-dim) while Phase 3 will populate Broker/Property/Tenant (128-dim).

Filter parameters:
  market        — canonical market name (case-insensitive)
  asset_class   — canonical asset class (case-insensitive)
  date_from     — ISO date string, inclusive (published_at >= date_from)
  date_to       — ISO date string, inclusive (published_at <= date_to)
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# Lazy-load the sentence-transformers model to avoid import overhead in tests
_model = None
_TRANSFORMERS_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass


def _get_model():
    global _model
    if _model is None:
        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError("sentence-transformers not installed")
        log.info("semantic_search_model_loading", model="all-MiniLM-L6-v2")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("semantic_search_model_loaded")
    return _model


def _embed_query(text: str) -> list[float]:
    """Embed query text using all-MiniLM-L6-v2, returning a 384-dim vector."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two pre-normalised vectors."""
    if len(a) != len(b):
        # Mismatched dims — different embedding models; similarity undefined
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    # If both are l2-normalised, dot product IS cosine similarity
    return dot


# ---------------------------------------------------------------------------
# Cypher templates
# ---------------------------------------------------------------------------

_INSIGHT_QUERY = """
MATCH (i:Insight)
WHERE i.embedding IS NOT NULL
{filter_clause}
RETURN
  i.insight_id  AS node_id,
  i.title       AS name,
  i.body        AS body,
  i.market      AS market,
  i.asset_class AS asset_class,
  i.published_at AS published_at,
  i.embedding   AS embedding
"""

_ANCHOR_INSIGHT_QUERY = """
MATCH (i:Insight {insight_id: $anchor_id})
RETURN i.embedding AS embedding, i.title AS name
"""

_BROKER_QUERY = """
MATCH (b:Broker)
WHERE b.embedding IS NOT NULL
RETURN
  b.broker_key AS node_id,
  b.name       AS name,
  b.embedding  AS embedding
"""

_ANCHOR_BROKER_QUERY = """
MATCH (b:Broker {broker_key: $anchor_id})
RETURN b.embedding AS embedding, b.name AS name
"""

_PROPERTY_QUERY = """
MATCH (p:Property)
WHERE p.embedding IS NOT NULL
RETURN
  p.property_key  AS node_id,
  p.address_line1 AS name,
  p.embedding     AS embedding
"""

_ANCHOR_PROPERTY_QUERY = """
MATCH (p:Property {property_key: $anchor_id})
RETURN p.embedding AS embedding, p.address_line1 AS name
"""

_TENANT_QUERY = """
MATCH (t:Tenant)
WHERE t.embedding IS NOT NULL
RETURN
  t.tenant_key AS node_id,
  t.name       AS name,
  t.embedding  AS embedding
"""

_ANCHOR_TENANT_QUERY = """
MATCH (t:Tenant {tenant_key: $anchor_id})
RETURN t.embedding AS embedding, t.name AS name
"""


_LABEL_CONFIG = {
    "Insight": {
        "list_query_template": _INSIGHT_QUERY,
        "anchor_query": _ANCHOR_INSIGHT_QUERY,
        "anchor_id_param": "anchor_id",
    },
    "Broker": {
        "list_query_template": _BROKER_QUERY,
        "anchor_query": _ANCHOR_BROKER_QUERY,
        "anchor_id_param": "anchor_id",
    },
    "Property": {
        "list_query_template": _PROPERTY_QUERY,
        "anchor_query": _ANCHOR_PROPERTY_QUERY,
        "anchor_id_param": "anchor_id",
    },
    "Tenant": {
        "list_query_template": _TENANT_QUERY,
        "anchor_query": _ANCHOR_TENANT_QUERY,
        "anchor_id_param": "anchor_id",
    },
}


def _build_insight_filter(
    market: Optional[str],
    asset_class: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> str:
    """Build a Cypher WHERE fragment for Insight filters."""
    q = "'"  # single quote character — avoids f-string nesting issues
    clauses = []
    if market:
        m = market.replace("'", "")
        clauses.append(f"AND toLower(i.market) = toLower({q}{m}{q})")
    if asset_class:
        ac = asset_class.replace("'", "")
        clauses.append(f"AND toLower(i.asset_class) = toLower({q}{ac}{q})")
    if date_from:
        df = date_from.replace("'", "")
        clauses.append(f"AND i.published_at >= datetime({q}{df}{q})")
    if date_to:
        dt_ = date_to.replace("'", "")
        clauses.append(f"AND i.published_at <= datetime({q}{dt_}{q})")
    return " ".join(clauses)


async def run_semantic_search(
    driver,
    *,
    label: str,
    query_text: Optional[str] = None,
    anchor_node_id: Optional[str] = None,
    top_k: int = 10,
    min_score: float = 0.0,
    filter_market: Optional[str] = None,
    filter_asset_class: Optional[str] = None,
    filter_date_from: Optional[str] = None,
    filter_date_to: Optional[str] = None,
) -> dict[str, Any]:
    """Core logic — exported for direct test use."""
    if label not in _LABEL_CONFIG:
        return {
            "status": "ERROR",
            "error": f"Unknown label '{label}'. Must be one of: {list(_LABEL_CONFIG.keys())}",
            "results": [],
            "truncated": False,
        }

    config = _LABEL_CONFIG[label]

    # --- Obtain query embedding ---
    query_embedding: Optional[list[float]] = None

    if query_text:
        try:
            query_embedding = _embed_query(query_text)
        except Exception as exc:
            return {
                "status": "ERROR",
                "error": f"Embedding failed: {exc}",
                "results": [],
                "truncated": False,
            }

    elif anchor_node_id:
        try:
            with driver.session() as session:
                result = session.run(
                    config["anchor_query"],
                    anchor_id=anchor_node_id,
                )
                row = result.single()
                if row is None:
                    return {
                        "status": "ERROR",
                        "error": "Anchor node not found",
                        "results": [],
                        "truncated": False,
                    }
                query_embedding = list(row["embedding"])
        except Exception as exc:
            return {
                "status": "ERROR",
                "error": f"Anchor lookup failed: {exc}",
                "results": [],
                "truncated": False,
            }

    else:
        return {
            "status": "ERROR",
            "error": "Provide either query_text or anchor_node_id",
            "results": [],
            "truncated": False,
        }

    # --- Fetch candidate nodes ---
    try:
        with driver.session() as session:
            # Build filter clause for Insight queries
            filter_clause = ""
            if label == "Insight":
                filter_clause = _build_insight_filter(
                    filter_market, filter_asset_class, filter_date_from, filter_date_to
                )
                cypher = config["list_query_template"].format(filter_clause=filter_clause)
            else:
                cypher = config["list_query_template"].format(filter_clause="")

            result = session.run(cypher)
            candidates = [dict(r) for r in result]
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": f"Graph query failed: {exc}",
            "results": [],
            "truncated": False,
        }

    if not candidates:
        return {
            "status": "DEGRADED",
            "error": "Embeddings not yet generated; run ML enrichment" if label != "Insight" else None,
            "results": [],
            "truncated": False,
        }

    # --- Score candidates ---
    scored: list[tuple[float, dict]] = []
    for cand in candidates:
        emb = cand.get("embedding")
        if not emb:
            continue
        score = _cosine_similarity(query_embedding, list(emb))
        if score >= min_score:
            scored.append((score, cand))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)

    truncated = len(scored) > top_k
    top = scored[:top_k]

    results = []
    for score, cand in top:
        node_id = str(cand.get("node_id", ""))
        node_name = str(cand.get("name", ""))
        entry: dict[str, Any] = {
            "node": {
                "id": node_id,
                "label": label,
                "name": node_name,
            },
            "score": round(score, 4),
        }
        # Include extra fields for Insight
        if label == "Insight" and cand.get("body"):
            entry["body_snippet"] = cand["body"][:200]
            entry["market"] = cand.get("market")
            entry["asset_class"] = cand.get("asset_class")
            entry["published_at"] = str(cand.get("published_at") or "")

        results.append(entry)

    status = "OK" if results else "OK"
    if not candidates:
        status = "DEGRADED"

    return {
        "status": status,
        "label": label,
        "results": results,
        "truncated": truncated,
    }


def register(mcp_server, driver_factory):
    """Register the semantic_search tool on the MCP server instance."""

    @mcp_server.tool(
        name="semantic_search",
        description=(
            "Find graph nodes semantically similar to either a text query or an anchor "
            "node, using stored embedding vectors. Use this to answer 'find brokers like X', "
            "'find properties similar to this one', or 'find insights related to sublease "
            "pressure / tenant downsizing / industrial absorption'. "
            "label must be one of: Insight, Broker, Property, Tenant. "
            "Provide query_text OR anchor_node_id (not both). "
            "Optional filter fields for Insight: market, asset_class, date_from, date_to."
        ),
    )
    async def semantic_search(
        label: str,
        query_text: Optional[str] = None,
        anchor_node_id: Optional[str] = None,
        top_k: int = 10,
        min_score: float = 0.0,
        market: Optional[str] = None,
        asset_class: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        driver = driver_factory()
        return await run_semantic_search(
            driver,
            label=label,
            query_text=query_text,
            anchor_node_id=anchor_node_id,
            top_k=top_k,
            min_score=min_score,
            filter_market=market,
            filter_asset_class=asset_class,
            filter_date_from=date_from,
            filter_date_to=date_to,
        )
