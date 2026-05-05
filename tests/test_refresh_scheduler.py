"""
tests/test_refresh_scheduler.py

Unit tests for ml/refresh.py.

Asserts:
- run_ml_pipeline calls embeddings → communities → link_prediction in order
- run_ml_pipeline updates :MLRunMeta after success
- Override fires when new insight count >= 50
- Override does NOT fire when count < 50
- run_ml_pipeline returns ERROR if any sub-step fails
- _count_new_insights correctly counts insights since last_run_at
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

import ml.refresh as refresh_module
from ml.refresh import (
    run_ml_pipeline,
    _should_override,
    _count_new_insights,
    _get_last_run_time,
    _update_last_run_time,
    NEW_INSIGHT_THRESHOLD,
    ML_META_KEY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session_mock(count: int = 0, last_run_at_val=None):
    """Mock session that returns a fixed count for count queries."""
    cnt_row = MagicMock()
    cnt_row.__getitem__ = lambda self, key: count if key == "cnt" else None

    meta_row = MagicMock()
    meta_row.__getitem__ = lambda self, key: last_run_at_val if key == "last_run_at" else None

    session = MagicMock()

    def _run(cypher, **kwargs):
        result = MagicMock()
        if "count(i)" in cypher:
            result.single.return_value = cnt_row
        elif "MLRunMeta" in cypher and "RETURN" in cypher:
            result.single.return_value = meta_row
        elif "MLRunMeta" in cypher and "SET" in cypher:
            result.single.return_value = None
        else:
            result.single.return_value = None
        return result

    session.run.side_effect = _run
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# _count_new_insights tests
# ---------------------------------------------------------------------------

class TestCountNewInsights:
    def test_returns_count_from_db(self):
        session = _make_session_mock(count=42)

        count = _count_new_insights(session, since=None)

        assert count == 42

    def test_count_with_since_uses_time_filter(self):
        session = _make_session_mock(count=5)
        since = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)

        count = _count_new_insights(session, since=since)

        assert count == 5
        call_args = session.run.call_args
        cypher = call_args.args[0]
        assert "ingested_at" in cypher

    def test_count_without_since_matches_all(self):
        session = _make_session_mock(count=100)

        count = _count_new_insights(session, since=None)

        assert count == 100
        call_args = session.run.call_args
        cypher = call_args.args[0]
        # No time filter when since=None
        assert "ingested_at" not in cypher


# ---------------------------------------------------------------------------
# _should_override tests
# ---------------------------------------------------------------------------

class TestShouldOverride:
    def test_override_fires_at_threshold(self):
        session = _make_session_mock(count=50)
        result = _should_override(session, last_run_at=None)
        assert result is True

    def test_override_fires_above_threshold(self):
        session = _make_session_mock(count=75)
        result = _should_override(session, last_run_at=None)
        assert result is True

    def test_override_does_not_fire_below_threshold(self):
        session = _make_session_mock(count=49)
        result = _should_override(session, last_run_at=None)
        assert result is False

    def test_override_does_not_fire_at_zero(self):
        session = _make_session_mock(count=0)
        result = _should_override(session, last_run_at=None)
        assert result is False

    def test_threshold_constant_is_50(self):
        assert NEW_INSIGHT_THRESHOLD == 50


# ---------------------------------------------------------------------------
# run_ml_pipeline tests
# ---------------------------------------------------------------------------

class TestRunMlPipeline:
    def _make_ok_result(self):
        return {"status": "OK"}

    def _make_error_result(self, msg="fail"):
        return {"status": "ERROR", "error": msg}

    def test_returns_ok_when_all_steps_succeed(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_communities", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_link_prediction", return_value=self._make_ok_result())

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        result = run_ml_pipeline(driver=driver)

        assert result["status"] == "OK"

    def test_embeddings_called_before_communities(self, mocker):
        call_order = []
        mocker.patch("ml.refresh.run_embeddings", side_effect=lambda *a, **kw: (call_order.append("emb"), {"status": "OK"})[1])
        mocker.patch("ml.refresh.run_communities", side_effect=lambda *a, **kw: (call_order.append("comm"), {"status": "OK"})[1])
        mocker.patch("ml.refresh.run_link_prediction", side_effect=lambda *a, **kw: (call_order.append("link"), {"status": "OK"})[1])

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        run_ml_pipeline(driver=driver)

        assert call_order.index("emb") < call_order.index("comm")

    def test_communities_called_before_link_prediction(self, mocker):
        call_order = []
        mocker.patch("ml.refresh.run_embeddings", side_effect=lambda *a, **kw: (call_order.append("emb"), {"status": "OK"})[1])
        mocker.patch("ml.refresh.run_communities", side_effect=lambda *a, **kw: (call_order.append("comm"), {"status": "OK"})[1])
        mocker.patch("ml.refresh.run_link_prediction", side_effect=lambda *a, **kw: (call_order.append("link"), {"status": "OK"})[1])

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        run_ml_pipeline(driver=driver)

        assert call_order.index("comm") < call_order.index("link")

    def test_ml_run_meta_updated_after_success(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_communities", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_link_prediction", return_value=self._make_ok_result())

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        run_ml_pipeline(driver=driver)

        # Verify SET last_run_at was called
        all_cyphers = [str(c.args[0]) for c in session.run.call_args_list]
        meta_updates = [q for q in all_cyphers if "MLRunMeta" in q and "SET" in q]
        assert len(meta_updates) >= 1, "Expected MLRunMeta SET call after success"

    def test_returns_error_when_embeddings_fail(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value=self._make_error_result("emb fail"))
        mocker.patch("ml.refresh.run_communities", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_link_prediction", return_value=self._make_ok_result())

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        result = run_ml_pipeline(driver=driver)

        assert result["status"] == "ERROR"

    def test_returns_error_when_communities_fail(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_communities", return_value=self._make_error_result("comm fail"))
        mocker.patch("ml.refresh.run_link_prediction", return_value=self._make_ok_result())

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        result = run_ml_pipeline(driver=driver)

        assert result["status"] == "ERROR"

    def test_run_at_present_in_ok_result(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_communities", return_value=self._make_ok_result())
        mocker.patch("ml.refresh.run_link_prediction", return_value=self._make_ok_result())

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        result = run_ml_pipeline(driver=driver)

        assert "run_at" in result

    def test_results_dict_contains_all_three_sub_results(self, mocker):
        mocker.patch("ml.refresh.run_embeddings", return_value={"status": "OK", "node_count": 100})
        mocker.patch("ml.refresh.run_communities", return_value={"status": "OK", "community_count": 7})
        mocker.patch("ml.refresh.run_link_prediction", return_value={"status": "OK", "count": 20})

        session = _make_session_mock()
        driver = MagicMock()
        driver.session.return_value = session

        result = run_ml_pipeline(driver=driver)

        assert "embeddings" in result["results"]
        assert "communities" in result["results"]
        assert "link_prediction" in result["results"]
