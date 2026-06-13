"""
Tests for analysts/discord/vinod.py parser functions.

All tests use synthetic message dicts that mirror the scraped Discord format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from analysts.discord.vinod import (
    BuySignal,
    SellSignal,
    parse_other_buy,
    parse_spx_buy,
    parse_sell,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _buy_msg(content: str, author: str = "INFRA TRADE ALERT [BOT]") -> dict:
    return {
        "message_id": "111",
        "channel_id": "1495516216645783562",
        "timestamp": "2026-06-12T14:00:00+00:00",
        "author_id": "9001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": True,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


def _sell_msg(content: str, author: str = "singhvinod77 [BOT]") -> dict:
    return {
        "message_id": "222",
        "channel_id": "1495516216645783562",
        "timestamp": "2026-06-12T15:00:00+00:00",
        "author_id": "9002",
        "author_name": author,
        "author_global_name": author,
        "is_bot": True,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ─── SPX Buy parser ───────────────────────────────────────────────────────────

class TestParseSPXBuy:
    def test_call_basic(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550C at 3.50 Small Trade above 7500")
        sig = parse_spx_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "CALL"
        assert sig.strike == 7550.0
        assert sig.price == 3.50

    def test_put_basic(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7440P at 4")
        sig = parse_spx_buy(msg)
        assert sig is not None
        assert sig.direction == "PUT"
        assert sig.strike == 7440.0
        assert sig.price == 4.0

    def test_decimal_strike(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550.5C at 2.80")
        sig = parse_spx_buy(msg)
        assert sig is not None
        assert sig.strike == 7550.5

    def test_wrong_author_ignored(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550C at 3.50", author="random user")
        assert parse_spx_buy(msg) is None

    def test_non_bot_ignored(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550C at 3.50")
        msg["is_bot"] = False
        assert parse_spx_buy(msg) is None

    def test_es_futures_ignored(self) -> None:
        msg = _buy_msg("**SPX :** Bought ES 7550C at 3.50")
        assert parse_spx_buy(msg) is None

    def test_butterfly_ignored(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550C butterfly at 3.50")
        assert parse_spx_buy(msg) is None

    def test_condor_ignored(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX iron condor 7500/7550/7600/7650 at 5.00")
        assert parse_spx_buy(msg) is None

    def test_no_spx_pattern_returns_none(self) -> None:
        msg = _buy_msg("**OTHER :** Bought TSLA 430C at 1.70 Expiring today")
        assert parse_spx_buy(msg) is None

    def test_expiry_is_none_for_spx(self) -> None:
        msg = _buy_msg("**SPX :** Bought SPX 7550C at 3.50")
        sig = parse_spx_buy(msg)
        assert sig is not None
        assert sig.expiry is None  # SPX channel doesn't include expiry


# ─── Other Buy parser ─────────────────────────────────────────────────────────

class TestParseOtherBuy:
    def test_expiring_today(self) -> None:
        msg = _buy_msg("**OTHER :** Bought TSLA 430C at 1.70 Expiring today")
        sig = parse_other_buy(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.direction == "CALL"
        assert sig.strike == 430.0
        assert sig.price == 1.70
        assert sig.expiry == datetime.now(tz=timezone.utc).date()

    def test_exp_with_date(self) -> None:
        msg = _buy_msg("**OTHER :** Bought MSFT 455C at 4.80 Exp: 06/26/2026")
        sig = parse_other_buy(msg)
        assert sig is not None
        assert sig.symbol == "MSFT"
        assert sig.expiry == date(2026, 6, 26)

    def test_put(self) -> None:
        msg = _buy_msg("**OTHER :** Bought AAPL 200P at 2.10 Exp: 07/18/2026")
        sig = parse_other_buy(msg)
        assert sig is not None
        assert sig.direction == "PUT"

    def test_no_expiry_returns_none_expiry(self) -> None:
        msg = _buy_msg("**OTHER :** Bought NVDA 1200C at 10.50")
        sig = parse_other_buy(msg)
        assert sig is not None
        assert sig.expiry is None

    def test_bougth_typo_handled(self) -> None:
        """Vinod's common typo 'Bougth' must be parsed identically to 'Bought'."""
        msg = _buy_msg("**OTHER :** Bougth AMD 500C at 1.20 Lotto Expiring tomm")
        sig = parse_other_buy(msg)
        assert sig is not None
        assert sig.symbol == "AMD"
        assert sig.direction == "CALL"
        assert sig.strike == 500.0
        assert sig.price == 1.20
        # "tomm" → tomorrow

    def test_expiring_tomorrow_typo(self) -> None:
        msg = _buy_msg("**OTHER :** Bought TSLA 450C at 2.50 Expiring tomm")
        sig = parse_other_buy(msg)
        assert sig is not None
        from datetime import datetime, timezone, timedelta
        assert sig.expiry == datetime.now(tz=timezone.utc).date() + timedelta(days=1)

    def test_spx_symbol_rejected(self) -> None:
        msg = _buy_msg("**OTHER :** Bought SPX 7550C at 3.50 Exp: 06/12/2026")
        assert parse_other_buy(msg) is None

    def test_butterfly_ignored(self) -> None:
        msg = _buy_msg("**OTHER :** Bought TSLA butterfly 430/440/450 at 1.70")
        assert parse_other_buy(msg) is None

    def test_wrong_author(self) -> None:
        msg = _buy_msg("**OTHER :** Bought TSLA 430C at 1.70 Expiring today", author="randomboi")
        assert parse_other_buy(msg) is None


