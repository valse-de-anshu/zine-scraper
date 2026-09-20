import re
import subprocess
import logging
from typing import Dict, Any, List, Tuple
from core.asset_engine import AssetBaseScraper
from .engine import PinterestEngine

logger = logging.getLogger(__name__)


class PinterestScraper(AssetBaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.engine = PinterestEngine()
        self.scraper_type = "asset"

    def get_link_type(self) -> str:
        """Returns 'profile', 'board', or 'pin'."""
        path = re.sub(r"https?://[^/]+/", "", self.url).strip("/")
        parts = path.split("/")
        if "/pin/" in self.url.lower():
            return "pin"
        if len(parts) == 1 or (
            len(parts) == 2 and parts[1] in ["_saved", "pins", "boards"]
        ):
            return "profile"
        return "board"

    def get_metadata_and_assets(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Determine link type and extract pins accordingly.
        """
        url_lower = self.url.lower()
        path = re.sub(r"https?://[^/]+/", "", self.url).strip("/")
        parts = path.split("/")

        if len(parts) == 1 or (
            len(parts) == 2 and parts[1] in ["_saved", "_created", "pins"]
        ):
            meta, pins = self.engine.get_profile_pins(self.url)
        elif "/pin/" in url_lower:
            pin_info = self.engine.get_pin_info(self.url)
            meta = {
                "Title": pin_info.get("title", "Pinterest Pin"),
                "Source": "Pinterest",
            }
            pins = [pin_info] if pin_info else []
        else:
            meta, pins = self.engine.get_board_pins(self.url)
            if "Channel/Series" in meta:
                meta["Title"] = meta.pop("Channel/Series")

        assets = []
        for pin in pins:
            direct_url = pin.get("direct_url", "")
            if not direct_url:
                continue

            title = pin.get("title", "pin")
            clean_title = "".join(
                [c for c in title if c.isalnum() or c in " .-_()"]
            ).strip()
            if not clean_title:
                clean_title = "pin"

            # Extension: video → .mp4, image based on URL
            is_video = pin.get("is_video", False)
            if is_video:
                ext = ".mp4"
            elif ".png" in direct_url.lower():
                ext = ".png"
            elif ".gif" in direct_url.lower():
                ext = ".gif"
            elif ".webp" in direct_url.lower():
                ext = ".webp"
            else:
                ext = ".jpg"

            assets.append(
                {
                    "id": pin.get("id"),
                    "name": title,
                    "url": direct_url,
                    # For videos we'll use the pin page URL so yt-dlp can process it
                    "_pin_page_url": pin.get("url"),
                    "filename": f"{clean_title}_{pin.get('id')}{ext}",
                    "size_bytes": 0,
                    "is_video": is_video,
                }
            )

        return meta, assets

    def download_asset(self, url: str, path: str, stats_callback=None, is_video: bool = False) -> bool:
        """
        Download a Pinterest asset:
        - Videos: yt-dlp on the individual pin page URL (reliable)
        - Images: direct HTTP download
        """
        if not url:
            logger.error("download_asset called with empty URL")
            return False

        # Detect video from explicit flag OR url pattern
        use_ytdlp = is_video or url.endswith(".mp4") or ".m3u8" in url

        if use_ytdlp:
            # Use yt-dlp on the pin page URL — much more reliable than direct m3u8
            # We'll try to get the pin page URL from the caller context
            # The url passed may already be direct m3u8; convert to pin page if possible
            pin_page_url = url  # fallback
            try:
                ytdlp_bin = "yt-dlp"
                cmd = [
                    ytdlp_bin,
                    "-o", str(path),
                    "--no-warnings",
                    "--quiet",
                    "--no-playlist",
                    pin_page_url,
                ]
                result = subprocess.run(cmd, timeout=120)
                return result.returncode == 0
            except subprocess.TimeoutExpired:
                logger.error("yt-dlp timeout downloading Pinterest video")
                return False
            except Exception as e:
                logger.error(f"yt-dlp error: {e}")
                return False

        # Image/GIF/WebP — direct download
        return self.download_file(url, path, stats_callback=stats_callback)
