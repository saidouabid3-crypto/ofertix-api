from __future__ import annotations

import os

os.environ.setdefault("FIREBASE_REQUIRED", "false")

from scripts.hide_dhgate_products import (
    HIDDEN_REASON,
    hide_update,
    is_already_hidden,
    is_dhgate_product,
    scan_and_hide,
)
from services.public_product_service import is_usable_public_product, prepare_public_product


class _FakeDoc:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = dict(data)
        self.reference = f"products/{doc_id}"

    def to_dict(self):
        return dict(self._data)


class _FakeBatch:
    def __init__(self):
        self.updates = []
        self.commits = 0

    def update(self, ref, data):
        self.updates.append((ref, data))

    def commit(self):
        self.commits += 1


def _product(**overrides):
    data = {
        "name": "Wireless headphones",
        "store": "Example Store",
        "source": "impact",
        "sourceType": "affiliate_product",
        "listingType": "affiliate_product",
        "image": "https://example.com/p.jpg",
        "newPrice": 19.99,
        "currency": "EUR",
        "status": "active",
        "visibleToUsers": True,
        "countryCode": "global",
        "country": "global",
        "availableCountries": ["es"],
        "shipsTo": ["es"],
        "affiliateUrl": "https://example.com/offer",
    }
    data.update(overrides)
    return data


def test_dhgate_matching_uses_store_program_metadata_url_and_doc_id():
    assert is_dhgate_product(_product(store="DHgate")).matched
    assert is_dhgate_product(_product(programName="DHgate Global")).matched
    assert is_dhgate_product(_product(productUrl="https://www.dhgate.com/product/abc")).matched
    assert is_dhgate_product(
        _product(programId="12108"),
        doc_id="impact_12108_SKU-1",
        dhgate_program_ids={"12108"},
    ).matched


def test_non_dhgate_affiliate_product_is_preserved():
    product = _product(store="PcComponentes", programName="PcComponentes", programId="999")
    result = is_dhgate_product(
        product,
        doc_id="impact_999_SKU-1",
        dhgate_program_ids={"12108"},
    )
    assert result.matched is False


def test_hidden_dhgate_product_is_excluded_from_app_feed():
    data = _product(store="DHgate")
    data.update(hide_update(data))

    prepared = prepare_public_product(data, "es")
    assert is_usable_public_product(prepared, "es") is False
    assert prepared["visibleToUsers"] is False
    assert prepared["status"] == "hidden"
    assert prepared["hiddenReason"] == HIDDEN_REASON


def test_script_dry_run_does_not_write():
    docs = [
        _FakeDoc("impact_12108_A", _product(store="DHgate", programId="12108")),
        _FakeDoc("impact_999_B", _product(store="Other", programId="999")),
    ]
    batch = _FakeBatch()

    report = scan_and_hide(
        docs,
        apply=False,
        batch_factory=lambda: batch,
        dhgate_program_ids={"12108"},
    )

    assert report["totalProductsScanned"] == 2
    assert report["dhgateProductsMatched"] == 1
    assert report["productsThatWillBeHidden"] == 1
    assert report["productsHidden"] == 0
    assert batch.updates == []
    assert batch.commits == 0


def test_apply_is_idempotent_for_already_hidden_dhgate_products():
    hidden = _product(store="DHgate", programId="12108")
    hidden.update(
        {
            "active": False,
            "visibleToUsers": False,
            "status": "hidden",
            "hiddenReason": HIDDEN_REASON,
        }
    )
    docs = [_FakeDoc("impact_12108_A", hidden)]
    batch = _FakeBatch()

    report = scan_and_hide(
        docs,
        apply=True,
        batch_factory=lambda: batch,
        dhgate_program_ids={"12108"},
    )

    assert is_already_hidden(hidden) is True
    assert report["dhgateProductsMatched"] == 1
    assert report["alreadyHidden"] == 1
    assert report["productsHidden"] == 0
    assert report["writesAttempted"] == 0
    assert batch.updates == []
    assert batch.commits == 0
