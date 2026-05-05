"""
Unit tests for mcp_server/tools/health_check.py.

Mocks the Neo4j driver; tests OK and DEGRADED paths.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from mcp_server.tools.health_check import run_health_check


def _make_mock_driver(gds_version="2.6.0", node_rows=None, edge_rows=None, raises=None):
    """
    Build a mock Neo4j Driver whose session().run() returns canned data.

    _get_gds_version() tries three queries in sequence (gdsVersion, version, bare).
    The first two fail on KeyError because the mock returns {"gdsVersion": version}.
    We supply a side_effect list long enough for all three GDS attempts plus the
    node-count and edge-count queries.
    """
    mock_driver = MagicMock()

    if raises is not None:
        mock_driver.session.return_value.__enter__.side_effect = raises
        return mock_driver

    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__ = lambda s: mock_session
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    # _get_gds_version (M6): GDS 2.6 returns gdsVersion column.
    # First attempt "CALL gds.version() YIELD gdsVersion" succeeds directly.
    gds_result_ok = MagicMock()
    gds_result_ok.single.return_value = {"gdsVersion": gds_version}

    # node count result
    node_rows = node_rows or [{"label": "Broker", "cnt": 100}, {"label": "Property", "cnt": 500}]
    node_result = MagicMock()
    node_result.__iter__ = lambda s: iter(node_rows)

    # edge count result
    edge_rows = edge_rows or [{"rel_type": "BROKERED_BY", "cnt": 300}]
    edge_result = MagicMock()
    edge_result.__iter__ = lambda s: iter(edge_rows)

    # insight age result (no Insight nodes yet)
    insight_result = MagicMock()
    insight_result.single.return_value = None

    # ml_freshness result (B-P3-5 FIX: now queries MLRunMeta)
    ml_meta_result = MagicMock()
    ml_meta_result.single.return_value = None  # no ML run yet

    # side_effect order: gds -> node_counts -> edge_counts -> insight_age -> ml_freshness
    mock_session.run.side_effect = [gds_result_ok, node_result, edge_result, insight_result, ml_meta_result]

    return mock_driver


@pytest.mark.asyncio
async def test_health_check_ok_status():
    driver = _make_mock_driver(gds_version="2.6.0")
    result = await run_health_check(driver)
    assert result["status"] == "OK"
    assert result["neo4j_reachable"] is True
    assert result["gds"] == "2.6.0"
    assert result["snowflake"] == "not_probed_by_mcp_process"


@pytest.mark.asyncio
async def test_health_check_node_counts_populated():
    driver = _make_mock_driver(
        node_rows=[
            {"label": "Broker", "cnt": 1240},
            {"label": "Property", "cnt": 87234},
        ]
    )
    result = await run_health_check(driver)
    assert result["node_counts"]["Broker"] == 1240
    assert result["node_counts"]["Property"] == 87234


@pytest.mark.asyncio
async def test_health_check_degraded_when_neo4j_unreachable():
    driver = MagicMock()
    driver.session.side_effect = Exception("Connection refused")

    result = await run_health_check(driver)
    assert result["status"] == "DEGRADED"
    assert result["neo4j_reachable"] is False
    assert "Connection refused" in result["error"]
    assert len(result["warnings"]) > 0


@pytest.mark.asyncio
async def test_health_check_never_raises():
    """health_check must never propagate an exception to the MCP caller."""
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("unexpected crash")

    # Should not raise
    result = await run_health_check(driver)
    assert result["status"] == "DEGRADED"


# ---------------------------------------------------------------------------
# B-P3-5: last_ml_run_at and ml_freshness_warning tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_check_last_ml_run_at_none_when_no_ml_meta():
    """B-P3-5: last_ml_run_at is None when no MLRunMeta node exists."""
    driver = _make_mock_driver()
    result = await run_health_check(driver)
    # No ML run meta seeded — last 4th entry is None from the mock
    assert result["last_ml_run_at"] is None
    assert result["ml_freshness_warning"] is False


@pytest.mark.asyncio
async def test_health_check_last_ml_run_at_populated_from_neo4j():
    """B-P3-5: last_ml_run_at is populated from MLRunMeta node query."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock

    # Simulate a recent ML run (5 minutes ago — not stale)
    recent_dt = datetime.now(timezone.utc) - timedelta(minutes=5)

    # Build mock where ml_meta row returns a Neo4j-like datetime
    neo4j_dt = MagicMock()
    neo4j_dt.to_native.return_value = recent_dt

    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__ = lambda s: mock_session
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    gds_result = MagicMock()
    gds_result.single.return_value = {"gdsVersion": "2.6.0"}
    node_result = MagicMock()
    node_result.__iter__ = lambda s: iter([])
    edge_result = MagicMock()
    edge_result.__iter__ = lambda s: iter([])
    insight_result = MagicMock()
    insight_result.single.return_value = None
    ml_meta_result = MagicMock()
    ml_meta_result.single.return_value = {"last_ml_run_at": neo4j_dt}

    mock_session.run.side_effect = [gds_result, node_result, edge_result, insight_result, ml_meta_result]

    result = await run_health_check(mock_driver)
    assert result["last_ml_run_at"] is not None
    assert result["ml_freshness_warning"] is False


@pytest.mark.asyncio
async def test_health_check_ml_freshness_warning_when_stale():
    """B-P3-5: ml_freshness_warning is True when last ML run was >30 min ago."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import MagicMock

    # Simulate a stale ML run (35 minutes ago)
    stale_dt = datetime.now(timezone.utc) - timedelta(minutes=35)

    neo4j_dt = MagicMock()
    neo4j_dt.to_native.return_value = stale_dt

    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__ = lambda s: mock_session
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    gds_result = MagicMock()
    gds_result.single.return_value = {"gdsVersion": "2.6.0"}
    node_result = MagicMock()
    node_result.__iter__ = lambda s: iter([])
    edge_result = MagicMock()
    edge_result.__iter__ = lambda s: iter([])
    insight_result = MagicMock()
    insight_result.single.return_value = None
    ml_meta_result = MagicMock()
    ml_meta_result.single.return_value = {"last_ml_run_at": neo4j_dt}

    mock_session.run.side_effect = [gds_result, node_result, edge_result, insight_result, ml_meta_result]

    result = await run_health_check(mock_driver)
    assert result["ml_freshness_warning"] is True
    assert any("stale" in w.lower() or "ml" in w.lower() for w in result["warnings"])
