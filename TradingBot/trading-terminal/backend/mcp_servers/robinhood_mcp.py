#!/usr/bin/env python3
"""Robinhood MCP Server — JSON-RPC over stdio.

Provides trading tools as MCP (Model Context Protocol) tools:
- robinhood_login: Authenticate with Robinhood
- get_quote: Get current stock/option quote
- get_positions: List current positions
- get_account: Account balance and buying power
- place_stock_order: Buy/sell stocks
- place_option_order: Buy/sell options
- close_position: Close a specific position
- get_order_status: Check order fill status
- place_order_with_stop_loss: Order + immediate stop loss
- modify_stop_loss: Update stop loss on existing position
- cancel_and_close: Cancel pending + close position
- get_option_chain: Get options chain for a ticker

Uses robin-stocks library. Supports PAPER_MODE env var for simulated trading.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# MCP server framework
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

# Robinhood
try:
    import robin_stocks.robinhood as rh
    HAS_ROBIN = True
except ImportError:
    HAS_ROBIN = False

import pyotp

# Config
PAPER_MODE = os.environ.get("PAPER_MODE", "false").lower() == "true"
CONFIG_PATH = os.environ.get("ROBINHOOD_CONFIG", "config.json")

# ── Stable Device Token ──
DEVICE_TOKEN_PATH = Path(os.path.expanduser("~/.tokens/rh_device_token"))


def _get_stable_device_token() -> str:
    """Return a persistent device token, creating one if it does not exist.

    Robinhood uses the device token to identify trusted devices.  The default
    robin_stocks implementation generates a fresh UUID on every login which
    triggers 2FA challenges and 'new device' warnings.  By persisting the
    token we present the same device identity across restarts.
    """
    if DEVICE_TOKEN_PATH.exists():
        token = DEVICE_TOKEN_PATH.read_text().strip()
        if token:
            logger.info("Loaded existing device token from %s", DEVICE_TOKEN_PATH)
            return token
    token = str(uuid.uuid4())
    DEVICE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_TOKEN_PATH.write_text(token)
    logger.info("Generated new device token and saved to %s", DEVICE_TOKEN_PATH)
    return token


# Monkey-patch robin_stocks so it uses the stable device token instead of
# generating a random one on each login.  This must happen at module level
# (before any login call).
if HAS_ROBIN and not PAPER_MODE:
    try:
        import robin_stocks.robinhood.authentication as _rh_auth
        _rh_auth.generate_device_token = _get_stable_device_token
        logger.info("Patched robin_stocks.robinhood.authentication.generate_device_token")
    except Exception:
        logger.exception("Failed to monkey-patch generate_device_token")

# ── Keep-Alive Threads ──
_keep_alive_started = False
_keep_alive_lock = threading.Lock()

REFRESH_INTERVAL_SECONDS = 20 * 60 * 60   # 20 hours
HEARTBEAT_INTERVAL_SECONDS = 30 * 60       # 30 minutes


def _refresh_token_loop() -> None:
    """Re-authenticate with Robinhood every 20 hours to prevent session expiry."""
    while True:
        time.sleep(REFRESH_INTERVAL_SECONDS)
        try:
            config = _load_config()
            totp_secret = config.get("totp_secret", "")
            mfa_code = pyotp.TOTP(totp_secret).now() if totp_secret else None
            pickle_name = os.environ.get("ROBINHOOD_PICKLE_NAME", "") or ""
            pickle_path = os.environ.get("ROBINHOOD_PICKLE_PATH", "") or ""
            login_kwargs: dict = dict(
                store_session=True,
                pickle_name=pickle_name,
                pickle_path=pickle_path,
            )
            if mfa_code:
                login_kwargs["mfa_code"] = mfa_code
            rh.login(config["username"], config["password"], **login_kwargs)
            logger.info("Session refreshed successfully")
        except Exception:
            logger.exception("Failed to refresh Robinhood session")


def _heartbeat_loop() -> None:
    """Call a lightweight Robinhood endpoint every 30 minutes to prevent idle timeout."""
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SECONDS)
        try:
            rh.profiles.load_portfolio_profile()
            logger.info("Heartbeat OK")
        except Exception:
            logger.exception("Heartbeat failed")


def _start_keep_alive_threads() -> None:
    """Start the refresh and heartbeat daemon threads (at most once)."""
    global _keep_alive_started
    with _keep_alive_lock:
        if _keep_alive_started:
            return
        _keep_alive_started = True

    refresh_thread = threading.Thread(
        target=_refresh_token_loop, name="rh-refresh", daemon=True
    )
    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, name="rh-heartbeat", daemon=True
    )
    refresh_thread.start()
    heartbeat_thread.start()
    logger.info("Started keep-alive threads (rh-refresh, rh-heartbeat)")

# Paper mode state
_paper_positions = {}
_paper_orders = {}
_paper_balance = 100000.0


def _load_config():
    """Load credentials from config.json or environment."""
    if Path(CONFIG_PATH).exists():
        config = json.loads(Path(CONFIG_PATH).read_text())
        return config.get("robinhood", config)
    return {
        "username": os.environ.get("ROBINHOOD_USERNAME", ""),
        "password": os.environ.get("ROBINHOOD_PASSWORD", ""),
        "totp_secret": os.environ.get("ROBINHOOD_TOTP_SECRET", ""),
    }


def _login():
    """Login to Robinhood."""
    if PAPER_MODE:
        return {"status": "logged_in", "mode": "paper"}

    config = _load_config()
    totp_secret = config.get("totp_secret", "")
    mfa_code = pyotp.TOTP(totp_secret).now() if totp_secret else None
    pickle_name = os.environ.get("ROBINHOOD_PICKLE_NAME", "") or ""
    pickle_path = os.environ.get("ROBINHOOD_PICKLE_PATH", "") or ""
    login_kwargs: dict = dict(
        store_session=True,
        pickle_name=pickle_name,
        pickle_path=pickle_path,
    )
    if mfa_code:
        login_kwargs["mfa_code"] = mfa_code
    rh.login(config["username"], config["password"], **login_kwargs)
    _start_keep_alive_threads()
    return {
        "status": "logged_in",
        "mode": "live",
        "device_token_path": str(DEVICE_TOKEN_PATH),
    }


def _get_quote(symbol: str) -> dict:
    """Get current quote for a symbol."""
    if PAPER_MODE:
        # Return simulated quote
        import random
        base = hash(symbol) % 500 + 10
        return {
            "symbol": symbol,
            "last_price": float(base + random.uniform(-5, 5)),
            "bid": float(base - 0.05),
            "ask": float(base + 0.05),
            "volume": random.randint(100000, 50000000),
            "mode": "paper",
        }

    quotes = rh.stocks.get_latest_price(symbol)
    quote_data = rh.stocks.get_quotes(symbol)[0]
    return {
        "symbol": symbol,
        "last_price": float(quotes[0]) if quotes[0] else 0,
        "bid": float(quote_data.get("bid_price", 0) or 0),
        "ask": float(quote_data.get("ask_price", 0) or 0),
        "volume": int(quote_data.get("volume", 0) or 0),
        "mode": "live",
    }


def _get_positions() -> list[dict]:
    """Get current open positions."""
    if PAPER_MODE:
        return list(_paper_positions.values())

    positions = rh.account.get_open_stock_positions()
    result = []
    for pos in positions:
        instrument = rh.stocks.get_instrument_by_url(pos["instrument"])
        result.append({
            "symbol": instrument.get("symbol", ""),
            "quantity": float(pos["quantity"]),
            "avg_cost": float(pos["average_buy_price"]),
            "current_price": float(rh.stocks.get_latest_price(instrument["symbol"])[0] or 0),
        })
    return result


def _get_account() -> dict:
    """Get account info."""
    if PAPER_MODE:
        return {"balance": _paper_balance, "buying_power": _paper_balance, "mode": "paper"}

    profile = rh.profiles.load_account_profile()
    return {
        "balance": float(profile.get("portfolio_cash", 0) or 0),
        "buying_power": float(profile.get("buying_power", 0) or 0),
        "equity": float(profile.get("equity", 0) or 0),
        "mode": "live",
    }


def _place_stock_order(symbol: str, quantity: int, side: str, order_type: str = "market",
                        limit_price: float | None = None) -> dict:
    """Place a stock order."""
    global _paper_balance

    if PAPER_MODE:
        order_id = str(uuid.uuid4())[:8]
        price = hash(symbol) % 500 + 10  # Simulated
        cost = price * quantity
        if side == "buy":
            _paper_balance -= cost
            _paper_positions[symbol] = {
                "symbol": symbol, "quantity": quantity,
                "avg_cost": price, "current_price": price, "order_id": order_id,
            }
        else:
            _paper_balance += cost
            _paper_positions.pop(symbol, None)

        _paper_orders[order_id] = {
            "order_id": order_id, "symbol": symbol, "side": side,
            "quantity": quantity, "fill_price": price, "status": "filled",
            "mode": "paper", "timestamp": datetime.utcnow().isoformat(),
        }
        return _paper_orders[order_id]

    if side == "buy":
        if order_type == "limit" and limit_price:
            order = rh.orders.order_buy_limit(symbol, quantity, limit_price)
        else:
            order = rh.orders.order_buy_market(symbol, quantity)
    else:
        if order_type == "limit" and limit_price:
            order = rh.orders.order_sell_limit(symbol, quantity, limit_price)
        else:
            order = rh.orders.order_sell_market(symbol, quantity)

    return {
        "order_id": order.get("id", ""),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "status": order.get("state", "unknown"),
        "fill_price": float(order.get("average_price", 0) or 0),
        "mode": "live",
    }


def _place_option_order(symbol: str, expiry: str, strike: float, option_type: str,
                         quantity: int = 1, side: str = "buy",
                         order_type: str = "market", limit_price: float | None = None) -> dict:
    """Place an options order."""
    if PAPER_MODE:
        order_id = str(uuid.uuid4())[:8]
        price = abs(hash(f"{symbol}{strike}{expiry}")) % 10 + 0.5
        _paper_orders[order_id] = {
            "order_id": order_id, "symbol": symbol, "option_type": option_type,
            "strike": strike, "expiry": expiry, "side": side, "quantity": quantity,
            "fill_price": price, "status": "filled", "mode": "paper",
            "timestamp": datetime.utcnow().isoformat(),
        }
        return _paper_orders[order_id]

    # Build option symbol
    if side == "buy":
        if option_type.lower() in ("call", "c"):
            order = rh.options.order_buy_option_limit(
                "open", "debit", limit_price or 0, symbol, quantity,
                expiry, strike, "call"
            ) if limit_price else rh.options.order_buy_option_limit(
                "open", "debit", 999, symbol, quantity, expiry, strike, "call"
            )
        else:
            order = rh.options.order_buy_option_limit(
                "open", "debit", limit_price or 999, symbol, quantity,
                expiry, strike, "put"
            )
    else:
        opt_type = "call" if option_type.lower() in ("call", "c") else "put"
        order = rh.options.order_sell_option_limit(
            "close", "credit", limit_price or 0.01, symbol, quantity,
            expiry, strike, opt_type
        )

    return {
        "order_id": order.get("id", ""),
        "symbol": symbol,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "side": side,
        "quantity": quantity,
        "status": order.get("state", "unknown"),
        "mode": "live",
    }


def _close_position(symbol: str, quantity: int | None = None) -> dict:
    """Close a position (stock or option)."""
    if PAPER_MODE:
        pos = _paper_positions.pop(symbol, None)
        if pos:
            return {"status": "closed", "symbol": symbol, "mode": "paper"}
        return {"status": "no_position", "symbol": symbol}

    # Try stock first
    positions = rh.account.get_open_stock_positions()
    for pos in positions:
        instrument = rh.stocks.get_instrument_by_url(pos["instrument"])
        if instrument.get("symbol") == symbol:
            qty = quantity or int(float(pos["quantity"]))
            return _place_stock_order(symbol, qty, "sell")

    return {"status": "no_position", "symbol": symbol}


def _get_order_status(order_id: str) -> dict:
    """Check order status."""
    if PAPER_MODE:
        return _paper_orders.get(order_id, {"status": "not_found", "order_id": order_id})

    order = rh.orders.get_stock_order_info(order_id)
    return {
        "order_id": order_id,
        "status": order.get("state", "unknown"),
        "fill_price": float(order.get("average_price", 0) or 0),
        "filled_quantity": float(order.get("cumulative_quantity", 0) or 0),
    }


def _place_order_with_stop_loss(symbol: str, quantity: int, side: str,
                                  stop_price: float) -> dict:
    """Place an order with an immediate stop loss."""
    # Place the main order
    main_order = _place_stock_order(symbol, quantity, side)

    # Place stop loss
    if PAPER_MODE:
        stop_id = str(uuid.uuid4())[:8]
        _paper_orders[stop_id] = {
            "order_id": stop_id, "type": "stop_loss",
            "symbol": symbol, "stop_price": stop_price, "status": "pending",
        }
        return {**main_order, "stop_loss_order_id": stop_id, "stop_price": stop_price}

    stop_order = rh.orders.order_sell_stop_loss(symbol, quantity, stop_price)
    return {
        **main_order,
        "stop_loss_order_id": stop_order.get("id", ""),
        "stop_price": stop_price,
    }


def _modify_stop_loss(symbol: str, new_stop_price: float, quantity: int | None = None) -> dict:
    """Modify stop loss price."""
    if PAPER_MODE:
        for oid, order in _paper_orders.items():
            if order.get("type") == "stop_loss" and order.get("symbol") == symbol:
                order["stop_price"] = new_stop_price
                return {"status": "modified", "new_stop_price": new_stop_price}
        return {"status": "no_stop_found", "symbol": symbol}

    # Cancel existing stop and create new one
    orders = rh.orders.get_all_open_stock_orders()
    for order in orders:
        if order.get("trigger") == "stop" and order.get("state") == "queued":
            instrument = rh.stocks.get_instrument_by_url(order["instrument"])
            if instrument.get("symbol") == symbol:
                rh.orders.cancel_stock_order(order["id"])
                qty = quantity or int(float(order.get("quantity", 1)))
                new_stop = rh.orders.order_sell_stop_loss(symbol, qty, new_stop_price)
                return {"status": "modified", "new_stop_price": new_stop_price, "order_id": new_stop.get("id")}

    return {"status": "no_stop_found", "symbol": symbol}


def _get_option_chain(symbol: str, expiry: str | None = None) -> dict:
    """Get options chain for a ticker."""
    if PAPER_MODE:
        return {
            "symbol": symbol,
            "expiry": expiry or "2026-04-10",
            "calls": [{"strike": 150, "bid": 2.50, "ask": 2.70, "iv": 0.35, "volume": 1000}],
            "puts": [{"strike": 150, "bid": 2.30, "ask": 2.50, "iv": 0.33, "volume": 800}],
            "mode": "paper",
        }

    chain = rh.options.get_chains(symbol)
    expirations = chain.get("expiration_dates", [])
    target_expiry = expiry or (expirations[0] if expirations else None)

    if not target_expiry:
        return {"error": "No expirations found", "symbol": symbol}

    options = rh.options.find_options_by_expiration(symbol, target_expiry)
    calls = [o for o in options if o.get("type") == "call"]
    puts = [o for o in options if o.get("type") == "put"]

    return {
        "symbol": symbol,
        "expiry": target_expiry,
        "calls": [{"strike": float(o["strike_price"]), "bid": float(o.get("bid_price", 0) or 0),
                    "ask": float(o.get("ask_price", 0) or 0), "iv": float(o.get("implied_volatility", 0) or 0),
                    "volume": int(o.get("volume", 0) or 0)} for o in calls[:20]],
        "puts": [{"strike": float(o["strike_price"]), "bid": float(o.get("bid_price", 0) or 0),
                   "ask": float(o.get("ask_price", 0) or 0), "iv": float(o.get("implied_volatility", 0) or 0),
                   "volume": int(o.get("volume", 0) or 0)} for o in puts[:20]],
        "mode": "live",
    }


# ── Watchlist Functions ──

def _add_to_watchlist(symbol: str, reason: str = "", conditions: str = "",
                       side: str = "long", agent_id: str = "", entry_target: float = 0,
                       confidence: float = 0, expires_hours: int = 24) -> dict:
    """Add a ticker to the agent's watchlist."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from lib.db import get_conn, insert
        from lib.config import get_db_path
        from datetime import timedelta

        now = datetime.utcnow()
        expires = (now + timedelta(hours=expires_hours)).isoformat() + "Z"

        with get_conn(str(get_db_path())) as conn:
            wid = insert(conn, "watchlist", {
                "agent_id": agent_id,
                "ticker": symbol.upper(),
                "side": side,
                "original_confidence": confidence,
                "original_reasoning": reason,
                "entry_target": entry_target,
                "conditions_needed": conditions,
                "status": "watching",
                "expires_at": expires,
            })
        return {"status": "added", "id": wid, "ticker": symbol, "expires_at": expires}
    except Exception as e:
        return {"error": str(e)}


