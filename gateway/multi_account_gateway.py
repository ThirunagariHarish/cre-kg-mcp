"""
gateway/multi_account_gateway.py — Fan-out execution across multiple Robinhood accounts.

Design:
  - AccountGateway wraps one RHGateway with account metadata.
  - MultiAccountGateway fans out signals/closes to all enabled accounts
    concurrently via asyncio.gather.
  - Failures in one account are logged but do not block other accounts.
  - Combined open positions are written to shared/state/open_positions.json
    with account_id injected into source_metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from gateway.account_manager import AccountConfig, load_accounts
from gateway.rh_gateway import RHGateway
from core.schemas import OrderRecord, PositionRecord, TradeSignal

logger = logging.getLogger(__name__)

_OPEN_POSITIONS_PATH = Path("shared/state/open_positions.json")


class AccountGateway:
    """
    Wraps a single RHGateway instance with account metadata (id, display name,
    paper mode flag).

    All public methods delegate directly to the underlying RHGateway.
    """

    def __init__(self, config: AccountConfig) -> None:
        self.account_id: str = config.account_id
        self.display_name: str = config.display_name
        self.paper_mode: bool = config.paper_mode
        self._config = config
        self._rh = RHGateway(paper_mode=config.paper_mode)

    async def execute_signal(self, signal: TradeSignal) -> OrderRecord | None:
        logger.info(
            "[%s] execute_signal: %s %s %s",
            self.account_id, signal.symbol, signal.direction, signal.strike,
        )
        return await self._rh.execute_signal(signal)

    async def close_position(
        self, position: PositionRecord, qty: int, reason: str
    ) -> OrderRecord | None:
        logger.info(
            "[%s] close_position: %s x%d reason=%s",
            self.account_id, position.symbol, qty, reason,
        )
        return await self._rh.close_position(position, qty, reason)

    async def get_positions(self) -> list[PositionRecord]:
        return await self._rh.get_positions()

    async def get_account(self) -> dict[str, Any]:
        info = await self._rh.get_account()
        info["account_id"] = self.account_id
        info["display_name"] = self.display_name
        return info


class MultiAccountGateway:
    """
    Fan-out execution gateway that runs signals/closes across all enabled
    Robinhood accounts concurrently.

    Parameters
    ----------
    accounts : list[AccountConfig] | None
        If None, accounts are loaded from ``configs/accounts.json``.
    redis_client : optional
        Passed through to each AccountGateway (currently unused at this layer;
        RHGateway inside each AccountGateway does not receive it — extend if needed).
    """

    def __init__(
        self,
        accounts: list[AccountConfig] | None = None,
        redis_client: Any | None = None,
    ) -> None:
        if accounts is None:
            accounts = load_accounts()
        self._gateways: list[AccountGateway] = [AccountGateway(a) for a in accounts]
        self._redis = redis_client

    # ─────────────────────────────────────────────
    # Signal execution
    # ─────────────────────────────────────────────

    async def execute_signal(self, signal: TradeSignal) -> dict[str, OrderRecord | None]:
        """
        Execute a TradeSignal in all accounts concurrently.

        Returns
        -------
        dict[str, OrderRecord | None]
            Maps account_id to the resulting OrderRecord, or None if the
            account rejected/failed the signal.
        """
        results = await asyncio.gather(
            *[gw.execute_signal(signal) for gw in self._gateways],
            return_exceptions=True,
        )

        output: dict[str, OrderRecord | None] = {}
        for gw, result in zip(self._gateways, results):
            if isinstance(result, Exception):
                logger.error(
                    "[%s] execute_signal failed: %s", gw.account_id, result
                )
                output[gw.account_id] = None
            else:
                output[gw.account_id] = result

        return output

    # ─────────────────────────────────────────────
    # Position closing
    # ─────────────────────────────────────────────

    async def close_position_all(
        self, position: PositionRecord, qty: int, reason: str
    ) -> dict[str, OrderRecord | None]:
        """
        Close a position in ALL accounts concurrently.

        Returns
        -------
        dict[str, OrderRecord | None]
            Maps account_id to the close OrderRecord, or None on failure.
        """
        results = await asyncio.gather(
            *[gw.close_position(position, qty, reason) for gw in self._gateways],
            return_exceptions=True,
        )

        output: dict[str, OrderRecord | None] = {}
        for gw, result in zip(self._gateways, results):
            if isinstance(result, Exception):
                logger.error(
                    "[%s] close_position_all failed: %s", gw.account_id, result
                )
                output[gw.account_id] = None
            else:
                output[gw.account_id] = result

        return output

    async def close_position_in_account(
        self, account_id: str, position: PositionRecord, qty: int, reason: str
    ) -> OrderRecord | None:
        """
        Close a position in a specific account only.

        Parameters
        ----------
        account_id : str
            The target account.  If not found, logs a warning and returns None.
        """
        for gw in self._gateways:
            if gw.account_id == account_id:
                return await gw.close_position(position, qty, reason)
        logger.warning(
            "close_position_in_account: account_id=%s not found in %s",
            account_id, self.get_account_ids(),
        )
        return None

    # ─────────────────────────────────────────────
    # Positions & account info
    # ─────────────────────────────────────────────

    async def get_all_positions(self) -> dict[str, list[PositionRecord]]:
        """
        Gather open positions from all accounts concurrently.

        Side effect: writes combined positions to
        ``shared/state/open_positions.json`` with ``account_id`` injected
        into each position's ``source_metadata``.

        Returns
        -------
        dict[str, list[PositionRecord]]
            Maps account_id to its list of open PositionRecords.
        """
        results = await asyncio.gather(
            *[gw.get_positions() for gw in self._gateways],
            return_exceptions=True,
        )

        output: dict[str, list[PositionRecord]] = {}
        for gw, result in zip(self._gateways, results):
            if isinstance(result, Exception):
                logger.error(
                    "[%s] get_all_positions failed: %s", gw.account_id, result
                )
                output[gw.account_id] = []
            else:
                output[gw.account_id] = result  # type: ignore[assignment]

        self._write_combined_positions(output)
        return output

    async def get_all_accounts(self) -> dict[str, dict[str, Any]]:
        """
        Gather account info from all accounts concurrently.

        Returns
        -------
        dict[str, dict[str, Any]]
            Maps account_id to the account info dict from each AccountGateway.
        """
        results = await asyncio.gather(
            *[gw.get_account() for gw in self._gateways],
            return_exceptions=True,
        )

        output: dict[str, dict[str, Any]] = {}
        for gw, result in zip(self._gateways, results):
            if isinstance(result, Exception):
                logger.error(
                    "[%s] get_all_accounts failed: %s", gw.account_id, result
                )
                output[gw.account_id] = {"account_id": gw.account_id, "error": str(result)}
            else:
                output[gw.account_id] = result  # type: ignore[assignment]

        return output

    def get_account_ids(self) -> list[str]:
        """Return all loaded account IDs."""
        return [gw.account_id for gw in self._gateways]

    # ─────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────

    def _write_combined_positions(
        self, positions_by_account: dict[str, list[PositionRecord]]
    ) -> None:
        """
        Serialize all positions to shared/state/open_positions.json.

        Each position dict gets ``account_id`` injected into its
        ``source_metadata`` field before writing.
        """
        combined: list[dict[str, Any]] = []
        for account_id, positions in positions_by_account.items():
            for pos in positions:
                pos_dict = json.loads(pos.model_dump_json())
                pos_dict.setdefault("source_metadata", {})
                pos_dict["source_metadata"]["account_id"] = account_id
                combined.append(pos_dict)

        try:
            _OPEN_POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _OPEN_POSITIONS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(combined, default=str, indent=2))
            tmp.replace(_OPEN_POSITIONS_PATH)
            logger.debug(
                "Wrote %d combined positions to %s", len(combined), _OPEN_POSITIONS_PATH
            )
        except Exception as exc:
            logger.error("Failed to write combined positions: %s", exc)
