"""
Alpaca broker adapter — paper and live trading.
Implements IBrokerAdapter for the Alpaca Trade API.
"""
from __future__ import annotations

import logging
from typing import Any

from ..domain.models import Order, OrderSide, OrderType
from ..domain.exceptions import BrokerConnectionError, BrokerOrderError

logger = logging.getLogger(__name__)

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"


class AlpacaBrokerAdapter:
    """
    Alpaca broker adapter using alpaca-trade-api.
    Supports both paper (default) and live trading modes.
    
    TODO: Switch to alpaca-py (newer SDK) when ready for production.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        mode: str = "paper",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._mode = mode
        self._base_url = PAPER_URL if mode == "paper" else LIVE_URL
        self._api: Any = None
        self._connected = False

    async def connect(self) -> None:
        """Initialize Alpaca REST API client."""
        if not self._api_key or not self._api_secret:
            raise BrokerConnectionError("alpaca", "Missing API key or secret")

        try:
            import alpaca_trade_api as tradeapi  # type: ignore

            self._api = tradeapi.REST(
                key_id=self._api_key,
                secret_key=self._api_secret,
                base_url=self._base_url,
                api_version="v2",
            )
            # Validate credentials
            account = self._api.get_account()
            self._connected = True
            logger.info(
                "Alpaca %s connected — account: %s, equity: %s",
                self._mode,
                account.status,
                account.equity,
            )
        except ImportError:
            raise BrokerConnectionError("alpaca", "alpaca-trade-api not installed")
        except Exception as exc:
            raise BrokerConnectionError("alpaca", str(exc)) from exc

    async def disconnect(self) -> None:
        self._connected = False
        self._api = None
        logger.info("Alpaca adapter disconnected")

    def _to_alpaca_order(self, order: Order) -> dict[str, Any]:
        """Convert domain Order to Alpaca order parameters."""
        params: dict[str, Any] = {
            "symbol": order.symbol,
            "qty": order.quantity,
            "side": order.side.value,
            "type": order.order_type.value.replace("_", " "),  # stop_limit → stop limit
            "time_in_force": order.time_in_force,
        }
        if order.limit_price:
            params["limit_price"] = str(order.limit_price)
        if order.stop_price:
            params["stop_price"] = str(order.stop_price)
        return params

    async def submit_order(self, order: Order) -> dict[str, Any]:
        """Submit order to Alpaca."""
        if not self._connected or not self._api:
            raise BrokerConnectionError("alpaca", "Not connected")

        try:
            params = self._to_alpaca_order(order)
            alpaca_order = self._api.submit_order(**params)
            return {
                "broker_order_id": alpaca_order.id,
                "status": alpaca_order.status,
                "filled_quantity": float(alpaca_order.filled_qty or 0),
                "average_fill_price": float(alpaca_order.filled_avg_price or 0),
                "submitted_at": str(alpaca_order.submitted_at),
            }
        except Exception as exc:
            raise BrokerOrderError("alpaca", order.order_id, str(exc)) from exc

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an Alpaca order."""
        if not self._connected or not self._api:
            return False
        try:
            self._api.cancel_order(broker_order_id)
            return True
        except Exception as exc:
            logger.error("Failed to cancel Alpaca order %s: %s", broker_order_id, exc)
            return False

    async def get_account(self) -> dict[str, Any]:
        """Get Alpaca account details."""
        if not self._connected or not self._api:
            raise BrokerConnectionError("alpaca", "Not connected")
        account = self._api.get_account()
        return {
            "status": account.status,
            "mode": self._mode,
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "portfolio_value": float(account.portfolio_value),
            "day_trade_count": int(account.daytrade_count),
            "pattern_day_trader": account.pattern_day_trader,
            "currency": "USD",
        }

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all open Alpaca positions."""
        if not self._connected or not self._api:
            return []
        positions = self._api.list_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": p.side,
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price or 0),
                "unrealized_pnl": float(p.unrealized_pl or 0),
                "market_value": float(p.market_value or 0),
            }
            for p in positions
        ]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy" if self._connected else "disconnected",
            "broker": f"alpaca_{self._mode}",
            "base_url": self._base_url,
            "connected": self._connected,
        }


__all__ = ["AlpacaBrokerAdapter"]
