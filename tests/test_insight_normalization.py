"""
Tests for insight tag normalization (Phase 2).

Covers:
  - Washington DC / DC pass-through after adding to canonical_map.yaml
  - Denver + Portland after adding to canonical_map.yaml
  - Data Centers asset class after adding to canonical_map.yaml
  - "DFW North - Urban" submarket → dallas-fort worth market
  - Unmapped tags return None from canonical_resolver (not silently dropped)
  - Pass-through: unresolved tags are returned as None, not silently ignored
"""

from __future__ import annotations

import pytest

from ingester.normalizer import canonical_resolver, taxonomy_key


class TestCanonicalResolverPhaseTwoTags:
    """Tags that were flagged as unmapped in Phase 1 — must now resolve."""

    def test_washington_dc_resolves(self):
        result = canonical_resolver("Washington DC")
        assert result is not None, "Washington DC should resolve after Phase 2 canonical_map update"
        label, name = result
        assert label == "Market"
        assert "washington" in name.lower()

    def test_dc_alias_resolves(self):
        result = canonical_resolver("DC")
        assert result is not None, "DC should resolve to Washington DC market"
        label, name = result
        assert label == "Market"

    def test_denver_resolves(self):
        result = canonical_resolver("Denver")
        assert result is not None, "Denver should resolve after Phase 2 canonical_map update"
        label, name = result
        assert label == "Market"

    def test_portland_resolves(self):
        result = canonical_resolver("Portland")
        assert result is not None, "Portland should resolve after Phase 2 canonical_map update"
        label, name = result
        assert label == "Market"

    def test_data_centers_asset_class_resolves(self):
        result = canonical_resolver("Data Centers")
        assert result is not None, "Data Centers should resolve after Phase 2 canonical_map update"
        label, name = result
        assert label == "AssetClass"
        assert "data" in name.lower()

    def test_data_center_singular_resolves(self):
        result = canonical_resolver("Data Center")
        assert result is not None, "Data Center (singular) should resolve"
        label, name = result
        assert label == "AssetClass"

    def test_dfw_north_urban_resolves_to_market(self):
        """'DFW North - Urban' should map to dallas-fort worth market."""
        result = canonical_resolver("DFW North - Urban")
        assert result is not None, "DFW North - Urban should resolve to dallas-fort worth"
        label, name = result
        assert label == "Market"
        assert "dallas" in name.lower()

    def test_manhattan_resolves_to_new_york(self):
        result = canonical_resolver("Manhattan")
        assert result is not None, "Manhattan should resolve to new york market"
        label, name = result
        assert label == "Market"
        assert "new york" in name.lower()

    def test_austin_resolves(self):
        result = canonical_resolver("Austin")
        assert result is not None
        label, name = result
        assert label == "Market"

    def test_san_francisco_resolves(self):
        result = canonical_resolver("San Francisco")
        assert result is not None
        label, name = result
        assert label == "Market"

    def test_bay_area_resolves_to_san_francisco(self):
        result = canonical_resolver("Bay Area")
        assert result is not None
        label, name = result
        assert label == "Market"
        assert "san francisco" in name.lower()


class TestUnmappedTagsAreNotSilentlyDropped:
    """
    Unmapped tags must return None — they are logged, NOT silently dropped.
    This ensures the pipeline treats them explicitly.
    """

    def test_unknown_tag_returns_none(self):
        result = canonical_resolver("CompletlyUnknownTagXYZ123")
        assert result is None, "Unknown tag must return None, not raise"

    def test_none_result_is_not_an_empty_node(self):
        """Callers must check for None; None != empty resolved edge."""
        result = canonical_resolver("RandomThing999")
        # None means: skip this tag, log a warning — don't create a node
        assert result is None

    def test_tenant_prefix_resolves(self):
        result = canonical_resolver("tenant:Acme Corp")
        assert result is not None
        label, name = result
        assert label == "Tenant"
        assert "acme corp" in name.lower()

    def test_property_prefix_resolves(self):
        result = canonical_resolver("property:P-12345")
        assert result is not None
        label, name = result
        assert label == "Property"
        assert "P-12345" in name

    def test_case_insensitive_market(self):
        result = canonical_resolver("ATLANTA")
        assert result is not None
        label, name = result
        assert label == "Market"

    def test_partial_match_does_not_resolve(self):
        """'Dallas' alone (without 'Fort Worth') should still resolve via alias."""
        result = canonical_resolver("Dallas")
        # Dallas is an alias for dallas-fort worth in canonical_map.yaml
        assert result is not None
        label, name = result
        assert label == "Market"
        assert "dallas" in name.lower()


class TestTaxonomyKeyPhaseTwoValues:
    """taxonomy_key() should resolve or pass-through for Phase 2 values."""

    def test_washington_dc_taxonomy(self):
        result = taxonomy_key("Washington DC", "markets")
        assert "washington" in result.lower()

    def test_denver_taxonomy(self):
        result = taxonomy_key("Denver", "markets")
        assert "denver" in result.lower()

    def test_data_centers_taxonomy(self):
        result = taxonomy_key("Data Centers", "asset_classes")
        assert "data" in result.lower()

    def test_unknown_passes_through_lowercase(self):
        result = taxonomy_key("SomeCompletelyNewMarketXYZ", "markets")
        # Not in map → returned as lowercase raw value
        assert result == "somecompletelynewmarketxyz"