def _remove_from_watchlist(symbol: str = "", watchlist_id: str = "") -> dict:
    """Remove from watchlist by ticker or ID."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from lib.db import get_conn, execute
        from lib.config import get_db_path
        with get_conn(str(get_db_path())) as conn:
            if watchlist_id:
                execute(conn, "UPDATE watchlist SET status = 'removed' WHERE id = ?", (watchlist_id,))
            elif symbol:
                execute(conn, "UPDATE watchlist SET status = 'removed' WHERE ticker = ? AND status = 'watching'", (symbol.upper(),))
        return {"status": "removed", "ticker": symbol or watchlist_id}
    except Exception as e:
        return {"error": str(e)}


def _get_watchlist(agent_id: str = "all") -> list:
    """Get all watching items."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from lib.db import get_conn, fetch_all
        from lib.config import get_db_path
        with get_conn(str(get_db_path())) as conn:
            if agent_id == "all":
                items = fetch_all(conn, "SELECT * FROM watchlist WHERE status = 'watching' ORDER BY current_score DESC")
            else:
                items = fetch_all(conn, "SELECT * FROM watchlist WHERE agent_id = ? AND status = 'watching' ORDER BY current_score DESC", (agent_id,))
        return [dict(i) for i in items]
    except Exception as e:
        return [{"error": str(e)}]


