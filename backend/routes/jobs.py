from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException, status

from services.price_alert_checker_service import price_alert_checker_service

logger = logging.getLogger("ofertix.routes.jobs")

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

_JOB_SECRET_ENV = "JOB_SECRET"


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
