"""
mcp_server/ranker.py — Shared deterministic ranking helpers.

Used by find_matching_properties_for_insight, suggest_next_best_actions_for_deal,
and recommend_broker_for_deal.

Weights are documented inline as named constants so Phase 5+ can tune them
without hunting through tool code.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Broker-ranking weights (used by recommend_broker_for_deal +
# find_matching_properties_for_insight)
# ---------------------------------------------------------------------------

# Weight applied to normalised deal-volume rank (0–1).
BROKER_DEAL_VOLUME_WEIGHT: float = 0.40

# Weight applied to asset-class specialization match (0 or 1).
BROKER_SPECIALIZATION_WEIGHT: float = 0.25

# Weight applied to active SPOC assignment (0 or 1; 0.5 for expired).
BROKER_SPOC_WEIGHT: float = 0.20

# Weight applied to community overlap with requesting broker (0 or 1).
BROKER_COMMUNITY_WEIGHT: float = 0.10

# Weight applied to PREDICTED_AFFINITY score (0–1).
BROKER_AFFINITY_WEIGHT: float = 0.05


# ---------------------------------------------------------------------------
# Property-ranking weights (used by find_matching_properties_for_insight)
# ---------------------------------------------------------------------------

# Weight applied to asset-class match (0 or 1).
PROPERTY_ASSET_CLASS_WEIGHT: float = 0.40

# Weight applied to market/submarket match (0 or 1).
PROPERTY_MARKET_WEIGHT: float = 0.40

# Weight applied to recency (lease recency, normalised 0–1).
PROPERTY_RECENCY_WEIGHT: float = 0.20


# ---------------------------------------------------------------------------
# Core ranking helpers
# ---------------------------------------------------------------------------


def weighted_sum(components: dict[str, tuple[float, float]]) -> float:
    """
    Compute a weighted sum from a dict of {name: (value, weight)} pairs.

    Values are expected to already be normalised to [0, 1].
    Returns a float in [0, 1].

    Example:
        weighted_sum({
            "deal_volume": (0.8, 0.4),
            "spec_match":  (1.0, 0.3),
            "spoc":        (1.0, 0.3),
        })
    """
    total_weight = sum(w for _, w in components.values())
    if total_weight == 0:
        return 0.0
    score = sum(v * w for v, w in components.values())
    return round(score / total_weight, 4)


def normalise_rank(values: list[float]) -> list[float]:
    """
    Map a list of raw values to the [0, 1] range using min-max normalisation.

    Ties are preserved; if all values are equal every element maps to 1.0
    (best case — no discrimination possible).
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def stable_sort(
    items: list[dict[str, Any]],
    key_field: str = "score",
    secondary_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Sort items descending by key_field, with optional secondary_key for tie-breaking.

    Deterministic: items with identical (key_field, secondary_key) values retain
    their original relative order (stable sort).
    """
    def sort_key(item: dict) -> tuple:
        primary = -item.get(key_field, 0.0)
        secondary = -(item.get(secondary_key, 0.0) if secondary_key else 0.0)
        return (primary, secondary)

    return sorted(items, key=sort_key)


def build_reason_string(components: dict[str, tuple[float, float]], labels: dict[str, str]) -> list[str]:
    """
    Produce a human-readable list of reason strings from active scoring components.

    components: {name: (value, weight)}
    labels:     {name: "Human-readable description template"}

    Only components where value > 0 produce a reason string.
    """
    reasons: list[str] = []
    for name, (value, weight) in components.items():
        if value > 0 and name in labels:
            reasons.append(labels[name])
    return reasons


def spoc_value(spoc_status: str | None) -> float:
    """Convert a SPOC status string to a [0, 1] numeric value for ranking."""
    if spoc_status == "active":
        return 1.0
    if spoc_status == "expired":
        return 0.5
    return 0.0