# ── New Tools (Phase 1.2) ──


def _get_buying_power() -> dict:
    """Get buying power, cash, and portfolio cash."""
    if PAPER_MODE:
        return {
            "buying_power": _paper_balance,
            "cash": _paper_balance,
            "portfolio_cash": _paper_balance,
            "mode": "paper",
        }

    try:
        profile = rh.profiles.load_account_profile()
        return {
            "buying_power": float(profile.get("buying_power", 0) or 0),
            "cash": float(profile.get("cash", 0) or 0),
            "portfolio_cash": float(profile.get("portfolio_cash", 0) or 0),
            "mode": "live",
        }
    except Exception as e:
        return {"error": str(e)}


def _get_option_positions() -> list[dict]:
    """Get open option positions."""
    if PAPER_MODE:
        # Return any paper orders that look like options
        return [
            v for v in _paper_orders.values()
            if v.get("option_type") and v.get("status") == "filled" and v.get("side") == "buy"
        ] or [
            {
                "symbol": "SPY",
                "option_type": "call",
                "strike": 520.0,
                "expiry": "2026-04-17",
                "quantity": 2,
                "avg_price": 3.50,
                "current_price": 4.10,
                "pnl": 120.0,
                "mode": "paper",
            }
        ]

    try:
        positions = rh.options.get_open_option_positions()
        result = []
        for pos in positions:
            chain_sym = pos.get("chain_symbol", "")
            result.append({
                "symbol": chain_sym,
                "option_type": pos.get("type", ""),
                "strike": float(pos.get("strike_price", 0) or 0),
                "expiry": pos.get("expiration_date", ""),
                "quantity": float(pos.get("quantity", 0) or 0),
                "avg_price": float(pos.get("average_price", 0) or 0),
                "current_price": float(pos.get("mark_price", 0) or 0),
                "pnl": float(pos.get("quantity", 0) or 0) * 100 * (
                    float(pos.get("mark_price", 0) or 0) - float(pos.get("average_price", 0) or 0)
                ),
                "mode": "live",
            })
        return result
    except Exception as e:
        return [{"error": str(e)}]


