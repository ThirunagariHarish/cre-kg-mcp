"""
Tests for analysts/discord/zabes.py parser functions.

All tests use synthetic message dicts that mirror the scraped Discord format.
No live Discord connection required — pure unit tests.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from analysts.discord.zabes import (
    ZabesBuySignal,
    _parse_expiry,
    parse_zabes_buy,
    parse_zabes_sell,
)

ZABES_CHANNEL_ID = "1495516822349414430"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _msg(content: str, channel_id: str = ZABES_CHANNEL_ID) -> dict:
    return {
        "message_id": "999",
        "channel_id": channel_id,
        "timestamp": "2026-06-13T14:00:00+00:00",
        "author_id": "7777",
        "author_name": "Zabes",
        "author_global_name": "ZAPs",
        "is_bot": False,
        "content_raw": content,
        "content": content,
        "embeds": [],
    }


# ─── Date parsing ─────────────────────────────────────────────────────────────

class TestParseExpiry:
    def test_future_date_current_year(self) -> None:
        # 06/15 is in the future relative to 2026-06-13
        result = _parse_expiry("06/15")
        assert result == date(2026, 6, 15)

    def test_same_day(self) -> None:
        result = _parse_expiry("06/13")
        # Today is 2026-06-13 — should not roll to next year (not strictly before today)
        assert result == date(2026, 6, 13)

    def test_past_date_rolls_to_next_year(self) -> None:
        # 01/10 has already passed in 2026 — should roll to 2027
        result = _parse_expiry("01/10")
        assert result == date(2027, 1, 10)

    def test_december_expiry(self) -> None:
        result = _parse_expiry("12/20")
        assert result == date(2026, 12, 20)

    def test_leading_zeros_stripped(self) -> None:
        result = _parse_expiry("6/20")
        assert result == date(2026, 6, 20)


# ─── Format 1: Multi-line HIGH RISK ───────────────────────────────────────────

class TestParseZabesBuyFormat1HighRisk:
    def test_spy_put_high_risk(self) -> None:
        content = "@here **HIGH RISK**\nSPY here\n06/15 735P\nAvg. 1.50"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "SPY"
        assert sig.direction == "PUT"
        assert sig.strike == 735.0
        assert sig.price == 1.50
        assert sig.expiry == date(2026, 6, 15)
        assert sig.is_high_risk is True

    def test_spy_call_high_risk(self) -> None:
        content = "@here **HIGH RISK**\nSPY here\n06/20 580C\nAvg. 2.30"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.direction == "CALL"
        assert sig.strike == 580.0
        assert sig.price == 2.30
        assert sig.is_high_risk is True

    def test_spx_put_high_risk(self) -> None:
        content = "@here **HIGH RISK**\nSPX here\n06/15 5500P\nAvg. 3.00"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "PUT"
        assert sig.strike == 5500.0

    def test_qqq_high_risk(self) -> None:
        content = "@here **HIGH RISK**\nQQQ here\n06/20 460P\nAvg. 1.20"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "QQQ"
        assert sig.strike == 460.0

    def test_decimal_strike(self) -> None:
        content = "@here **HIGH RISK**\nSPY here\n06/15 735.5P\nAvg. 1.75"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.strike == 735.5

    def test_decimal_price(self) -> None:
        content = "@here **HIGH RISK**\nSPY here\n06/15 735P\nAvg. 1.75"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.price == 1.75


# ─── Format 2: Multi-line standard ───────────────────────────────────────────

class TestParseZabesBuyFormat2Standard:
    def test_spy_call_standard(self) -> None:
        content = "@here SPY here\n06/20 740C\nAvg. 1.80"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "SPY"
        assert sig.direction == "CALL"
        assert sig.strike == 740.0
        assert sig.price == 1.80
        assert sig.expiry == date(2026, 6, 20)
        assert sig.is_high_risk is False

    def test_spy_put_standard(self) -> None:
        content = "@here SPY here\n06/27 530P\nAvg. 2.10"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.direction == "PUT"
        assert sig.strike == 530.0
        assert sig.price == 2.10

    def test_iwm_standard(self) -> None:
        content = "@here IWM here\n07/18 210C\nAvg. 0.90"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "IWM"
        assert sig.direction == "CALL"
        assert sig.strike == 210.0

    def test_single_digit_month(self) -> None:
        content = "@here SPY here\n7/18 545C\nAvg. 1.50"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.expiry == date(2026, 7, 18)


# ─── Format 3: Direct single-line ─────────────────────────────────────────────

class TestParseZabesBuyFormat3Direct:
    def test_spx_put_at_syntax(self) -> None:
        content = "@here SPX 7400P at 2.50 exp 6/20"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "SPX"
        assert sig.direction == "PUT"
        assert sig.strike == 7400.0
        assert sig.price == 2.50
        assert sig.expiry == date(2026, 6, 20)

    def test_spy_call_at_syntax(self) -> None:
        content = "@here SPY 540C at 1.20 exp 6/27"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.symbol == "SPY"
        assert sig.direction == "CALL"
        assert sig.strike == 540.0
        assert sig.price == 1.20
        assert sig.expiry == date(2026, 6, 27)

    def test_direct_no_expiry_defaults_to_7_days(self) -> None:
        content = "@here SPY 540C at 1.20"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        from datetime import datetime, timezone
        today = datetime.now(tz=timezone.utc).date()
        assert sig.expiry == today + timedelta(days=7)

    def test_direct_at_symbol_syntax(self) -> None:
        content = "@here SPX 7400P @ 2.50 exp 6/20"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.price == 2.50


# ─── Negative cases ───────────────────────────────────────────────────────────

class TestParseZabesBuyNegative:
    def test_non_at_here_message_returns_none(self) -> None:
        content = "SPY here\n06/15 735P\nAvg. 1.50"
        sig = parse_zabes_buy(_msg(content))
        assert sig is None

    def test_random_message_returns_none(self) -> None:
        content = "@here good morning everyone!"
        sig = parse_zabes_buy(_msg(content))
        assert sig is None

    def test_sell_message_returns_none_from_buy_parser(self) -> None:
        content = "@here Sold SPY 735P at 2.80"
        sig = parse_zabes_buy(_msg(content))
        # Sell message should not match buy patterns
        assert sig is None

    def test_empty_content_returns_none(self) -> None:
        sig = parse_zabes_buy(_msg(""))
        assert sig is None

    def test_missing_avg_price_multi_line_returns_none(self) -> None:
        content = "@here SPY here\n06/20 740C"
        sig = parse_zabes_buy(_msg(content))
        assert sig is None


# ─── Sell detection ───────────────────────────────────────────────────────────

class TestParseZabesSell:
    def test_sold_keyword(self) -> None:
        assert parse_zabes_sell(_msg("@here Sold SPY 735P at 2.80")) is True

    def test_closed_keyword(self) -> None:
        assert parse_zabes_sell(_msg("@here Closed SPY positions")) is True

    def test_out_keyword(self) -> None:
        assert parse_zabes_sell(_msg("@here Out of SPY")) is True

    def test_sell_keyword(self) -> None:
        assert parse_zabes_sell(_msg("@here sell half here")) is True

    def test_selling_keyword(self) -> None:
        assert parse_zabes_sell(_msg("selling now")) is True

    def test_exit_keyword(self) -> None:
        assert parse_zabes_sell(_msg("exit the trade")) is True

    def test_exiting_keyword(self) -> None:
        assert parse_zabes_sell(_msg("exiting position now")) is True

    def test_case_insensitive_sold(self) -> None:
        assert parse_zabes_sell(_msg("SOLD SPY 735P")) is True

    def test_case_insensitive_closed(self) -> None:
        assert parse_zabes_sell(_msg("CLOSED the position")) is True

    def test_buy_message_not_sell(self) -> None:
        content = "@here SPY here\n06/20 740C\nAvg. 1.80"
        assert parse_zabes_sell(_msg(content)) is False

    def test_random_message_not_sell(self) -> None:
        assert parse_zabes_sell(_msg("@here good entry here")) is False

    def test_empty_message_not_sell(self) -> None:
        assert parse_zabes_sell(_msg("")) is False


# ─── Signal metadata ─────────────────────────────────────────────────────────

class TestZabesBuySignalMetadata:
    def test_channel_id_preserved(self) -> None:
        content = "@here SPY here\n06/20 740C\nAvg. 1.80"
        sig = parse_zabes_buy(_msg(content, channel_id=ZABES_CHANNEL_ID))
        assert sig is not None
        assert sig.channel_id == ZABES_CHANNEL_ID

    def test_message_id_preserved(self) -> None:
        msg = _msg("@here SPY here\n06/20 740C\nAvg. 1.80")
        msg["message_id"] = "12345678"
        sig = parse_zabes_buy(msg)
        assert sig is not None
        assert sig.message_id == "12345678"

    def test_raw_content_preserved(self) -> None:
        content = "@here SPY here\n06/20 740C\nAvg. 1.80"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.raw_content == content

    def test_high_risk_false_for_standard(self) -> None:
        content = "@here SPY here\n06/20 740C\nAvg. 1.80"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.is_high_risk is False

    def test_high_risk_true_for_high_risk(self) -> None:
        content = "@here **HIGH RISK**\nSPY here\n06/15 735P\nAvg. 1.50"
        sig = parse_zabes_buy(_msg(content))
        assert sig is not None
        assert sig.is_high_risk is True
