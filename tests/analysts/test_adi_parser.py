"""
Tests for analysts/discord/adi.py parser functions.

All tests use synthetic message dicts that mirror the scraped Discord format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

import pytest

from analysts.discord.adi import (
    BuySignal,
    SellSignal,
    parse_adi_buy,
    parse_adi_sell,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

_CHANNEL_ID = "1495517143599415507"


def _msg(content: str, author: str = "Aadi [INFR]", is_bot: bool = True) -> dict:
    return {
        "message_id": "100",
        "channel_id": _CHANNEL_ID,
        "timestamp": "2026-06-13T14:00:00+00:00",
        "author_id": "9001",
        "author_name": author,
        "author_global_name": author,
        "is_bot": is_bot,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ─── Buy parser ───────────────────────────────────────────────────────────────


class TestParseAdiBuy:
    def test_spx_call_buy(self) -> None:
        msg = _msg("@here SPX 7400C at 2.50")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "CALL"
        assert sig.strike == 7400.0
        assert sig.price == 2.50

    def test_spx_put_buy(self) -> None:
        msg = _msg("@here SPX 7350P at 1.80")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "PUT"
        assert sig.strike == 7350.0
        assert sig.price == 1.80

    def test_dual_direction_call_taken(self) -> None:
        """@here SPX 7400C/P at 2.50 — strike is on the C side, so CALL is taken."""
        msg = _msg("@here SPX 7400C/P at 2.50")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.direction == "CALL"
        assert sig.strike == 7400.0
        assert sig.price == 2.50

    def test_expiry_is_none(self) -> None:
        """ADI messages do not include expiry — should be None (0DTE)."""
        msg = _msg("@here SPX 7400C at 2.50")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.expiry is None

    def test_decimal_strike(self) -> None:
        msg = _msg("@here SPX 7400.5C at 3.00")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.strike == 7400.5

    def test_decimal_price(self) -> None:
        msg = _msg("@here SPX 7500C at 4.75")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.price == 4.75

    def test_infr_bot_author_accepted(self) -> None:
        """INFR [BOT] author variant should also be accepted."""
        msg = _msg("@here SPX 7400C at 2.50", author="INFR [BOT]")
        sig = parse_adi_buy(msg)
        assert sig is not None

    def test_wrong_author_ignored(self) -> None:
        """Message from unrecognized author must be ignored."""
        msg = _msg("@here SPX 7400C at 2.50", author="random_trader")
        assert parse_adi_buy(msg) is None

    def test_non_bot_ignored(self) -> None:
        """Human messages (is_bot=False) must be ignored even if author matches."""
        msg = _msg("@here SPX 7400C at 2.50", is_bot=False)
        assert parse_adi_buy(msg) is None

    def test_non_spx_symbol_ignored(self) -> None:
        """ADI analyst only handles SPX — other symbols must return None."""
        msg = _msg("@here AAPL 200C at 1.50")
        assert parse_adi_buy(msg) is None

    def test_missing_at_here_ignored(self) -> None:
        """Message without @here prefix must not match."""
        msg = _msg("SPX 7400C at 2.50")
        assert parse_adi_buy(msg) is None

    def test_channel_id_preserved(self) -> None:
        msg = _msg("@here SPX 7400C at 2.50")
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.channel_id == _CHANNEL_ID

    def test_message_id_preserved(self) -> None:
        msg = _msg("@here SPX 7400C at 2.50")
        msg["message_id"] = "abc123"
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.message_id == "abc123"

    def test_raw_content_preserved(self) -> None:
        content = "@here SPX 7400C at 2.50 small size"
        msg = _msg(content)
        sig = parse_adi_buy(msg)
        assert sig is not None
        assert sig.raw_content == content


# ─── Sell parser ──────────────────────────────────────────────────────────────


class TestParseAdiSell:
    def test_sold_call(self) -> None:
        msg = _msg("@here Sold SPX 7400C at 5.00")
        sig = parse_adi_sell(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "CALL"
        assert sig.strike == 7400.0
        assert sig.price == 5.00

    def test_closed_put(self) -> None:
        msg = _msg("@here Closed SPX 7350P at 3.20")
        sig = parse_adi_sell(msg)
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "PUT"
        assert sig.strike == 7350.0
        assert sig.price == 3.20

    def test_out_keyword(self) -> None:
        msg = _msg("@here Out SPX 7400C at 4.50")
        sig = parse_adi_sell(msg)
        assert sig is not None
        assert sig.price == 4.50

    def test_wrong_author_ignored(self) -> None:
        msg = _msg("@here Sold SPX 7400C at 5.00", author="random_user")
        assert parse_adi_sell(msg) is None

    def test_non_bot_ignored(self) -> None:
        msg = _msg("@here Sold SPX 7400C at 5.00", is_bot=False)
        assert parse_adi_sell(msg) is None

    def test_buy_message_not_parsed_as_sell(self) -> None:
        msg = _msg("@here SPX 7400C at 2.50")
        assert parse_adi_sell(msg) is None

    def test_case_insensitive_sold(self) -> None:
        msg = _msg("@here sold SPX 7400C at 5.00")
        sig = parse_adi_sell(msg)
        assert sig is not None
        assert sig.price == 5.00
