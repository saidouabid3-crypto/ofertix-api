from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routes.products import router as products_router
from routes.ai_search import router as ai_search_router
from routes.video_deals import router as video_deals_router

app = FastAPI(
    title="Ofertix API",
    description="Backend API for Ofertix products, AI search, and optimized video deals.",
    version="5.2.0",
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

# Cloudinary optimized video deals routes
app.include_router(video_deals_router)


@app.get("/")
def home():
    return {
        "app": "Ofertix API",
        "status": "running",
        "version": "5.2.0",
        "message": "Ofertix backend is running successfully.",
        "routes": {
            "products": "/products",
            "ai_search": "/api/ai/search",
            "video_deals_create": "/video-deals/create",
            "health": "/health",
        },
        "features": [
            "products",
            "ai_search",
            "cloudinary_video_upload",
            "optimized_reels_video",
            "video_thumbnail_generation",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ofertix-api",
        "version": "5.2.0",
    }