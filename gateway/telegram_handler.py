"""
gateway/telegram_handler.py — Two-way Telegram alert and command handler.

Sends trade/position alerts outbound and receives /commands inbound via
long-polling. No webhook server required; safe to run alongside any async
event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from core.kill_switch import is_blocked, set_blocked

# ---------------------------------------------------------------------------
# State file paths
# ---------------------------------------------------------------------------
PAUSED_ANALYSTS_FILE = Path("shared/state/paused_analysts.json")
MANUAL_CLOSE_FILE = Path("shared/state/manual_close_queue.jsonl")


# ---------------------------------------------------------------------------
# Module-level helpers (no self, easy to unit-test in isolation)
# ---------------------------------------------------------------------------

def _load_paused_analysts() -> set[str]:
    """Read PAUSED_ANALYSTS_FILE and return set of analyst_ids. Empty set on error."""
    try:
        raw = PAUSED_ANALYSTS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        return set(data.get("paused", []))
    except Exception:
        return set()


def _save_paused_analysts(paused: set[str]) -> None:
    """Write {'paused': [...]} to PAUSED_ANALYSTS_FILE."""
    PAUSED_ANALYSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSED_ANALYSTS_FILE.write_text(
        json.dumps({"paused": sorted(paused)}, indent=2),
        encoding="utf-8",
    )


def _append_to_file(path: Path, data: dict[str, Any]) -> None:
    """Append a JSON line to *path*, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data) + "\n")


# ---------------------------------------------------------------------------
# Main handler class
# ---------------------------------------------------------------------------

