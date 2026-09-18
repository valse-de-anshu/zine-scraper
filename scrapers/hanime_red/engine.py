import logging
from pathlib import Path
from typing import Dict, Any, Optional
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

class HanimeRedEngine(VideoEngine):
    def __init__(self):
        super().__init__(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def download_hanime_red_video(self, url: str, output_dir: Path, progress_hook, quality: str = "1080p", fixed_title: Optional[str] = None) -> bool:
        """
        Direct high-speed video download via yt-dlp and HanimeRed extractor plugin.
        """
        return self.download_video(
            url=url,
            output_dir=output_dir,
            progress_hook=progress_hook,
            fixed_title=fixed_title
        )

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        """Downloads and verifies cover art using 2-step magic-byte and PIL verification."""
        if not avatar_url:
            return False
        try:
            from core.cover_utils import download_verified_cover
            saved = download_verified_cover(
                cover_url=avatar_url,
                folder=dest.parent,
                filename=dest.stem,
                headers=self.headers
            )
            return saved is not None
        except Exception as e:
            logger.debug(f"Failed to download verified cover: {e}")
            return False

    def save_metadata(
        self,
        root_dir: Path,
        info: Dict[str, Any],
        source: str,
        model_name: str,
        avatar_url: Optional[str] = None,
        videos: Optional[list] = None,
        skip_cover: bool = False,
        custom_metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Persists clean, normalized metadata and 2-step verified cover art into folder.
        """
        url = info.get("url", "")
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]

        alt_title = (custom_metadata.get("Alternative Title") or info.get("alt_title") or "") if custom_metadata else ""
        studio = (custom_metadata.get("Studio") or info.get("uploader_id") or "") if custom_metadata else ""
        tags = (custom_metadata.get("Tags") or "") if custom_metadata else ""
        summary = (custom_metadata.get("Description") or "") if custom_metadata else ""
        raw_date = (custom_metadata.get("Release Date") or info.get("upload_date") or "") if custom_metadata else ""
        year = str(raw_date).split("-")[0] if raw_date else ""
        views = str(custom_metadata.get("Views") or info.get("views") or "") if custom_metadata else ""
        likes = str(custom_metadata.get("Likes") or info.get("likes") or "") if custom_metadata else ""

        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        if isinstance(tags, list):
            tags_list = tags
        elif isinstance(tags, str):
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tags_list = []

        payload = ZineMetadataPayload(
            title=model_name,
            type="Series",
            alt_title=alt_title,
            author=studio or model_name,
            artist=studio,
            description=summary,
            tags=tags_list,
            year=year,
            views=views,
            likes=likes,
            url=url
        )
        MetadataEngine.save_metadata(root_dir, payload)

        # 2-step verification cover download
        if not skip_cover and avatar_url:
            from core.cover_utils import download_verified_cover
            download_verified_cover(
                cover_url=avatar_url,
                folder=root_dir,
                filename="cover",
                headers=self.headers
            )
