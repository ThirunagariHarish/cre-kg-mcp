"""Unit tests for core/vix_regime.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import core.vix_regime as vr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_vix(tmp_path: Path, vix_value: float, nested: bool = True) -> Path:
    """Write a ta_signal.json with the given VIX value."""
    ta_path = tmp_path / "ta_signal.json"
    if nested:
        payload = {"indicators": {"vix": vix_value}}
    else:
        payload = {"vix": vix_value}
    ta_path.write_text(json.dumps(payload))
    return ta_path


# ---------------------------------------------------------------------------
# get_current_vix
# ---------------------------------------------------------------------------

class TestGetCurrentVix:
    def test_reads_nested_vix(self, tmp_path):
        ta_path = _write_vix(tmp_path, 18.5, nested=True)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            assert vr.get_current_vix() == pytest.approx(18.5)

    def test_reads_top_level_vix(self, tmp_path):
        ta_path = _write_vix(tmp_path, 22.0, nested=False)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            assert vr.get_current_vix() == pytest.approx(22.0)

    def test_missing_file_returns_none(self, tmp_path):
        missing = tmp_path / "no_such_file.json"
        with patch.object(vr, "_TA_SIGNAL_PATH", missing):
            assert vr.get_current_vix() is None

    def test_no_vix_field_returns_none(self, tmp_path):
        ta_path = tmp_path / "ta_signal.json"
        ta_path.write_text(json.dumps({"indicators": {"rsi": 55}}))
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            assert vr.get_current_vix() is None


# ---------------------------------------------------------------------------
# adjust_confidence_threshold
# ---------------------------------------------------------------------------

class TestAdjustConfidenceThreshold:
    def test_low_vix_reduces_threshold(self, tmp_path):
        """VIX=12 (< 15) should reduce threshold by 0.05."""
        ta_path = _write_vix(tmp_path, 12.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.70)
        assert result == pytest.approx(0.65)

    def test_neutral_vix_no_change(self, tmp_path):
        """VIX=18 (15-20) should leave threshold unchanged."""
        ta_path = _write_vix(tmp_path, 18.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.70)
        assert result == pytest.approx(0.70)

    def test_elevated_vix_raises_threshold(self, tmp_path):
        """VIX=22 (20-25) should raise threshold by 0.05."""
        ta_path = _write_vix(tmp_path, 22.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.70)
        assert result == pytest.approx(0.75)

    def test_high_vix_raises_threshold(self, tmp_path):
        """VIX=27 (25-30) should raise threshold by 0.10."""
        ta_path = _write_vix(tmp_path, 27.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.70)
        assert result == pytest.approx(0.80)

    def test_crisis_vix_max_threshold(self, tmp_path):
        """VIX=35 (>=30) should raise by 0.15; result clamped at 0.90."""
        ta_path = _write_vix(tmp_path, 35.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.80)
        assert result == pytest.approx(0.90)

    def test_crisis_vix_clamp_ceiling(self, tmp_path):
        """VIX=40 with high base should not exceed 0.90."""
        ta_path = _write_vix(tmp_path, 40.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.85)
        assert result == pytest.approx(0.90)

    def test_low_vix_clamp_floor(self, tmp_path):
        """Very low base + low VIX should not go below 0.50."""
        ta_path = _write_vix(tmp_path, 5.0)
        with patch.object(vr, "_TA_SIGNAL_PATH", ta_path):
            result = vr.adjust_confidence_threshold(0.52)
        assert result == pytest.approx(0.50)

    def test_no_vix_no_change(self, tmp_path):
        """Missing file → base_threshold returned unchanged."""
        missing = tmp_path / "no_file.json"
        with patch.object(vr, "_TA_SIGNAL_PATH", missing):
            result = vr.adjust_confidence_threshold(0.70)
        assert result == pytest.approx(0.70)

    def test_vix_provided_directly(self):
        """Explicit vix kwarg skips file read."""
        result = vr.adjust_confidence_threshold(0.70, vix=12.0)
        assert result == pytest.approx(0.65)

        result = vr.adjust_confidence_threshold(0.70, vix=35.0)
        assert result == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# should_pause_high_risk_analysts
# ---------------------------------------------------------------------------

class TestShouldPause:
    def test_pause_above_30(self):
        """VIX=31 (> VIX_CRISIS=30) → True."""
        assert vr.should_pause_high_risk_analysts(vix=31.0) is True

    def test_no_pause_at_30(self):
        """VIX=30.0 exactly is NOT above 30 → False."""
        assert vr.should_pause_high_risk_analysts(vix=30.0) is False

    def test_no_pause_below_30(self):
        assert vr.should_pause_high_risk_analysts(vix=25.0) is False

    def test_no_pause_when_vix_unknown(self, tmp_path):
        missing = tmp_path / "no_file.json"
        with patch.object(vr, "_TA_SIGNAL_PATH", missing):
            assert vr.should_pause_high_risk_analysts() is False


# ---------------------------------------------------------------------------
# get_regime_label
# ---------------------------------------------------------------------------

class TestRegimeLabel:
    def test_low_vol_label(self):
        """VIX=14 → LOW_VOL."""
        label = vr.get_regime_label(vix=14.0)
        assert label.startswith("LOW_VOL")
        assert "14.0" in label

    def test_neutral_label(self):
        label = vr.get_regime_label(vix=18.5)
        assert label.startswith("NEUTRAL")

    def test_elevated_label(self):
        """VIX=22 → ELEVATED."""
        label = vr.get_regime_label(vix=22.0)
        assert label.startswith("ELEVATED")

    def test_high_label(self):
        label = vr.get_regime_label(vix=27.8)
        assert label.startswith("HIGH")

    def test_crisis_label(self):
        """VIX=32 → CRISIS."""
        label = vr.get_regime_label(vix=32.0)
        assert label.startswith("CRISIS")

    def test_unknown_when_no_file(self, tmp_path):
        missing = tmp_path / "no_file.json"
        with patch.object(vr, "_TA_SIGNAL_PATH", missing):
            assert vr.get_regime_label() == "UNKNOWN"

    @pytest.mark.parametrize("vix,expected_prefix", [
        (14.0, "LOW_VOL"),
        (22.0, "ELEVATED"),
        (32.0, "CRISIS"),
    ])
    def test_regime_labels_parametrized(self, vix, expected_prefix):
        assert vr.get_regime_label(vix=vix).startswith(expected_prefix)
