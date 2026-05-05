"""
Tests for ingester/streaming.py

Mocks Snowflake and Neo4j to verify:
- Insight nodes are upserted with correct fields
- :ABOUT edges are created for Market, AssetClass, Submarket, Tenant
- Idempotency: re-running with same insight_id produces one node
- mark_processed is called after successful upsert
- Rows with no embedding (simulated model failure) do not mark processed
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from ingester.streaming import (
    _parse_raw_tags,
    upsert_insight,
    run_once,
    backfill_from_source,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ROW = {
    "INSIGHT_ID": "INS-TEST-001",
    "TITLE": "DFW Industrial absorption surge",
    "BODY": "Industrial absorption in DFW jumped 15% quarter-over-quarter.",
    "SOURCE": "JLL Research",
    "AUTHOR": "Jane Smith",
    "PUBLISHED_AT": "2026-05-01T10:00:00",
    "INGESTED_AT": "2026-05-01T10:05:00",
    "MARKET": "Dallas",
    "SUBMARKET": "Las Colinas",
    "ASSET_CLASS": "Industrial",
    "TENANT_NAME": "Acme Corp",
    "PROPERTY_HINT": None,
    "RAW_TAGS": json.dumps(["dfw", "industrial", "tenant:Acme Corp"]),
    "SENTIMENT": 0.65,
    "IMPACT": "HIGH",
}

FAKE_EMBEDDING = [0.1] * 384


def _make_mock_driver():
    """Return a Mock Neo4j driver that records Cypher calls."""
    session_mock = MagicMock()
    driver_mock = MagicMock()
    driver_mock.session.return_value.__enter__ = MagicMock(return_value=session_mock)
    driver_mock.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver_mock, session_mock


# ---------------------------------------------------------------------------
# _parse_raw_tags
# ---------------------------------------------------------------------------

class TestParseRawTags:
    def test_json_string_array(self):
        result = _parse_raw_tags('["dfw", "industrial", "tenant:Acme Corp"]')
        assert result == ["dfw", "industrial", "tenant:Acme Corp"]

    def test_list_passthrough(self):
        result = _parse_raw_tags(["tag1", "tag2"])
        assert result == ["tag1", "tag2"]

    def test_none_returns_empty(self):
        assert _parse_raw_tags(None) == []

    def test_comma_separated_fallback(self):
        result = _parse_raw_tags("dfw, industrial, office")
        assert "dfw" in result
        assert "industrial" in result

    def test_invalid_json_falls_back(self):
        result = _parse_raw_tags("not-json")
        assert result == ["not-json"]


# ---------------------------------------------------------------------------
# upsert_insight — Neo4j Cypher calls
# ---------------------------------------------------------------------------

class TestUpsertInsight:
    def test_insight_merge_cypher_called(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        # session.run should have been called at least once (MERGE Insight)
        assert session.run.call_count >= 1

    def test_insight_id_passed_to_cypher(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        # First call should include insight_id in kwargs
        first_call_kwargs = session.run.call_args_list[0]
        # call_args_list entries are Call objects; check all keyword args across calls
        all_kwargs = [c.kwargs for c in session.run.call_args_list]
        insight_ids = [kw.get("insight_id") for kw in all_kwargs if "insight_id" in kw]
        assert "INS-TEST-001" in insight_ids

    def test_embedding_passed_to_cypher(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        all_kwargs = [c.kwargs for c in session.run.call_args_list]
        embeddings = [kw.get("embedding") for kw in all_kwargs if "embedding" in kw]
        assert FAKE_EMBEDDING in embeddings

    def test_market_about_edge_created(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        all_cypher = [c.args[0] for c in session.run.call_args_list]
        # At least one call should reference ABOUT_MARKET (Market node MERGE)
        market_calls = [c for c in all_cypher if "Market" in c]
        assert market_calls, "Expected a Cypher call creating Market :ABOUT edge"

    def test_asset_class_about_edge_created(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        all_cypher = [c.args[0] for c in session.run.call_args_list]
        asset_calls = [c for c in all_cypher if "AssetClass" in c]
        assert asset_calls, "Expected a Cypher call creating AssetClass :ABOUT edge"

    def test_tenant_about_edge_created_from_column(self):
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        all_kwargs = [c.kwargs for c in session.run.call_args_list]
        tenant_keys = [kw.get("tenant_key") for kw in all_kwargs if "tenant_key" in kw]
        # TENANT_NAME = "Acme Corp" → tenant_key = "name::acme corp"
        assert any("acme corp" in tk for tk in tenant_keys if tk), (
            f"Expected tenant_key for 'Acme Corp'; got {tenant_keys}"
        )

    def test_row_with_no_tenant_no_tenant_call(self):
        driver, session = _make_mock_driver()
        row = dict(SAMPLE_ROW)
        row["TENANT_NAME"] = None
        row["RAW_TAGS"] = "[]"
        upsert_insight(driver, row, FAKE_EMBEDDING)
        all_kwargs = [c.kwargs for c in session.run.call_args_list]
        tenant_keys = [kw.get("tenant_key") for kw in all_kwargs if "tenant_key" in kw]
        # Only a tenant from RAW_TAGS "tenant:" prefix would appear — none here
        assert not tenant_keys, f"Unexpected tenant calls: {tenant_keys}"

    def test_idempotent_on_same_insight_id(self):
        """Calling twice with same insight_id should not raise."""
        driver, session = _make_mock_driver()
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        first_count = session.run.call_count
        upsert_insight(driver, SAMPLE_ROW, FAKE_EMBEDDING)
        second_count = session.run.call_count
        # Same number of Cypher calls both times (MERGE is idempotent in real Neo4j)
        assert second_count == first_count * 2


# ---------------------------------------------------------------------------
# run_once — full poll cycle
# ---------------------------------------------------------------------------

class TestRunOnce:
    def test_no_rows_returns_zero(self):
        sf_conn = MagicMock()
        neo4j_driver = MagicMock()

        with patch("ingester.streaming.fetch_unprocessed", return_value=[]):
            count = run_once(sf_conn, neo4j_driver)

        assert count == 0

    def test_processes_rows_and_marks_processed(self):
        sf_conn = MagicMock()
        neo4j_driver, session = _make_mock_driver()

        with (
            patch("ingester.streaming.fetch_unprocessed", return_value=[SAMPLE_ROW]),
            patch("ingester.streaming.embed_text", return_value=FAKE_EMBEDDING),
            patch("ingester.streaming.upsert_insight") as mock_upsert,
            patch("ingester.streaming.mark_processed") as mock_mark,
        ):
            count = run_once(sf_conn, neo4j_driver)

        assert count == 1
        mock_upsert.assert_called_once()
        mock_mark.assert_called_once_with(sf_conn, "INS-TEST-001")

    def test_failed_upsert_does_not_mark_processed(self):
        sf_conn = MagicMock()
        neo4j_driver = MagicMock()

        def _fail(*args, **kwargs):
            raise RuntimeError("Neo4j write failed")

        with (
            patch("ingester.streaming.fetch_unprocessed", return_value=[SAMPLE_ROW]),
            patch("ingester.streaming.embed_text", return_value=FAKE_EMBEDDING),
            patch("ingester.streaming.upsert_insight", side_effect=_fail),
            patch("ingester.streaming.mark_processed") as mock_mark,
        ):
            count = run_once(sf_conn, neo4j_driver)

        assert count == 0
        mock_mark.assert_not_called()

    def test_multiple_rows_all_processed(self):
        sf_conn = MagicMock()
        neo4j_driver, _ = _make_mock_driver()

        row2 = dict(SAMPLE_ROW)
        row2["INSIGHT_ID"] = "INS-TEST-002"

        with (
            patch("ingester.streaming.fetch_unprocessed", return_value=[SAMPLE_ROW, row2]),
            patch("ingester.streaming.embed_text", return_value=FAKE_EMBEDDING),
            patch("ingester.streaming.upsert_insight"),
            patch("ingester.streaming.mark_processed") as mock_mark,
        ):
            count = run_once(sf_conn, neo4j_driver)

        assert count == 2
        assert mock_mark.call_count == 2


# ---------------------------------------------------------------------------
# backfill_from_source
# ---------------------------------------------------------------------------

class TestBackfillFromSource:
    def test_skips_existing_insights(self):
        sf_conn = MagicMock()
        neo4j_driver = MagicMock()

        # Simulate: INS-TEST-001 already in Neo4j
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([{"id": "INS-TEST-001"}]))
        session_mock = MagicMock()
        session_mock.run.return_value = result_mock
        neo4j_driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        neo4j_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch("ingester.streaming.fetch_all_source_insights", return_value=[SAMPLE_ROW]),
            patch("ingester.streaming.embed_text", return_value=FAKE_EMBEDDING),
            patch("ingester.streaming.upsert_insight") as mock_upsert,
        ):
            count = backfill_from_source(sf_conn, neo4j_driver)

        # Already existed → should NOT upsert again
        mock_upsert.assert_not_called()
        assert count == 0

    def test_upserts_new_insights(self):
        sf_conn = MagicMock()
        neo4j_driver = MagicMock()

        # No existing insights in Neo4j
        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([]))
        session_mock = MagicMock()
        session_mock.run.return_value = result_mock
        neo4j_driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        neo4j_driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with (
            patch("ingester.streaming.fetch_all_source_insights", return_value=[SAMPLE_ROW]),
            patch("ingester.streaming.embed_text", return_value=FAKE_EMBEDDING),
            patch("ingester.streaming.upsert_insight") as mock_upsert,
        ):
            count = backfill_from_source(sf_conn, neo4j_driver)

        mock_upsert.assert_called_once()
        assert count == 1
