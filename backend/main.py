from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from routes.products import router as products_router
from routes.ai_search import router as ai_search_router
from routes.smart_reels import router as smart_reels_router
from routes.messages import router as messages_router
from routes.community import router as community_router
from routes.coupons import router as coupons_router
from routes.user_deals import router as user_deals_router
from routes.geo_alerts import router as geo_alerts_router
from routes.ai_brain import router as ai_brain_router
from routes.i18n import router as i18n_router
from routes.marketplace import router as marketplace_router
from routes.ads import router as ads_router
from routes.mystery_box import router as mystery_box_router
from routes.profiles import router as profiles_router

app = FastAPI(
    title="Ofertix API",
    description="Ofertix Pro Max backend: products, Groq AI search, reels, marketplace, coupons, community, geo alerts, ads revenue, and messages.",
    version="7.3.0-pro-max",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core existing routes — preserved
app.include_router(products_router)
app.include_router(ai_search_router)
app.include_router(smart_reels_router)

# Super-app routes
app.include_router(messages_router)
app.include_router(profiles_router)
app.include_router(community_router)
app.include_router(coupons_router)
app.include_router(user_deals_router)
app.include_router(geo_alerts_router)
app.include_router(ai_brain_router)
app.include_router(mystery_box_router)
app.include_router(i18n_router)

# Pro Max additions
app.include_router(marketplace_router)
app.include_router(ads_router)


@app.get("/")
def home():
    return {
        "app": "Ofertix API",
        "status": "running",
        "version": "7.3.0-pro-max",
        "message": "Ofertix Pro Max backend is running successfully.",
        "routes": {
            "products": "/products",
            "ai_search": "/api/ai/search",
            "ai_brain": "/ai/brain/analyze",
            "mystery_box": "/mystery-box/today",
            "smart_reels_feed": "/smart-reels/feed",
            "messages": "/messages/conversations",
            "community_vote": "/community/vote",
            "coupons": "/coupons",
            "user_deals": "/user-deals",
            "geo_alerts": "/geo-alerts/nearby",
            "countries": "/i18n/countries",
            "languages": "/i18n/languages",
            "marketplace": "/marketplace/items",
            "ads_impression": "/ads/impression",
            "ads_click": "/ads/click",
            "ads_estimate": "/ads/revenue/estimate",
            "health": "/health",
            "docs": "/docs",
        },
        "features": [
            "products",
            "groq_ai_search_preserved",
            "ai_deal_brain_pro",
            "smart_deal_reels_preserved",
            "creator_profiles",
            "messages",
            "hot_cold_voting",
            "community_trust",
            "coupon_system",
            "user_generated_deals",
            "geo_fencing_alert_foundation",
            "marketplace_users_sell",
            "ads_revenue_estimator",
            "cloudinary_optimized_video",
            "blind_deal_box",
            "ai_deal_brain_pro",
            "fake_discount_detection",
            "rewards_ready_events",
        ],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "ofertix-api",
        "version": "7.3.0-pro-max",
        "super_app": "enabled",
        "marketplace": "enabled",
        "ads_revenue": "enabled",
    }
