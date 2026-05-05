"""
tests/test_predict_links.py

Unit tests for mcp_server/tools/predict_links.py.

M-P3-5: Asserts display names are resolved from source nodes (not merge keys).
Asserts node_id format documentation is present in tool description.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from mcp_server.tools.predict_links import run_predict_links, _resolve_display_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pl_row(from_id, to_id, score=0.8, from_label="Broker", to_label="Property",
                 broker_name=None, property_name=None, tenant_name=None, computed_at="2026-05-05T12:00:00Z"):
    """Build a mock PredictedLink row."""
    row = MagicMock()
    data = {
        "from_id": from_id,
        "from_label": from_label,
        "to_id": to_id,
        "to_label": to_label,
        "score": score,
        "algo": "adamicAdar",
        "computed_at": computed_at,
        "broker_name": broker_name,
        "property_name": property_name,
        "tenant_name": tenant_name,
    }
    row.__getitem__ = lambda self, key: data[key]
    return row


def _make_driver_mock(total_count: int, pl_rows: list):
    """Build a mock driver returning total_count and pl_rows."""
    count_row = MagicMock()
    count_row.__getitem__ = lambda self, key: total_count

    predictions_result = MagicMock()
    predictions_result.__iter__ = lambda s: iter(pl_rows)

    session_mock = MagicMock()
    session_mock.__enter__ = lambda s: s
    session_mock.__exit__ = MagicMock(return_value=False)

    call_count = [0]
    def _run(cypher, **kwargs):
        c = call_count[0]
        call_count[0] += 1
        if c == 0:
            # COUNT query
            cnt = MagicMock()
            cnt.single.return_value = count_row
            return cnt
        else:
            return predictions_result

    session_mock.run.side_effect = _run
    driver = MagicMock()
    driver.session.return_value = session_mock
    return driver


# ---------------------------------------------------------------------------
# M-P3-5: display name resolution
# ---------------------------------------------------------------------------

class TestResolvDisplayName:
    def test_broker_name_resolved_from_broker_name_field(self):
        """M-P3-5: Broker display name comes from .name property, not merge key."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {"broker_name": "Jane Liu", "property_name": None, "tenant_name": None}[key]

        result = _resolve_display_name(row, "Broker", "email::jane@cbre.com")

        assert result == "Jane Liu"

    def test_broker_falls_back_to_node_id_when_name_is_none(self):
        """M-P3-5: Falls back to node_id when broker_name is None (node not found)."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {"broker_name": None, "property_name": None, "tenant_name": None}[key]

        result = _resolve_display_name(row, "Broker", "email::unknown@firm.com")

        assert result == "email::unknown@firm.com"

    def test_property_name_resolved_from_address(self):
        """M-P3-5: Property display name comes from .address_line1."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {"broker_name": None, "property_name": "1450 Logistics Pkwy", "tenant_name": None}[key]

        result = _resolve_display_name(row, "Property", "id::P-9921")

        assert result == "1450 Logistics Pkwy"

    def test_tenant_name_resolved_from_name_field(self):
        """M-P3-5: Tenant display name comes from .name property."""
        row = MagicMock()
        row.__getitem__ = lambda self, key: {"broker_name": None, "property_name": None, "tenant_name": "Acme Corp"}[key]

        result = _resolve_display_name(row, "Tenant", "name::acme corp")

        assert result == "Acme Corp"

    def test_unknown_label_returns_node_id(self):
        """Unknown label returns node_id as fallback."""
        row = MagicMock()
        result = _resolve_display_name(row, "UnknownLabel", "some::id")
        assert result == "some::id"


