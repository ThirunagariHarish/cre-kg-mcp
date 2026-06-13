"""
Tests for analysts/discord/pilla_swings.py parser functions.

All tests use synthetic message dicts that mirror the Discord message format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from analysts.discord.pilla_swings import (
    PillaBuySignal,
    PillaSellSignal,
    is_pilla_sell,
    parse_pilla_buy,
    parse_pilla_sell,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _msg(content: str, channel_id: str = "PILLA_CHANNEL_PLACEHOLDER") -> dict:
    return {
        "message_id": "100",
        "channel_id": channel_id,
        "timestamp": "2026-06-12T14:00:00+00:00",
        "author_id": "9001",
        "author_name": "Pilla",
        "author_global_name": "Pilla",
        "is_bot": False,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ─── Buy parser ──────────────────────────────────────────────────────────────

class TestParsePillaBuy:

    # ── "Entering" format ────────────────────────────────────────────────────

    def test_entering_call_with_exp(self) -> None:
        sig = parse_pilla_buy(_msg("Entering TSLA 430C at 3.50 exp 06/20"))
        assert sig is not None
        assert sig.symbol == "TSLA"
        assert sig.direction == "CALL"
        assert sig.strike == 430.0
        assert sig.price == 3.50
        # 06/20 → current year
        today = datetime.now(tz=timezone.utc)
        assert sig.expiry == date(today.year, 6, 20)

    def test_entering_put_no_exp(self) -> None:
        sig = parse_pilla_buy(_msg("Entering SPY 735P at 1.10"))
        assert sig is not None
        assert sig.symbol == "SPY"
        assert sig.direction == "PUT"
        assert sig.strike == 735.0
        assert sig.price == 1.10
        assert sig.expiry is None

    def test_entering_decimal_strike(self) -> None:
        sig = parse_pilla_buy(_msg("Entering AAPL 200.5C at 2.10"))
        assert sig is not None
        assert sig.strike == 200.5

    # ── "Buy" format ──────────────────────────────────────────────────────────

    def test_buy_call_basic(self) -> None:
        sig = parse_pilla_buy(_msg("Buy AAPL 200C at 2.10"))
        assert sig is not None
        assert sig.symbol == "AAPL"
        assert sig.direction == "CALL"
        assert sig.strike == 200.0
        assert sig.price == 2.10

    def test_buy_put_with_full_exp_date(self) -> None:
        sig = parse_pilla_buy(_msg("Buy MSFT 455P at 4.80 exp 07/18/2026"))
        assert sig is not None
        assert sig.symbol == "MSFT"
        assert sig.direction == "PUT"
        assert sig.expiry == date(2026, 7, 18)

    def test_buy_with_exp_two_digit_year(self) -> None:
        sig = parse_pilla_buy(_msg("Buy NVDA 1200C at 10.50 exp 06/20/26"))
        assert sig is not None
        assert sig.expiry == date(2026, 6, 20)

    def test_buy_at_sign(self) -> None:
        """'@' is accepted in place of 'at'."""
        sig = parse_pilla_buy(_msg("Buy TSLA 430C @ 3.50"))
        assert sig is not None
        assert sig.price == 3.50

    # ── "Added" format ────────────────────────────────────────────────────────

    def test_added_call(self) -> None:
        sig = parse_pilla_buy(_msg("Added NVDA 1200C at 10.50 exp 07/18/2026"))
        assert sig is not None
        assert sig.symbol == "NVDA"
        assert sig.expiry == date(2026, 7, 18)

    def test_added_put(self) -> None:
        sig = parse_pilla_buy(_msg("Added SPY 735P at 1.10"))
        assert sig is not None
        assert sig.direction == "PUT"

    # ── "Bought" / "Bougth" (typo) format ────────────────────────────────────

    def test_bought_call(self) -> None:
        sig = parse_pilla_buy(_msg("Bought TSLA 430C at 3.50"))
        assert sig is not None
        assert sig.symbol == "TSLA"

    def test_bougth_typo(self) -> None:
        """Pilla's typo 'Bougth' must be parsed identically to 'Bought'."""
        sig = parse_pilla_buy(_msg("Bougth MSFT 455C at 4.80"))
        assert sig is not None
        assert sig.symbol == "MSFT"
        assert sig.direction == "CALL"
        assert sig.strike == 455.0
        assert sig.price == 4.80

    # ── Case insensitivity ────────────────────────────────────────────────────

    def test_lowercase_keyword(self) -> None:
        sig = parse_pilla_buy(_msg("entering AAPL 200c at 2.10"))
        assert sig is not None
        assert sig.direction == "CALL"

    def test_mixed_case_keyword(self) -> None:
        sig = parse_pilla_buy(_msg("BUY TSLA 430C at 3.50"))
        assert sig is not None
        assert sig.symbol == "TSLA"

    # ── Expiry parsing edge cases ─────────────────────────────────────────────

    def test_expiry_with_colon(self) -> None:
        """'exp: 06/20' (with colon) must still parse."""
        sig = parse_pilla_buy(_msg("Entering AAPL 200C at 2.10 exp: 06/20"))
        assert sig is not None
        today = datetime.now(tz=timezone.utc)
        assert sig.expiry == date(today.year, 6, 20)

    def test_expiry_keyword_expiry(self) -> None:
        """'expiry 06/20' (full keyword) must parse."""
        sig = parse_pilla_buy(_msg("Buy TSLA 430C at 3.50 expiry 06/20"))
        assert sig is not None
        today = datetime.now(tz=timezone.utc)
        assert sig.expiry == date(today.year, 6, 20)

    def test_expiry_keyword_expires(self) -> None:
        sig = parse_pilla_buy(_msg("Buy TSLA 430C at 3.50 expires 06/20"))
        assert sig is not None

    # ── Channel / message metadata ────────────────────────────────────────────

    def test_channel_id_preserved(self) -> None:
        sig = parse_pilla_buy(_msg("Buy AAPL 200C at 2.10", channel_id="99999"))
        assert sig is not None
        assert sig.channel_id == "99999"

    def test_message_id_preserved(self) -> None:
        msg = _msg("Buy AAPL 200C at 2.10")
        msg["message_id"] = "888"
        sig = parse_pilla_buy(msg)
        assert sig is not None
        assert sig.message_id == "888"

    # ── Non-matching messages ─────────────────────────────────────────────────

    def test_no_match_returns_none(self) -> None:
        assert parse_pilla_buy(_msg("Market is looking strong today")) is None

    def test_sell_message_returns_none(self) -> None:
        assert parse_pilla_buy(_msg("Selling some TSLA")) is None

    def test_out_of_message_returns_none(self) -> None:
        assert parse_pilla_buy(_msg("Out of NVDA")) is None

    def test_empty_content_returns_none(self) -> None:
        assert parse_pilla_buy(_msg("")) is None

    def test_partial_match_no_price_returns_none(self) -> None:
        """Missing price → must return None."""
        assert parse_pilla_buy(_msg("Buy TSLA 430C")) is None

    def test_general_commentary_returns_none(self) -> None:
        assert parse_pilla_buy(_msg("Watching TSLA for a breakout above 430")) is None


