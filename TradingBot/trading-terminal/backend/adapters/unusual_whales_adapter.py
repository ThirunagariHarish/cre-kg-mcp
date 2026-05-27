"""Unusual Whales async HTTP adapter.

API docs: https://api.unusualwhales.com/docs
Auth: Authorization: Bearer <API_KEY> + UW-CLIENT-API-ID header
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class UnusualWhalesAdapter:
    BASE_URL = "https://api.unusualwhales.com"

    def __init__(self, api_key: str = "", client_api_id: str = "100001") -> None:
        self.api_key = api_key or os.environ.get("UW_API_KEY", "")
        self.client_api_id = client_api_id or os.environ.get("UW_CLIENT_API_ID", "100001")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "UW-CLIENT-API-ID": self.client_api_id,
            "Accept": "application/json",
        }

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.api_key:
            return {"error": "UW_API_KEY not set", "data": []}
        try:
            import httpx
            url = f"{self.BASE_URL}{path if path.startswith('/') else '/' + path}"
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=self._headers(), params=params or {})
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("UW API error %s: %s", path, exc)
            return {"error": str(exc), "data": []}

    # ── Core signal feeds ──────────────────────────────────────────────

    async def flow_alerts(self, **params: Any) -> dict[str, Any]:
        """GET /api/option-trades/flow-alerts — sweeps, blocks, golden sweeps."""
        return await self.get("/api/option-trades/flow-alerts", params)

    async def screener(self, **params: Any) -> dict[str, Any]:
        """GET /api/screener/option-contracts — hottest chains screener."""
        return await self.get("/api/screener/option-contracts", params)

    async def darkpool_recent(self, **params: Any) -> dict[str, Any]:
        """GET /api/darkpool/recent — recent dark pool prints."""
        return await self.get("/api/darkpool/recent", params)

    async def darkpool_ticker(self, ticker: str, **params: Any) -> dict[str, Any]:
        """GET /api/darkpool/{ticker} — dark pool for specific ticker."""
        return await self.get(f"/api/darkpool/{ticker.upper()}", params)

    async def congress_trades(self, **params: Any) -> dict[str, Any]:
        """GET /api/congress/recent-trades — congressional stock trades."""
        return await self.get("/api/congress/recent-trades", params)

    async def market_tide(self, **params: Any) -> dict[str, Any]:
        """GET /api/market/market-tide — net call/put premium market-wide."""
        return await self.get("/api/market/market-tide", params)

    async def earnings_premarket(self, **params: Any) -> dict[str, Any]:
        """GET /api/earnings/premarket — pre-market earnings."""
        return await self.get("/api/earnings/premarket", params)

    async def earnings_afterhours(self, **params: Any) -> dict[str, Any]:
        """GET /api/earnings/afterhours — after-hours earnings."""
        return await self.get("/api/earnings/afterhours", params)

    # ── Per-ticker enrichment ──────────────────────────────────────────

    async def iv_rank(self, ticker: str, **params: Any) -> dict[str, Any]:
        """IV Rank and percentile for a ticker."""
        return await self.get(f"/api/stock/{ticker.upper()}/iv_rank", params)

    async def stock_flow_recent(self, ticker: str, **params: Any) -> dict[str, Any]:
        """Recent flow for a single ticker."""
        return await self.get(f"/api/stock/{ticker.upper()}/flow-recent", params)

    async def gex_by_strike(self, ticker: str, **params: Any) -> dict[str, Any]:
        """GET /api/stock/{ticker}/spot-exposures/strike — GEX by strike."""
        return await self.get(f"/api/stock/{ticker.upper()}/spot-exposures/strike", params)

    async def net_prem_ticks(self, ticker: str, **params: Any) -> dict[str, Any]:
        """Net premium ticks — call vs put flow bias."""
        return await self.get(f"/api/stock/{ticker.upper()}/net-prem-ticks", params)

    async def short_interest(self, ticker: str, **params: Any) -> dict[str, Any]:
        """Short interest float for squeeze detection."""
        return await self.get(f"/api/short/{ticker.upper()}/interest-float-v2", params)

    async def max_pain(self, ticker: str, **params: Any) -> dict[str, Any]:
        """Max pain strike for options expiry."""
        return await self.get(f"/api/stock/{ticker.upper()}/max-pain", params)

    async def option_chain(self, ticker: str, **params: Any) -> dict[str, Any]:
        """Full options chain with greeks."""
        return await self.get(f"/api/stock/{ticker.upper()}/option-chains", params)


__all__ = ["UnusualWhalesAdapter"]