def _default_watchlist_name() -> str:
    """Owner-overridable default watchlist name.

    `robin_stocks.robinhood.account.post_symbols_to_watchlist` / `get_watchlist_by_name`
    default to ``"My First List"``, which is the label Robinhood auto-assigns
    to the first watchlist on a new account. Callers can override via the
    ``PHOENIX_WATCHLIST_NAME`` env var if they want a non-default list.
    """
    return os.environ.get("PHOENIX_WATCHLIST_NAME", "My First List")


# Feature C Phase 1 (api-contracts.md §1.4, architecture.md §8.4):
# server-side allowlist rejecting any non-default watchlist name. Blocks
# any path where a caller could spray into arbitrary named watchlists.
_ALLOWED_WATCHLISTS = frozenset({_default_watchlist_name()})


def _get_rh_watchlist(name: str | None = None) -> dict:
    """Get a Robinhood watchlist by name."""
    if not name:
        name = _default_watchlist_name()
    if PAPER_MODE:
        return {
            "name": name,
            "tickers": ["AAPL", "TSLA", "NVDA", "SPY", "QQQ"],
            "mode": "paper",
        }

    try:
        watchlist = rh.account.get_watchlist_by_name(name=name)
        tickers = []
        if watchlist:
            for item in watchlist:
                instrument_url = item.get("instrument", "")
                if instrument_url:
                    inst = rh.stocks.get_instrument_by_url(instrument_url)
                    if inst and inst.get("symbol"):
                        tickers.append(inst["symbol"])
        return {"name": name, "tickers": tickers, "mode": "live"}
    except Exception as e:
        return {"error": str(e)}


