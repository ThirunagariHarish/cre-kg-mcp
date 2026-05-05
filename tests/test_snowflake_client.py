"""
Unit tests for ingester/snowflake_client.py — Snowflake connection (mocked).

No actual Snowflake calls. Uses pytest-mock to patch snowflake.connector.connect.
"""

from __future__ import annotations

import pytest
import snowflake.connector
from unittest.mock import MagicMock, patch

from ingester.snowflake_client import get_connection, probe_tables, fetch_all


class TestGetConnection:
    def test_connect_called_with_env_params(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "TEST_ACCOUNT")
        monkeypatch.setenv("SNOWFLAKE_USER", "TEST_USER")
        monkeypatch.setenv("SNOWFLAKE_PASSWORD", "TEST_PASS")
        monkeypatch.setenv("SNOWFLAKE_ROLE", "SYSADMIN")
        monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "WH")
        monkeypatch.setenv("SNOWFLAKE_DATABASE", "DB")
        monkeypatch.setenv("SNOWFLAKE_SCHEMA", "SCH")

        mock_conn = MagicMock()
        with patch("snowflake.connector.connect", return_value=mock_conn) as mock_connect:
            conn = get_connection()
            assert conn is mock_conn
            call_kwargs = mock_connect.call_args.kwargs
            assert call_kwargs["account"] == "TEST_ACCOUNT"
            assert call_kwargs["user"] == "TEST_USER"
            assert call_kwargs["password"] == "TEST_PASS"

    def test_connect_raises_on_auth_failure(self, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "BAD")
        monkeypatch.setenv("SNOWFLAKE_USER", "BAD")
        monkeypatch.setenv("SNOWFLAKE_PASSWORD", "BAD")

        with patch(
            "snowflake.connector.connect",
            side_effect=snowflake.connector.errors.DatabaseError("250001: auth failed"),
        ):
            with pytest.raises(snowflake.connector.errors.DatabaseError):
                get_connection()


class TestProbeTables:
    def test_all_tables_ok(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor

        results = probe_tables(mock_conn)
        for table, status in results.items():
            assert status == "ok", f"{table} unexpectedly not ok: {status}"

    def test_failed_table_reported(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_cursor.execute.side_effect = Exception("permission denied")
        mock_conn.cursor.return_value = mock_cursor

        results = probe_tables(mock_conn)
        for table, status in results.items():
            assert status.startswith("error:"), f"{table} should have failed but got: {status}"


class TestFetchAll:
    def test_yields_batches_as_dicts(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = lambda s: s
        mock_cursor.__exit__ = MagicMock(return_value=False)

        # Simulate two batches then empty
        batch1 = [{"BROKER_NAME": "Alice", "FIRM": "CBRE"}]
        batch2 = [{"BROKER_NAME": "Bob", "FIRM": "JLL"}]
        mock_cursor.fetchmany.side_effect = [batch1, batch2, []]
        mock_conn.cursor.return_value = mock_cursor

        rows = []
        for batch in fetch_all(mock_conn, "CRE_BROKERS", batch_size=1):
            rows.extend(batch)

        assert len(rows) == 2
        assert rows[0]["BROKER_NAME"] == "Alice"
        assert rows[1]["BROKER_NAME"] == "Bob"
