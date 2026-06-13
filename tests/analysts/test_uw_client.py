"""
Tests for analysts/unusual_whales/uw_client.py

All tests mock httpx — no live network calls.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from analysts.unusual_whales.uw_client import UWClient, _cache_path, _read_cache, _write_cache


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> UWClient:
    return UWClient(api_token="test-token", requests_per_minute=60)


@pytest.fixture
def fast_client() -> UWClient:
    """Client with a high rate limit so token bucket never blocks in tests."""
    return UWClient(api_token="test-token", requests_per_minute=600)


# ─── Cache helpers ────────────────────────────────────────────────────────────

class TestCacheHelpers:
    def test_cache_path_is_deterministic(self) -> None:
        p1 = _cache_path("flow", {"ticker": "AAPL"})
        p2 = _cache_path("flow", {"ticker": "AAPL"})
        assert p1 == p2

    def test_cache_path_differs_on_different_params(self) -> None:
        p1 = _cache_path("flow", {"ticker": "AAPL"})
        p2 = _cache_path("flow", {"ticker": "MSFT"})
        assert p1 != p2

    def test_read_cache_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        result = _read_cache(tmp_path / "nonexistent.json")
        assert result is None

    def test_read_cache_returns_none_on_expired_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "expired.json"
        cache_file.write_text(json.dumps({"data": []}))
        # Backdate the mtime by 120 seconds (TTL is 60)
        old_time = time.time() - 120
        import os
        os.utime(cache_file, (old_time, old_time))
        assert _read_cache(cache_file) is None

    def test_write_and_read_cache(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        data = [{"ticker": "AAPL", "premium": 150_000}]
        _write_cache(cache_file, data)
        result = _read_cache(cache_file)
        assert result == data


# ─── test_uw_client_caches_on_404 ────────────────────────────────────────────

class TestGetOptionFlow:
    @pytest.mark.asyncio
    async def test_returns_list_on_success(self, fast_client: UWClient, tmp_path: Path) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [{"ticker": "AAPL", "premium": 200_000}]}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await fast_client.get_option_flow("AAPL")

        assert isinstance(result, list)
        assert result[0]["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_caches_on_404(self, fast_client: UWClient, tmp_path: Path) -> None:
        """
        test_uw_client_caches_on_404: mock httpx to return 404 after cache file exists
        → should return cached data instead of [].
        """
        # Pre-populate a cache file
        slug = "option_flow_NVDA"
        params = {"ticker": "NVDA"}
        cache_file = _cache_path(slug, params)
        cached_data = [{"ticker": "NVDA", "premium": 120_000}]

        # Write cache into the correct location relative to the test's tmp_path override
        real_cache_file = tmp_path / cache_file.name
        _write_cache(real_cache_file, cached_data)

        # Mock 404 response
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        # We need to patch _cache_path to return our tmp path file
        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._cache_path", return_value=real_cache_file):
            result = await fast_client.get_option_flow("NVDA")

        # Should serve from cache, not return []
        assert result == cached_data

    @pytest.mark.asyncio
    async def test_returns_empty_on_404_without_cache(self, fast_client: UWClient, tmp_path: Path) -> None:
        """If 404 and no cache, return []."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_option_flow("TSLA")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_error(self, fast_client: UWClient, tmp_path: Path) -> None:
        """Any exception → return []."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_option_flow("AMZN")

        assert result == []

    @pytest.mark.asyncio
    async def test_normalizes_list_response(self, fast_client: UWClient, tmp_path: Path) -> None:
        """API returning a bare list (not wrapped in dict) should be handled."""
        payload = [{"ticker": "MSFT", "premium": 80_000}]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_option_flow("MSFT")

        assert result == payload


# ─── test_uw_client_rate_limit ────────────────────────────────────────────────

class TestRateLimit:
    @pytest.mark.asyncio
    async def test_acquire_token_sleeps_when_empty(self) -> None:
        """
        test_uw_client_rate_limit: verify _acquire_token sleeps when bucket is empty.

        We create a client with 1 req/min and drain the bucket, then mock
        asyncio.sleep to capture the sleep call.
        """
        # 1 token per minute client — bucket starts full (1 token)
        client = UWClient(api_token="tok", requests_per_minute=1)

        sleep_calls: list[float] = []

        async def mock_sleep(duration: float) -> None:
            sleep_calls.append(duration)
            # After "sleeping", advance the token refill by draining and re-filling
            # Simulate time passing so refill happens
            client._tokens = 1.0

        # Drain the bucket first
        client._tokens = 0.0

        with patch("analysts.unusual_whales.uw_client.asyncio.sleep", side_effect=mock_sleep):
            await client._acquire_token()

        assert len(sleep_calls) >= 1, "Expected at least one sleep call when bucket is empty"
        assert all(s > 0 for s in sleep_calls), "Sleep duration must be positive"

    @pytest.mark.asyncio
    async def test_acquire_token_does_not_sleep_when_full(self) -> None:
        """No sleep when tokens are available."""
        client = UWClient(api_token="tok", requests_per_minute=60)
        client._tokens = 60.0  # Full bucket

        sleep_calls: list[float] = []

        async def mock_sleep(duration: float) -> None:
            sleep_calls.append(duration)

        with patch("analysts.unusual_whales.uw_client.asyncio.sleep", side_effect=mock_sleep):
            await client._acquire_token()

        assert sleep_calls == [], "Should not sleep when tokens are available"
        assert client._tokens == 59.0  # One token consumed

    @pytest.mark.asyncio
    async def test_tokens_decrease_on_each_acquire(self) -> None:
        """Each _acquire_token call reduces the bucket by 1."""
        client = UWClient(api_token="tok", requests_per_minute=10)
        client._tokens = 5.0

        for i in range(3):
            await client._acquire_token()

        # Allow for minor float drift but should be approximately 2.0
        assert abs(client._tokens - 2.0) < 0.1


# ─── test_get_unusual_activity ────────────────────────────────────────────────

class TestGetUnusualActivity:
    @pytest.mark.asyncio
    async def test_returns_sorted_by_premium(self, fast_client: UWClient, tmp_path: Path) -> None:
        payload = {"data": [
            {"symbol": "AAPL", "premium": 50_000},
            {"symbol": "NVDA", "premium": 200_000},
            {"symbol": "META", "premium": 100_000},
        ]}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_unusual_activity(min_premium=50_000)

        assert result[0]["symbol"] == "NVDA"  # highest premium first
        assert result[1]["symbol"] == "META"
        assert result[2]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, fast_client: UWClient, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_unusual_activity()

        assert result == []


# ─── test_get_market_overview ─────────────────────────────────────────────────

class TestGetMarketOverview:
    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self, fast_client: UWClient, tmp_path: Path) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"call_put_ratio": 1.2, "gex": 500_000}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_market_overview()

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_error(self, fast_client: UWClient, tmp_path: Path) -> None:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("error"))

        with patch("httpx.AsyncClient", return_value=mock_client), \
             patch("analysts.unusual_whales.uw_client._CACHE_DIR", tmp_path):
            result = await fast_client.get_market_overview()

        assert result == {}
