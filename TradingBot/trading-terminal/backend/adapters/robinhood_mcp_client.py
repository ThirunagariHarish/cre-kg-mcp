"""Robinhood MCP subprocess client — JSON-RPC over stdio."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MCP_SCRIPT = Path(__file__).parent.parent / "mcp_servers" / "robinhood_mcp.py"


class RobinhoodMCPClient:
    """
    Manages a single subprocess running robinhood_mcp.py.
    All trading agents call this — never call Robinhood directly.
    Thread-safe via lock.
    """

    def __init__(self, paper_mode: bool = True) -> None:
        self.paper_mode = paper_mode
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._start()

    def _start(self) -> None:
        env = os.environ.copy()
        env["PAPER_MODE"] = "true" if self.paper_mode else "false"
        self._proc = subprocess.Popen(
            [sys.executable, str(MCP_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        logger.info("Robinhood MCP subprocess started PID=%d paper=%s", self._proc.pid, self.paper_mode)

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _restart(self) -> None:
        logger.warning("Restarting Robinhood MCP subprocess...")
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                self._proc.wait(timeout=5)
        except Exception:
            pass
        self._start()

    def _call_once(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self._is_alive():
            raise RuntimeError("Robinhood MCP subprocess is not running")
        request = json.dumps({"tool": tool, "arguments": args}) + "\n"
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(request)
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP returned empty response — subprocess may have died")
        return json.loads(line.strip())

    def call(self, tool: str, args: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        with self._lock:
            last_exc: Exception | None = None
            for attempt in range(retries):
                try:
                    return self._call_once(tool, args)
                except Exception as e:
                    last_exc = e
                    wait = 2 ** attempt
                    logger.warning("MCP call '%s' attempt %d/%d failed: %s. Retry in %ds", tool, attempt+1, retries, e, wait)
                    time.sleep(wait)
                    if not self._is_alive():
                        self._restart()
            raise RuntimeError(f"MCP tool '{tool}' failed after {retries} retries: {last_exc}")

    def login(self) -> dict[str, Any]:
        return self.call("robinhood_login", {})

    def get_account(self) -> dict[str, Any]:
        return self.call("get_account", {})

    def get_positions(self) -> list[dict[str, Any]]:
        result = self.call("get_positions", {})
        return result if isinstance(result, list) else result.get("positions", [])

    def get_quote(self, symbol: str) -> dict[str, Any]:
        return self.call("get_quote", {"symbol": symbol})

    def place_stock_order(self, symbol: str, quantity: int, side: str) -> dict[str, Any]:
        return self.call("place_stock_order", {"symbol": symbol, "quantity": quantity, "side": side})

    def place_option_order(
        self, symbol: str, expiry: str, strike: float,
        option_type: str, quantity: int = 1, side: str = "buy"
    ) -> dict[str, Any]:
        return self.call("place_option_order", {
            "symbol": symbol, "expiry": expiry, "strike": strike,
            "option_type": option_type, "quantity": quantity, "side": side,
        })

    def close_position(self, symbol: str, quantity: int | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"symbol": symbol}
        if quantity is not None:
            args["quantity"] = quantity
        return self.call("close_position", args)

    def place_order_with_stop_loss(
        self, symbol: str, quantity: int, side: str, stop_loss_pct: float = 15.0
    ) -> dict[str, Any]:
        return self.call("place_order_with_stop_loss", {
            "symbol": symbol, "quantity": quantity, "side": side,
            "stop_loss_pct": stop_loss_pct,
        })

    def cancel_and_close(self, symbol: str) -> dict[str, Any]:
        return self.call("cancel_and_close", {"symbol": symbol})

    def shutdown(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        logger.info("Robinhood MCP subprocess stopped")


__all__ = ["RobinhoodMCPClient"]
