class CloudinaryService:
    @staticmethod
    def optimize_video_url(url: str) -> str:
        if not url or "/upload/" not in url:
            return url

        if "f_auto,q_auto" in url:
            return url

        return url.replace(
            "/upload/",
            "/upload/f_auto,q_auto:eco,w_720/"
        )

    @staticmethod
    def generate_thumbnail_url(url: str) -> str:
        if not url or "/upload/" not in url:
            return ""

        thumbnail = url.replace(
            "/upload/",
            "/upload/so_1,w_720,f_jpg,q_auto/"
        )

        if "." in thumbnail:
            thumbnail = thumbnail.rsplit(".", 1)[0] + ".jpg"

        return thumbnail

    @staticmethod
    def generate_hls_url(url: str) -> str:
        """
        HLS placeholder.
        Cloudinary HLS may need proper video transformation/settings depending on account.
        We keep this field ready so Flutter does not break later.
        """
        if not url or "/upload/" not in url:
            return ""

        hls = url.replace(
            "/upload/",
            "/upload/sp_hd/"
        )

        if "." in hls:
            hls = hls.rsplit(".", 1)[0] + ".m3u8"

        return hls