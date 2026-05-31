from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from contextlib import asynccontextmanager
from typing import Iterable

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.middleware import LocaleMiddleware

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("ofertix")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ofertix API starting")
    yield
    logger.info("Ofertix API stopping")


app = FastAPI(
    title=os.getenv("API_TITLE", "Ofertix API"),
    version=os.getenv("API_VERSION", "7.1.0"),
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or ["*"]


def _cors_allow_credentials(origins: list[str]) -> bool:
    raw = os.getenv("CORS_ALLOW_CREDENTIALS")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    # Browsers reject credentials with wildcard origins.
    # This keeps wildcard CORS useful for dev/mobile while avoiding invalid CORS.
    return "*" not in origins


origins = _cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=_cors_allow_credentials(origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Bind normalized request-scoped locale:
# X-App-Locale / Accept-Language / X-App-Country / X-App-Currency
# باش AI والـ backend يرجعو النصوص بنفس لغة التطبيق.
app.add_middleware(LocaleMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "safeMessage": "The Ofertix API is temporarily unavailable.",
            "path": request.url.path,
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ofertix-api",
        "version": os.getenv("API_VERSION", "7.1.0"),
    }


ROUTER_MODULES: tuple[str, ...] = (
    "routes.products",
    "routes.scan",
    "routes.ai_search",
    "routes.home_feed",
    "routes.i18n",
    "routes.market",
    "routes.marketplace",
    "routes.ads",
    "routes.ai_brain",
    "routes.community",
    "routes.coupons",
    "routes.geo_alerts",
    "routes.messages",
    "routes.mystery_box",
    "routes.profiles",
    "routes.smart_reels",
    "routes.user_deals",
    "routes.admin",
    "routes.intelligence",
    "routes.setup",
    "routes.ai_deal_brain",

    # Ofertix Local Engine:
    # /api/local/stores
    # /api/local/stores/nearby
    # /api/local/offers/nearby
    # /api/merchant/stores
    # /api/merchant/offers
    # /api/admin/local/offers/pending
    "routes.local_engine",
)


def include_project_routers(app: FastAPI, module_paths: Iterable[str]) -> None:
    strict = os.getenv("STRICT_ROUTE_IMPORTS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    for module_path in module_paths:
        if importlib.util.find_spec(module_path) is None:
            message = f"Router module not found and skipped: {module_path}"
            if strict:
                raise ModuleNotFoundError(message)

            logger.warning(message)
            continue

        try:
            module = importlib.import_module(module_path)
            router = getattr(module, "router")
            app.include_router(router)
            logger.info("Included router: %s", module_path)

        except Exception as exc:
            message = f"Failed to include router {module_path}: {exc}"
            if strict:
                raise

            logger.exception(message)


include_project_routers(app, ROUTER_MODULES)