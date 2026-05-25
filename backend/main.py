from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routes.products import router as products_router
from routes.ai_search import router as ai_search_router
from routes.smart_reels import router as smart_reels_router

app = FastAPI(
    title="Ofertix API",
    description="Backend API for Ofertix products, AI search, and Smart Deal Reels.",
    version="6.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Products routes
app.include_router(products_router)

# AI search routes
app.include_router(ai_search_router)

# New professional Smart Reels routes
app.include_router(smart_reels_router)


@app.get("/")
def home():
    return {
        "app": "Ofertix API",
        "status": "running",
        "version": "6.0.0",
        "message": "Ofertix backend is running successfully.",
        "routes": {
            "products": "/products",
            "ai_search": "/api/ai/search",
            "smart_reels_feed": "/smart-reels/feed",
            "smart_reels_create": "/smart-reels",
            "health": "/health",
            "docs": "/docs",
        },
        "features": [
            "products",
            "ai_search",
            "smart_deal_reels",
            "cloudinary_optimized_video",
            "video_thumbnail_generation",
            "deal_score",
            "fake_discount_detection",
            "reels_analytics",
            "pagination_ready_feed",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ofertix-api",
        "version": "6.0.0",
        "smart_reels": "enabled",
    }