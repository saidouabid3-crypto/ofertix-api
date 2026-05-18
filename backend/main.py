from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.products import router as products_router

app = FastAPI(
    title="Ofertix API",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products_router)


@app.get("/")
def home():
    return {
        "app": "Ofertix API",
        "status": "running",
        "version": "5.0.0",
    }