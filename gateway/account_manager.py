"""
gateway/account_manager.py — Multi-account configuration management.

Loads account configs from configs/accounts.json, resolves secrets from
environment variables, and filters to only enabled accounts.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AccountConfig:
    """Configuration for a single Robinhood account."""

    account_id: str
    display_name: str
    username_secret: str
    password_secret: str
    totp_secret: str
    paper_mode: bool
    enabled: bool
    max_position_size_usd: float
    notes: str

    @property
    def username(self) -> str | None:
        return os.getenv(self.username_secret)

    @property
    def password(self) -> str | None:
        return os.getenv(self.password_secret)

    @property
    def totp(self) -> str | None:
        return os.getenv(self.totp_secret)

    @property
    def is_configured(self) -> bool:
        """True if account has all credentials needed to operate."""
        if self.paper_mode:
            return True
        return all([self.username, self.password, self.totp])


def load_accounts(path: str = "configs/accounts.json") -> list[AccountConfig]:
    """
    Parse accounts.json, apply global_paper_mode_override, and return
    only enabled accounts.

    Parameters
    ----------
    path : str
        Path to the accounts config file.  Relative paths are resolved
        from the current working directory.

    Returns
    -------
    list[AccountConfig]
        Only accounts with ``enabled=True`` are returned.
    """
    config_path = Path(path)
    with config_path.open() as fh:
        data: dict[str, Any] = json.load(fh)

    global_paper_override: bool = data.get("global_paper_mode_override", False)

    accounts: list[AccountConfig] = []
    for raw in data.get("accounts", []):
        paper_mode = raw.get("paper_mode", True)
        if global_paper_override:
            paper_mode = True

        config = AccountConfig(
            account_id=raw["account_id"],
            display_name=raw.get("display_name", raw["account_id"]),
            username_secret=raw["username_secret"],
            password_secret=raw["password_secret"],
            totp_secret=raw["totp_secret"],
            paper_mode=paper_mode,
            enabled=raw.get("enabled", True),
            max_position_size_usd=float(raw.get("max_position_size_usd", 200)),
            notes=raw.get("notes", ""),
        )
        if config.enabled:
            accounts.append(config)

    return accounts
