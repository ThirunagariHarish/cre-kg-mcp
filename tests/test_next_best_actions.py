"""
Tests for mcp_server/tools/suggest_next_best_actions_for_deal.py

Verifies:
  - Pursuit not found → ERROR
  - With one similar historical comparable → it appears in comparables
  - Fallback path triggers cleanly when no comparables exist
  - Output shape matches api-contracts §5
  - fallback_used flag is accurate
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.tools.suggest_next_best_actions_for_deal import (
    run_suggest_next_best_actions,
    _infer_action_for_stage,
    _actions_from_comparables,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dict_record(d: dict) -> MagicMock:
    record = MagicMock()
    record.keys.return_value = d.keys()
    record.__iter__ = MagicMock(return_value=iter(d.keys()))
    record.__getitem__ = MagicMock(side_effect=lambda k: d.get(k))
    record.get = MagicMock(side_effect=lambda k, default=None: d.get(k, default))
    record.items.return_value = d.items()
    return record


def _make_driver(pursuit_row: dict | None, similar_rows: list[dict] | None = None):
    """
    Build a mock driver with configurable pursuit and comparables responses.

    pursuit_row=None simulates pursuit not found.
    """
    session_mock = MagicMock()

    def run_side_effect(cypher, **kwargs):
        result_mock = MagicMock()

        if "Pursuit {pursuit_id" in cypher:
            if pursuit_row is None:
                result_mock.single.return_value = None
            else:
                result_mock.single.return_value = _dict_record(pursuit_row)
            result_mock.__iter__ = MagicMock(return_value=iter([]))

        elif "outcome IN" in cypher or "win_loss" in cypher:
            rows = similar_rows or []
            result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(
                return_value=iter([_dict_record(r) for r in rows])
            )

        else:
            result_mock.single.return_value = None
            result_mock.__iter__ = MagicMock(return_value=iter([]))

        return result_mock

    session_mock.run.side_effect = run_side_effect
    driver = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session_mock)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestInferActionForStage:
    def test_prospecting_stage(self):
        actions = _infer_action_for_stage("Prospecting")
        assert len(actions) > 0
        assert any("discovery" in a.lower() or "schedule" in a.lower() for a in actions)

    def test_proposal_stage(self):
        actions = _infer_action_for_stage("Proposal Sent")
        assert any("proposal" in a.lower() or "follow" in a.lower() for a in actions)

    def test_negotiation_stage(self):
        actions = _infer_action_for_stage("Negotiation")
        assert any("tour" in a.lower() or "negotiat" in a.lower() for a in actions)

    def test_closed_stage(self):
        actions = _infer_action_for_stage("Closed Won")
        assert len(actions) > 0

    def test_unknown_stage_returns_generic(self):
        actions = _infer_action_for_stage("Weird Unknown Stage")
        assert len(actions) > 0

    def test_none_stage_returns_generic(self):
        actions = _infer_action_for_stage(None)
        assert len(actions) > 0


class TestActionsFromComparables:
    def test_won_comparables_produce_follow_up_action(self):
        comparables = [
            {
                "outcome": "Closed Won",
                "closing_broker_name": "Jane Liu",
                "asset_class": "Industrial",
                "market": "Dallas",
            }
        ]
        actions = _actions_from_comparables(comparables, stage="Proposal Sent")
        assert any("follow-up" in a.lower() or "schedule" in a.lower() for a in actions)

    def test_broker_name_surfaces_in_action(self):
        comparables = [
            {
                "outcome": "Closed Won",
                "closing_broker_name": "Tom Patel",
                "asset_class": "Office",
                "market": "Chicago",
            }
        ]
        actions = _actions_from_comparables(comparables, stage="Proposal Sent")
        full_text = " ".join(actions)
        assert "Tom Patel" in full_text

    def test_empty_comparables_falls_back_to_stage_inference(self):
        actions = _actions_from_comparables([], stage="Prospecting")
        assert len(actions) > 0

    def test_caps_at_four_actions(self):
        comparables = [
            {"outcome": "Closed Won", "closing_broker_name": f"Broker{i}",
             "asset_class": "Office", "market": "Chicago"}
            for i in range(10)
        ]
        actions = _actions_from_comparables(comparables, stage="Proposal Sent")
        assert len(actions) <= 4


# ---------------------------------------------------------------------------
# run_suggest_next_best_actions
# ---------------------------------------------------------------------------

class TestPursuitNotFound:
    @pytest.mark.asyncio
    async def test_missing_pursuit_returns_error(self):
        driver = _make_driver(pursuit_row=None)
        result = await run_suggest_next_best_actions(driver, pursuit_id="NONEXISTENT")
        assert result["status"] == "ERROR"
        assert "not found" in result["error"].lower()


class TestWithHistoricalComparable:
    @pytest.mark.asyncio
    async def test_comparable_appears_in_response(self):
        pursuit_row = {
            "pursuit_id": "PUR-001",
            "stage": "Proposal Sent",
            "probability": 0.6,
            "deal_size_sf": 50000,
            "asset_class": "Industrial",
            "market": "Dallas-Fort Worth",
            "win_loss": None,
            "client_name": "Acme Corp",
            "client_key": "name::acme corp",
            "broker_key": "email::jane@cbre.com",
            "broker_name": "Jane Liu",
            "service_line": "TenantRep",
        }
        similar = [
            {
                "pursuit_id": "PUR-201",
                "stage": "Closed Won",
                "outcome": "Closed Won",
                "asset_class": "Industrial",
                "market": "Dallas-Fort Worth",
                "probability": 1.0,
                "client_name": "Other Corp",
                "closing_broker_key": "email::tom@jll.com",
                "closing_broker_name": "Tom Patel",
                "service_line": "TenantRep",
            }
        ]
        driver = _make_driver(pursuit_row, similar_rows=similar)

        result = await run_suggest_next_best_actions(
            driver, pursuit_id="PUR-001", comparable_count=3
        )

        assert result["status"] == "OK"
        assert len(result["comparables"]) >= 1
        comparable_ids = [c["pursuit"]["id"] for c in result["comparables"]]
        assert "PUR-201" in comparable_ids

    @pytest.mark.asyncio
    async def test_fallback_used_is_false_when_comparables_exist(self):
        pursuit_row = {
            "pursuit_id": "PUR-002", "stage": "Prospecting", "probability": 0.3,
            "deal_size_sf": None, "asset_class": "Office", "market": "Chicago",
            "win_loss": None, "client_name": "Beta Inc", "client_key": "name::beta inc",
            "broker_key": None, "broker_name": None, "service_line": None,
        }
        similar = [
            {
                "pursuit_id": "PUR-100", "stage": "Closed Won", "outcome": "Closed Won",
                "asset_class": "Office", "market": "Chicago", "probability": 1.0,
                "client_name": "Gamma LLC",
                "closing_broker_key": "email::bob@cbre.com",
                "closing_broker_name": "Bob Smith", "service_line": "Leasing",
            }
        ]
        driver = _make_driver(pursuit_row, similar_rows=similar)
        result = await run_suggest_next_best_actions(driver, pursuit_id="PUR-002")

        assert result["fallback_used"] is False


class TestFallbackPath:
    @pytest.mark.asyncio
    async def test_no_comparables_triggers_fallback(self):
        """
        api-contracts §5: fallback_used=True when no comparables;
        suggested_actions includes fallback message.
        """
        pursuit_row = {
            "pursuit_id": "PUR-003", "stage": "Negotiation", "probability": 0.8,
            "deal_size_sf": None, "asset_class": "Retail", "market": "Atlanta",
            "win_loss": None, "client_name": "Zeta Retail", "client_key": "name::zeta retail",
            "broker_key": None, "broker_name": None, "service_line": "Leasing",
        }
        driver = _make_driver(pursuit_row, similar_rows=[])  # no comparables

        result = await run_suggest_next_best_actions(driver, pursuit_id="PUR-003")

        assert result["status"] == "OK"
        assert result["fallback_used"] is True
        assert result["comparables"] == []
        # Fallback message should mention market/asset_class or community
        fallback_mentions = [
            a for a in result["suggested_actions"]
            if "comparable" in a.lower() or "community" in a.lower()
            or "atlanta" in a.lower() or "retail" in a.lower()
        ]
        assert len(fallback_mentions) > 0

    @pytest.mark.asyncio
    async def test_fallback_still_returns_suggested_actions(self):
        pursuit_row = {
            "pursuit_id": "PUR-004", "stage": "Proposal Sent", "probability": 0.4,
            "deal_size_sf": None, "asset_class": "Office", "market": "Boston",
            "win_loss": None, "client_name": None, "client_key": None,
            "broker_key": None, "broker_name": None, "service_line": None,
        }
        driver = _make_driver(pursuit_row, similar_rows=[])

        result = await run_suggest_next_best_actions(driver, pursuit_id="PUR-004")
        assert result["suggested_actions"]


class TestOutputShape:
    @pytest.mark.asyncio
    async def test_response_has_required_fields(self):
        pursuit_row = {
            "pursuit_id": "PUR-005", "stage": "Prospecting", "probability": 0.2,
            "deal_size_sf": None, "asset_class": "Industrial", "market": "Houston",
            "win_loss": None, "client_name": "Test Co", "client_key": "name::test co",
            "broker_key": None, "broker_name": None, "service_line": None,
        }
        driver = _make_driver(pursuit_row)

        result = await run_suggest_next_best_actions(driver, pursuit_id="PUR-005")

        required_keys = [
            "status", "pursuit", "comparables", "suggested_actions",
            "related_insights", "available_spocs", "fallback_used", "truncated",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

        assert result["pursuit"]["id"] == "PUR-005"
        assert result["pursuit"]["stage"] == "Prospecting"
        assert isinstance(result["comparables"], list)
        assert isinstance(result["suggested_actions"], list)
