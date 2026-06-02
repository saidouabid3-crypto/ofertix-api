from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.product_sync_worker import run_product_sync_batch

logger = logging.getLogger("ofertix.scheduler")

SYNC_HOURS = float(os.getenv("PRODUCT_SYNC_INTERVAL_HOURS", "12"))
ALERT_CHECK_HOURS = float(os.getenv("PRICE_ALERT_CHECK_INTERVAL_HOURS", "4"))
_ALERT_SCHEDULER_ENABLED = (
    os.getenv("ENABLE_PRICE_ALERT_SCHEDULER", "false").strip().lower()
    in {"1", "true", "yes", "on"}
)


class SchedulerService:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    def start(self) -> None:
        if self._scheduler is not None:
            return

        self._scheduler = AsyncIOScheduler(timezone="UTC")

        self._scheduler.add_job(
            run_product_sync_batch,
            trigger=IntervalTrigger(hours=SYNC_HOURS),
            id="product_sync_worker",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduler: product sync every %s hours", SYNC_HOURS)

        if _ALERT_SCHEDULER_ENABLED:
            from services.price_alert_checker_service import (
                price_alert_checker_service,
            )

            self._scheduler.add_job(
                price_alert_checker_service.run,
                trigger=IntervalTrigger(hours=ALERT_CHECK_HOURS),
                id="price_alert_checker",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                "Scheduler: price alert checker every %s hours", ALERT_CHECK_HOURS
            )
        else:
            logger.info(
                "Scheduler: price alert checker disabled "
                "(set ENABLE_PRICE_ALERT_SCHEDULER=true to enable)"
            )

        self._scheduler.start()
        logger.info("Scheduler started")

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped")


scheduler_service = SchedulerService()
