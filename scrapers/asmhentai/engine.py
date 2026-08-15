import os
import re
import time
import random
import logging
import shutil
import sys
from pathlib import Path
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

Image.MAX_IMAGE_PIXELS = None
CHUNK_HEIGHT = 2000

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

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

# Setup logging — silent (no stdout handler)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)


class BaseScraper:
    scraper_type = "toon"

    IMAGE_DELAY = 0.7
    MAX_CONSECUTIVE_FAILURES = 5
    MAX_WORKERS = 3

    # Supported image MIME types — accept and preserve all common formats
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
        self.domain = self.url.split("/")[2].lower()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.session.headers["Referer"] = f"https://{self.domain}/"
        self.consecutive_failures = 0

    def get_soup(self, url: str) -> BeautifulSoup:
        for attempt in range(5):
            try:
                r = self.session.get(url, timeout=35)
                r.raise_for_status()
                r.encoding = "utf-8"
                return BeautifulSoup(r.text, "lxml")
            except Exception as e:
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Failed page: {url}")

    def download_image(self, src: str, path: Path, referer: str = None) -> int:
        """Download a single image, preserving its original format.
        Returns 1 on success, -1 on dead/fake link, 0 on retriable failure."""
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            return 0

        time.sleep(self.IMAGE_DELAY + random.uniform(0, 0.5))
        for attempt in range(3):
            try:
                headers = HEADERS.copy()

                # Attempt 1: Base domain referer
                headers["Referer"] = f"https://{self.domain}/"
                r = self.session.get(src, stream=True, timeout=30, headers=headers)

                if r.status_code == 403 and referer:
                    # Attempt 2: Chapter page as referer
                    headers["Referer"] = referer
                    r = self.session.get(src, stream=True, timeout=30, headers=headers)

                if r.status_code == 403:
                    # Attempt 3: No referer
                    headers.pop("Referer", None)
                    r = self.session.get(src, stream=True, timeout=30, headers=headers)

                if r.status_code in (403, 404):
                    return -1

                r.raise_for_status()

                # Verify Content-Type is a real image — reject trackers/ads
                ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
                if ct and ct not in self.VALID_IMAGE_MIMES:
                    logging.debug(f"Rejected non-image response ({ct}) for {src}")
                    return -1

                # Preserve original extension from Content-Type
                real_ext = self.MIME_TO_EXT.get(ct, path.suffix or ".jpg")
                if path.suffix.lower() != real_ext:
                    path = path.with_suffix(real_ext)

                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)

                if path.stat().st_size < 2000:
                    path.unlink()
                    return -1

                self.consecutive_failures = 0
                return 1
            except Exception:
                if path.exists(): path.unlink()
                time.sleep(1)

        self.consecutive_failures += 1
        return 0

    def download_cover(self, folder: Path):
        """Download cover image, preserving original format. Skips if any cover.* already exists."""
        cover_url = getattr(self, "cover_url", None)
        if not cover_url:
            return

        # Recognise any existing cover regardless of extension
        if folder.exists() and list(folder.glob("cover.*")):
            return

        from urllib.parse import urlparse
        ext = Path(urlparse(cover_url).path).suffix or ".jpg"
        path = folder / f"cover{ext}"

        for attempt in range(1, 4):
            if self.download_image(cover_url, path) == 1:
                logging.info("Cover: Saved")
                return
            if attempt < 3:
                time.sleep(2)

        logging.error("Cover: Failed after 3 tries")

    def process_chapter_multi(self, img_urls: List[str], folder: Path, ch_num: str, ch_url: str, live=None, stats_callback=None) -> dict:
        temp_dir = folder / f"_temp_{ch_num}"
        temp_dir.mkdir(exist_ok=True, parents=True)
        paths = []

        total_pages = len(img_urls)

        if stats_callback:
            stats_callback({"total": total_pages, "downloaded": 0, "missing": 0})

        def dl_task(idx, src):
            # Use neutral ext — download_image renames to real format
            p = temp_dir / f"{idx+1:03d}.bin"
            res = self.download_image(src, p, referer=ch_url)
            if res == 1:
                # Find the renamed file (download_image may have changed the extension)
                candidates = list(temp_dir.glob(f"{idx+1:03d}.*"))
                actual_p = candidates[0] if candidates else p
                return (1, actual_p)
            elif res == -1:
                return (-1, None)
            return (0, None)

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            futures = [executor.submit(dl_task, i, src) for i, src in enumerate(img_urls)]
            valid_pages = total_pages
            for future in as_completed(futures):
                res_code, p = future.result()
                if res_code == 1:
                    paths.append(p)
                elif res_code == -1:
                    valid_pages -= 1

                if stats_callback:
                    stats_callback({"total": valid_pages, "downloaded": len(paths), "missing": valid_pages - len(paths)})

        success = False
        missing = valid_pages - len(paths)
        final_chunks = 0
        if paths:
            if stats_callback:
                stats_callback({"total": valid_pages, "downloaded": len(paths), "missing": missing, "status": "baking"})
            with ThreadPoolExecutor(max_workers=1) as slice_exec:
                slice_future = slice_exec.submit(self.slice_and_save, paths, folder)
                while not slice_future.done():
                    if stats_callback:
                        stats_callback({"total": valid_pages, "downloaded": len(paths), "missing": missing, "status": "baking"})
                    time.sleep(0.1)
                final_chunks = slice_future.result()
            if len(paths) == valid_pages:
                success = True

        shutil.rmtree(temp_dir, ignore_errors=True)

        if success and final_chunks:
            return {"total": final_chunks, "downloaded": final_chunks, "missing": missing, "success": success}
        return {"total": valid_pages, "downloaded": len(paths), "missing": missing, "success": success}

    def slice_and_save(self, paths: List[Path], output_dir: Path):
        """Combine images into a vertical canvas, slice into 2000px chunks.
        Preserves original format — JPEG only when formats are mixed or unknown."""
        images = []
        source_formats = []

        for p in sorted(paths):
            try:
                img = Image.open(p)
                img.verify()
                img = Image.open(p)  # reopen after verify
                # Skip extremely wide images (ads/banners)
                if img.width > img.height * 3.0:
                    continue
                images.append(img)
                source_formats.append(p.suffix.lower())
            except Exception:
                pass

        if not images:
            return 0

        output_dir.mkdir(exist_ok=True, parents=True)

        # Choose output format: unanimous source wins; else fallback to JPEG
        unique_fmts = set(source_formats) - {".bin", ".tmp", ""}
        if len(unique_fmts) == 1:
            out_ext = unique_fmts.pop()
            fmt_map = {
                ".jpg": "JPEG", ".jpeg": "JPEG",
                ".png": "PNG",
                ".webp": "WEBP",
                ".avif": "AVIF",
                ".gif": "GIF",
                ".bmp": "BMP",
            }
            pil_fmt = fmt_map.get(out_ext, "JPEG")
        else:
            out_ext = ".jpg"
            pil_fmt = "JPEG"

        # Mode conversion only when necessary
        if pil_fmt == "JPEG":
            images = [img.convert("RGB") for img in images]
        elif pil_fmt in ("PNG", "WEBP"):
            images = [
                img.convert("RGBA") if img.mode in ("P", "LA") else img
                for img in images
            ]

        widths, heights = zip(*(im.size for im in images))
        max_w = max(widths)
        total_h = sum(heights)

        bg_color = (255, 255, 255, 255) if pil_fmt in ("PNG", "WEBP") else (255, 255, 255)
        canvas_mode = "RGBA" if pil_fmt in ("PNG", "WEBP") else "RGB"
        canvas = Image.new(canvas_mode, (max_w, total_h), bg_color)
        y_offset = 0
        for im in images:
            if im.mode != canvas_mode:
                im = im.convert(canvas_mode)
            canvas.paste(im, ((max_w - im.width) // 2, y_offset))
            y_offset += im.height

        save_kwargs = {}
        if pil_fmt == "JPEG":
            save_kwargs = {"quality": 90, "optimize": True}
        elif pil_fmt == "WEBP":
            save_kwargs = {"quality": 90, "method": 4}
        elif pil_fmt == "PNG":
            save_kwargs = {"optimize": True}

        count = 1
        for top in range(0, total_h, CHUNK_HEIGHT):
            bottom = min(top + CHUNK_HEIGHT, total_h)
            if bottom - top < 50 and count > 1:
                break  # skip tiny remainder slices
            crop = canvas.crop((0, top, max_w, bottom))
            output_path = output_dir / f"{count:03d}{out_ext}"
            crop.save(output_path, pil_fmt, **save_kwargs)
            count += 1

        return count - 1
