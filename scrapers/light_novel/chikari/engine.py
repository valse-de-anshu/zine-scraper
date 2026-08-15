"""
scrapers/light_novel/chikari/engine.py
--------------------------------------
Lightweight HTTP engine for chikari.moe.
"""

import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


def detect_image_extension(header: bytes) -> str:
    """Sniff real image format from magic bytes."""
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    elif header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    elif header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return ".webp"
    elif header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return ".gif"
    elif len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in (b"avif", b"avis", b"MA1A", b"MA1B"):
        return ".avif"
    return ".jpg"


class ChikariBaseEngine:
    """Base engine for chikari.moe."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.domain = "chikari.moe"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Referer"] = "https://chikari.moe/"

    def get_soup(self, url: str) -> BeautifulSoup:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                r.encoding = "utf-8"
                return BeautifulSoup(r.text, "lxml")
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed to fetch: {url}")

    def get_json(self, url: str) -> dict:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=30)
                r.raise_for_status()
                return r.json()
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed to fetch JSON: {url}")

    def download_cover(self, cover_url: str, folder: Path) -> bool:
        """Download cover image and detect real image format via magic bytes."""
        if not cover_url:
            return False
        for ext in [".jpg", ".png", ".webp", ".jpeg", ".avif"]:
            if (folder / f"cover{ext}").exists():
                return True
        for attempt in range(3):
            try:
                r = self.session.get(cover_url, timeout=30)
                r.raise_for_status()
                data = r.content
                if len(data) > 500:
                    ext = detect_image_extension(data[:32])
                    path = folder / f"cover{ext}"
                    path.write_bytes(data)
                    return True
            except Exception:
                time.sleep(2)
        return False
