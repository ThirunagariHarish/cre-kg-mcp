"""Tests for core/kill_switch.py — the safe-fail kill switch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.kill_switch import is_blocked, require_healthy, set_blocked, set_healthy


class TestKillSwitch:
    def test_missing_file_returns_blocked(self, tmp_path: Path) -> None:
        """Missing kill_switch.json → BLOCKED (safe fail)."""
        missing = tmp_path / "kill_switch.json"
        assert is_blocked(missing) is True

    def test_malformed_json_returns_blocked(self, tmp_path: Path) -> None:
        """Malformed JSON → BLOCKED (safe fail)."""
        path = tmp_path / "kill_switch.json"
        path.write_text("{not valid json}", encoding="utf-8")
        assert is_blocked(path) is True

    def test_active_true_returns_blocked(self, tmp_path: Path) -> None:
        path = tmp_path / "kill_switch.json"
        path.write_text(json.dumps({"active": True, "reason": "test"}), encoding="utf-8")
        assert is_blocked(path) is True

    def test_active_false_returns_not_blocked(self, tmp_path: Path) -> None:
        path = tmp_path / "kill_switch.json"
        path.write_text(json.dumps({"active": False, "reason": None}), encoding="utf-8")
        assert is_blocked(path) is False

    def test_unknown_schema_returns_blocked(self, tmp_path: Path) -> None:
        """JSON with no 'active' or 'triggered' field → BLOCKED."""
        path = tmp_path / "kill_switch.json"
        path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
        assert is_blocked(path) is True

    def test_legacy_triggered_field_compat(self, tmp_path: Path) -> None:
        """Legacy files with 'triggered' field must still work."""
        path = tmp_path / "kill_switch.json"
        path.write_text(json.dumps({"triggered": True}), encoding="utf-8")
        assert is_blocked(path) is True

        path.write_text(json.dumps({"triggered": False}), encoding="utf-8")
        assert is_blocked(path) is False

    def test_set_blocked_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "state" / "kill_switch.json"
        set_blocked("test reason", path)
        assert is_blocked(path) is True
        data = json.loads(path.read_text())
        assert data["active"] is True
        assert data["reason"] == "test reason"

    def test_set_healthy_clears_block(self, tmp_path: Path) -> None:
        path = tmp_path / "kill_switch.json"
        set_blocked("testing", path)
        assert is_blocked(path) is True
        set_healthy(path)
        assert is_blocked(path) is False

    def test_require_healthy_raises_when_blocked(self, tmp_path: Path) -> None:
        path = tmp_path / "kill_switch.json"
        set_blocked("emergency stop", path)
        with pytest.raises(RuntimeError, match="Kill switch is active"):
            require_healthy(path)

    def test_require_healthy_passes_when_healthy(self, tmp_path: Path) -> None:
        path = tmp_path / "kill_switch.json"
        set_healthy(path)
        require_healthy(path)  # should not raise
