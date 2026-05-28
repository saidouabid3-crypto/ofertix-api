from core.firebase import db

def is_valid_product(p):
    name = p.get("name") or p.get("title")
    image = p.get("imageUrl") or p.get("image")
    price = p.get("newPrice") or p.get("price")
    link = p.get("affiliateUrl") or p.get("productUrl") or p.get("url")
    return bool(name and image and price and link)

def main():
    docs = db.collection("products").limit(500).get()

    fixed = 0
    skipped = 0

    for d in docs:
        p = d.to_dict() or {}

        country = (p.get("countryCode") or p.get("country") or "").lower()
        source = str(p.get("source") or p.get("store") or p.get("affiliateUrl") or "").lower()

        # Safe rule:
        # - if already marked Spain -> activate
        # - if AliExpress product without country -> allow Spain because Ofertix Spain can show online products
        should_be_es = country == "es" or "aliexpress" in source or "ali" in source

        if not should_be_es or not is_valid_product(p):
            skipped += 1
            continue

        update = {
            "status": "active",
            "country": "es",
            "countryCode": "es",
            "availableCountries": ["es"],
            "shipsTo": ["es"],
            "currency": "EUR",
            "isOnline": True,
        }

        db.collection("products").document(d.id).set(update, merge=True)
        fixed += 1

    print({"fixed": fixed, "skipped": skipped})

if __name__ == "__main__":
    main()
