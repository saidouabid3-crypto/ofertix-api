import os
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from fastapi import UploadFile


class CloudinaryUploadService:
    def __init__(self):
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET"),
            secure=True,
        )

    def upload_reel_video(self, file: UploadFile) -> dict:
        public_id = f"ofertix/smart_reels/reel_{uuid4().hex[:16]}"

        file.file.seek(0)

        result = cloudinary.uploader.upload_large(
            file.file,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
            chunk_size=6_000_000,
        )

        return {
            "secure_url": result.get("secure_url", ""),
            "public_id": result.get("public_id", public_id),
            "duration": result.get("duration"),
            "format": result.get("format"),
            "bytes": result.get("bytes"),
        }


cloudinary_upload_service = CloudinaryUploadService()