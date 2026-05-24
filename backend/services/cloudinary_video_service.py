import os
import time
import uuid
import tempfile
from typing import Any, Dict

import cloudinary
import cloudinary.uploader


CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")


def configure_cloudinary() -> None:
    if not CLOUDINARY_CLOUD_NAME or not CLOUDINARY_API_KEY or not CLOUDINARY_API_SECRET:
        raise RuntimeError(
            "Missing Cloudinary env vars: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET"
        )

    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )


def _build_optimized_video_url(public_id: str) -> str:
    cloud_name = CLOUDINARY_CLOUD_NAME

    return (
        f"https://res.cloudinary.com/{cloud_name}/video/upload/"
        f"f_mp4,vc_h264,q_auto:good,w_720,h_1280,c_fill,br_1400k,ac_aac/"
        f"{public_id}.mp4"
    )


def _build_thumbnail_url(public_id: str) -> str:
    cloud_name = CLOUDINARY_CLOUD_NAME

    return (
        f"https://res.cloudinary.com/{cloud_name}/video/upload/"
        f"so_0.2,w_720,h_1280,c_fill,q_auto:good,f_jpg/"
        f"{public_id}.jpg"
    )


async def upload_reels_video(file_bytes: bytes, original_filename: str = "") -> Dict[str, Any]:
    configure_cloudinary()

    extension = "mp4"
    if "." in original_filename:
        extension = original_filename.rsplit(".", 1)[-1].lower().strip() or "mp4"

    unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:12]}"
    public_id = f"ofertix/reels/{unique_id}"

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extension}") as temp_file:
        temp_file.write(file_bytes)
        temp_path = temp_file.name

    try:
        result = cloudinary.uploader.upload_large(
            temp_path,
            resource_type="video",
            public_id=public_id,
            overwrite=True,
            invalidate=True,
            eager=[
                {
                    "format": "mp4",
                    "video_codec": "h264",
                    "quality": "auto:good",
                    "width": 720,
                    "height": 1280,
                    "crop": "fill",
                    "bit_rate": "1400k",
                    "audio_codec": "aac",
                },
                {
                    "format": "jpg",
                    "start_offset": "0.2",
                    "quality": "auto:good",
                    "width": 720,
                    "height": 1280,
                    "crop": "fill",
                },
            ],
            eager_async=False,
        )

        secure_url = result.get("secure_url", "")
        duration = result.get("duration") or 0

        return {
            "cloudinaryPublicId": public_id,
            "videoUrlOriginal": secure_url,
            "videoUrlOptimized": _build_optimized_video_url(public_id),
            "thumbnailUrl": _build_thumbnail_url(public_id),
            "durationSeconds": int(float(duration)) if duration else 0,
        }

    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass