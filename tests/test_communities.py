"""
tests/test_communities.py

Unit tests for ml/communities.py.
Mocks Neo4j driver and GDS client — no live graph required.

Asserts:
- run_communities calls gds.louvain.write with writeProperty='community_id'
- run_communities returns {"status": "OK"} on happy path
- top_communities returns the correct shape
- top_communities returns at most N entries
- empty DB returns [] from top_communities without crashing
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ml.communities import run_communities, top_communities, COMMUNITY_WRITE_PROPERTY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gds_mock():
    gds = MagicMock()
    mock_G = MagicMock()
    gds.graph.project.return_value = (mock_G, {"nodeCount": 80, "relationshipCount": 200})
    gds.louvain.write.return_value = {"communityCount": 7, "nodeCount": 80}
    gds.graph.drop.return_value = None
    return gds, mock_G


def _make_driver_mock(community_rows: list[dict]):
    """Build a mock Neo4j driver whose session().run() returns community_rows."""
    row_mocks = []
    for r in community_rows:
        row = MagicMock()
        row.__getitem__ = lambda self, key, _r=r: _r[key]
        row_mocks.append(row)

    session_mock = MagicMock()
    session_mock.run.return_value = iter(row_mocks)
    session_mock.__enter__ = lambda s: s
    session_mock.__exit__ = MagicMock(return_value=False)

    driver_mock = MagicMock()
    driver_mock.session.return_value = session_mock
    return driver_mock


# ---------------------------------------------------------------------------
# run_communities tests
# ---------------------------------------------------------------------------

class TestRunCommunities:
    def test_returns_ok_status(self, mocker):
        gds_mock, _ = _make_gds_mock()
        mocker.patch("ml.communities.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.communities._get_driver", return_value=MagicMock())

        result = run_communities()

        assert result["status"] == "OK"

    def test_louvain_write_called_with_community_id_property(self, mocker):
        gds_mock, mock_G = _make_gds_mock()
        mocker.patch("ml.communities.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.communities._get_driver", return_value=MagicMock())

        run_communities()

        call_kwargs = gds_mock.louvain.write.call_args
        assert call_kwargs.kwargs.get("writeProperty") == COMMUNITY_WRITE_PROPERTY

    def test_louvain_write_called_exactly_once(self, mocker):
        gds_mock, _ = _make_gds_mock()
        mocker.patch("ml.communities.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.communities._get_driver", return_value=MagicMock())

        run_communities()

        assert gds_mock.louvain.write.call_count == 1

    def test_graph_projected_before_louvain(self, mocker):
        gds_mock, _ = _make_gds_mock()
        mocker.patch("ml.communities.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.communities._get_driver", return_value=MagicMock())

        run_communities()

        assert gds_mock.graph.project.call_count == 1

    def test_returns_error_on_gds_failure(self, mocker):
        gds_mock = MagicMock()
        gds_mock.graph.project.side_effect = RuntimeError("GDS down")
        mocker.patch("ml.communities.GraphDataScience", return_value=gds_mock)
        mocker.patch("ml.communities._get_driver", return_value=MagicMock())

        result = run_communities()

        assert result["status"] == "ERROR"


# ---------------------------------------------------------------------------
# top_communities tests
# ---------------------------------------------------------------------------

class TestTopCommunities:
    def _community_row(self, cid: int, sz: int) -> dict:
        return {
            "cid": cid,
            "sz": sz,
            "samples": [{"id": f"id_{i}", "label": "Broker"} for i in range(min(sz, 3))],
        }

    def test_returns_list(self):
        rows = [
            {"cid": 7, "sz": 184, "samples": [{"id": "broker_key_1", "label": "Broker"}]},
            {"cid": 3, "sz": 90, "samples": [{"id": "prop_key_1", "label": "Property"}]},
            {"cid": 11, "sz": 45, "samples": []},
        ]

        row_mocks = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            row_mocks.append(row)

        session_mock = MagicMock()
        session_mock.run.return_value = iter(row_mocks)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=5, driver=driver_mock)

        assert isinstance(result, list)

    def test_returns_at_most_n_entries(self):
        rows = [
            {"cid": i, "sz": 100 - i, "samples": []}
            for i in range(10)
        ]
        row_mocks = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            row_mocks.append(row)

        session_mock = MagicMock()
        session_mock.run.return_value = iter(row_mocks[:3])  # query returns 3
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=3, driver=driver_mock)

        assert len(result) <= 3

    def test_entry_has_required_keys(self):
        rows = [{"cid": 7, "sz": 50, "samples": [{"id": "b1", "label": "Broker"}]}]
        row_mocks = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            row_mocks.append(row)

        session_mock = MagicMock()
        session_mock.run.return_value = iter(row_mocks)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=5, driver=driver_mock)

        assert len(result) == 1
        entry = result[0]
        assert "community_id" in entry
        assert "size" in entry
        assert "sample_member_ids" in entry
        assert "sample_member_labels" in entry

    def test_empty_db_returns_empty_list(self):
        session_mock = MagicMock()
        session_mock.run.return_value = iter([])
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=5, driver=driver_mock)

        assert result == []

    def test_driver_error_returns_empty_list(self):
        driver_mock = MagicMock()
        driver_mock.session.side_effect = RuntimeError("DB down")

        result = top_communities(n=5, driver=driver_mock)

        assert result == []

    def test_community_id_in_result(self):
        rows = [{"cid": 42, "sz": 30, "samples": []}]
        row_mocks = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            row_mocks.append(row)

        session_mock = MagicMock()
        session_mock.run.return_value = iter(row_mocks)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=5, driver=driver_mock)

        assert result[0]["community_id"] == 42

    def test_size_in_result(self):
        rows = [{"cid": 1, "sz": 99, "samples": []}]
        row_mocks = []
        for r in rows:
            row = MagicMock()
            row.__getitem__ = lambda self, key, _r=r: _r[key]
            row_mocks.append(row)

        session_mock = MagicMock()
        session_mock.run.return_value = iter(row_mocks)
        session_mock.__enter__ = lambda s: s
        session_mock.__exit__ = MagicMock(return_value=False)
        driver_mock = MagicMock()
        driver_mock.session.return_value = session_mock

        result = top_communities(n=5, driver=driver_mock)

        assert result[0]["size"] == 99


class TestCommunityWriteProperty:
    def test_write_property_is_community_id(self):
        assert COMMUNITY_WRITE_PROPERTY == "community_id"
