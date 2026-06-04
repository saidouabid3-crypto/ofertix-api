from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status

from services.price_alert_checker_service import price_alert_checker_service

logger = logging.getLogger("ofertix.routes.jobs")

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

_JOB_SECRET_ENV = "JOB_SECRET"

# Render Cron setup:
# - Env var required on Render: JOB_SECRET=<strong-random-secret>
# - Method/URL: POST https://ofertix-api.onrender.com/api/jobs/check-price-alerts
# - Header: X-Job-Secret: <JOB_SECRET>
# - Recommended schedule before launch: every 6 hours.


def _verify_secret(provided: str | None) -> None:
    """Reject the request if JOB_SECRET is not configured or does not match."""
    expected = os.getenv(_JOB_SECRET_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "JOB_SECRET not configured",
                "hint": (
                    "Set JOB_SECRET in Render environment variables to enable "
                    "job endpoints. Example: JOB_SECRET=<strong-random-secret>"
                ),
            },
        )
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Job-Secret header.",
        )


@router.post("/check-price-alerts")
async def check_price_alerts(
    x_job_secret: str | None = Header(default=None, alias="X-Job-Secret"),
) -> dict:
    """
    Manually triggers the price alert checker.

    Protected: requires X-Job-Secret header matching the JOB_SECRET env var.

    Designed to be called by:
    - Render Cron Jobs (scheduled external HTTP trigger)
    - Admin scripts
    - Manual curl for testing

    Example:
        curl -X POST https://your-api.onrender.com/api/jobs/check-price-alerts \\
             -H "X-Job-Secret: your-secret"

    Response: {checked, triggered, skipped, errors}
    """
    _verify_secret(x_job_secret)
    logger.info("Manual price alert check triggered via API")
    try:
        result = await price_alert_checker_service.run()
        return result
    except Exception as exc:
        logger.exception("Price alert check job failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def _run_backfill(limit: int) -> dict[str, Any]:
    """Synchronous backfill runner — called in a thread from the async handler."""
    from core.firebase import db
    from services.price_history_collector_service import price_history_collector_service

    try:
        docs = list(db.collection("products").limit(limit).stream())
    except Exception as exc:
        return {"error": str(exc), "checked": 0, "recorded": 0, "skipped": 0, "errors": 1}

    checked = recorded = skipped = errors = 0
    for doc in docs:
        checked += 1
        try:
            result = price_history_collector_service.record(
                product_id=doc.id,
                data=doc.to_dict() or {},
                reason="job_backfill",
            )
            if result["recorded"]:
                recorded += 1
            else:
                skipped += 1
        except Exception as exc:
            errors += 1
            logger.warning("Backfill error for %s: %s", doc.id, exc)

    return {"checked": checked, "recorded": recorded, "skipped": skipped, "errors": errors}


@router.post("/backfill-price-history")
async def backfill_price_history(
    limit: int = 200,
    x_job_secret: str | None = Header(default=None, alias="X-Job-Secret"),
) -> dict:
    """
    Backfill one price_history point per product with a valid price.

    Safe to re-run — dedupe prevents duplicate writes for the same product/price/day.
    Protected: requires X-Job-Secret header matching JOB_SECRET env var.

    Query params:
        limit: max products to process (default 200, max 1000)

    Example:
        curl -X POST https://your-api.onrender.com/api/jobs/backfill-price-history?limit=200 \\
             -H "X-Job-Secret: your-secret"

    Response: {checked, recorded, skipped, errors}
    """
    _verify_secret(x_job_secret)
    safe_limit = max(1, min(limit, 1000))
    logger.info("Backfill price history triggered via API (limit=%d)", safe_limit)
    try:
        result = await asyncio.to_thread(_run_backfill, safe_limit)
        return result
    except Exception as exc:
        logger.exception("Backfill price history job failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