class TelegramHandler:
    """Two-way Telegram gateway: send alerts, receive /commands."""

    def __init__(self) -> None:
        self._token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
        self._enabled: bool = bool(self._token and self._chat_id)
        self._base_url: str = f"https://api.telegram.org/bot{self._token}"
        self._last_update_id: int = 0
        self._http: httpx.AsyncClient = httpx.AsyncClient(timeout=35.0)
        self._kill_switch_path: Path = Path("shared/state/kill_switch.json")
        self._log: logging.Logger = logging.getLogger("telegram_handler")

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send_alert(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a plain text alert to the configured chat.

        Returns True on success, False on any failure. NEVER raises.
        """
        if not self._enabled:
            self._log.debug("Telegram not configured — skipping alert")
            return False

        try:
            url = f"{self._base_url}/sendMessage"
            payload = {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            response = await self._http.post(url, json=payload)
            if response.status_code == 200:
                return True
            self._log.warning(
                "Telegram sendMessage returned HTTP %s: %s",
                response.status_code,
                response.text[:200],
            )
            return False
        except Exception as exc:
            self._log.error("Telegram send_alert failed: %s", exc)
            return False

    async def send_position_alert(self, symbol: str, pnl_pct: float, reason: str) -> None:
        """Format and send a position P&L alert."""
        emoji = "🟢" if pnl_pct >= 0 else "🔴"
        sign = "+" if pnl_pct >= 0 else ""
        text = (
            f"{emoji} *{symbol}* position alert\n"
            f"P&L: `{sign}{pnl_pct:.2f}%`\n"
            f"Reason: {reason}"
        )
        await self.send_alert(text)

    # ------------------------------------------------------------------
    # Inbound polling loop
    # ------------------------------------------------------------------

    async def run_polling(self) -> None:
        """
        Long-poll Telegram for updates and dispatch commands.

        Exits cleanly on CancelledError; logs and retries after other errors.
        """
        if not self._enabled:
            self._log.warning(
                "Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID) "
                "— polling disabled"
            )
            return

        self._log.info("Telegram polling started")
        while True:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._handle_update(update)
            except asyncio.CancelledError:
                self._log.info("Telegram polling cancelled — shutting down")
                break
            except Exception as exc:
                self._log.error("Telegram polling error: %s — retrying in 5s", exc)
                await asyncio.sleep(5)

    async def _get_updates(self) -> list[dict[str, Any]]:
        """
        Fetch new updates from Telegram using long-polling.

        Returns a list of update dicts. Returns [] on any error.
        """
        try:
            url = f"{self._base_url}/getUpdates"
            params = {
                "offset": self._last_update_id + 1,
                "timeout": 30,
            }
            response = await self._http.get(url, params=params)
            if response.status_code != 200:
                self._log.warning("getUpdates returned HTTP %s", response.status_code)
                return []

            data = response.json()
            results: list[dict[str, Any]] = data.get("result", [])
            if results:
                self._last_update_id = max(r["update_id"] for r in results)
            return results
        except Exception as exc:
            self._log.error("_get_updates failed: %s", exc)
            return []

    async def _handle_update(self, update: dict[str, Any]) -> None:
        """Parse a Telegram update dict and dispatch to the appropriate _cmd_* method."""
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        text: str = message.get("text", "").strip()
        chat_id: str = str(message.get("chat", {}).get("id", ""))

        # Security: only respond to the configured chat
        if chat_id != str(self._chat_id):
            self._log.debug("Ignoring message from unknown chat %s", chat_id)
            return

        if not text:
            return

        parts = text.split()
        command = parts[0].lower()
        # Strip BotFather @mention suffix (e.g. /kill@mybot)
        command = command.split("@")[0]
        args = parts[1:]

        dispatch: dict[str, Any] = {
            "/status":   self._cmd_status,
            "/positions": self._cmd_positions,
            "/close":    self._cmd_close,
            "/closeall": self._cmd_closeall,
            "/pause":    self._cmd_pause,
            "/resume":   self._cmd_resume,
            "/kill":     self._cmd_kill,
            "/health":   self._cmd_health,
        }

        handler = dispatch.get(command)
        if handler is None:
            await self._cmd_unknown(command)
        else:
            await handler(args)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_status(self, args: list[str]) -> None:
        blocked = is_blocked(self._kill_switch_path)
        kill_state = "BLOCKED 🔴" if blocked else "HEALTHY 🟢"
        paper = os.getenv("PAPER_TRADING", "true").lower() != "false"
        mode = "Paper" if paper else "Live"
        paused = _load_paused_analysts()
        msg = (
            f"*System Status*\n"
            f"Kill switch: {kill_state}\n"
            f"Mode: {mode}\n"
            f"Paused analysts: {len(paused)}"
        )
        await self.send_alert(msg)

    async def _cmd_positions(self, args: list[str]) -> None:
        positions_path = Path("shared/state/open_positions.json")
        try:
            raw = positions_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            positions: list[Any] = data if isinstance(data, list) else data.get("positions", [])
            positions = positions[:10]
            if not positions:
                await self.send_alert("No open positions.")
                return
            lines = ["*Open Positions*"]
            for pos in positions:
                if isinstance(pos, dict):
                    sym = pos.get("symbol", "?")
                    qty = pos.get("quantity", pos.get("qty", "?"))
                    pnl = pos.get("pnl_pct", pos.get("pnl", "?"))
                    lines.append(f"• {sym}  qty={qty}  pnl={pnl}")
                else:
                    lines.append(f"• {pos}")
            await self.send_alert("\n".join(lines))
        except FileNotFoundError:
            await self.send_alert("No open positions file found.")
        except Exception as exc:
            self._log.error("_cmd_positions error: %s", exc)
            await self.send_alert(f"Error reading positions: {exc}")

    async def _cmd_close(self, args: list[str]) -> None:
        if not args:
            await self.send_alert("Usage: /close SYMBOL")
            return
        symbol = args[0].upper()
        _append_to_file(MANUAL_CLOSE_FILE, {"symbol": symbol, "action": "close_by_symbol"})
        await self.send_alert(f"Close queued for *{symbol}*.")

    async def _cmd_closeall(self, args: list[str]) -> None:
        _append_to_file(MANUAL_CLOSE_FILE, {"action": "close_all"})
        await self.send_alert("Close-all queued.")

    async def _cmd_pause(self, args: list[str]) -> None:
        if not args:
            await self.send_alert("Usage: /pause ANALYST_ID")
            return
        analyst_id = args[0]
        paused = _load_paused_analysts()
        paused.add(analyst_id)
        _save_paused_analysts(paused)
        await self.send_alert(f"Analyst *{analyst_id}* paused.")

    async def _cmd_resume(self, args: list[str]) -> None:
        if not args:
            await self.send_alert("Usage: /resume ANALYST_ID")
            return
        analyst_id = args[0]
        paused = _load_paused_analysts()
        paused.discard(analyst_id)
        _save_paused_analysts(paused)
        await self.send_alert(f"Analyst *{analyst_id}* resumed.")

    async def _cmd_kill(self, args: list[str]) -> None:
        set_blocked("Activated via Telegram /kill command", self._kill_switch_path)
        await self.send_alert("🚨 Kill switch *ACTIVATED*. All trading halted.")

    async def _cmd_health(self, args: list[str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        py = sys.version.split()[0]
        await self.send_alert(f"*Health OK*\nPython: {py}\nTimestamp: {now}")

    async def _cmd_unknown(self, command: str) -> None:
        help_text = (
            "Unknown command. Available commands:\n"
            "/status    — kill switch state, mode, paused analysts\n"
            "/positions — list open positions (max 10)\n"
            "/close SYMBOL — queue close for a symbol\n"
            "/closeall  — queue close for all positions\n"
            "/pause ANALYST_ID — pause an analyst\n"
            "/resume ANALYST_ID — resume an analyst\n"
            "/kill      — activate kill switch\n"
            "/health    — Python version + timestamp"
        )
        await self.send_alert(help_text)