def _rh_watchlist_add(symbol: str, watchlist_name: str | None = None,
                      profile_id: str = "") -> dict:
    """Add a single symbol to the agent's Robinhood ACCOUNT watchlist.

    NOT to be confused with `add_to_watchlist`, which writes to the internal
    `watchlist` SQLite table. This tool hits the real Robinhood API via
    `robin_stocks.robinhood.account.post_symbols_to_watchlist` and the result
    is visible in the owner's Robinhood mobile/web app within seconds.

    Contract (api-contracts.md §1): never raises. Every failure is an
    in-band response with an `error` key and a `retryable` flag. The
    `profile_id` parameter is informational only — per-profile credentials
    are injected into the subprocess env *before* spawn via
    `lib.robinhood_profile_env.apply_robinhood_profile`; the handler body
    does not consume `profile_id`.
    """
    if watchlist_name is None or watchlist_name == "":
        watchlist_name = _default_watchlist_name()
    mode = "paper" if PAPER_MODE else "live"
    sym = (symbol or "").upper().strip()

    if not sym:
        return {"error": "invalid_symbol", "symbol": sym,
                "retryable": False, "mode": mode}
    if watchlist_name not in _ALLOWED_WATCHLISTS:
        return {"error": "invalid_watchlist_name", "symbol": sym,
                "retryable": False, "mode": mode}

    if PAPER_MODE:
        return {"status": "added", "symbol": sym,
                "watchlist": watchlist_name, "mode": "paper"}

    # Live path — lazily import requests so the paper-mode path (and unit
    # tests that monkey-patch the library) stay lightweight.
    try:
        import requests  # type: ignore
    except Exception:
        requests = None  # type: ignore

    try:
        rh.account.post_symbols_to_watchlist(
            inputSymbols=[sym], name=watchlist_name
        )
        return {"status": "added", "symbol": sym,
                "watchlist": watchlist_name, "mode": "live"}
    except Exception as exc:
        # Classify. robin_stocks surfaces 4xx/5xx via requests.HTTPError most
        # of the time; ConnectionError/Timeout for transport failures; and
        # auth errors as generic Exception subclasses we can only see by
        # string-matching.
        reason = "unknown"
        retryable = True

        if requests is not None:
            http_err = getattr(requests, "HTTPError", None)
            conn_err = getattr(requests, "ConnectionError", None)
            timeout_err = getattr(requests, "Timeout", None)

            if http_err is not None and isinstance(exc, http_err):
                resp = getattr(exc, "response", None)
                code = getattr(resp, "status_code", 0) or 0
                if code == 429:
                    reason, retryable = "rate_limited", True
                elif code in (401, 403):
                    reason, retryable = "rh_session_expired", False
                else:
                    reason, retryable = "unknown", True
            elif (conn_err is not None and isinstance(exc, conn_err)) or (
                timeout_err is not None and isinstance(exc, timeout_err)
            ):
                reason, retryable = "network_error", True

        # Catch common auth-expiry string leaks from robin_stocks when the
        # library raises generic Exceptions with 401-ish signals.
        if reason == "unknown":
            emsg = str(exc).lower()
            if "401" in emsg or "unauthorized" in emsg or "expired" in emsg:
                reason, retryable = "rh_session_expired", False
            elif "429" in emsg or "rate" in emsg:
                reason, retryable = "rate_limited", True

        return {"error": reason, "symbol": sym,
                "retryable": retryable, "mode": "live"}


