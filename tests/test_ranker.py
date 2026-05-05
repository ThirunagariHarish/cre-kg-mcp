"""
Tests for mcp_server/ranker.py

Verifies:
  - weighted_sum: deterministic, respects weights, handles zero-weight edge case
  - normalise_rank: min-max mapping, ties → all 1.0, empty list
  - stable_sort: descending order, stable ties
  - build_reason_string: only active components surface reasons
  - spoc_value: active → 1.0, expired → 0.5, none/unknown → 0.0
"""

from __future__ import annotations

import pytest

from mcp_server.ranker import (
    BROKER_DEAL_VOLUME_WEIGHT,
    BROKER_SPECIALIZATION_WEIGHT,
    BROKER_SPOC_WEIGHT,
    build_reason_string,
    normalise_rank,
    spoc_value,
    stable_sort,
    weighted_sum,
)


class TestWeightedSum:
    def test_returns_float_in_range(self):
        result = weighted_sum({
            "a": (0.8, 0.4),
            "b": (1.0, 0.3),
            "c": (0.5, 0.3),
        })
        assert 0.0 <= result <= 1.0

    def test_all_zeros_returns_zero(self):
        result = weighted_sum({"a": (0.0, 1.0), "b": (0.0, 1.0)})
        assert result == 0.0

    def test_all_ones_returns_one(self):
        result = weighted_sum({"a": (1.0, 1.0), "b": (1.0, 1.0)})
        assert result == 1.0

    def test_deterministic_across_calls(self):
        components = {
            "deal_volume": (0.75, BROKER_DEAL_VOLUME_WEIGHT),
            "spec":        (1.0, BROKER_SPECIALIZATION_WEIGHT),
            "spoc":        (0.0, BROKER_SPOC_WEIGHT),
        }
        r1 = weighted_sum(components)
        r2 = weighted_sum(components)
        assert r1 == r2

    def test_zero_total_weight_returns_zero(self):
        # Should not raise ZeroDivisionError
        result = weighted_sum({"a": (1.0, 0.0)})
        assert result == 0.0

    def test_single_component_equals_value(self):
        # With a single component of weight 1.0, result == value
        result = weighted_sum({"only": (0.6, 1.0)})
        assert abs(result - 0.6) < 1e-4

    def test_higher_weight_component_dominates(self):
        result_high_vol = weighted_sum({
            "deal_volume":  (1.0, 0.8),
            "specialization": (0.0, 0.2),
        })
        result_low_vol = weighted_sum({
            "deal_volume":  (0.0, 0.8),
            "specialization": (1.0, 0.2),
        })
        assert result_high_vol > result_low_vol


class TestNormaliseRank:
    def test_empty_returns_empty(self):
        assert normalise_rank([]) == []

    def test_single_element_returns_one(self):
        assert normalise_rank([42.0]) == [1.0]

    def test_all_equal_returns_all_ones(self):
        result = normalise_rank([5.0, 5.0, 5.0])
        assert all(v == 1.0 for v in result)

    def test_min_max_mapping(self):
        values = [0.0, 50.0, 100.0]
        result = normalise_rank(values)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.5)
        assert result[2] == pytest.approx(1.0)

    def test_length_preserved(self):
        values = [10.0, 20.0, 30.0, 40.0]
        assert len(normalise_rank(values)) == len(values)

    def test_highest_raw_value_maps_to_one(self):
        values = [3.0, 7.0, 1.0, 5.0]
        result = normalise_rank(values)
        max_idx = values.index(max(values))
        assert result[max_idx] == pytest.approx(1.0)

    def test_lowest_raw_value_maps_to_zero(self):
        values = [3.0, 7.0, 1.0, 5.0]
        result = normalise_rank(values)
        min_idx = values.index(min(values))
        assert result[min_idx] == pytest.approx(0.0)


class TestStableSort:
    def test_descending_order(self):
        items = [
            {"score": 0.3, "name": "c"},
            {"score": 0.9, "name": "a"},
            {"score": 0.6, "name": "b"},
        ]
        result = stable_sort(items, key_field="score")
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_returns_all_items(self):
        items = [{"score": float(i)} for i in range(5)]
        assert len(stable_sort(items)) == 5

    def test_ties_are_stable(self):
        """
        Items with identical score should retain original relative order
        (Python sort is stable).
        """
        items = [
            {"score": 0.5, "name": "first"},
            {"score": 0.5, "name": "second"},
        ]
        result = stable_sort(items, key_field="score")
        assert result[0]["name"] == "first"
        assert result[1]["name"] == "second"

    def test_empty_list(self):
        assert stable_sort([]) == []

    def test_secondary_key_used_for_ties(self):
        items = [
            {"score": 0.5, "vol": 100.0, "name": "low_vol"},
            {"score": 0.5, "vol": 500.0, "name": "high_vol"},
        ]
        result = stable_sort(items, key_field="score", secondary_key="vol")
        # Higher vol wins the tie
        assert result[0]["name"] == "high_vol"


class TestBuildReasonString:
    def test_zero_value_components_excluded(self):
        components = {
            "market_match": (1.0, 0.4),
            "ac_match":     (0.0, 0.3),   # zero — should NOT produce reason
            "spoc":         (1.0, 0.3),
        }
        labels = {
            "market_match": "Covers market",
            "ac_match": "Specializes in asset class",
            "spoc": "Active SPOC",
        }
        reasons = build_reason_string(components, labels)
        assert "Covers market" in reasons
        assert "Active SPOC" in reasons
        assert "Specializes in asset class" not in reasons

    def test_all_zero_returns_empty(self):
        components = {"a": (0.0, 1.0)}
        labels = {"a": "Reason A"}
        assert build_reason_string(components, labels) == []

    def test_missing_label_key_ignored(self):
        components = {"a": (1.0, 1.0), "b": (1.0, 1.0)}
        labels = {"a": "Reason A"}  # "b" missing from labels
        reasons = build_reason_string(components, labels)
        assert reasons == ["Reason A"]


class TestSpocValue:
    def test_active_returns_one(self):
        assert spoc_value("active") == 1.0

    def test_expired_returns_half(self):
        assert spoc_value("expired") == 0.5

    def test_none_returns_zero(self):
        assert spoc_value(None) == 0.0

    def test_unknown_string_returns_zero(self):
        assert spoc_value("unknown") == 0.0

    def test_empty_string_returns_zero(self):
        assert spoc_value("") == 0.0
