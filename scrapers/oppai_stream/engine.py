from pathlib import Path
from typing import Dict, Any, Optional, List
import requests
import re
import json
import logging
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Referer": "https://oppai.stream/",
}

class OppaiStreamEngine(VideoEngine):
    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.headers = HEADERS

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url:
            return False
        try:
            r = self.session.get(avatar_url, timeout=20)
            r.raise_for_status()
            
            ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
            mime_map = {
                "image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp",
                "image/avif": ".avif", "image/gif": ".gif"
            }
            real_ext = mime_map.get(ct, dest.suffix or ".jpg")
            if dest.suffix.lower() != real_ext:
                dest = dest.with_suffix(real_ext)
                
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
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
        
        metadata_content = {
            "Series": model_name,
            "Source": source,
            "URL": url,
            "Total Videos": len(video_list),
            "Studio": studio,
            "Tags": tags,
            "Summary": summary,
            "videos": video_list
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_content, f, indent=2, ensure_ascii=False)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

    def extract_stream_url(self, page_url: str) -> Optional[str]:
        try:
            r = self.session.get(page_url, timeout=15)
            r.raise_for_status()
            
            # Look for var availableres = {"4k":"...", "1080":"...", "720":"..."};
            match = re.search(r'var availableres = (\{.*?\});', r.text)
            if match:
                res_dict = json.loads(match.group(1).replace(r'\/', '/'))
                for q in ['4k', '1080', '720', '480', '360']:
                    if q in res_dict and res_dict[q]:
                        logger.info(f"OppaiStream: Picked {q} quality")
                        return res_dict[q]
            
            logger.error("OppaiStream: Could not find availableres JSON in page source")
            return None
        except Exception as e:
            logger.error(f"OppaiStream extract error: {e}")
            return None

    def download_oppai_stream_video(
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
        Downloads a OppaiStream video.
        """
        stream_url = pre_extracted_stream or self.extract_stream_url(url)
        if not stream_url:
            return False

        try:
            return self.download_video(
                url=stream_url,
                output_dir=output_dir,
                progress_hook=progress_hook or (lambda d: None),
                is_audio=is_audio,
                fixed_title=fixed_title,
                fixed_artist=fixed_artist,
            )
        except Exception as e:
            logger.error(f"OppaiStream download_video failed: {e}")
            return False