def _get_portfolio_history() -> dict:
    """Get portfolio profile with equity values."""
    if PAPER_MODE:
        return {
            "equity": _paper_balance,
            "extended_hours_equity": _paper_balance,
            "market_value": _paper_balance * 0.8,
            "excess_margin": _paper_balance * 0.5,
            "mode": "paper",
        }

    try:
        profile = rh.profiles.load_portfolio_profile()
        return {
            "equity": float(profile.get("equity", 0) or 0),
            "extended_hours_equity": float(profile.get("extended_hours_equity", 0) or 0),
            "market_value": float(profile.get("market_value", 0) or 0),
            "excess_margin": float(profile.get("excess_margin", 0) or 0),
            "mode": "live",
        }
    except Exception as e:
        return {"error": str(e)}


def _place_trailing_stop(symbol: str, quantity: int, side: str = "sell",
                          trail_amount: float = 0, trail_type: str = "amount") -> dict:
    """Place a trailing stop order."""
    if PAPER_MODE:
        order_id = str(uuid.uuid4())[:8]
        _paper_orders[order_id] = {
            "order_id": order_id,
            "type": "trailing_stop",
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "trail_amount": trail_amount,
            "trail_type": trail_type,
            "status": "pending",
            "mode": "paper",
            "timestamp": datetime.utcnow().isoformat(),
        }
        return _paper_orders[order_id]

    try:
        order = rh.orders.order(
            symbol,
            quantity,
            side,
            trailAmount=trail_amount,
            trailType=trail_type,
            timeInForce="gtc",
            trigger="stop",
        )
        return {
            "order_id": order.get("id", ""),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "trail_amount": trail_amount,
            "trail_type": trail_type,
            "status": order.get("state", "unknown"),
            "mode": "live",
        }
    except Exception as e:
        return {"error": str(e)}


def _get_fundamentals(ticker: str) -> dict:
    """Get stock fundamentals (PE, market cap, dividend yield, etc.)."""
    if PAPER_MODE:
        return {
            "symbol": ticker,
            "pe_ratio": 25.4,
            "market_cap": 2500000000000.0,
            "dividend_yield": 0.65,
            "average_volume": 75000000,
            "shares_outstanding": 15000000000,
            "sector": "Technology",
            "description": f"Paper mode fundamentals for {ticker}",
            "mode": "paper",
        }

    try:
        data = rh.stocks.get_fundamentals(ticker)
        if isinstance(data, list) and data:
            data = data[0]
        if not data:
            return {"error": f"No fundamentals found for {ticker}"}
        return {
            "symbol": ticker,
            "pe_ratio": float(data.get("pe_ratio", 0) or 0),
            "market_cap": float(data.get("market_cap", 0) or 0),
            "dividend_yield": float(data.get("dividend_yield", 0) or 0),
            "average_volume": float(data.get("average_volume", 0) or 0),
            "shares_outstanding": float(data.get("shares_outstanding", 0) or 0),
            "sector": data.get("sector", ""),
            "description": data.get("description", ""),
            "high_52_weeks": float(data.get("high_52_weeks", 0) or 0),
            "low_52_weeks": float(data.get("low_52_weeks", 0) or 0),
            "mode": "live",
        }
    except Exception as e:
        return {"error": str(e)}


def _cancel_all_orders() -> dict:
    """Cancel all open orders."""
    if PAPER_MODE:
        count = len([o for o in _paper_orders.values() if o.get("status") == "pending"])
        for oid in list(_paper_orders):
            if _paper_orders[oid].get("status") == "pending":
                _paper_orders[oid]["status"] = "cancelled"
        return {"status": "cancelled", "count": count, "mode": "paper"}

    try:
        result = rh.orders.cancel_all_open_orders()
        cancelled = len(result) if isinstance(result, list) else 0
        return {"status": "cancelled", "count": cancelled, "mode": "live"}
    except Exception as e:
        return {"error": str(e)}


