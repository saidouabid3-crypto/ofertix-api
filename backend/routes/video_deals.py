import os
import tempfile
from typing import Optional

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from google.cloud import firestore

router = APIRouter(prefix="/video-deals", tags=["Video Deals"])

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)

db = firestore.Client()


@router.post("/create")
async def create_video_deal(
    title: str = Form(...),
    price: float = Form(...),
    oldPrice: Optional[float] = Form(None),
    store: str = Form(...),
    city: str = Form(...),
    countryCode: str = Form("ES"),
    buyLink: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    video: UploadFile = File(...),
):
    try:
        if not video.content_type or not video.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="File must be a video")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
            tmp.write(await video.read())
            tmp_path = tmp.name

        upload_result = cloudinary.uploader.upload_large(
            tmp_path,
            resource_type="video",
            folder="ofertix/videos",
            overwrite=False,
        )

        os.remove(tmp_path)

        video_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")

        if not video_url:
            raise HTTPException(status_code=500, detail="Cloudinary upload failed")

        deal_data = {
            "title": title,
            "price": price,
            "oldPrice": oldPrice,
            "store": store,
            "city": city,
            "countryCode": countryCode,
            "buyLink": buyLink,
            "whatsapp": whatsapp,
            "videoUrl": video_url,
            "cloudinaryPublicId": public_id,
            "mediaType": "video",
            "isActive": True,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }

        doc_ref = db.collection("products").document()
        doc_ref.set(deal_data)

        return {
            "success": True,
            "message": "Video deal published successfully",
            "id": doc_ref.id,
            "videoUrl": video_url,
            "data": deal_data,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))