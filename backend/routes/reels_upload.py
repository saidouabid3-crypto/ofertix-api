from fastapi import APIRouter, File, HTTPException, UploadFile

from services.cloudinary_video_service import upload_reels_video

router = APIRouter(prefix="/api/reels", tags=["reels"])


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    try:
        if not file.content_type or not file.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="Only video files are allowed")

        file_bytes = await file.read()

        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file")

        max_size_mb = 80
        if len(file_bytes) > max_size_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"Video too large. Max allowed size is {max_size_mb}MB",
            )

        result = await upload_reels_video(
            file_bytes=file_bytes,
            original_filename=file.filename or "video.mp4",
        )

        return {
            "ok": True,
            "data": result,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))