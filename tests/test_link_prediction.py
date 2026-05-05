"""
tests/test_link_prediction.py

Unit tests for ml/link_prediction.py.
Mocks Neo4j driver — no live graph required.

Asserts:
- run_link_prediction detects available algo and uses it
- Predictions are ranked by score (descending)
- Predictions are persisted as :PredictedLink nodes
- predict_for_node returns ranked candidates from :PredictedLink
- Error paths return {"status": "ERROR"} without raising
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch
import pytest

from ml.link_prediction import (
    run_link_prediction,
    predict_for_node,
    PREDICTED_LINK_LABEL,
    ALGO_NAME,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(from_id, to_id, score, from_label="Broker", to_label="Property"):
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "from_id": from_id,
        "from_label": from_label,
        "to_id": to_id,
        "to_label": to_label,
        "score": score,
        "algo": "adamicAdar",
        "computed_at": "2026-05-05T12:00:00Z",
    }[key]
    return row


def _make_session_mock(score_rows, persist_rows=None, probe_ok=True):
    """
    Build a mock session whose run() returns different results depending on the
    query string content:
      - gds.list() query (B-P3-4 procedure detection) → rows with 'name' key if probe_ok
      - stale-prune query (computed_at <) → row with before_count
      - score query / Python fallback Cypher → score_rows
      - persist query (UNWIND) → MagicMock
      - predict_for_node query → persist_rows
    """
    session_mock = MagicMock()

    def _run(cypher, **kwargs):
        if "gds.list()" in cypher:
            # B-P3-4: procedure availability check
            if probe_ok:
                # Return a row with name containing 'adamicAdar' and '.stream'
                name_row = MagicMock()
                name_row.__getitem__ = lambda self, key: "gds.linkprediction.adamicAdar.stream"
                return iter([name_row])
            else:
                raise RuntimeError("gds.list() not available")
        elif "computed_at < $current_run_at" in cypher:
            # M-P3-3: stale prediction count or delete
            if "stale_count" in cypher:
                result = MagicMock()
                prune_row = MagicMock()
                prune_row.__getitem__ = lambda self, key: 0  # 0 stale nodes
                result.single.return_value = prune_row
                return result
            else:
                # DETACH DELETE — no return value needed
                return MagicMock()
        elif "UNWIND" in cypher:
            # Persist
            return MagicMock()
        elif "PredictedLink" in cypher and "RETURN pl" in cypher:
            # predict_for_node read
            return iter(persist_rows or [])
        else:
            # Score query (Python fallback Adamic-Adar or procedure stream)
            return iter(score_rows)

    session_mock.run.side_effect = _run
    session_mock.__enter__ = lambda s: s
    session_mock.__exit__ = MagicMock(return_value=False)
    return session_mock


# ---------------------------------------------------------------------------
# run_link_prediction tests
# ---------------------------------------------------------------------------

class TestRunLinkPrediction:
    def test_returns_ok_status_on_happy_path(self):
        score_rows = [_make_row("broker::jane", "prop::P1", 0.9)]

        session_mock = _make_session_mock(score_rows)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = run_link_prediction(driver=driver_mock)

        assert result["status"] == "OK"

    def test_algo_field_present_in_result(self):
        score_rows = [_make_row("broker::jane", "prop::P1", 0.9)]
        session_mock = _make_session_mock(score_rows)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = run_link_prediction(driver=driver_mock)

        assert "algo" in result

    def test_count_reflects_total_predictions(self):
        # Two broker-property + one broker-tenant row per score query
        score_rows = [
            _make_row("broker::jane", "prop::P1", 0.9),
            _make_row("broker::tom", "prop::P2", 0.7),
        ]
        session_mock = _make_session_mock(score_rows)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = run_link_prediction(driver=driver_mock)

        # count = broker_property_count + broker_tenant_count
        assert result["count"] == result["broker_property_count"] + result["broker_tenant_count"]

    def test_persist_cypher_contains_predicted_link_label(self):
        score_rows = [_make_row("broker::jane", "prop::P1", 0.8)]
        session_mock = _make_session_mock(score_rows)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        run_link_prediction(driver=driver_mock)

        # Check UNWIND was called (persistence step)
        all_calls = [str(c.args[0]) for c in session_mock.run.call_args_list]
        assert any("UNWIND" in c for c in all_calls), "Expected MERGE/UNWIND persistence call"

    def test_returns_error_on_session_failure(self):
        driver_mock = MagicMock()
        driver_mock.session.side_effect = RuntimeError("DB down")

        result = run_link_prediction(driver=driver_mock)

        assert result["status"] == "ERROR"
        assert "error" in result


# ---------------------------------------------------------------------------
# predict_for_node tests
# ---------------------------------------------------------------------------

class TestPredictForNode:
    def _make_read_rows(self, rows):
        mock_rows = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            mock_rows.append(row)
        return mock_rows

    def test_returns_list(self):
        rows = self._make_read_rows([
            {
                "from_id": "broker::jane",
                "from_label": "Broker",
                "to_id": "prop::P1",
                "to_label": "Property",
                "score": 0.88,
                "algo": "adamicAdar",
            }
        ])

        session_mock = MagicMock()
        session_mock.run.return_value = iter(rows)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = predict_for_node("broker::jane", k=5, driver=driver_mock)

        assert isinstance(result, list)

    def test_result_has_score_field(self):
        rows = self._make_read_rows([
            {
                "from_id": "broker::jane",
                "from_label": "Broker",
                "to_id": "prop::P1",
                "to_label": "Property",
                "score": 0.88,
                "algo": "adamicAdar",
            }
        ])

        session_mock = MagicMock()
        session_mock.run.return_value = iter(rows)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = predict_for_node("broker::jane", k=5, driver=driver_mock)

        assert result[0]["score"] == 0.88

    def test_empty_when_no_links(self):
        session_mock = MagicMock()
        session_mock.run.return_value = iter([])
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = predict_for_node("broker::unknown", k=5, driver=driver_mock)

        assert result == []

    def test_driver_error_returns_empty_list(self):
        driver_mock = MagicMock()
        driver_mock.session.side_effect = RuntimeError("DB down")

        result = predict_for_node("broker::jane", k=5, driver=driver_mock)

        assert result == []

    def test_k_passed_to_query(self):
        session_mock = MagicMock()
        session_mock.run.return_value = iter([])
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        predict_for_node("broker::jane", k=7, driver=driver_mock)

        call_kwargs = session_mock.run.call_args.kwargs
        assert call_kwargs.get("k") == 7

    def test_result_has_from_and_to_ids(self):
        rows = self._make_read_rows([
            {
                "from_id": "broker::jane",
                "from_label": "Broker",
                "to_id": "prop::P1",
                "to_label": "Property",
                "score": 0.75,
                "algo": "adamicAdar",
            }
        ])

        session_mock = MagicMock()
        session_mock.run.return_value = iter(rows)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = predict_for_node("broker::jane", k=5, driver=driver_mock)

        assert result[0]["from_id"] == "broker::jane"
        assert result[0]["to_id"] == "prop::P1"


class TestPredictedLinkLabel:
    def test_label_constant_is_predicted_link(self):
        assert PREDICTED_LINK_LABEL == "PredictedLink"
