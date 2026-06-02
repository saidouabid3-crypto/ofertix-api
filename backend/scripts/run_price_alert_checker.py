"""
Local/manual runner for the price alert checker.

Usage:
    cd backend
    python scripts/run_price_alert_checker.py

Requires Firebase credentials to be configured (FIREBASE_CREDENTIALS_JSON
or FIREBASE_KEY_PATH env var, or firebase_key.json in the backend directory).
No secrets are printed.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Allow imports from backend root regardless of where the script is run from.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_price_alert_checker")


async def main() -> None:
    from services.price_alert_checker_service import price_alert_checker_service

    logger.info("Starting price alert checker run...")
    result = await price_alert_checker_service.run()
    print("\n=== Price Alert Checker Result ===")
    print(f"  Checked  : {result['checked']}")
    print(f"  Triggered: {result['triggered']}")
    print(f"  Skipped  : {result['skipped']}")
    print(f"  Errors   : {result['errors']}")
    print("==================================\n")


if __name__ == "__main__":
    asyncio.run(main())
