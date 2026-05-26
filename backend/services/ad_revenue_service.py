from datetime import datetime, timezone
from typing import Any, Dict

from core.firebase import db

DEFAULT_RPM = {
    "home_banner_top": 1.50,
    "marketplace_sponsored_top": 1.80,
    "product_detail_native": 2.20,
    "coupons_sponsored": 1.70,
    "feed_native": 2.50,
}


class AdRevenueService:
    def track_event(self, slot: str, event_type: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        db.collection("ad_events").document().set({
            "slot": slot,
            "type": event_type,
            "createdAt": now,
            "day": now.strftime("%Y-%m-%d"),
        })
        return {"ok": True, "slot": slot, "type": event_type}

    def estimate(self, slot: str, impressions: int, rpm: float | None = None, clicks: int = 0) -> Dict[str, Any]:
        final_rpm = float(rpm if rpm is not None else DEFAULT_RPM.get(slot, 1.50))
        revenue = (max(impressions, 0) / 1000) * final_rpm
        ctr = (clicks / impressions * 100) if impressions > 0 else 0
        return {
            "slot": slot,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": round(ctr, 2),
            "rpm": final_rpm,
            "estimatedRevenue": round(revenue, 2),
            "currency": "EUR",
        }
