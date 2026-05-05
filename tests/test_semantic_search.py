"""
Tests for mcp_server/tools/semantic_search.py

Uses mocked Neo4j driver and pre-computed embeddings.
Verifies:
  - Ranking by cosine similarity (higher score first)
  - top_k truncation
  - min_score filtering
  - Insight filter (market, asset_class, date_from, date_to) applied via Cypher
  - anchor_node_id path
  - anchor node not found returns ERROR
  - Unknown label returns ERROR
  - Empty results when no embeddings exist returns DEGRADED (non-Insight labels)
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.tools.semantic_search import (
    run_semantic_search,
    _cosine_similarity,
    _build_insight_filter,
    _LABEL_CONFIG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit_vec(dim: int, dominant_idx: int) -> list[float]:
    """Return a mostly-zero unit vector with 1.0 at dominant_idx."""
    v = [0.0] * dim
    v[dominant_idx] = 1.0
    return v


def _make_driver_with_candidates(candidates: list[dict[str, Any]], anchor_embedding: list[float] | None = None):
    """
    Build a mock Neo4j driver that returns `candidates` from MATCH queries
    and `anchor_embedding` from an anchor lookup.
    """
    session_mock = MagicMock()
    driver_mock = MagicMock()

    def run_side_effect(cypher, **kwargs):
        result_mock = MagicMock()
        # Anchor lookup — single() call
        if "anchor_id" in kwargs and anchor_embedding is not None:
            single_mock = MagicMock()
            single_mock.__getitem__ = MagicMock(
                side_effect=lambda k: anchor_embedding if k == "embedding" else "Anchor Name"
            )
            result_mock.single.return_value = single_mock
        elif "anchor_id" in kwargs and anchor_embedding is None:
            result_mock.single.return_value = None
        else:
            # List query — return candidates
            result_mock.__iter__ = MagicMock(return_value=iter([
                _dict_to_cypher_record(c) for c in candidates
            ]))
            result_mock.single.return_value = None
        return result_mock

    session_mock.run.side_effect = run_side_effect
    driver_mock.session.return_value.__enter__ = MagicMock(return_value=session_mock)
    driver_mock.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver_mock


def _dict_to_cypher_record(d: dict) -> MagicMock:
    """Wrap a dict as a MagicMock that supports dict(record) via .items()."""
    record = MagicMock()
    record.keys.return_value = d.keys()
    record.__iter__ = MagicMock(return_value=iter(d.keys()))
    record.__getitem__ = MagicMock(side_effect=lambda k: d.get(k))
    # Make dict(record) work
    record.items.return_value = d.items()
    # The code does dict(r) so we need MagicMock to behave like a mapping
    record.__class__ = type("FakeRecord", (), {
        "keys": d.keys,
        "items": d.items,
        "__getitem__": lambda self, k: d.get(k),
        "__iter__": lambda self: iter(d.keys()),
    })
    return record


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    def test_identical_vectors_score_one(self):
        v = [0.5, 0.5, 0.5, 0.5]
        # Normalise manually
        norm = math.sqrt(sum(x ** 2 for x in v))
        v_n = [x / norm for x in v]
        assert abs(_cosine_similarity(v_n, v_n) - 1.0) < 1e-6

    def test_orthogonal_vectors_score_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_opposite_vectors_score_negative(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) < 0.0

    def test_mismatched_dims_returns_zero(self):
        a = [1.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


# ---------------------------------------------------------------------------
# _build_insight_filter
# ---------------------------------------------------------------------------

class TestBuildInsightFilter:
    """B-P2-1: _build_insight_filter must return (clause, params) with no literals."""

    def test_empty_filter_returns_empty_string_and_no_params(self):
        clause, params = _build_insight_filter(None, None, None, None)
        assert clause == ""
        assert params == {}

    def test_market_filter_uses_named_param_not_literal(self):
        """B-P2-1: market value must go through a $param, never inline."""
        clause, params = _build_insight_filter("Atlanta", None, None, None)
        # Param key exists; literal value NOT in clause string
        assert "filter_market" in params
        assert params["filter_market"] == "Atlanta"
        assert "Atlanta" not in clause, "Literal value must not appear in clause string"
        assert "$filter_market" in clause

    def test_injection_attempt_safely_parameterized(self):
        """B-P2-1: value containing quotes reaches params dict, not Cypher string."""
        evil = "' OR 1=1 OR i.market = '"
        clause, params = _build_insight_filter(evil, None, None, None)
        assert params.get("filter_market") == evil
        assert evil not in clause, "Injection payload must not appear in clause string"

    def test_date_from_uses_named_param(self):
        clause, params = _build_insight_filter(None, None, "2026-01-01", None)
        assert "filter_date_from" in params
        assert params["filter_date_from"] == "2026-01-01"
        assert "2026-01-01" not in clause

    def test_date_to_uses_named_param(self):
        clause, params = _build_insight_filter(None, None, None, "2026-12-31")
        assert "filter_date_to" in params
        assert params["filter_date_to"] == "2026-12-31"

    def test_all_filters_combined_returns_four_params(self):
        clause, params = _build_insight_filter("Atlanta", "Office", "2026-01-01", "2026-12-31")
        assert len(params) == 4
        assert "$filter_market" in clause
        assert "$filter_asset_class" in clause
        assert "$filter_date_from" in clause
        assert "$filter_date_to" in clause


class TestNonInsightLabelNoKeyError:
    """B-P2-2: Broker/Property/Tenant templates have no {filter_clause} placeholder."""

    def test_broker_template_has_no_filter_clause_placeholder(self):
        """Confirm the template is used directly without .format()."""
        tmpl = _LABEL_CONFIG["Broker"]["list_query_template"]
        assert "{filter_clause}" not in tmpl

    def test_property_template_has_no_filter_clause_placeholder(self):
        tmpl = _LABEL_CONFIG["Property"]["list_query_template"]
        assert "{filter_clause}" not in tmpl

    def test_tenant_template_has_no_filter_clause_placeholder(self):
        tmpl = _LABEL_CONFIG["Tenant"]["list_query_template"]
        assert "{filter_clause}" not in tmpl

    @pytest.mark.asyncio
    async def test_broker_query_text_returns_degraded_not_key_error(self):
        """
        B-P2-2 + M-P2-1: query_text + label=Broker must return DEGRADED,
        not raise KeyError from .format(filter_clause='').
        """
        driver = MagicMock()
        result = await run_semantic_search(
            driver,
            label="Broker",
            query_text="senior industrial broker",
        )
        assert result["status"] == "DEGRADED"
        assert "not yet supported" in result["error"]
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_property_query_text_returns_degraded(self):
        driver = MagicMock()
        result = await run_semantic_search(
            driver,
            label="Property",
            query_text="logistics warehouse",
        )
        assert result["status"] == "DEGRADED"

    @pytest.mark.asyncio
    async def test_tenant_query_text_returns_degraded(self):
        driver = MagicMock()
        result = await run_semantic_search(
            driver,
            label="Tenant",
            query_text="e-commerce tenant",
        )
        assert result["status"] == "DEGRADED"


# ---------------------------------------------------------------------------
# run_semantic_search — ranking, filtering, error paths
# ---------------------------------------------------------------------------

class TestRunSemanticSearch:
    """Tests using mocked embeddings in Neo4j."""

    @pytest.mark.asyncio
    async def test_ranking_by_cosine_similarity(self):
        """
        Three Insight nodes with known embeddings. Query vector closest to node_b.
        Expected order: node_b > node_a > node_c.
        """
        dim = 384
        # node_b is most similar to query (same direction)
        query_emb = _unit_vec(dim, 0)  # [1, 0, 0, ..., 0]
        node_a_emb = [0.7] + [0.0] * (dim - 2) + [0.7]  # angle ~45 degrees
        node_b_emb = [1.0] + [0.0] * (dim - 1)          # identical to query
        node_c_emb = [0.0] + [1.0] + [0.0] * (dim - 2) # orthogonal to query

        # Normalise node_a
        norm = math.sqrt(sum(x ** 2 for x in node_a_emb))
        node_a_emb = [x / norm for x in node_a_emb]

        candidates = [
            {"node_id": "INS-A", "name": "Node A", "embedding": node_a_emb,
             "body": "Body A", "market": "Atlanta", "asset_class": "Office", "published_at": None},
            {"node_id": "INS-B", "name": "Node B", "embedding": node_b_emb,
             "body": "Body B", "market": "Dallas", "asset_class": "Industrial", "published_at": None},
            {"node_id": "INS-C", "name": "Node C", "embedding": node_c_emb,
             "body": "Body C", "market": "Chicago", "asset_class": "Retail", "published_at": None},
        ]

        driver = _make_driver_with_candidates(candidates)

        with patch("mcp_server.tools.semantic_search._embed_query", return_value=query_emb):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="industrial absorption surge",
                top_k=3,
            )

        assert result["status"] == "OK"
        ids = [r["node"]["id"] for r in result["results"]]
        # node_b should be first (highest cosine with query)
        assert ids[0] == "INS-B", f"Expected INS-B first; got {ids}"
        # node_c (orthogonal) should be last
        assert ids[-1] == "INS-C", f"Expected INS-C last; got {ids}"

    @pytest.mark.asyncio
    async def test_top_k_truncation(self):
        dim = 384
        query_emb = _unit_vec(dim, 0)
        candidates = [
            {"node_id": f"INS-{i}", "name": f"Node {i}",
             "embedding": [float(i) / 10] + [0.0] * (dim - 1),
             "body": "body", "market": None, "asset_class": None, "published_at": None}
            for i in range(1, 8)  # 7 candidates
        ]

        driver = _make_driver_with_candidates(candidates)

        with patch("mcp_server.tools.semantic_search._embed_query", return_value=query_emb):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="test",
                top_k=5,
            )

        assert len(result["results"]) == 5
        assert result["truncated"] is True

    @pytest.mark.asyncio
    async def test_min_score_filter(self):
        dim = 384
        query_emb = _unit_vec(dim, 0)
        # node_a has near-zero similarity (almost orthogonal)
        node_a_emb = [0.01] + [0.999] + [0.0] * (dim - 2)
        norm = math.sqrt(sum(x ** 2 for x in node_a_emb))
        node_a_emb = [x / norm for x in node_a_emb]

        node_b_emb = [1.0] + [0.0] * (dim - 1)  # similarity = 1.0

        candidates = [
            {"node_id": "INS-A", "name": "Low score", "embedding": node_a_emb,
             "body": "low", "market": None, "asset_class": None, "published_at": None},
            {"node_id": "INS-B", "name": "High score", "embedding": node_b_emb,
             "body": "high", "market": None, "asset_class": None, "published_at": None},
        ]

        driver = _make_driver_with_candidates(candidates)

        with patch("mcp_server.tools.semantic_search._embed_query", return_value=query_emb):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="test",
                top_k=10,
                min_score=0.5,
            )

        ids = [r["node"]["id"] for r in result["results"]]
        assert "INS-B" in ids
        assert "INS-A" not in ids, "Low-score node should be filtered by min_score"

    @pytest.mark.asyncio
    async def test_unknown_label_returns_error(self):
        driver = MagicMock()
        result = await run_semantic_search(
            driver,
            label="InvalidLabel",
            query_text="test",
        )
        assert result["status"] == "ERROR"
        assert "InvalidLabel" in result["error"]

    @pytest.mark.asyncio
    async def test_anchor_not_found_returns_error(self):
        # anchor_embedding=None → single() returns None
        driver = _make_driver_with_candidates([], anchor_embedding=None)

        result = await run_semantic_search(
            driver,
            label="Insight",
            anchor_node_id="NONEXISTENT-ID",
        )
        assert result["status"] == "ERROR"
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_query_or_anchor_returns_error(self):
        driver = MagicMock()
        result = await run_semantic_search(
            driver,
            label="Insight",
        )
        assert result["status"] == "ERROR"

    @pytest.mark.asyncio
    async def test_empty_insight_nodes_returns_degraded(self):
        """M-P2-5: empty Insight candidates must be DEGRADED per api-contracts §3."""
        driver = _make_driver_with_candidates([])
        with patch("mcp_server.tools.semantic_search._embed_query", return_value=[0.1] * 384):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="test query",
            )
        assert result["status"] == "DEGRADED"
        assert result["results"] == []
        assert "No Insight nodes" in result["error"]

    @pytest.mark.asyncio
    async def test_result_includes_body_snippet_for_insight(self):
        dim = 384
        emb = [1.0] + [0.0] * (dim - 1)
        candidates = [
            {"node_id": "INS-X", "name": "Test Insight",
             "embedding": emb,
             "body": "A" * 300,  # longer than 200 chars
             "market": "Atlanta", "asset_class": "Office", "published_at": "2026-05-01"},
        ]
        driver = _make_driver_with_candidates(candidates)

        with patch("mcp_server.tools.semantic_search._embed_query", return_value=emb):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="test",
            )

        assert result["results"]
        snippet = result["results"][0].get("body_snippet", "")
        assert len(snippet) <= 200, "body_snippet should be truncated to 200 chars"

    @pytest.mark.asyncio
    async def test_sublease_pressure_query_returns_results(self):
        """Regression: 'sublease pressure' should surface matching insights."""
        dim = 384
        emb = [1.0] + [0.0] * (dim - 1)
        candidates = [
            {"node_id": "INS-SUB", "name": "Sublease pressure rising",
             "embedding": emb, "body": "Sublease availability climbs in office sector.",
             "market": "Atlanta", "asset_class": "Office", "published_at": None},
        ]
        driver = _make_driver_with_candidates(candidates)

        with patch("mcp_server.tools.semantic_search._embed_query", return_value=emb):
            result = await run_semantic_search(
                driver,
                label="Insight",
                query_text="sublease pressure",
            )

        assert result["status"] == "OK"
        assert len(result["results"]) >= 1
        assert result["results"][0]["node"]["id"] == "INS-SUB"
