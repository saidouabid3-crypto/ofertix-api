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
        Return a verified HLS URL only when the platform provides one.

        Ofertix currently serves the optimized MP4 URL as the reliable playback
        source. Returning an invented .m3u8 path would create broken reels on
        accounts where adaptive streaming is not enabled.
        """
        return ""