def _get_open_orders() -> list[dict]:
    """Get all open/pending orders."""
    if PAPER_MODE:
        return [
            o for o in _paper_orders.values()
            if o.get("status") in ("pending", "queued")
        ]

    try:
        orders = rh.orders.get_all_open_orders()
        result = []
        for o in orders:
            instrument_url = o.get("instrument", "")
            symbol = ""
            if instrument_url:
                try:
                    inst = rh.stocks.get_instrument_by_url(instrument_url)
                    symbol = inst.get("symbol", "")
                except Exception:
                    pass
            result.append({
                "order_id": o.get("id", ""),
                "symbol": symbol,
                "side": o.get("side", ""),
                "quantity": float(o.get("quantity", 0) or 0),
                "price": float(o.get("price", 0) or 0),
                "type": o.get("type", ""),
                "trigger": o.get("trigger", ""),
                "state": o.get("state", ""),
                "created_at": o.get("created_at", ""),
                "mode": "live",
            })
        return result
    except Exception as e:
        return [{"error": str(e)}]


def _batch_close_positions(tickers: list[str]) -> dict:
    """Close positions for multiple tickers."""
    results = {}
    for ticker in tickers:
        try:
            result = _close_position(ticker)
            results[ticker] = result
        except Exception as e:
            results[ticker] = {"error": str(e)}
    return {
        "closed": len([r for r in results.values() if r.get("status") != "no_position"]),
        "skipped": len([r for r in results.values() if r.get("status") == "no_position"]),
        "results": results,
    }


# ── MCP Server Setup ──

