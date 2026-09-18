from pathlib import Path
from typing import Dict, Any, Optional, List
import requests
import re
import yt_dlp
import logging
logger = logging.getLogger(__name__)
from core.video_engine import VideoEngine

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://hstream.moe/",
}

class HstreamEngine(VideoEngine):
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url:
            return False
        try:
            from core.cover_utils import save_verified_cover
            r = self.session.get(avatar_url, timeout=20)
            if r.status_code == 200 and len(r.content) > 500:
                saved = save_verified_cover(r.content, dest.parent, filename=dest.stem)
                return saved is not None
            return False
        except Exception:
            return False

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str,
                      model_name: str, avatar_url: Optional[str] = None,
                      videos: Optional[list] = None, skip_cover: bool = False, custom_metadata: Optional[Dict[str, Any]] = None):
        import json
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        video_list = videos or []
        url = info.get("webpage_url") or info.get("url") or ""
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]
            
        studio = custom_metadata.get("Studio", "") if custom_metadata else ""
        tags = custom_metadata.get("Tags", "") if custom_metadata else ""
        summary = custom_metadata.get("Description", "") if custom_metadata else ""
        
        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        tags_list = [t.strip() for t in tags.split(",") if t.strip()] if isinstance(tags, str) else (tags or [])
        payload = ZineMetadataPayload(
            title=model_name,
            type="Series",
            author=studio or model_name,
            artist=studio,
            description=summary,
            tags=tags_list,
            url=url
        )
        MetadataEngine.save_metadata(root_dir, payload)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

    def extract_stream_url(self, page_url: str) -> Optional[str]:
        # Using yt-dlp to extract directly since it's supported natively
        return page_url

    def download_hstream_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook=None,
        is_audio: bool = False,
        quality: str = "",
        fixed_title: str = "",
        fixed_artist: str = "",
        pre_extracted_stream: str = "",
    ) -> bool:
        """
        Downloads a Hstream video via yt-dlp.
        """
        try:
            return self.download_video(
                url=url,
                output_dir=output_dir,
                progress_hook=progress_hook or (lambda d: None),
                is_audio=is_audio,
                fixed_title=fixed_title,
                fixed_artist=fixed_artist,
            )
        except Exception as e:
            logger.error(f"Hstream download_video failed: {e}")
            return False
