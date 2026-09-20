import os
import re
import subprocess
import logging
from typing import Dict, Any, List, Tuple
from core.asset_engine import AssetBaseScraper
from .engine import InstagramEngine

logger = logging.getLogger(__name__)


class InstagramScraper(AssetBaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.engine = InstagramEngine()
        self.scraper_type = "asset"
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
            "Accept": "*/*",
        })

    def get_link_type(self) -> str:
        """Returns 'profile', 'board', or 'pin'."""
        path = re.sub(r"https?://[^/]+/", "", self.url).strip("/")
        parts = path.split("/")
        if "/pin/" in self.url.lower():
            return "pin"
        if len(parts) == 1 or (
            len(parts) == 2 and parts[1] in ["_saved", "_created", "pins", "boards"]
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
                "Title": pin_info.get("title", "Instagram Pin"),
                "Source": "Instagram",
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

    def _export_cookie_file(self) -> str:
        """Export engine's browser cookies to a Netscape cookie file for yt-dlp."""
        cookie_file = "/tmp/ig_ytdlp_cookies.txt"
        try:
            cookies = getattr(self.engine, "pw_cookies", [])
            if not cookies:
                return ""
            with open(cookie_file, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c.get("domain", ".instagram.com")
                    if not domain.startswith("."):
                        domain = "." + domain.lstrip(".")
                    flag = "TRUE" if domain.startswith(".") else "FALSE"
                    path = c.get("path", "/")
                    secure = "TRUE" if c.get("secure") else "FALSE"
                    expiration = "2147483647"
                    name = c.get("name", "")
                    value = c.get("value", "")
                    if name and value:
                        f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}\n")
            return cookie_file
        except Exception as e:
            logger.debug(f"Failed to export cookies for yt-dlp: {e}")
            return ""

    def download_asset(self, url: str, path: str, stats_callback=None, is_video: bool = False) -> bool:
        """
        Download an Instagram asset:
        - Videos: yt-dlp with Referer header & cookies (handles DASH fragments & produces valid playable MP4s)
        - Images: direct HTTP download with Referer header
        """
        if not url:
            logger.error("download_asset called with empty URL")
            return False

        # If it's a video, ALWAYS use yt-dlp so DASH/HLS fragments are stitched into a full MP4 file
        use_ytdlp = is_video or "video/mp4" in url or ".m3u8" in url or "/o1/v/t2/" in url

        if use_ytdlp:
            try:
                ytdlp_bin = "yt-dlp"
                cmd = [
                    ytdlp_bin,
                    "-o", str(path),
                    "--no-warnings",
                    "--quiet",
                    "--referer", "https://www.instagram.com/",
                    "-f", "bestvideo+bestaudio/best",
                    "--no-playlist",
                ]
                cfile = self._export_cookie_file()
                if cfile and os.path.exists(cfile):
                    cmd.extend(["--cookies", cfile])
                cmd.append(url)

                result = subprocess.run(cmd, timeout=120)
                if result.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 10000:
                    return True
                # If yt-dlp returncode!=0 or output size <= 10KB, fall back to direct download
                logger.debug(f"yt-dlp returned code {result.returncode}, trying direct fallback...")
                return self.download_file(url, path, stats_callback=stats_callback)
            except Exception as e:
                logger.error(f"yt-dlp error: {e}, falling back to direct download")
                return self.download_file(url, path, stats_callback=stats_callback)

        # Image/GIF/WebP — direct download
        return self.download_file(url, path, stats_callback=stats_callback)
