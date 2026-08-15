"""
scrapers/light_novel/novelarchive/engine.py
-------------------------------------------
HTTP engine for novelarchive.cc API.
Fetches JSON from their /api/ endpoints.
"""

import time
import requests
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Origin": "https://novelarchive.cc",
    "Referer": "https://novelarchive.cc/",
}


class NABaseEngine:
    """Base engine — HTTP session + JSON API fetcher."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.domain = "novelarchive.cc"
        self.api_base = "https://novelarchive.cc/api"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get_json(self, url: str, **kwargs) -> dict:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=35, **kwargs)
                r.raise_for_status()
                return r.json()
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed to fetch JSON: {url}")

    def download_cover(self, cover_url: str, folder: Path) -> bool:
        """Download cover image to folder/cover.jpg."""
        if not cover_url:
            return False
        if cover_url.startswith("/"):
            cover_url = f"https://novelarchive.cc{cover_url}"
            
        from urllib.parse import urlparse
        ext = Path(urlparse(cover_url).path).suffix or ".jpg"
        path = folder / f"cover{ext}"
        if path.exists():
            return True
        for attempt in range(3):
            try:
                r = self.session.get(cover_url, stream=True, timeout=30)
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
                if path.stat().st_size > 2000:
                    # Convert to proper JPEG
                    return True
                path.unlink()
            except Exception:
                if path.exists():
                    path.unlink()
                time.sleep(2)
        return False
