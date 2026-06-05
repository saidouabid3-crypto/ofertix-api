from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth import optional_user, require_active_user, require_admin, require_user

router = APIRouter(tags=["ofertix-local"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * radius * asin(sqrt(a))


class LocalStorePayload(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1)
    description: str = ""
    logo: str = ""
    cover_image: str = ""
    category: str = "general"
    address: str = ""
    city: str = ""
    country_code: str = "es"
    latitude: float = 0
    longitude: float = 0
    phone: str = ""
    whatsapp: str = ""
    website: str = ""
    merchant_id: str = ""
    verified: bool = False
    featured: bool = False
    active: bool = True
    opening_hours: Dict[str, str] = Field(default_factory=dict)


class LocalOfferPayload(BaseModel):
    id: Optional[str] = None
    store_id: str = ""
    store_name: str = ""
    title: str = Field(min_length=1)
    description: str = ""
    image: str = ""
    category: str = "general"
    old_price: float = 0
    new_price: float = Field(ge=0)
    currency: str = "EUR"
    discount_percent: int = 0
    city: str = ""
    country_code: str = "es"
    latitude: float = 0
    longitude: float = 0
    whatsapp: str = ""
    status: str = "pending"
    source: str = "merchant"
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None


class _LocalRepository:
    def __init__(self) -> None:
        self._db = self._load_firestore()
        self._stores: Dict[str, Dict[str, Any]] = {}
        self._offers: Dict[str, Dict[str, Any]] = {}

    def _load_firestore(self):
        try:
            import firebase_admin
            from firebase_admin import firestore
            if not firebase_admin._apps:
                return None
            return firestore.client()
        except Exception:
            return None

    def _collection(self, name: str):
        if self._db is None:
            return None
        return self._db.collection(name)

    def list_stores(
        self,
        *,
        country: str = "es",
        city: Optional[str] = None,
        featured: Optional[bool] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        collection = self._collection("local_stores")
        if collection is not None:
            query = collection.where("country_code", "==", country.lower()).where("active", "==", True)
            if city:
                query = query.where("city", "==", city)
            if featured is not None:
                query = query.where("featured", "==", featured)
            docs = query.limit(limit).stream()
            return [self._with_id(doc.id, doc.to_dict()) for doc in docs]
        values = [
            s for s in self._stores.values()
            if s.get("active", True) and s.get("country_code", "es") == country.lower()
        ]
        if city:
            values = [s for s in values if s.get("city") == city]
        if featured is not None:
            values = [s for s in values if bool(s.get("featured")) == featured]
        return values[:limit]

    def nearby_stores(
        self,
        *,
        lat: float,
        lng: float,
        radius_km: float,
        category: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        stores = self.list_stores(limit=500)
        ranked: List[Dict[str, Any]] = []
        for store in stores:
            store_lat = float(store.get("latitude") or 0)
            store_lng = float(store.get("longitude") or 0)
            if not store_lat or not store_lng:
                continue
            if category and store.get("category") != category:
                continue
            distance = _distance_km(lat, lng, store_lat, store_lng)
            if distance <= radius_km:
                ranked.append({**store, "distance_km": round(distance, 2)})
        ranked.sort(key=lambda item: item["distance_km"])
        return ranked[:limit]

    def get_store(self, store_id: str) -> Dict[str, Any]:
        collection = self._collection("local_stores")
        if collection is not None:
            doc = collection.document(store_id).get()
            if not doc.exists:
                raise HTTPException(status_code=404, detail="Store not found")
            return self._with_id(doc.id, doc.to_dict())
        if store_id not in self._stores:
            raise HTTPException(status_code=404, detail="Store not found")
        return self._stores[store_id]

    def save_store(self, payload: LocalStorePayload, merchant_id: str) -> Dict[str, Any]:
        store_id = payload.id or f"store_{uuid4().hex[:16]}"
        data = payload.model_dump(exclude={"id"})
        data.update({
            "id": store_id,
            "merchant_id": merchant_id or data.get("merchant_id") or "anonymous",
            "country_code": data.get("country_code", "es").lower(),
            "views": 0,
            "offer_count": 0,
            "created_at": _now(),
            "updated_at": _now(),
        })
        collection = self._collection("local_stores")
        if collection is not None:
            collection.document(store_id).set(data, merge=True)
        self._stores[store_id] = data
        return data

    def list_offers(
        self,
        *,
        status: Optional[str] = "active",
        country: str = "es",
        city: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        collection = self._collection("local_offers")
        if collection is not None:
            query = collection.where("country_code", "==", country.lower())
            if status:
                query = query.where("status", "==", status)
            if city:
                query = query.where("city", "==", city)
            docs = query.limit(limit).stream()
            return [self._with_id(doc.id, doc.to_dict()) for doc in docs]
        values = [o for o in self._offers.values() if o.get("country_code", "es") == country.lower()]
        if status:
            values = [o for o in values if o.get("status") == status]
        if city:
            values = [o for o in values if o.get("city") == city]
        return values[:limit]

    def nearby_offers(
        self,
        *,
        lat: float,
        lng: float,
        radius_km: float,
        category: Optional[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        offers = self.list_offers(limit=500)
        ranked: List[Dict[str, Any]] = []
        for offer in offers:
            offer_lat = float(offer.get("latitude") or 0)
            offer_lng = float(offer.get("longitude") or 0)
            if not offer_lat or not offer_lng:
                continue
            if category and offer.get("category") != category:
                continue
            distance = _distance_km(lat, lng, offer_lat, offer_lng)
            if distance <= radius_km:
                ranked.append({**offer, "distance_km": round(distance, 2)})
        ranked.sort(key=lambda item: item["distance_km"])
        return ranked[:limit]

    def store_offers(self, store_id: str) -> List[Dict[str, Any]]:
        collection = self._collection("local_offers")
        if collection is not None:
            docs = (
                collection
                .where("store_id", "==", store_id)
                .where("status", "==", "active")
                .limit(100)
                .stream()
            )
            return [self._with_id(doc.id, doc.to_dict()) for doc in docs]
        return [
            o for o in self._offers.values()
            if o.get("store_id") == store_id and o.get("status") == "active"
        ]

    def save_offer(self, payload: LocalOfferPayload, merchant_id: str) -> Dict[str, Any]:
        offer_id = payload.id or f"offer_{uuid4().hex[:16]}"
        data = payload.model_dump(exclude={"id"})
        if data["discount_percent"] <= 0 and data["old_price"] > data["new_price"] > 0:
            data["discount_percent"] = round(
                ((data["old_price"] - data["new_price"]) / data["old_price"]) * 100
            )
        data.update({
            "id": offer_id,
            "merchant_id": merchant_id or "anonymous",
            "country_code": data.get("country_code", "es").lower(),
            "risk_level": self._risk_level(data),
            "risk_score": self._risk_score(data),
            "views": 0,
            "clicks": 0,
            "created_at": _now(),
            "updated_at": _now(),
        })
        collection = self._collection("local_offers")
        if collection is not None:
            collection.document(offer_id).set(data, merge=True)
        self._offers[offer_id] = data
        return data

    def update_offer_status(self, offer_id: str, status: str, reason: str = "") -> Dict[str, Any]:
        collection = self._collection("local_offers")
        patch = {
            "status": status,
            "review_reason": reason,
            "reviewed_at": _now(),
            "updated_at": _now(),
        }
        if collection is not None:
            doc = collection.document(offer_id).get()
            if not doc.exists:
                raise HTTPException(status_code=404, detail="Offer not found")
            collection.document(offer_id).set(patch, merge=True)
            return self._with_id(offer_id, {**doc.to_dict(), **patch})
        if offer_id not in self._offers:
            raise HTTPException(status_code=404, detail="Offer not found")
        self._offers[offer_id].update(patch)
        return self._offers[offer_id]

    def click_offer(self, offer_id: str) -> Dict[str, Any]:
        collection = self._collection("local_offers")
        if collection is not None:
            doc_ref = collection.document(offer_id)
            doc = doc_ref.get()
            if not doc.exists:
                raise HTTPException(status_code=404, detail="Offer not found")
            data = self._with_id(offer_id, doc.to_dict())
            data["clicks"] = int(data.get("clicks") or 0) + 1
            doc_ref.set({"clicks": data["clicks"], "updated_at": _now()}, merge=True)
            return data
        if offer_id not in self._offers:
            raise HTTPException(status_code=404, detail="Offer not found")
        self._offers[offer_id]["clicks"] = int(self._offers[offer_id].get("clicks") or 0) + 1
        return self._offers[offer_id]

    def _risk_score(self, data: Dict[str, Any]) -> int:
        score = 0
        if not data.get("image"):
            score += 15
        if not data.get("store_name"):
            score += 20
        if float(data.get("new_price") or 0) <= 0:
            score += 30
        if int(data.get("discount_percent") or 0) >= 70:
            score += 20
        if not data.get("latitude") or not data.get("longitude"):
            score += 10
        return min(score, 100)

    def _risk_level(self, data: Dict[str, Any]) -> str:
        score = self._risk_score(data)
        if score >= 60:
            return "RED"
        if score >= 30:
            return "YELLOW"
        return "GREEN"

    def _with_id(self, doc_id: str, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(data or {})
        payload.setdefault("id", doc_id)
        return payload


repo = _LocalRepository()


def _uid_from_user(current_user: dict | None) -> str:
    if current_user and current_user.get("uid"):
        return current_user["uid"]
    return "anonymous"


def _required_uid(current_user: dict) -> str:
    uid = str(current_user.get("uid") or "").strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return uid


# ---------------------------------------------------------------------------
# Public store endpoints
# ---------------------------------------------------------------------------

@router.get("/api/local/stores")
async def list_local_stores(
    country: str = "es",
    city: Optional[str] = None,
    featured: Optional[bool] = None,
    limit: int = Query(30, ge=1, le=100),
):
    items = await asyncio.to_thread(
        repo.list_stores, country=country, city=city, featured=featured, limit=limit
    )
    return {"items": items}


@router.get("/api/local/stores/nearby")
async def nearby_local_stores(
    lat: float,
    lng: float,
    radiusKm: float = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
):
    items = await asyncio.to_thread(
        repo.nearby_stores, lat=lat, lng=lng, radius_km=radiusKm, category=category, limit=limit
    )
    return {"items": items}


@router.get("/api/local/stores/{store_id}")
async def get_local_store(store_id: str):
    store = await asyncio.to_thread(repo.get_store, store_id)
    return {"store": store}


@router.get("/api/local/stores/{store_id}/offers")
async def get_local_store_offers(store_id: str):
    items = await asyncio.to_thread(repo.store_offers, store_id)
    return {"items": items}


@router.get("/api/local/offers/nearby")
async def nearby_local_offers(
    lat: float,
    lng: float,
    radiusKm: float = Query(10, ge=1, le=100),
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
):
    items = await asyncio.to_thread(
        repo.nearby_offers, lat=lat, lng=lng, radius_km=radiusKm, category=category, limit=limit
    )
    return {"items": items}


@router.get("/api/local/offers/hot")
async def hot_local_offers(
    country: str = "es",
    city: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
):
    items = await asyncio.to_thread(
        repo.list_offers, status="active", country=country, city=city, limit=limit
    )
    items.sort(
        key=lambda item: (int(item.get("clicks") or 0), int(item.get("discount_percent") or 0)),
        reverse=True,
    )
    return {"items": items[:limit]}


@router.post("/api/local/offers/{offer_id}/click")
async def click_local_offer(offer_id: str):
    offer = await asyncio.to_thread(repo.click_offer, offer_id)
    return {"offer": offer}


# ---------------------------------------------------------------------------
# Merchant endpoints — identity verified from Firebase JWT
# ---------------------------------------------------------------------------

@router.get("/api/merchant/stores")
async def merchant_stores(current_user: dict | None = Depends(optional_user)):
    merchant = _uid_from_user(current_user)
    all_stores = await asyncio.to_thread(repo.list_stores, limit=100)
    return {"items": [s for s in all_stores if s.get("merchant_id") == merchant]}


@router.post("/api/merchant/stores")
async def create_merchant_store(
    payload: LocalStorePayload,
    current_user: dict = Depends(require_active_user),
):
    merchant = _required_uid(current_user)
    store = await asyncio.to_thread(repo.save_store, payload, merchant)
    return {"store": store}


@router.get("/api/merchant/offers")
async def merchant_offers(current_user: dict | None = Depends(optional_user)):
    merchant = _uid_from_user(current_user)
    all_offers = await asyncio.to_thread(repo.list_offers, status=None, limit=100)
    return {"items": [o for o in all_offers if o.get("merchant_id") == merchant]}


@router.post("/api/merchant/offers")
async def create_merchant_offer(
    payload: LocalOfferPayload,
    current_user: dict = Depends(require_active_user),
):
    payload.status = "pending"
    merchant = _required_uid(current_user)
    offer = await asyncio.to_thread(repo.save_offer, payload, merchant)
    return {"offer": offer}


# ---------------------------------------------------------------------------
# Admin endpoints — require verified admin role
# ---------------------------------------------------------------------------

@router.get("/api/admin/local/offers/pending")
async def admin_pending_local_offers(
    limit: int = Query(50, ge=1, le=100),
    _: dict = Depends(require_admin),
):
    items = await asyncio.to_thread(repo.list_offers, status="pending", limit=limit)
    return {"items": items}


@router.post("/api/admin/local/offers/{offer_id}/approve")
async def admin_approve_local_offer(
    offer_id: str,
    _: dict = Depends(require_admin),
):
    offer = await asyncio.to_thread(repo.update_offer_status, offer_id, "active")
    return {"offer": offer}


@router.post("/api/admin/local/offers/{offer_id}/reject")
async def admin_reject_local_offer(
    offer_id: str,
    payload: Dict[str, Any] | None = None,
    _: dict = Depends(require_admin),
):
    reason = str((payload or {}).get("reason") or "Rejected by admin")
    offer = await asyncio.to_thread(repo.update_offer_status, offer_id, "rejected", reason)
    return {"offer": offer}
