from pathlib import Path

from scripts.import_impact_catalog import (
    build_impact_product,
    import_catalog_files,
    inspect_catalog_file,
    normalize_price,
    stable_impact_doc_id,
)
from services.public_product_service import is_usable_public_product, prepare_public_product


def _row(**overrides):
    row = {
        "Sku": "ABC-123",
        "Program Id": "12108",
        "Program Names": "DHgate",
        "Name": "Wireless charging station with stand",
        "Description": "Phone charging accessory",
        "Url": "https://impact.example/c/1?u=https%3A%2F%2Fstore.example%2Fp%2Fabc",
        "Original Url": "",
        "Image Url": "https://cdn.example/product.jpg",
        "Additional ImageUrls": "https://cdn.example/product-2.jpg|bad",
        "Current Price": "1,234.56",
        "Original Price": "1,499.00",
        "Discount Percentage": "",
        "Currency": "USD",
        "Category Name": "Phone accessories",
        "Category Path": "electronics > phone accessories",
        "Stock Availability": "InStock",
        "Last Updated": "Thu Jun 25 03:04:14 UTC 2026",
    }
    row.update(overrides)
    return row


def test_price_normalization_handles_comma_and_dot_decimals():
    assert normalize_price("1,234.56") == 1234.56
    assert normalize_price("1.234,56") == 1234.56
    assert normalize_price("48,33") == 48.33
    assert normalize_price("$48.33") == 48.33
    assert normalize_price("not a price") is None


def test_deterministic_id_prefers_program_and_sku():
    assert stable_impact_doc_id("12108", "ABC-123") == "impact_12108_ABC-123"
    assert stable_impact_doc_id("12108", "ABC-123") == stable_impact_doc_id("12108", "ABC-123")
    assert stable_impact_doc_id("37610", "ABC-123") != stable_impact_doc_id("12108", "ABC-123")


def test_build_impact_product_maps_affiliate_catalog_fields():
    doc_id, product, reason = build_impact_product(_row())

    assert reason is None
    assert doc_id == "impact_12108_ABC-123"
    assert product["name"] == "Wireless charging station with stand"
    assert product["affiliateUrl"].startswith("https://impact.example/")
    assert product["productUrl"] == "https://store.example/p/abc"
    assert product["image"] == "https://cdn.example/product.jpg"
    assert product["images"] == [
        "https://cdn.example/product.jpg",
        "https://cdn.example/product-2.jpg",
    ]
    assert product["newPrice"] == 1234.56
    assert product["oldPrice"] == 1499.0
    assert product["discount"] == 18
    assert product["currency"] == "USD"
    assert product["source"] == "impact"
    assert product["listingType"] == "affiliate_product"
    assert product["contactSellerEnabled"] is False


def test_invalid_rows_are_skipped_with_reasons():
    assert build_impact_product(_row(Name=""))[2] == "missing_name"
    assert build_impact_product(_row(Url="not-a-url"))[2] == "missing_or_invalid_url"
    assert build_impact_product(_row(**{"Current Price": ""}))[2] == "missing_or_invalid_current_price"
    assert build_impact_product(_row(**{"Stock Availability": "OutOfStock"}))[2] == "out_of_stock"


def test_catalog_inspection_counts_rows_and_detects_tsv(tmp_path: Path):
    feed = tmp_path / "impact.tsv"
    feed.write_text(
        "Sku\tProgram Id\tProgram Names\tName\tUrl\tImage Url\tCurrent Price\tCurrency\n"
        "A\t1\tStore\tProduct A\thttps://example/a\thttps://example/a.jpg\t10.00\tEUR\n"
        "B\t1\tStore\tProduct B\thttps://example/b\thttps://example/b.jpg\t20.00\tEUR\n",
        encoding="utf-8",
    )

    inspection = inspect_catalog_file(feed)

    assert inspection.format == "TSV"
    assert inspection.delimiter == "TAB"
    assert inspection.row_count == 2
    assert inspection.first_valid_row["Sku"] == "A"
    assert inspection.last_valid_row["Sku"] == "B"


def test_dry_run_import_deduplicates_and_batches(tmp_path: Path):
    feed = tmp_path / "impact.tsv"
    headers = list(_row().keys())
    row = _row()
    feed.write_text(
        "\t".join(headers)
        + "\n"
        + "\t".join(row[key] for key in headers)
        + "\n"
        + "\t".join(row[key] for key in headers)
        + "\n",
        encoding="utf-8",
    )

    result = import_catalog_files([feed], apply=False, limit=None, batch_size=1)
    stats = result["stats"]

    assert stats["scanned"] == 2
    assert stats["upserted"] == 1
    assert stats["duplicates_in_run"] == 1
    assert stats["skip_reasons"]["duplicate_in_input"] == 1


def test_imported_affiliate_product_is_public_but_not_seller_listing():
    _, product, _ = build_impact_product(_row())
    prepared = prepare_public_product(product, "es")

    assert is_usable_public_product(prepared, "es") is True
    assert prepared["isAffiliateProduct"] is True
    assert prepared["listingType"] == "affiliate_product"
    assert prepared["contactSellerEnabled"] is False
    assert prepared.get("sellerId") is None
