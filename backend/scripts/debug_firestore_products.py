from collections import Counter
from core.firebase import db

collections = ["products", "Products", "deals", "offers", "user_deals"]

for col in collections:
    try:
        docs = db.collection(col).limit(20).get()
        print("\nCOLLECTION:", col)
        print("FOUND:", len(docs))

        statuses = Counter()
        countries = Counter()

        for d in docs:
            item = d.to_dict() or {}
            statuses[str(item.get("status", "MISSING"))] += 1
            countries[str(item.get("countryCode") or item.get("country") or item.get("availableCountries") or "MISSING")] += 1

        print("STATUSES:", dict(statuses))
        print("COUNTRIES:", dict(countries))

        if docs:
            first = docs[0].to_dict() or {}
            print("FIRST DOC ID:", docs[0].id)
            print("FIRST KEYS:", sorted(first.keys()))
            print("FIRST SAMPLE:", {
                "name": first.get("name") or first.get("title"),
                "status": first.get("status"),
                "countryCode": first.get("countryCode"),
                "country": first.get("country"),
                "availableCountries": first.get("availableCountries"),
                "price": first.get("price") or first.get("newPrice"),
                "image": first.get("imageUrl") or first.get("image"),
            })
    except Exception as e:
        print("\nCOLLECTION:", col, "ERROR:", e)
