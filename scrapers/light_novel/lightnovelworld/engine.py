"""
scrapers/light_novel/lightnovelworld/engine.py
----------------------------------------------
Lightweight HTTP engine for lightnovelworld.org.
Handles session management, soup fetching, and plain-text chapter saving.
No image processing needed — text is written as .txt files.
"""

import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}


class LNWBaseEngine:
    """Base engine — HTTP session + soup fetcher."""

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.domain = self.url.split("/")[2].lower()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Referer"] = f"https://{self.domain}/"

    def get_soup(self, url: str) -> BeautifulSoup:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=35)
                r.raise_for_status()
                r.encoding = "utf-8"
                return BeautifulSoup(r.text, "lxml")
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed to fetch: {url}")

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
        path = folder / "cover.jpg"
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
