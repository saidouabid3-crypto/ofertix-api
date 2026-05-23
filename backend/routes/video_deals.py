import os
import json
import tempfile
from typing import Optional

import cloudinary
import cloudinary.uploader
import firebase_admin
from firebase_admin import credentials, firestore
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

router = APIRouter(prefix="/video-deals", tags=["Video Deals"])


def init_firebase():
    if firebase_admin._apps:
        return

    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS")
    firebase_key_path = os.getenv("FIREBASE_KEY_PATH")

    if firebase_credentials_json:
        cred_dict = json.loads(firebase_credentials_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
        return

    if firebase_key_path and os.path.exists(firebase_key_path):
        cred = credentials.Certificate(firebase_key_path)
        firebase_admin.initialize_app(cred)
        return

    raise RuntimeError(
        "Firebase credentials not found. Set FIREBASE_CREDENTIALS or FIREBASE_KEY_PATH in Render."
    )


init_firebase()
db = firestore.client()


cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)


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
    tmp_path = None

    try:
        if not video.content_type or not video.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="File must be a video")

        suffix = os.path.splitext(video.filename or "video.mp4")[1] or ".mp4"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await video.read())
            tmp_path = tmp.name

        upload_result = cloudinary.uploader.upload_large(
            tmp_path,
            resource_type="video",
            folder="ofertix/videos",
            overwrite=False,
        )

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
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)