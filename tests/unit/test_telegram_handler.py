"""
tests/unit/test_telegram_handler.py — Unit tests for TelegramHandler.

All network calls are mocked; no real Telegram token is needed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.telegram_handler import (
    MANUAL_CLOSE_FILE,
    PAUSED_ANALYSTS_FILE,
    TelegramHandler,
    _append_to_file,
    _load_paused_analysts,
    _save_paused_analysts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler(token: str = "tok", chat_id: str = "123") -> TelegramHandler:
    """Return a TelegramHandler with env vars pre-set."""
    with patch.dict(
        os.environ,
        {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id},
        clear=False,
    ):
        return TelegramHandler()


def _fake_update(text: str, chat_id: str = "123") -> dict:
    return {
        "update_id": 1,
        "message": {
            "text": text,
            "chat": {"id": int(chat_id)},
        },
    }


# ---------------------------------------------------------------------------
# test_send_alert_no_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_alert_no_config(monkeypatch):
    """When no env vars set, send_alert returns False without raising."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    handler = TelegramHandler()
    result = await handler.send_alert("hello")
    assert result is False


# ---------------------------------------------------------------------------
# test_handle_status_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_status_command(tmp_path, monkeypatch):
    """
    /status command replies with a message containing kill-switch state info.
    """
    # Point kill switch to a tmp file that says healthy
    ks_path = tmp_path / "kill_switch.json"
    ks_path.write_text(json.dumps({"active": False, "reason": None}))

    handler = _make_handler()
    handler._kill_switch_path = ks_path

    sent: list[str] = []

    async def fake_send(text, parse_mode="Markdown"):
        sent.append(text)
        return True

    handler.send_alert = fake_send  # type: ignore[method-assign]

    update = _fake_update("/status")
    await handler._handle_update(update)

    assert sent, "Expected at least one alert to be sent"
    combined = " ".join(sent).lower()
    assert "status" in combined or "kill" in combined or "healthy" in combined


# ---------------------------------------------------------------------------
# test_handle_close_command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_close_command(tmp_path, monkeypatch):
    """/close SPY appends an entry with symbol=SPY to MANUAL_CLOSE_FILE."""
    close_file = tmp_path / "manual_close_queue.jsonl"

    # Patch the module-level constant so _append_to_file writes here
    monkeypatch.setattr(
        "gateway.telegram_handler.MANUAL_CLOSE_FILE", close_file
    )

    handler = _make_handler()
    handler.send_alert = AsyncMock(return_value=True)  # type: ignore[method-assign]

    update = _fake_update("/close SPY")
    await handler._handle_update(update)

    assert close_file.exists(), "MANUAL_CLOSE_FILE should be created"
    lines = [l for l in close_file.read_text().splitlines() if l.strip()]
    assert lines, "Expected at least one line in close file"
    entry = json.loads(lines[-1])
    assert entry["symbol"] == "SPY"
    assert entry["action"] == "close_by_symbol"


# ---------------------------------------------------------------------------
# test_pause_and_resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_and_resume(tmp_path, monkeypatch):
    """/pause vinod_spx adds to file; /resume removes it."""
    paused_file = tmp_path / "paused_analysts.json"

    monkeypatch.setattr("gateway.telegram_handler.PAUSED_ANALYSTS_FILE", paused_file)

    handler = _make_handler()
    handler.send_alert = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # Pause
    await handler._handle_update(_fake_update("/pause vinod_spx"))
    data = json.loads(paused_file.read_text())
    assert "vinod_spx" in data["paused"]

    # Resume
    await handler._handle_update(_fake_update("/resume vinod_spx"))
    data = json.loads(paused_file.read_text())
    assert "vinod_spx" not in data["paused"]


# ---------------------------------------------------------------------------
# test_unknown_command_shows_help
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_command_shows_help():
    """/foo triggers a help message listing available commands."""
    handler = _make_handler()
    sent: list[str] = []

    async def fake_send(text, parse_mode="Markdown"):
        sent.append(text)
        return True

    handler.send_alert = fake_send  # type: ignore[method-assign]

    await handler._handle_update(_fake_update("/foo"))

    assert sent, "Expected help message to be sent"
    help_text = sent[-1].lower()
    assert "/status" in help_text
    assert "/kill" in help_text
    assert "/close" in help_text


# ---------------------------------------------------------------------------
# test_kill_command_activates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_kill_command_activates(tmp_path):
    """/kill writes kill_switch.json with active=True."""
    ks_path = tmp_path / "kill_switch.json"

    handler = _make_handler()
    handler._kill_switch_path = ks_path
    handler.send_alert = AsyncMock(return_value=True)  # type: ignore[method-assign]

    await handler._handle_update(_fake_update("/kill"))

    assert ks_path.exists(), "kill_switch.json should be created"
    data = json.loads(ks_path.read_text())
    assert data["active"] is True


# ---------------------------------------------------------------------------
# test_cross_chat_ignored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_chat_ignored():
    """Message from a different chat_id is silently ignored."""
    handler = _make_handler(chat_id="123")
    handler.send_alert = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # Build update from chat 999, which differs from configured 123
    update = {
        "update_id": 2,
        "message": {
            "text": "/kill",
            "chat": {"id": 999},
        },
    }

    await handler._handle_update(update)

    # send_alert should NOT have been called (message was ignored)
    handler.send_alert.assert_not_called()
