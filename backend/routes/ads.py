from typing import Optional

from fastapi import APIRouter, Query

from services.ad_revenue_service import AdRevenueService

router = APIRouter(prefix="/ads", tags=["ads"])
service = AdRevenueService()


@router.post("/impression")
def track_impression(payload: dict):
    return service.track_event(payload.get("slot", "unknown"), "impression")


@router.post("/click")
def track_click(payload: dict):
    return service.track_event(payload.get("slot", "unknown"), "click")


@router.get("/revenue/estimate")
def estimate_revenue(
    slot: str = "home_banner_top",
    impressions: int = Query(default=10000, ge=0),
    rpm: Optional[float] = None,
    clicks: int = Query(default=0, ge=0),
):
    return service.estimate(slot=slot, impressions=impressions, rpm=rpm, clicks=clicks)