# ─── Sell detector ────────────────────────────────────────────────────────────

class TestIsPillaSell:

    def test_selling_some(self) -> None:
        assert is_pilla_sell(_msg("Selling some TSLA")) is True

    def test_selling_all(self) -> None:
        assert is_pilla_sell(_msg("Selling all AAPL")) is True

    def test_selling_most(self) -> None:
        assert is_pilla_sell(_msg("Selling most NVDA")) is True

    def test_selling_half(self) -> None:
        assert is_pilla_sell(_msg("Selling half SPY")) is True

    def test_selling_partial(self) -> None:
        assert is_pilla_sell(_msg("Selling partial TSLA")) is True

    def test_selling_remaining(self) -> None:
        assert is_pilla_sell(_msg("Selling remaining MSFT")) is True

    def test_out_of(self) -> None:
        assert is_pilla_sell(_msg("Out of SPY")) is True

    def test_closed(self) -> None:
        assert is_pilla_sell(_msg("Closed TSLA")) is True

    def test_selling_lowercase(self) -> None:
        assert is_pilla_sell(_msg("selling some tsla")) is True

    def test_buy_message_not_sell(self) -> None:
        assert is_pilla_sell(_msg("Entering TSLA 430C at 3.50")) is False

    def test_general_commentary_not_sell(self) -> None:
        assert is_pilla_sell(_msg("Market looking strong, watching TSLA")) is False

    def test_empty_content_not_sell(self) -> None:
        assert is_pilla_sell(_msg("")) is False

    def test_price_update_not_sell(self) -> None:
        assert is_pilla_sell(_msg("TSLA hitting resistance at 435")) is False


# ─── Sell parser ─────────────────────────────────────────────────────────────

class TestParsePillaSell:

    def test_selling_some_returns_signal(self) -> None:
        sig = parse_pilla_sell(_msg("Selling some TSLA"))
        assert sig is not None
        assert isinstance(sig, PillaSellSignal)
        assert sig.raw_content == "Selling some TSLA"

    def test_out_of_returns_signal(self) -> None:
        sig = parse_pilla_sell(_msg("Out of NVDA"))
        assert sig is not None

    def test_closed_returns_signal(self) -> None:
        sig = parse_pilla_sell(_msg("Closed AAPL"))
        assert sig is not None

    def test_non_sell_returns_none(self) -> None:
        assert parse_pilla_sell(_msg("Buy TSLA 430C at 3.50")) is None

    def test_channel_id_in_sell_signal(self) -> None:
        sig = parse_pilla_sell(_msg("Out of SPY", channel_id="77777"))
        assert sig is not None
        assert sig.channel_id == "77777"

    def test_message_id_in_sell_signal(self) -> None:
        msg = _msg("Closed TSLA")
        msg["message_id"] = "555"
        sig = parse_pilla_sell(msg)
        assert sig is not None
        assert sig.message_id == "555"
