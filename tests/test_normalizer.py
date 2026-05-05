"""
Unit tests for ingester/normalizer.py.

Table-driven, covering:
- broker_key: email present, email absent, email upper-cased
- property_key: property_id present, address-only with suite, address normalization
- tenant_key / landlord_key / client_key
- lease_key: explicit lease_id, fallback hash
- taxonomy_key: known alias, unknown value (logs warning)
- canonical_resolver: known market, known asset class, tenant: prefix, unknown tag
"""

from __future__ import annotations

import pytest

from ingester.normalizer import (
    broker_key,
    property_key,
    tenant_key,
    landlord_key,
    lease_key,
    client_key,
    taxonomy_key,
    canonical_resolver,
)


# ---------------------------------------------------------------------------
# broker_key
# ---------------------------------------------------------------------------

class TestBrokerKey:
    def test_email_present_lowercased(self):
        row = {"EMAIL": "Jane@CBRE.COM", "BROKER_NAME": "Jane Liu", "FIRM": "CBRE"}
        assert broker_key(row) == "email::jane@cbre.com"

    def test_email_absent_uses_name_firm(self):
        row = {"EMAIL": "", "BROKER_NAME": "Tom Patel", "FIRM": "JLL"}
        assert broker_key(row) == "name::tom patel::firm::jll"

    def test_email_none_uses_name_firm(self):
        row = {"BROKER_NAME": "  Alice Smith  ", "FIRM": "CBRE Global"}
        assert broker_key(row) == "name::alice smith::firm::cbre global"

    def test_lowercase_field_names(self):
        row = {"email": "bob@example.com", "broker_name": "Bob", "firm": "Acme"}
        assert broker_key(row) == "email::bob@example.com"


# ---------------------------------------------------------------------------
# property_key
# ---------------------------------------------------------------------------

class TestPropertyKey:
    def test_property_id_takes_priority(self):
        row = {"PROPERTY_ID": "P-9921", "ADDRESS": "123 Main St", "ZIP": "75001"}
        assert property_key(row) == "id::P-9921"

    def test_address_with_suite_stripped(self):
        row = {"ADDRESS": "100 Logistics Pkwy Suite 200", "ZIP": "75001"}
        key = property_key(row)
        assert "suite" not in key
        assert "200" not in key  # suite number removed
        assert "75001" in key

    def test_address_ste_stripped(self):
        row = {"ADDRESS": "50 Commerce Dr Ste B", "ZIP": "30301"}
        key = property_key(row)
        assert "ste" not in key

    def test_address_hash_unit_stripped(self):
        row = {"ADDRESS": "200 Broad St # 14", "ZIP": "10004"}
        key = property_key(row)
        assert "#" not in key

    def test_whitespace_collapsed(self):
        row = {"ADDRESS": "  1450   Logistics   Pkwy  ", "ZIP": "75201"}
        key = property_key(row)
        assert "  " not in key

    def test_lowercase_field_names(self):
        row = {"property_id": "P-001", "address": "1 Main", "zip": "10001"}
        assert property_key(row) == "id::P-001"


# ---------------------------------------------------------------------------
# tenant_key / landlord_key / client_key
# ---------------------------------------------------------------------------

class TestSimpleKeys:
    def test_tenant_key_lowercased(self):
        row = {"TENANT_NAME": "  Acme Corp  "}
        assert tenant_key(row) == "name::acme corp"

    def test_landlord_key_from_landlord_name(self):
        row = {"LANDLORD_NAME": "Blackstone RE", "OWNER": "Should Not Use"}
        assert landlord_key(row) == "name::blackstone re"

    def test_landlord_key_falls_back_to_owner(self):
        row = {"OWNER": "Prologis", "LANDLORD_NAME": ""}
        assert landlord_key(row) == "name::prologis"

    def test_client_key_lowercased(self):
        row = {"CLIENT_NAME": "  WeWork  "}
        assert client_key(row) == "name::wework"


# ---------------------------------------------------------------------------
# lease_key
# ---------------------------------------------------------------------------

class TestLeaseKey:
    def test_lease_id_takes_priority(self):
        row = {"LEASE_ID": "L-001", "ADDRESS": "1 Main", "ZIP": "10001",
               "TENANT_NAME": "Acme", "EXECUTION_DATE": "2024-01-15"}
        assert lease_key(row) == "id::L-001"

    def test_fallback_hash_is_deterministic(self):
        row = {"ADDRESS": "1 Main St", "ZIP": "10001",
               "TENANT_NAME": "Acme Corp", "EXECUTION_DATE": "2024-01-15"}
        key1 = lease_key(row)
        key2 = lease_key(row)
        assert key1 == key2
        assert key1.startswith("hash::")

    def test_fallback_hash_differs_by_tenant(self):
        base = {"ADDRESS": "1 Main St", "ZIP": "10001", "EXECUTION_DATE": "2024-01-15"}
        row_a = {**base, "TENANT_NAME": "Acme Corp"}
        row_b = {**base, "TENANT_NAME": "Globex LLC"}
        assert lease_key(row_a) != lease_key(row_b)


# ---------------------------------------------------------------------------
# taxonomy_key
# ---------------------------------------------------------------------------

class TestTaxonomyKey:
    def test_known_alias_maps_to_canonical(self):
        assert taxonomy_key("DFW", "markets") == "dallas-fort worth"
        assert taxonomy_key("dallas/ft worth", "markets") == "dallas-fort worth"

    def test_canonical_form_maps_to_itself(self):
        assert taxonomy_key("dallas-fort worth", "markets") == "dallas-fort worth"

    def test_case_insensitive(self):
        assert taxonomy_key("INDUSTRIAL", "asset_classes") == "industrial"
        assert taxonomy_key("Office", "asset_classes") == "office"

    def test_unknown_value_returns_raw_lower(self):
        result = taxonomy_key("HyperspecialNiche2099", "markets")
        assert result == "hyperspecialniche2099"

    def test_tenant_rep_alias(self):
        assert taxonomy_key("Tenant Rep", "service_lines") == "tenantrep"
        assert taxonomy_key("TR", "service_lines") == "tenantrep"


# ---------------------------------------------------------------------------
# canonical_resolver
# ---------------------------------------------------------------------------

class TestCanonicalResolver:
    def test_market_resolves(self):
        result = canonical_resolver("DFW")
        assert result == ("Market", "dallas-fort worth")

    def test_asset_class_resolves(self):
        result = canonical_resolver("industrial")
        assert result == ("AssetClass", "industrial")

    def test_tenant_prefix(self):
        result = canonical_resolver("tenant:Acme Corp")
        assert result == ("Tenant", "name::acme corp")

    def test_property_prefix(self):
        result = canonical_resolver("property:P-9921")
        assert result == ("Property", "id::P-9921")

    def test_unknown_tag_returns_none(self):
        result = canonical_resolver("ZZZUnknownTag999")
        assert result is None

    def test_office_alias(self):
        result = canonical_resolver("Office")
        assert result == ("AssetClass", "office")