TOOLS = {
    "robinhood_login": {
        "description": "Login to Robinhood. Must be called before any trading operations.",
        "params": {},
        "handler": lambda _: _login(),
    },
    "get_quote": {
        "description": "Get current stock quote (price, bid, ask, volume).",
        "params": {"symbol": "string"},
        "handler": lambda p: _get_quote(p["symbol"]),
    },
    "get_positions": {
        "description": "List all current open positions.",
        "params": {},
        "handler": lambda _: _get_positions(),
    },
    "get_account": {
        "description": "Get account balance, buying power, and equity.",
        "params": {},
        "handler": lambda _: _get_account(),
    },
    "place_stock_order": {
        "description": "Place a stock buy/sell order. side: 'buy' or 'sell'. order_type: 'market' or 'limit'.",
        "params": {"symbol": "string", "quantity": "integer", "side": "string",
                    "order_type": "string", "limit_price": "number"},
        "handler": lambda p: _place_stock_order(p["symbol"], p["quantity"], p["side"],
                                                  p.get("order_type", "market"), p.get("limit_price")),
    },
    "place_option_order": {
        "description": "Place an options order. option_type: 'call' or 'put'.",
        "params": {"symbol": "string", "expiry": "string", "strike": "number",
                    "option_type": "string", "quantity": "integer", "side": "string",
                    "order_type": "string", "limit_price": "number"},
        "handler": lambda p: _place_option_order(p["symbol"], p["expiry"], p["strike"],
                                                   p["option_type"], p.get("quantity", 1),
                                                   p.get("side", "buy"), p.get("order_type", "market"),
                                                   p.get("limit_price")),
    },
    "close_position": {
        "description": "Close an open position in a symbol.",
        "params": {"symbol": "string", "quantity": "integer"},
        "handler": lambda p: _close_position(p["symbol"], p.get("quantity")),
    },
    "get_order_status": {
        "description": "Check the status of a placed order.",
        "params": {"order_id": "string"},
        "handler": lambda p: _get_order_status(p["order_id"]),
    },
    "place_order_with_stop_loss": {
        "description": "Place a stock order with an immediate stop loss.",
        "params": {"symbol": "string", "quantity": "integer", "side": "string", "stop_price": "number"},
        "handler": lambda p: _place_order_with_stop_loss(p["symbol"], p["quantity"], p["side"], p["stop_price"]),
    },
    "modify_stop_loss": {
        "description": "Modify the stop loss price for an existing position.",
        "params": {"symbol": "string", "new_stop_price": "number", "quantity": "integer"},
        "handler": lambda p: _modify_stop_loss(p["symbol"], p["new_stop_price"], p.get("quantity")),
    },
    "cancel_and_close": {
        "description": "Close the position for a symbol (same as close_position; cancel pending orders not yet implemented in robin_stocks path).",
        "params": {"symbol": "string"},
        "handler": lambda p: _close_position(p["symbol"]),
    },
    "get_option_chain": {
        "description": "Get options chain for a ticker with strikes, IV, volume.",
        "params": {"symbol": "string", "expiry": "string"},
        "handler": lambda p: _get_option_chain(p["symbol"], p.get("expiry")),
    },
    "add_to_watchlist": {
        "description": "Add a ticker to the watchlist for monitoring. Use when confidence is 40-60% (interesting but not ready to trade).",
        "params": {"symbol": "string", "reason": "string", "conditions": "string",
                    "side": "string", "agent_id": "string", "entry_target": "number",
                    "confidence": "number", "expires_hours": "integer"},
        "handler": lambda p: _add_to_watchlist(p["symbol"], p.get("reason", ""), p.get("conditions", ""),
                                                 p.get("side", "long"), p.get("agent_id", ""),
                                                 p.get("entry_target", 0), p.get("confidence", 0),
                                                 p.get("expires_hours", 24)),
    },
    "remove_from_watchlist": {
        "description": "Remove a ticker from the watchlist.",
        "params": {"symbol": "string", "watchlist_id": "string"},
        "handler": lambda p: _remove_from_watchlist(p.get("symbol", ""), p.get("watchlist_id", "")),
    },
    "get_watchlist": {
        "description": "Get all items currently on the watchlist.",
        "params": {"agent_id": "string"},
        "handler": lambda p: _get_watchlist(p.get("agent_id", "all")),
    },
    "get_buying_power": {
        "description": "Get buying power, cash, and portfolio cash.",
        "params": {},
        "handler": lambda _: _get_buying_power(),
    },
    "get_option_positions": {
        "description": "Get all open option positions with P&L.",
        "params": {},
        "handler": lambda _: _get_option_positions(),
    },
    "get_rh_watchlist": {
        "description": (
            "Get a Robinhood watchlist by name. Defaults to the value of "
            "PHOENIX_WATCHLIST_NAME (falling back to 'My First List', which "
            "is robin_stocks' library default and the label Robinhood "
            "auto-assigns on a new account)."
        ),
        "params": {"name": "string"},
        "handler": lambda p: _get_rh_watchlist(p.get("name") or None),
    },
    "rh_watchlist_add": {
        "description": (
            "Add a symbol to the agent's Robinhood ACCOUNT watchlist. "
            "Visible in the owner's Robinhood mobile/web app within seconds. "
            "NOT to be confused with add_to_watchlist, which writes to the "
            "internal watchlist SQLite table. Never raises; errors return "
            "in the response body with an `error` key and a `retryable` flag."
        ),
        "params": {
            "symbol": "string",
            "watchlist_name": "string",
            "profile_id": "string",
        },
        "handler": lambda p: _rh_watchlist_add(
            p.get("symbol", ""),
            p.get("watchlist_name") or None,
            p.get("profile_id", ""),
        ),
    },
    "get_portfolio_history": {
        "description": "Get portfolio equity, extended hours equity, market value.",
        "params": {},
        "handler": lambda _: _get_portfolio_history(),
    },
    "place_trailing_stop": {
        "description": "Place a trailing stop order. trail_type: 'amount' or 'percentage'.",
        "params": {"symbol": "string", "quantity": "integer", "side": "string",
                    "trail_amount": "number", "trail_type": "string"},
        "handler": lambda p: _place_trailing_stop(
            p["symbol"], p["quantity"], p.get("side", "sell"),
            p.get("trail_amount", 0), p.get("trail_type", "amount")),
    },
    "get_fundamentals": {
        "description": "Get stock fundamentals: PE ratio, market cap, dividend yield, 52-week range.",
        "params": {"ticker": "string"},
        "handler": lambda p: _get_fundamentals(p["ticker"]),
    },
    "cancel_all_orders": {
        "description": "Cancel all open orders. Returns count of cancelled orders.",
        "params": {},
        "handler": lambda _: _cancel_all_orders(),
    },
    "get_open_orders": {
        "description": "List all open/pending orders with details.",
        "params": {},
        "handler": lambda _: _get_open_orders(),
    },
    "batch_close_positions": {
        "description": "Close positions for multiple tickers at once.",
        "params": {"tickers": "array"},
        "handler": lambda p: _batch_close_positions(p["tickers"]),
    },
}


def _run_line_protocol():
    """Simple JSON-line protocol for the executor subprocess.

    Accepts both:
      {"tool": "name", "arguments": {...}}
      {"method": "name", "params": {...}}
    Returns one JSON object per line.
    """
    for line in sys.stdin:
        try:
            req = json.loads(line.strip())
            tool_name = req.get("tool") or req.get("method", "")
            args = req.get("arguments") or req.get("params", {})
            tool = TOOLS.get(tool_name)
            if tool:
                result = tool["handler"](args)
                print(json.dumps(result))
            else:
                print(json.dumps({"error": f"Unknown tool: {tool_name}"}))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
        sys.stdout.flush()


async def main():
    if "--line-protocol" in sys.argv:
        _run_line_protocol()
        return

    if not HAS_MCP:
        print(json.dumps({"error": "MCP library not installed. Install with: pip install mcp"}), file=sys.stderr)
        _run_line_protocol()
        return

    server = Server("robinhood")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description=info["description"],
                inputSchema={
                    "type": "object",
                    "properties": {
                        k: {"type": v} for k, v in info["params"].items()
                    },
                },
            )
            for name, info in TOOLS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        tool = TOOLS.get(name)
        if not tool:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

        try:
            result = tool["handler"](arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
