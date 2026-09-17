import os
import re
import time
import random
import logging
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

from core.paths import PathAuthority

Image.MAX_IMAGE_PIXELS = None  # Allow processing huge continuous webtoon strips
CHUNK_HEIGHT = 2000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Chromium";v="123", "Not:A-Brand";v="8"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}


class BaseScraper:
    scraper_type = "toon"

    IMAGE_DELAY = 0.3
    MAX_CONSECUTIVE_FAILURES = 5
    MAX_WORKERS = 4

    VALID_IMAGE_MIMES = {
        "image/jpeg", "image/jpg", "image/png", "image/webp",
        "image/avif", "image/gif", "image/bmp", "image/tiff",
    }
    MIME_TO_EXT = {
        "image/jpeg": ".jpg", "image/jpg": ".jpg",
        "image/png": ".png", "image/webp": ".webp",
        "image/avif": ".avif", "image/gif": ".gif",
        "image/bmp": ".bmp", "image/tiff": ".tiff",
    }

    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.domain = "www.topmanhua.fan"
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Referer"] = f"https://{self.domain}/"
        self.consecutive_failures = 0

    def get_soup(self, url: str) -> BeautifulSoup:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=35)
                r.raise_for_status()
                return BeautifulSoup(r.text, "lxml")
            except Exception:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed page: {url}")

    def download_image(self, src: str, path: Path, referer: str = None) -> int:
        """Download a single image, preserving its original format.
        Returns 1 on success, -1 on failure."""
        time.sleep(self.IMAGE_DELAY + random.uniform(0, 0.1))
        for attempt in range(3):
            try:
                headers = HEADERS.copy()
                headers["Referer"] = referer or f"https://{self.domain}/"
                r = self.session.get(src, stream=True, timeout=(10, 20), headers=headers)
                if r.status_code == 200:
                    ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ct and ct not in self.VALID_IMAGE_MIMES and "octet-stream" not in ct:
                        continue
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=32768):
                            if chunk:
                                f.write(chunk)
                    if path.stat().st_size > 1024:
                        return 1
                    path.unlink(missing_ok=True)
                elif r.status_code == 429:
                    time.sleep(2.0 + attempt * 2)
            except Exception:
                if path.exists():
                    path.unlink(missing_ok=True)
                time.sleep(1.0)
        return -1

    def download_cover(self, *args) -> bool:
        """Download cover image with magic-byte format detection.
        Supports download_cover(folder) or download_cover(cover_url, folder)."""
        if len(args) == 1 and isinstance(args[0], Path):
            folder = args[0]
            cover_url = getattr(self, "cover_url", "")
        elif len(args) >= 2:
            cover_url = args[0]
            folder = args[1]
        else:
            return False

        if not cover_url:
            return False

        for ext in [".webp", ".jpg", ".png", ".jpeg", ".avif"]:
            if (folder / f"cover{ext}").exists():
                return True

        temp_root = PathAuthority().get_temp_root()
        temp_root.mkdir(parents=True, exist_ok=True)
        raw_temp = temp_root / f"topmanhua_cover_raw_{int(time.time()*1000)}"

        for attempt in range(3):
            try:
                headers = HEADERS.copy()
                headers["Referer"] = f"https://{self.domain}/"
                r = self.session.get(cover_url, stream=True, timeout=20, headers=headers)
                if r.status_code == 200:
                    with open(raw_temp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            if chunk:
                                f.write(chunk)
                    if raw_temp.exists() and raw_temp.stat().st_size > 500:
                        content_type = r.headers.get("content-type", "").split(";")[0].strip().lower()
                        ext = self.MIME_TO_EXT.get(content_type, "")
                        if not ext:
                            header_bytes = raw_temp.read_bytes()[:12]
                            if header_bytes.startswith(b"\xff\xd8\xff"):
                                ext = ".jpg"
                            elif header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                                ext = ".png"
                            elif header_bytes.startswith(b"RIFF") and b"WEBP" in header_bytes:
                                ext = ".webp"
                            else:
                                ext = ".jpg"

                        target_cover = folder / f"cover{ext}"
                        shutil.move(str(raw_temp), str(target_cover))
                        return True
            except Exception:
                if raw_temp.exists():
                    raw_temp.unlink(missing_ok=True)
                time.sleep(1.0)
            finally:
                if raw_temp.exists():
                    raw_temp.unlink(missing_ok=True)
        return False

    def slice_and_save(self, ordered_paths: List[Path], chapter_dir: Path) -> Tuple[int, int]:
        """Stitches downloaded strip images vertically and slices them into 2000px height chunks."""
        images = []
        for p in ordered_paths:
            try:
                im = Image.open(p)
                im.load()
                images.append(im)
            except Exception:
                continue

        if not images:
            return 0, 0

        target_width = images[0].width
        for idx, im in enumerate(images):
            if im.width != target_width:
                aspect = target_width / im.width
                new_h = max(1, int(im.height * aspect))
                images[idx] = im.resize((target_width, new_h), Image.Resampling.LANCZOS)

        total_height = sum(im.height for im in images)
        canvas = Image.new("RGB", (target_width, total_height))

        y_offset = 0
        for im in images:
            if im.mode != "RGB":
                im = im.convert("RGB")
            canvas.paste(im, (0, y_offset))
            y_offset += im.height

        num_chunks = max(1, (total_height + CHUNK_HEIGHT - 1) // CHUNK_HEIGHT)
        total_digits = len(str(num_chunks))
        chunk_idx = 1
        y = 0

        while y < total_height:
            box_bottom = min(y + CHUNK_HEIGHT, total_height)
            crop_box = (0, y, target_width, box_bottom)
            chunk = canvas.crop(crop_box)

            fname = f"{str(chunk_idx).zfill(total_digits)}.jpg"
            out_path = chapter_dir / fname
            chunk.save(out_path, "JPEG", quality=95, subsampling=0)

            chunk_idx += 1
            y += CHUNK_HEIGHT

        return len(images), chunk_idx - 1

    def process_chapter_multi(
        self,
        img_urls: List[str],
        chapter_dir: Path,
        chapter_num: str,
        live=None,
        overall_progress=None,
        overall_task=None,
        step_task=None,
        stats_callback=None
    ) -> Tuple[int, int]:
        if not img_urls:
            return 0, 0

        temp_root = PathAuthority().get_temp_root()
        temp_root.mkdir(parents=True, exist_ok=True)
        safe_num = re.sub(r"[^\w.-]", "_", str(chapter_num))
        temp_dir = temp_root / f"topmanhua_ch_{safe_num}_{int(time.time()*1000)}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            total_imgs = len(img_urls)
            if step_task is not None and overall_progress is not None:
                overall_progress.update(step_task, total=total_imgs, completed=0, visible=True)

            ordered_temp_paths = [
                temp_dir / f"img_{str(idx+1).zfill(4)}.tmp"
                for idx in range(total_imgs)
            ]

            futures_map = {}
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
                for idx, src in enumerate(img_urls):
                    tpath = ordered_temp_paths[idx]
                    f = executor.submit(self.download_image, src, tpath, referer=f"https://{self.domain}/")
                    futures_map[f] = idx

                for future in as_completed(futures_map):
                    idx = futures_map[future]
                    res = future.result()
                    if res == 1:
                        self.consecutive_failures = 0
                        if stats_callback:
                            stats_callback({"type": "file_done", "size": ordered_temp_paths[idx].stat().st_size})
                    else:
                        self.consecutive_failures += 1
                        if stats_callback:
                            stats_callback({"type": "file_error"})

                    if step_task is not None and overall_progress is not None:
                        overall_progress.advance(step_task, 1)

            downloaded_paths = [p for p in ordered_temp_paths if p.exists() and p.stat().st_size > 0]
            if not downloaded_paths:
                return 0, 0

            chapter_dir.mkdir(parents=True, exist_ok=True)
            raw_count, chunk_count = self.slice_and_save(downloaded_paths, chapter_dir)
            return raw_count, chunk_count

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
