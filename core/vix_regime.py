"""VIX Regime Filter — adjusts confidence thresholds based on market volatility."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Absolute path to shared state file
_TA_SIGNAL_PATH = Path(__file__).parent.parent / "shared" / "state" / "ta_signal.json"

# VIX regime thresholds
VIX_LOW = 15.0
VIX_MEDIUM = 20.0
VIX_HIGH = 25.0
VIX_CRISIS = 30.0


def get_current_vix() -> Optional[float]:
    """Read VIX value from shared/state/ta_signal.json.

    Checks both indicators.vix and top-level vix fields.
    Returns None if file is missing, unreadable, or VIX field absent.
    """
    try:
        if not _TA_SIGNAL_PATH.exists():
            return None
        with _TA_SIGNAL_PATH.open() as f:
            data = json.load(f)

        # Try indicators.vix first, then top-level vix
        vix = data.get("indicators", {}).get("vix")
        if vix is None:
            vix = data.get("vix")

        if vix is None:
            return None

        return float(vix)
    except Exception as exc:
        logger.warning("vix_regime: failed to read VIX from %s: %s", _TA_SIGNAL_PATH, exc)
        return None


def adjust_confidence_threshold(base_threshold: float, vix: Optional[float] = None) -> float:
    """Return confidence threshold adjusted for current VIX regime.

    Applies an offset to *base_threshold* based on VIX level:
      - VIX < 15   : -0.05 (more permissive — low vol)
      - 15 <= VIX < 20 :  0.00 (neutral)
      - 20 <= VIX < 25 : +0.05
      - 25 <= VIX < 30 : +0.10
      - VIX >= 30  : +0.15 (crisis)
      - VIX unknown:  0.00 (no change)

    Result is clamped to [0.50, 0.90].
    """
    if vix is None:
        vix = get_current_vix()

    if vix is None:
        return base_threshold

    if vix < VIX_LOW:
        offset = -0.05
    elif vix < VIX_MEDIUM:
        offset = 0.0
    elif vix < VIX_HIGH:
        offset = 0.05
    elif vix < VIX_CRISIS:
        offset = 0.10
    else:
        offset = 0.15

    adjusted = base_threshold + offset
    return max(0.50, min(0.90, adjusted))


def get_regime_label(vix: Optional[float] = None) -> str:
    """Return a human-readable VIX regime label with the VIX value.

    Examples: "LOW_VOL (12.3)", "NEUTRAL (18.5)", "ELEVATED (22.1)",
              "HIGH (27.8)", "CRISIS (35.2)", "UNKNOWN"
    """
    if vix is None:
        vix = get_current_vix()

    if vix is None:
        return "UNKNOWN"

    if vix < VIX_LOW:
        label = "LOW_VOL"
    elif vix < VIX_MEDIUM:
        label = "NEUTRAL"
    elif vix < VIX_HIGH:
        label = "ELEVATED"
    elif vix < VIX_CRISIS:
        label = "HIGH"
    else:
        label = "CRISIS"

    return f"{label} ({vix:.1f})"


def should_pause_high_risk_analysts(vix: Optional[float] = None) -> bool:
    """Return True when VIX exceeds VIX_CRISIS (30), signalling extreme volatility."""
    if vix is None:
        vix = get_current_vix()

    if vix is None:
        return False

    return vix > VIX_CRISIS