class TestPredictLinksDisplayNames:
    @pytest.mark.asyncio
    async def test_from_name_uses_broker_name_not_merge_key(self):
        """M-P3-5: from.name is broker's display name, not the merge key."""
        pl_row = _make_pl_row(
            from_id="email::jane@cbre.com",
            to_id="id::P-9921",
            broker_name="Jane Liu",
            property_name="1450 Logistics Pkwy",
        )
        driver = _make_driver_mock(total_count=1, pl_rows=[pl_row])

        result = await run_predict_links(driver, to_label="Property", min_score=0.5, k=10)

        assert result["status"] == "OK"
        prediction = result["predictions"][0]
        assert prediction["from"]["name"] == "Jane Liu"
        assert prediction["from"]["id"] == "email::jane@cbre.com"

    @pytest.mark.asyncio
    async def test_to_name_uses_property_address_not_merge_key(self):
        """M-P3-5: to.name is property address, not the merge key."""
        pl_row = _make_pl_row(
            from_id="email::jane@cbre.com",
            to_id="id::P-9921",
            broker_name="Jane Liu",
            property_name="1450 Logistics Pkwy",
        )
        driver = _make_driver_mock(total_count=1, pl_rows=[pl_row])

        result = await run_predict_links(driver, to_label="Property", min_score=0.5, k=10)

        prediction = result["predictions"][0]
        assert prediction["to"]["name"] == "1450 Logistics Pkwy"
        assert prediction["to"]["id"] == "id::P-9921"

    @pytest.mark.asyncio
    async def test_to_name_uses_tenant_name_for_tenant_label(self):
        """M-P3-5: to.name is tenant display name for Broker→Tenant predictions."""
        pl_row = _make_pl_row(
            from_id="email::tom@jll.com",
            to_id="name::acme corp",
            to_label="Tenant",
            broker_name="Tom Patel",
            tenant_name="Acme Corp",
        )
        driver = _make_driver_mock(total_count=1, pl_rows=[pl_row])

        result = await run_predict_links(driver, to_label="Tenant", min_score=0.5, k=10)

        prediction = result["predictions"][0]
        assert prediction["to"]["name"] == "Acme Corp"

    @pytest.mark.asyncio
    async def test_fallback_to_merge_key_when_node_not_found(self):
        """M-P3-5: Falls back to merge key when the source node is not found in Neo4j."""
        pl_row = _make_pl_row(
            from_id="email::ghost@gone.com",
            to_id="id::P-0000",
            broker_name=None,   # Node not found via JOIN
            property_name=None,
        )
        driver = _make_driver_mock(total_count=1, pl_rows=[pl_row])

        result = await run_predict_links(driver, to_label="Property", min_score=0.5, k=10)

        prediction = result["predictions"][0]
        assert prediction["from"]["name"] == "email::ghost@gone.com"
        assert prediction["to"]["name"] == "id::P-0000"


class TestPredictLinksNodeIdFormat:
    @pytest.mark.asyncio
    async def test_node_id_format_documented_in_description(self):
        """M-P3-5: Tool description documents the node_id merge key format."""
        from mcp_server.tools.predict_links import register
        from unittest.mock import MagicMock

        # Capture the tool description by registering on a fresh MCP-like mock
        mock_mcp = MagicMock()
        registered_description = []

        def capture_tool(*args, **kwargs):
            desc = kwargs.get("description", "")
            registered_description.append(desc)
            def decorator(fn):
                return fn
            return decorator

        mock_mcp.tool = capture_tool
        register(mock_mcp, lambda: MagicMock())

        desc = registered_description[0]
        assert "email::" in desc, "Tool description must document email:: broker id format"
        assert "id::" in desc, "Tool description must document id:: property id format"
        assert "name::" in desc, "Tool description must document name:: tenant id format"


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

class TestPredictLinksEdgeCases:
    @pytest.mark.asyncio
    async def test_invalid_to_label_returns_error(self):
        """to_label must be 'Property' or 'Tenant'."""
        driver = MagicMock()

        result = await run_predict_links(driver, to_label="Broker")

        assert result["status"] == "ERROR"
        assert result["predictions"] == []

    @pytest.mark.asyncio
    async def test_no_predictions_returns_ok_empty(self):
        """No predictions meeting min_score returns OK with empty list."""
        driver = _make_driver_mock(total_count=5, pl_rows=[])

        result = await run_predict_links(driver, to_label="Property", min_score=0.99, k=10)

        assert result["status"] == "OK"
        assert result["predictions"] == []

    @pytest.mark.asyncio
    async def test_zero_total_count_returns_degraded(self):
        """Zero PredictedLink nodes means link prediction has not yet run."""
        driver = _make_driver_mock(total_count=0, pl_rows=[])

        result = await run_predict_links(driver, to_label="Property")

        assert result["status"] == "DEGRADED"
        assert "has not yet run" in result["error"]
