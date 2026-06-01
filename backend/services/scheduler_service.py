from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.product_sync_worker import run_product_sync_batch

logger = logging.getLogger("ofertix.scheduler")

SYNC_HOURS = float(os.getenv("PRODUCT_SYNC_INTERVAL_HOURS", "12"))


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
        self._scheduler.start()
        logger.info("Scheduler started (product sync every %s hours)", SYNC_HOURS)

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped")


scheduler_service = SchedulerService()
