"""
Tests for mcp_server/tools/find_matching_properties_for_insight.py

Verifies:
  - Missing both insight_id and insight_text → ERROR
  - insight_id not found → ERROR
  - Dallas Industrial insight → properties in Dallas Industrial subgraph first
  - Empty property result returns OK with explanation in warnings
  - insight_text path uses semantic_search
  - Output shape matches api-contracts §4
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools.find_matching_properties_for_insight import (
    run_find_matching_properties_for_insight,
    _recency_score,
    _spoc_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(run_responses: dict[str, list[dict]]):
    """
    Build a mock driver + session.

    run_responses: {cypher_fragment: [list of row dicts]}
    The first matching key (substring match on the cypher) is returned.
    Unmatched queries return [].
    """
    session_mock = MagicMock()

    def run_side_effect(cypher, **kwargs):
        result_mock = MagicMock()
        rows = []
        for fragment, data in run_responses.items():
            if fragment in cypher:
                rows = data
                break

        # single() for insight lookup
        if "LIMIT 1" in cypher or "insight_id" in cypher.lower():
            if rows:
                single_mock = MagicMock()
                single_mock.__getitem__ = MagicMock(
                    side_effect=lambda k: rows[0].get(k)
                )
                result_mock.single.return_value = single_mock
            else:
                result_mock.single.return_value = None
        else:
            result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(
                return_value=iter([_dict_record(r) for r in rows])
            )

        return result_mock

    session_mock.run.side_effect = run_side_effect
    driver_mock = MagicMock()
    driver_mock.session.return_value.__enter__ = MagicMock(return_value=session_mock)
    driver_mock.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver_mock


def _dict_record(d: dict) -> MagicMock:
    """Wrap a dict so dict(record) works."""
    record = MagicMock()
    record.keys.return_value = d.keys()
    record.__iter__ = MagicMock(return_value=iter(d.keys()))
    record.__getitem__ = MagicMock(side_effect=lambda k: d.get(k))
    record.get = MagicMock(side_effect=lambda k, default=None: d.get(k, default))
    record.items.return_value = d.items()
    return record


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestRecencyScore:
    def test_none_returns_zero(self):
        assert _recency_score(None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _recency_score("") == 0.0

    def test_recent_date_returns_high_score(self):
        # A very recent date should give a score close to 1.0
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(tz=timezone.utc) - timedelta(days=10)).isoformat()
        score = _recency_score(recent)
        assert score > 0.95

    def test_old_date_returns_low_score(self):
        # 4 years old — beyond the 1095-day window → 0
        score = _recency_score("2020-01-01T00:00:00+00:00")
        assert score == 0.0


class TestSpocStatus:
    def test_no_expiry_returns_active(self):
        assert _spoc_status(None) == "active"

    def test_future_expiry_returns_active(self):
        assert _spoc_status("2030-01-01T00:00:00+00:00") == "active"

    def test_past_expiry_returns_expired(self):
        assert _spoc_status("2020-01-01T00:00:00+00:00") == "expired"

    def test_invalid_date_returns_unknown(self):
        assert _spoc_status("not-a-date") == "unknown"


# ---------------------------------------------------------------------------
# run_find_matching_properties_for_insight
# ---------------------------------------------------------------------------

class TestMissingInputs:
    @pytest.mark.asyncio
    async def test_neither_id_nor_text_returns_error(self):
        driver = MagicMock()
        result = await run_find_matching_properties_for_insight(driver)
        assert result["status"] == "ERROR"
        assert "insight_id or insight_text" in result["error"]


class TestInsightIdNotFound:
    @pytest.mark.asyncio
    async def test_nonexistent_insight_id_returns_error(self):
        # Session returns None for the insight lookup
        session_mock = MagicMock()
        result_mock = MagicMock()
        result_mock.single.return_value = None
        session_mock.run.return_value = result_mock

        driver = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = await run_find_matching_properties_for_insight(
            driver, insight_id="NONEXISTENT"
        )
        assert result["status"] == "ERROR"
        assert "not found" in result["error"].lower()


class TestDallasIndustrialInsight:
    """
    Fixture: insight tagged Industrial + Dallas.
    Expected: properties in Dallas Industrial subgraph are returned.
    """

    @pytest.mark.asyncio
    async def test_dallas_industrial_properties_returned(self):
        insight_row = {
            "insight_id": "INS-001",
            "title": "Dallas Industrial Absorption Surge",
            "market": "Dallas-Fort Worth",
            "asset_class": "Industrial",
        }
        prop_row = {
            "property_key": "id::P-001",
            "address": "1450 Logistics Pkwy, Dallas TX",
            "market_name": "Dallas-Fort Worth",
            "submarket_name": "DFW North",
            "asset_class_name": "Industrial",
            "lease_count": 5,
            "latest_lease": "2025-06-01T00:00:00+00:00",
        }

        # We need the session to handle multiple different calls
        session_mock = MagicMock()
        call_count = [0]

        def run_side_effect(cypher, **kwargs):
            result_mock = MagicMock()
            call_count[0] += 1

            if "Insight {insight_id" in cypher:
                single_row = MagicMock()
                single_row.__getitem__ = MagicMock(
                    side_effect=lambda k: insight_row.get(k)
                )
                result_mock.single.return_value = single_row
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            elif "ABOUT" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            elif "Property" in cypher and "LOCATED_IN" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(
                    return_value=iter([_dict_record(prop_row)])
                )
            elif "COVERS" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            elif "SPECIALIZES_IN" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            elif "BROKERED_BY" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            else:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            return result_mock

        session_mock.run.side_effect = run_side_effect
        driver = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = await run_find_matching_properties_for_insight(
            driver, insight_id="INS-001", limit=10
        )

        assert result["status"] == "OK"
        assert result["matched_market"] == "Dallas-Fort Worth"
        assert result["matched_asset_class"] == "Industrial"
        assert len(result["properties"]) >= 1
        assert result["properties"][0]["property"]["id"] == "id::P-001"

    @pytest.mark.asyncio
    async def test_property_has_required_output_shape(self):
        """Output shape must match api-contracts §4."""
        insight_row = {
            "insight_id": "INS-002",
            "title": "Test Insight",
            "market": "Chicago",
            "asset_class": "Office",
        }
        prop_row = {
            "property_key": "id::P-002",
            "address": "123 Main St",
            "market_name": "Chicago",
            "submarket_name": "Loop",
            "asset_class_name": "Office",
            "lease_count": 2,
            "latest_lease": None,
        }

        session_mock = MagicMock()

        def run_side_effect(cypher, **kwargs):
            result_mock = MagicMock()
            if "Insight {insight_id" in cypher:
                single_row = MagicMock()
                single_row.__getitem__ = MagicMock(
                    side_effect=lambda k: insight_row.get(k)
                )
                result_mock.single.return_value = single_row
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            elif "Property" in cypher and "LOCATED_IN" in cypher:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(
                    return_value=iter([_dict_record(prop_row)])
                )
            else:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            return result_mock

        session_mock.run.side_effect = run_side_effect
        driver = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = await run_find_matching_properties_for_insight(
            driver, insight_id="INS-002"
        )

        assert result["status"] == "OK"
        assert "insight" in result
        assert "matched_market" in result
        assert "matched_asset_class" in result
        assert "properties" in result
        assert "matching_brokers" in result
        assert "truncated" in result

        prop = result["properties"][0]
        assert "property" in prop
        assert "id" in prop["property"]
        assert "name" in prop["property"]
        assert "score" in prop
        assert "reasons" in prop
        assert "brokers" in prop


class TestEmptyResultPath:
    @pytest.mark.asyncio
    async def test_no_matching_properties_returns_ok_with_warning(self):
        """api-contracts §4: empty → status OK, warnings explain."""
        insight_row = {
            "insight_id": "INS-003",
            "title": "Obscure Market Insight",
            "market": "Mars",
            "asset_class": "Office",
        }

        session_mock = MagicMock()

        def run_side_effect(cypher, **kwargs):
            result_mock = MagicMock()
            if "Insight {insight_id" in cypher:
                single_row = MagicMock()
                single_row.__getitem__ = MagicMock(
                    side_effect=lambda k: insight_row.get(k)
                )
                result_mock.single.return_value = single_row
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            else:
                result_mock.single.return_value = None
                result_mock.__iter__ = MagicMock(return_value=iter([]))
            return result_mock

        session_mock.run.side_effect = run_side_effect
        driver = MagicMock()
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        result = await run_find_matching_properties_for_insight(
            driver, insight_id="INS-003"
        )

        assert result["status"] == "OK"
        assert result["properties"] == []
        assert len(result["warnings"]) > 0
        assert any("No properties found" in w for w in result["warnings"])


class TestInsightTextPath:
    @pytest.mark.asyncio
    async def test_insight_text_uses_semantic_search(self):
        """insight_text path must call semantic_search."""
        driver = MagicMock()

        ss_result = {
            "status": "OK",
            "results": [
                {
                    "node": {"id": "INS-SS-001", "name": "Matched Insight"},
                    "score": 0.88,
                    "market": "Atlanta",
                    "asset_class": "Retail",
                }
            ],
        }

        session_mock = MagicMock()

        def run_side_effect(cypher, **kwargs):
            result_mock = MagicMock()
            result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(return_value=iter([]))
            return result_mock

        session_mock.run.side_effect = run_side_effect
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "mcp_server.tools.semantic_search.run_semantic_search",
            new=AsyncMock(return_value=ss_result),
        ) as mock_ss:
            result = await run_find_matching_properties_for_insight(
                driver, insight_text="industrial absorption trend"
            )
            mock_ss.assert_called_once()

        assert result["status"] == "OK"
        assert result["matched_market"] == "Atlanta"
        assert result["matched_asset_class"] == "Retail"

    @pytest.mark.asyncio
    async def test_insight_text_no_match_returns_ok_with_warning(self):
        """If semantic_search returns no results, return OK with explanation."""
        driver = MagicMock()

        ss_result = {"status": "DEGRADED", "results": []}

        session_mock = MagicMock()
        session_mock.run.return_value.__iter__ = MagicMock(return_value=iter([]))
        driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "mcp_server.tools.semantic_search.run_semantic_search",
            new=AsyncMock(return_value=ss_result),
        ):
            result = await run_find_matching_properties_for_insight(
                driver, insight_text="completely unknown topic XYZ"
            )

        assert result["status"] == "OK"
        assert result["properties"] == []
        assert any("No Insight node matched" in w for w in result.get("warnings", []))
