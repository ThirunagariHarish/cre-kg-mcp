"""
Unit tests for mcp_server/tools/cypher_query.py.

Tests:
- read_only=True + MATCH query → OK
- read_only=True + CREATE clause → ERROR (pre-check)
- read_only=True + MERGE clause → ERROR (pre-check)
- read_only=True + DELETE clause → ERROR (pre-check)
- Driver exception → ERROR response (no raise)
- MCP tool registration smoke test
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_server.tools.cypher_query import register, _has_write_clause


class TestHasWriteClause:
    def test_match_is_safe(self):
        assert _has_write_clause("MATCH (n) RETURN count(n)") is False

    def test_create_flagged(self):
        assert _has_write_clause("CREATE (n:Broker {name: 'X'})") is True

    def test_merge_flagged(self):
        assert _has_write_clause("MERGE (n:Broker {broker_key: 'x'})") is True

    def test_delete_flagged(self):
        assert _has_write_clause("MATCH (n) DELETE n") is True

    def test_set_flagged(self):
        assert _has_write_clause("MATCH (n) SET n.x = 1") is True

    def test_case_insensitive(self):
        assert _has_write_clause("create (n)") is True


class TestCypherQueryTool:
    def _make_driver(self, records=None, raises=None):
        driver = MagicMock()
        session = MagicMock()
        driver.session.return_value.__enter__ = lambda s: session
        driver.session.return_value.__exit__ = MagicMock(return_value=False)

        if raises:
            session.execute_read.side_effect = raises
        else:
            rows = records or [{"count(n)": 42}]
            session.execute_read.return_value = rows

        return driver

    def _make_mock_server_and_tool(self, driver):
        """
        Extract the registered tool function by capturing the decorator call.
        """
        from mcp_server.tools import cypher_query as cq_mod

        captured = {}

        class FakeMCP:
            def tool(self, name, description):
                def decorator(fn):
                    captured["fn"] = fn
                    return fn
                return decorator

        register(FakeMCP(), lambda: driver)
        return captured["fn"]

    @pytest.mark.asyncio
    async def test_read_only_match_returns_ok(self):
        driver = self._make_driver(records=[{"count(n)": 42}])
        fn = self._make_mock_server_and_tool(driver)
        result = await fn(query="MATCH (n) RETURN count(n)", read_only=True)
        assert result["status"] == "OK"
        assert result["row_count"] == 1

    @pytest.mark.asyncio
    async def test_create_rejected_in_read_only(self):
        driver = self._make_driver()
        fn = self._make_mock_server_and_tool(driver)
        result = await fn(query="CREATE (n:Broker {name:'X'})", read_only=True)
        assert result["status"] == "ERROR"
        assert "Read-only" in result["error"]

    @pytest.mark.asyncio
    async def test_merge_rejected_in_read_only(self):
        driver = self._make_driver()
        fn = self._make_mock_server_and_tool(driver)
        result = await fn(query="MERGE (n:Broker {broker_key:'x'})", read_only=True)
        assert result["status"] == "ERROR"

    @pytest.mark.asyncio
    async def test_delete_rejected_in_read_only(self):
        driver = self._make_driver()
        fn = self._make_mock_server_and_tool(driver)
        result = await fn(query="MATCH (n) DELETE n", read_only=True)
        assert result["status"] == "ERROR"

    @pytest.mark.asyncio
    async def test_driver_exception_returns_error_not_raises(self):
        driver = self._make_driver(raises=Exception("Bolt connection reset"))
        fn = self._make_mock_server_and_tool(driver)
        result = await fn(query="MATCH (n) RETURN n", read_only=True)
        assert result["status"] == "ERROR"
        assert "Bolt connection reset" in result["error"]
