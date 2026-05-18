from fastapi import APIRouter, Query
from core.firebase import db

router = APIRouter()


@router.get("/products")
def get_products(
    country: str = "es",
    limit: int = Query(50, ge=1, le=100),
):
    docs = db.collection("products").limit(500).get()

    results = []

    for doc in docs:
        item = doc.to_dict()
        item["id"] = doc.id

        is_online = item.get("isOnline", True)
        product_country = str(item.get("country", "global")).lower()

        if is_online or product_country == country.lower():
            results.append(item)

        if len(results) >= limit:
            break

    return {
        "country": country,
        "count": len(results),
        "products": results,
    }