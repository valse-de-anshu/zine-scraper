import os
import re
import subprocess
import logging
from typing import Dict, Any, List, Tuple
from core.asset_engine import AssetBaseScraper
from .engine import FacebookEngine

logger = logging.getLogger(__name__)


class FacebookScraper(AssetBaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.engine = FacebookEngine()
        self.scraper_type = "asset"
        self.domain = "facebook.com"
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.facebook.com/",
            "Accept": "*/*",
        })

    def get_link_type(self) -> str:
        """Returns 'profile', 'board', or 'pin'."""
        path = re.sub(r"https?://[^/]+/", "", self.url).strip("/")
        parts = [p for p in path.split("/") if p]
        if "/reel/" in self.url.lower() or "/photo." in self.url.lower() or "fbid=" in self.url.lower():
            return "pin"
        if len(parts) <= 2 or "?target=" in self.url.lower():
            return "profile"
        return "board"

    def get_metadata_and_assets(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Determine link type and extract items accordingly."""
        url_lower = self.url.lower()
        if "/reel/" in url_lower or "/photo." in url_lower or "fbid=" in url_lower:
            item_info = self.engine.get_pin_info(self.url)
            meta = {
                "Title": item_info.get("title", "Facebook Media"),
                "Source": "Facebook",
            }
            pins = [item_info] if item_info else []
        else:
            meta, pins = self.engine.get_board_pins(self.url)

        assets = []
        for pin in pins:
            direct_url = pin.get("direct_url", "")
            if not direct_url:
                continue

            title = pin.get("title", "facebook_item")
            clean_title = "".join(
                [c for c in title if c.isalnum() or c in " .-_()"]
            ).strip()
            if not clean_title:
                clean_title = "facebook_item"

            is_video = pin.get("is_video", False)
            if is_video:
                ext = ".mp4"
            else:
                # Use a neutral placeholder — real extension fixed post-download by sniffing
                ext = ".jpg"

            assets.append(
                {
                    "id": pin.get("id"),
                    "name": title,
                    "url": direct_url,
                    "_pin_page_url": pin.get("url"),
                    "filename": f"{clean_title}_{pin.get('id')}{ext}",
                    "size_bytes": 0,
                    "is_video": is_video,
                }
            )

        return meta, assets

    def download_asset(self, url: str, path: str, stats_callback=None, is_video: bool = False) -> bool:
        """
        Download a Facebook asset:
        - Videos: yt-dlp with Referer header & cookies
        - Images: direct HTTP download with Content-Type + magic byte sniffing to fix extension
        """
        if not url:
            logger.error("download_asset called with empty URL")
            return False

        use_ytdlp = is_video or "facebook.com/reel/" in url or ".mp4" in url or ".m3u8" in url

        if use_ytdlp:
            try:
                ytdlp_bin = "yt-dlp"
                cmd = [
                    ytdlp_bin,
                    "-o", str(path),
                    "--no-warnings",
                    "--quiet",
                    "--referer", "https://www.facebook.com/",
                    "-f", "bestvideo+bestaudio/best",
                    "--no-playlist",
                    url
                ]
                result = subprocess.run(cmd, timeout=120)
                if result.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 10000:
                    return True
                logger.debug(f"yt-dlp returned code {result.returncode}, falling back to direct download...")
                return self.download_file(url, path, stats_callback=stats_callback)
            except Exception as e:
                logger.error(f"yt-dlp error: {e}, falling back to direct download")
                return self.download_file(url, path, stats_callback=stats_callback)

        # Image download with real-format sniffing + HTML rejection
        ok = self.download_file(url, path, stats_callback=stats_callback)
        if ok:
            ok = self._validate_and_fix_image(path)
        return ok

    @staticmethod
    def _validate_and_fix_image(path: str) -> bool:
        """
        Read the first 32 bytes of the downloaded file and:
        1. Reject HTML content (login walls, CDN error pages) — delete file and return False
        2. Rename to correct extension if the magic bytes don't match the saved extension
        Returns True if file is a valid image/video, False if corrupted/HTML.
        """
        from pathlib import Path as _Path
        p = _Path(path)
        if not p.exists() or p.stat().st_size < 12:
            if p.exists():
                p.unlink()
            return False

        try:
            with open(p, "rb") as f:
                header = f.read(32)
        except Exception:
            return False

        # Reject HTML content immediately — these are login walls or error pages
        html_signatures = (b"<!DO", b"<!do", b"<htm", b"<HTM", b"\xef\xbb\xbf<")  # includes UTF-8 BOM
        if any(header.startswith(sig) for sig in html_signatures):
            logger.warning(f"Deleting HTML content disguised as image: {p.name}")
            p.unlink()
            return False

        # Detect real format from magic bytes
        real_ext = None
        if header[:3] == b"\xff\xd8\xff":
            real_ext = ".jpg"
        elif header[:8] == b"\x89PNG\r\n\x1a\n":
            real_ext = ".png"
        elif header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            real_ext = ".webp"
        elif header[:6] in (b"GIF87a", b"GIF89a"):
            real_ext = ".gif"
        elif header[4:8] == b"ftyp":
            brand = header[8:12]
            if brand in (b"avif", b"avis", b"MA1A", b"MA1B"):
                real_ext = ".avif"
            else:
                real_ext = ".mp4"

        # Unknown format — not a recognised image, reject it
        if real_ext is None:
            logger.warning(f"Deleting unrecognised format file: {p.name} (header: {header[:8].hex()})")
            p.unlink()
            return False

        # Rename if extension is wrong
        if p.suffix.lower() != real_ext:
            new_path = p.with_suffix(real_ext)
            if new_path.exists():
                new_path = p.with_name(p.stem + "_1" + real_ext)
            try:
                p.rename(new_path)
                logger.debug(f"Renamed {p.name} → {new_path.name} (real format: {real_ext})")
            except Exception as e:
                logger.debug(f"Could not rename {p.name}: {e}")

        return True