# ─── Sell parser ──────────────────────────────────────────────────────────────

class TestParseSell:
    def test_sold_pct(self) -> None:
        msg = _sell_msg("@here Sold 50% SPX 7550C at 8.50")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.strike == 7550.0
        assert sig.direction == "CALL"
        assert sig.price == 8.50
        assert sig.quantity_hint == "50%"

    def test_sold_most(self) -> None:
        msg = _sell_msg("@here Sold most SPX 7550C at 8.50")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.quantity_hint == "most"
        assert sig.price == 8.50

    def test_closed_most(self) -> None:
        msg = _sell_msg("@here Closed most TSLA 430C at 3.20")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.price == 3.20

    def test_sold_runners(self) -> None:
        msg = _sell_msg("@here Sold most runners at 12.00")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.symbol is None
        assert sig.price == 12.00
        assert sig.quantity_hint == "runners"

    def test_not_sell_author_ignored(self) -> None:
        msg = _sell_msg("@here Sold SPX 7550C at 8.50", author="INFRA TRADE ALERT [BOT]")
        assert parse_sell(msg) is None

    def test_no_at_here_ignored(self) -> None:
        msg = _sell_msg("Sold 50% SPX 7550C at 8.50")
        assert parse_sell(msg) is None

    def test_put_sell(self) -> None:
        msg = _sell_msg("@here Sold 70% SPX 7440P at 6.20")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.direction == "PUT"
        assert sig.price == 6.20

    def test_last_sell(self) -> None:
        msg = _sell_msg("@here Last 2 SPX 7550C at 9.00")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.price == 9.00

    def test_sell_more(self) -> None:
        msg = _sell_msg("@here Sold 3 more TSLA 430C at 4.50")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.price == 4.50

    def test_non_bot_not_vinod_sell(self) -> None:
        msg = _sell_msg("@here Sold SPX 7550C at 8.50")
        msg["is_bot"] = False
        assert parse_sell(msg) is None

    def test_no_ticker_strike_only(self) -> None:
        """'@here Sold most 7395P at 2.20' — no ticker, 'MOST' must NOT be the symbol."""
        msg = _sell_msg("@here Sold most 7395P at 2.20")
        sig = parse_sell(msg)
        # Should not raise; "MOST" must not be the symbol
        if sig is not None:
            assert sig.symbol != "MOST"

    def test_sold_around_fallback(self) -> None:
        """'Sold most around 3.60' uses 'around' not 'at' — must still parse price."""
        msg = _sell_msg("@here Sold most runners around 3.60 Paid 150%")
        sig = parse_sell(msg)
        assert sig is not None
        assert sig.price == 3.60

    def test_bougth_typo_spx(self) -> None:
        """SPX channel buy with 'Bougth' typo must be parsed."""
        msg = _buy_msg("**SPX :** Bougth SPX 7500C at 2.80")
        sig = parse_spx_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.strike == 7500.0
        assert sig.price == 2.80
