"""Unit tests for core/earnings_calendar.py."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import core.earnings_calendar as ec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_cache(tmp_path: Path, data: dict[str, str]) -> Path:
    cache_path = tmp_path / "earnings_calendar.json"
    cache_path.write_text(json.dumps(data))
    return cache_path


# ---------------------------------------------------------------------------
# get_earnings_date
# ---------------------------------------------------------------------------

class TestGetEarningsDate:
    def test_returns_date_from_cache(self, tmp_path):
        future = (date.today() + timedelta(days=10)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": future})
        with patch.object(ec, "_CACHE_PATH", cache):
            d = ec.get_earnings_date("AAPL")
        assert d == date.fromisoformat(future)

    def test_symbol_not_in_cache(self, tmp_path):
        cache = _write_cache(tmp_path, {"MSFT": "2026-07-22"})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.get_earnings_date("AAPL") is None

    def test_case_insensitive(self, tmp_path):
        future = (date.today() + timedelta(days=5)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": future})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.get_earnings_date("aapl") is not None

    def test_missing_cache_file(self, tmp_path):
        missing = tmp_path / "no_cache.json"
        with patch.object(ec, "_CACHE_PATH", missing):
            assert ec.get_earnings_date("AAPL") is None

    def test_invalid_date_returns_none(self, tmp_path):
        cache = _write_cache(tmp_path, {"AAPL": "not-a-date"})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.get_earnings_date("AAPL") is None


# ---------------------------------------------------------------------------
# is_within_earnings_window
# ---------------------------------------------------------------------------

class TestIsWithinEarningsWindow:
    def test_within_window(self, tmp_path):
        """Earnings in 7 days → within 14-day gate → True."""
        earnings_date = (date.today() + timedelta(days=7)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL") is True

    def test_outside_window(self, tmp_path):
        """Earnings in 30 days → outside 14-day gate → False."""
        earnings_date = (date.today() + timedelta(days=30)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL") is False

    def test_no_date(self, tmp_path):
        """Symbol not in calendar → False."""
        cache = _write_cache(tmp_path, {})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("UNKNOWN") is False

    def test_exactly_at_gate_boundary(self, tmp_path):
        """Earnings exactly on gate_days → True (|diff| == gate_days)."""
        earnings_date = (date.today() + timedelta(days=14)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL", gate_days=14) is True

    def test_just_beyond_gate(self, tmp_path):
        """Earnings at gate_days+1 → False."""
        earnings_date = (date.today() + timedelta(days=15)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL", gate_days=14) is False

    def test_past_earnings_within_window(self, tmp_path):
        """Earnings 5 days AGO still within window (abs diff check)."""
        past_date = (date.today() - timedelta(days=5)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": past_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL") is True

    def test_custom_gate_days(self, tmp_path):
        """Custom gate_days=7: earnings in 10 days → False."""
        earnings_date = (date.today() + timedelta(days=10)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.is_within_earnings_window("AAPL", gate_days=7) is False


# ---------------------------------------------------------------------------
# days_to_earnings
# ---------------------------------------------------------------------------

class TestDaysToEarnings:
    def test_positive_days(self, tmp_path):
        earnings_date = (date.today() + timedelta(days=10)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": earnings_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.days_to_earnings("AAPL") == 10

    def test_negative_days_past(self, tmp_path):
        past_date = (date.today() - timedelta(days=3)).isoformat()
        cache = _write_cache(tmp_path, {"AAPL": past_date})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.days_to_earnings("AAPL") == -3

    def test_unknown_symbol_returns_none(self, tmp_path):
        cache = _write_cache(tmp_path, {})
        with patch.object(ec, "_CACHE_PATH", cache):
            assert ec.days_to_earnings("XYZ") is None

    def test_missing_cache_returns_none(self, tmp_path):
        missing = tmp_path / "no_cache.json"
        with patch.object(ec, "_CACHE_PATH", missing):
            assert ec.days_to_earnings("AAPL") is None


# ---------------------------------------------------------------------------
# refresh_calendar (async, mocked HTTP)
# ---------------------------------------------------------------------------

class TestRefreshCalendar:
    @pytest.mark.asyncio
    async def test_refresh_writes_future_date(self, tmp_path):
        """refresh_calendar should fetch and cache next earnings date."""
        future = (date.today() + timedelta(days=45)).isoformat()
        fake_response = {
            "quarterlyEarnings": [
                {"reportedDate": future, "fiscalDateEnding": future},
                # past date — should be ignored
                {"reportedDate": "2020-01-15", "fiscalDateEnding": "2020-01-15"},
            ]
        }

        # Empty starting cache
        cache_path = tmp_path / "earnings_calendar.json"
        cache_path.write_text("{}")

        import aiohttp
        from unittest.mock import AsyncMock, MagicMock

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=fake_response)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch.object(ec, "_CACHE_PATH", cache_path), \
             patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            await ec.refresh_calendar(["AAPL"])

        result = json.loads(cache_path.read_text())
        assert "AAPL" in result
        assert result["AAPL"] == future

    @pytest.mark.asyncio
    async def test_refresh_skips_on_error(self, tmp_path):
        """A network error for one symbol should not crash the whole refresh."""
        cache_path = tmp_path / "earnings_calendar.json"
        cache_path.write_text('{"MSFT": "2026-08-01"}')

        import aiohttp
        from unittest.mock import AsyncMock, MagicMock

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aiohttp.ClientError("network error"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch.object(ec, "_CACHE_PATH", cache_path), \
             patch("aiohttp.ClientSession", return_value=mock_session), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            # Should not raise
            await ec.refresh_calendar(["AAPL"])

        # Existing cache entry should be preserved
        result = json.loads(cache_path.read_text())
        assert "MSFT" in result
