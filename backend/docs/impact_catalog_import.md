# Impact Catalog Import

Impact catalog rows are imported into the existing public product collection:

- Firestore collection: `products`
- Public list route: `GET /products`
- Search route: `POST /api/products/search`
- Home feed route: `GET /home-feed`

Affiliate catalog products are not marketplace seller listings. Imported rows set
`source=impact`, `sourceType=affiliate_product`, `listingType=affiliate_product`,
`isAffiliateProduct=true`, and `contactSellerEnabled=false`.

## Inspect

```bash
cd backend
python scripts/import_impact_catalog.py --inspect-only
```

The script discovers `backend/data/impact_dhgate.txt` and catalog files in
`backend/data/impact_feeds/`. It reports file size, encoding, delimiter, headers,
row count, and first/last valid rows.

## Dry Run

```bash
cd backend
python scripts/import_impact_catalog.py --dry-run
```

Dry-run parses and validates rows without writing Firestore. A JSON report is
written under `backend/data/import_reports/`.

## Apply

Configure Firebase Admin credentials with one of:

- `FIREBASE_CREDENTIALS`
- `FIREBASE_CREDENTIALS_JSON`
- `FIREBASE_KEY_PATH`

Then run:

```bash
cd backend
python scripts/import_impact_catalog.py --apply
```

The importer writes batches below Firestore limits, upserts by deterministic
document ID, and stores a checkpoint in `backend/data/import_checkpoints/`.
Use `--resume` to continue from the checkpoint after an interruption.

## Mapping

- `Sku` + `Program Id` -> deterministic Firestore document ID
- `Name` -> `fullTitle` and display `name`
- `Url` -> `affiliateUrl`
- `Original Url` or decoded `Url.u` -> `productUrl`
- `Image Url` plus `Additional ImageUrls` -> `image`, `mainImage`, `images`
- `Current Price` -> `newPrice`
- valid `Original Price` -> `oldPrice`
- valid or derived `Discount Percentage` -> `discount`
- `Currency` -> `currency`
- `Program Names` -> `store`
- category fields -> source category fields plus Ofertix category/categoryGroup
- `Stock Availability` -> `stockAvailability` and `availabilityStatus`
- `Last Updated` -> `lastUpdatedFromFeed`

Rows missing a stable ID, title, valid affiliate URL, image, current price,
currency, or available stock are skipped and counted by reason.
