import os
import re
import time
import random
import logging
import json
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image
from core.paths import PathAuthority
from core.secrets import get_secret

Image.MAX_IMAGE_PIXELS = None  # Allow processing huge strips
CHUNK_HEIGHT = 2000           # Standard page slice height

logger = logging.getLogger("MangaDex")

HEADERS = {
    "User-Agent": "ZineScraper/1.0 (https://github.com/valse-de-anshu/zine-scraper)",
    "Accept": "application/json,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

class MangaDexAPI:
    """Robust MangaDex REST API client adhering to official rate-limits and caching standards."""
    BASE_API = "https://api.mangadex.org"
    AUTH_API = "https://auth.mangadex.org"

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id or get_secret("mangadex.client_id") or ""
        self.client_secret = client_secret or get_secret("mangadex.client_secret") or ""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.last_req_time = 0.0
        self.min_interval = 0.22  # Enforces safe <= 5 req/s limit

    def _rate_limit(self):
        elapsed = time.time() - self.last_req_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_req_time = time.time()

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 4) -> Optional[Dict[str, Any]]:
        url = f"{self.BASE_API}{endpoint}" if endpoint.startswith("/") else endpoint
        for attempt in range(max_retries):
            self._rate_limit()
            try:
                r = self.session.get(url, params=params, timeout=30)
                if r.status_code == 429:
                    # Exceeded rate limit backoff
                    retry_after = float(r.headers.get("Retry-After", 2.0))
                    backoff = max(retry_after, 2.0 ** attempt)
                    logger.warning(f"Rate limited (429) on {url}, cooling down {backoff:.1f}s...")
                    time.sleep(backoff)
                    continue
                if r.status_code in (403, 404):
                    logger.error(f"HTTP {r.status_code} for {url}")
                    return None
                r.raise_for_status()
                return r.json()
            except Exception as e:
                logger.warning(f"Request failed for {url} (attempt {attempt+1}/{max_retries}): {e}")
                time.sleep(1.5 * (attempt + 1))
        return None

    def get_manga(self, manga_id: str) -> Optional[Dict[str, Any]]:
        params = {
            "includes[]": ["cover_art", "author", "artist"]
        }
        res = self.get(f"/manga/{manga_id}", params=params)
        return res.get("data") if res else None

    def get_chapter(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        params = {
            "includes[]": ["manga", "scanlation_group"]
        }
        res = self.get(f"/chapter/{chapter_id}", params=params)
        return res.get("data") if res else None

    def get_feed(self, manga_id: str, lang: str = "en", limit: int = 500, offset: int = 0) -> Optional[Dict[str, Any]]:
        params = [
            ("limit", str(limit)),
            ("offset", str(offset)),
            ("order[chapter]", "asc"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"),
            ("contentRating[]", "pornographic"),
            ("includes[]", "scanlation_group")
        ]
        if lang:
            params.append(("translatedLanguage[]", lang))
        
        # Build query string cleanly with repeated keys
        import urllib.parse
        qs = urllib.parse.urlencode(params)
        endpoint = f"/manga/{manga_id}/feed?{qs}"
        return self.get(endpoint)

    def get_athome_server(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        res = self.get(f"/at-home/server/{chapter_id}?forcePort443=false")
        return res if res else None


class BaseScraper:
    scraper_type = "toon"
    IMAGE_DELAY = 0.15
    MAX_WORKERS = 4

    VALID_IMAGE_MIMES = {
        "image/jpeg", "image/jpg", "image/png", "image/webp",
        "image/avif", "image/gif", "image/bmp"
    }
    MIME_TO_EXT = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/webp": ".webp",
        "image/avif": ".avif", "image/gif": ".gif",
        "image/bmp": ".bmp"
    }

    def __init__(self, url: str):
        self.url = url.strip().rstrip("/")
        self.domain = "mangadex.org"
        self.api = MangaDexAPI()
        self.dl_session = requests.Session()
        # Per MangaDex docs: NEVER send auth headers or referer to image domains
        self.dl_session.headers.update({
            "User-Agent": "ZineScraper/1.0 (https://github.com/valse-de-anshu/zine-scraper)",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        })

    def download_image(self, src: str, path: Path) -> int:
        """Download image into given path, preserving authentic format and avoiding zero-byte writes."""
        for attempt in range(4):
            try:
                time.sleep(self.IMAGE_DELAY + random.uniform(0.02, 0.08))
                r = self.dl_session.get(src, stream=True, timeout=30)
                if r.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                if r.status_code in (403, 404):
                    return -1
                r.raise_for_status()

                ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
                real_ext = self.MIME_TO_EXT.get(ct, path.suffix or ".jpg")
                if path.suffix.lower() != real_ext:
                    path = path.with_suffix(real_ext)

                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)

                if path.stat().st_size < 1000:
                    path.unlink(missing_ok=True)
                    return -1
                return 1
            except Exception:
                if path.exists():
                    path.unlink(missing_ok=True)
                time.sleep(1.0)
        return 0

    def download_cover(self, folder: Path):
        """Downloads cover art into target folder using centralized temp directory buffer."""
        cover_url = getattr(self, "cover_url", None)
        if not cover_url:
            return

        if folder.exists() and list(folder.glob("cover.*")):
            return

        temp_root = PathAuthority().get_temp_root() / f"md_cover_{int(time.time()*1000)}"
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            parsed = urlparse(cover_url)
            ext = Path(parsed.path).suffix or ".jpg"
            temp_path = temp_root / f"cover{ext}"
            
            success = False
            for attempt in range(3):
                if self.download_image(cover_url, temp_path) == 1:
                    success = True
                    break
                time.sleep(1.5)

            if success and temp_path.exists():
                final_cover = folder / temp_path.name
                shutil.copy2(temp_path, final_cover)
                logger.info(f"Cover saved: {final_cover.name}")
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def process_chapter_multi(self, img_urls: List[str], folder: Path, ch_num: str, ch_url: str, live=None, stats_callback=None) -> dict:
        """Download all chapter pages into centralized temp buffer, process/slice strips, and atomically commit."""
        temp_dir = PathAuthority().get_temp_root() / f"md_ch_{ch_num}_{int(time.time()*1000)}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        total_pages = len(img_urls)
        if stats_callback:
            stats_callback({"total": total_pages, "downloaded": 0, "missing": 0})

        downloaded_files = {}

        def dl_task(idx: int, src: str):
            temp_img_path = temp_dir / f"page_{idx:04d}.tmp"
            status = self.download_image(src, temp_img_path)
            # Find the actual written file (extension might have been altered by MIME)
            found = list(temp_dir.glob(f"page_{idx:04d}.*"))
            actual_path = found[0] if found else None
            return idx, status, actual_path

        dl_count = 0
        missing_count = 0

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = [executor.submit(dl_task, i + 1, url) for i, url in enumerate(img_urls)]
            for future in as_completed(futures):
                idx, status, actual_path = future.result()
                if status == 1 and actual_path and actual_path.exists():
                    downloaded_files[idx] = actual_path
                    dl_count += 1
                else:
                    missing_count += 1
                if stats_callback:
                    stats_callback({"total": total_pages, "downloaded": dl_count, "missing": missing_count})

        if dl_count == 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {"total": total_pages, "downloaded": 0, "missing": total_pages, "success": False}

        # Slicing & Final Renaming Pipeline inside temp buffer
        if stats_callback:
            stats_callback({"status": "baking"})
        final_pages_dir = temp_dir / "final"
        final_pages_dir.mkdir(parents=True, exist_ok=True)
        
        current_page_idx = 1
        sorted_indices = sorted(downloaded_files.keys())

        for idx in sorted_indices:
            img_file = downloaded_files[idx]
            try:
                with Image.open(img_file) as img:
                    width, height = img.size
                    # Check for tall webtoon strips
                    if height > CHUNK_HEIGHT and height > (width * 2.2):
                        # Slice into 2000px height chunks
                        num_chunks = (height + CHUNK_HEIGHT - 1) // CHUNK_HEIGHT
                        for c in range(num_chunks):
                            top = c * CHUNK_HEIGHT
                            bottom = min((c + 1) * CHUNK_HEIGHT, height)
                            box = (0, top, width, bottom)
                            chunk_img = img.crop(box)
                            out_name = f"{current_page_idx:03d}.jpg"
                            chunk_img.convert("RGB").save(final_pages_dir / out_name, quality=95)
                            current_page_idx += 1
                    else:
                        out_name = f"{current_page_idx:03d}{img_file.suffix}"
                        shutil.copy2(img_file, final_pages_dir / out_name)
                        current_page_idx += 1
            except Exception as e:
                logger.warning(f"Error checking/slicing image {img_file.name}: {e}")
                out_name = f"{current_page_idx:03d}{img_file.suffix}"
                shutil.copy2(img_file, final_pages_dir / out_name)
                current_page_idx += 1

        # Commit to chapter directory without creating duplicate nested folders
        dest_dir = folder if folder.name == f"Chapter{ch_num}" else (folder / f"Chapter{ch_num}")
        dest_dir.mkdir(parents=True, exist_ok=True)

        for final_f in final_pages_dir.iterdir():
            if final_f.is_file():
                dest = dest_dir / final_f.name
                shutil.copy2(final_f, dest)

        # Cleanup centralized temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)

        return {
            "total": total_pages,
            "downloaded": dl_count,
            "missing": missing_count,
            "success": True
        }
