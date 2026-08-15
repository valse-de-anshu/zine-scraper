"""
OmegaScans Download Engine
===========================
Purpose-built for https://omegascans.org — NOT a copy of any other scraper.

Architecture (based on reverse-engineering the site):
  ┌─────────────────────────────────────────────┐
  │  omegascans.org  (Next.js frontend)          │
  │   ↓ REST API calls                           │
  │  api.omegascans.org  (chapter/image metadata)│
  │   ↓ image URLs                               │
  │  media.omegascans.org  (Backblaze B2 + CF)   │
  └─────────────────────────────────────────────┘

Key behaviours we handle:
  • API returns direct CDN image URLs — no encoding/obfuscation.
  • CDN has HTTP keep-alive: reusing the same session/connection per thread
    is dramatically faster than opening a fresh TLS handshake per image.
    Fix: thread-local sessions — one per worker thread, reused across all
    images that thread downloads.
  • Resume: if output slices already exist, skip the chapter entirely.
  • No artificial speed cutoffs or hard time limits that drop real pages.
"""

import os
import re
import sys
import time
import shutil
import logging
import threading
from pathlib import Path
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urljoin  # urljoin exported so scraper.py can import it

import requests
from PIL import Image

# ─── Logging setup ────────────────────────────────────────────────────────────
Image.MAX_IMAGE_PIXELS = None   # allow very tall webtoon strips
CHUNK_HEIGHT = 2000             # px height of each output slice

_log = logging.getLogger("omegascans")

# ─── Constants ────────────────────────────────────────────────────────────────
# OmegaScans-specific: images only ever come from media.omegascans.org
OMEGA_CDN_HOST   = "media.omegascans.org"
OMEGA_API_BASE   = "https://api.omegascans.org"
OMEGA_ORIGIN     = "https://omegascans.org"

VALID_IMAGE_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "image/avif", "image/gif", "image/bmp", "image/tiff",
}
MIME_TO_EXT = {
    "image/jpeg": ".jpg",  "image/jpg": ".jpg",
    "image/png":  ".png",  "image/webp": ".webp",
    "image/avif": ".avif", "image/gif":  ".gif",
    "image/bmp":  ".bmp",  "image/tiff": ".tiff",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp", ".tiff"}

# Browser-like headers that the frontend sends when fetching images
_IMG_HEADERS = {
    "User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept":            "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language":   "en-US,en;q=0.9",
    "Referer":           OMEGA_ORIGIN + "/",
    "Sec-Fetch-Dest":    "image",
    "Sec-Fetch-Mode":    "no-cors",
    "Sec-Fetch-Site":    "cross-site",
}

# Headers for API calls (JSON)
_API_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Origin":          OMEGA_ORIGIN,
    "Referer":         OMEGA_ORIGIN + "/",
}

# How many threads to use for downloading images within a chapter.
# 4 threads = 4 independent TCP connections → CDN gives each its own bandwidth bucket.
MAX_WORKERS = 4


# ─── URL validation (zero network) ────────────────────────────────────────────

def is_omega_image_url(url: str) -> bool:
    """
    Returns True only for real OmegaScans CDN image URLs.
    All real images come from media.omegascans.org with a known image extension.
    Decoy/tracker/ad URLs have different domains or no image extension — rejected.
    No network requests made.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        p = urlparse(url)
        host = p.netloc.lower()
        ext  = os.path.splitext(p.path.lower())[1]
        # Must be from the OmegaScans CDN host
        if host != OMEGA_CDN_HOST and not host.endswith("." + OMEGA_CDN_HOST):
            return False
        # Must have a known image extension
        if ext not in IMAGE_EXTS:
            return False
        return True
    except Exception:
        return False


# ─── Thread-local session pool ────────────────────────────────────────────────
# Each worker thread gets ONE persistent session reused for all its images.
# This keeps the TCP+TLS connection to the CDN alive between requests,
# matching browser behaviour and avoiding per-handshake throttling penalties.
_tls = threading.local()

def _get_thread_session() -> requests.Session:
    """Returns (or lazily creates) a per-thread requests.Session."""
    if not hasattr(_tls, "session"):
        s = requests.Session()
        s.headers.update(_IMG_HEADERS)
        # Allow up to MAX_WORKERS connections in the pool for this thread
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=2,
            pool_maxsize=4,
            max_retries=0,
        )
        s.mount("https://", adapter)
        s.mount("http://",  adapter)
        _tls.session = s
    return _tls.session


# ─── Single image downloader ───────────────────────────────────────────────────

def download_image(url: str, dest: Path) -> bool:
    """
    Download one image to `dest` using the calling thread's persistent session.

    Thread-local session design:
      The session is created once per worker thread and reused for every image
      that thread downloads. This keeps the HTTP keep-alive connection to the
      Backblaze B2 / Cloudflare CDN alive, so subsequent images on the same
      thread don't pay the TCP+TLS handshake cost — exactly what the browser does.

    Timeouts:
      (10, 60) — 10s connect, 60s read per socket call.
      Large images (4-5 MB) at CDN speeds need 20-60s.

    Returns True on success, False on any failure.
    Resume: if dest already exists and is ≥ 2 KB, returns True immediately.
    """
    # Resume: skip already-downloaded files
    if dest.exists() and dest.stat().st_size >= 2048:
        return True

    s = _get_thread_session()

    for attempt in range(2):  # 1 retry on transient errors
        try:
            r = s.get(url, timeout=(10, 60), stream=True)

            if r.status_code in (403, 404, 410, 500, 502, 503, 504):
                _log.debug(f"HTTP {r.status_code} for {url}")
                return False   # dead link — don't retry

            r.raise_for_status()

            # Validate Content-Type — reject tracker pixels / HTML error pages
            ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
            if ct and ct not in VALID_IMAGE_MIMES:
                _log.debug(f"Non-image content-type ({ct}) for {url}")
                return False

            # Honour real format from Content-Type (may differ from URL ext)
            real_ext = MIME_TO_EXT.get(ct, dest.suffix or ".jpg")
            if dest.suffix.lower() != real_ext:
                dest = dest.with_suffix(real_ext)

            # Write to .part file, rename on success (atomic)
            tmp = dest.with_suffix(dest.suffix + ".part")
            try:
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            except Exception:
                tmp.unlink(missing_ok=True)
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                return False

            if tmp.stat().st_size < 2048:
                tmp.unlink(missing_ok=True)
                return False

            tmp.rename(dest)
            return True

        except Exception as e:
            _log.debug(f"download_image attempt {attempt+1} error for {url}: {e}")
            dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
            if attempt == 0:
                time.sleep(0.5)

    return False


# ─── Chapter orchestrator ──────────────────────────────────────────────────────

def download_chapter(
    img_urls: List[str],
    folder: Path,
    ch_num: str,
    ch_url: str,
    stats_callback: Optional[Callable] = None,
) -> dict:
    """
    Downloads all pages of one chapter in parallel, then slices them into
    2000px-tall output chunks.

    Args:
        img_urls:       Raw image URL list from the OmegaScans API.
        folder:         Final output folder (e.g. Chapter 01/).
        ch_num:         Chapter number string for temp-dir naming.
        ch_url:         Chapter page URL used as Referer.
        stats_callback: Optional fn(dict) called with progress updates.

    Returns:
        {"total": int, "downloaded": int, "missing": int, "success": bool}
    """

    # ── 1. Filter to real CDN image URLs only (zero network) ─────────────────
    real_urls = [u for u in img_urls if is_omega_image_url(u)]
    total = len(real_urls)

    if not real_urls:
        return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

    _emit(stats_callback, {"total": total, "downloaded": 0, "missing": 0})

    # ── 2. Check if chapter output already exists (full resume) ──────────────
    existing_outputs = _existing_output_count(folder)
    if existing_outputs > 0:
        # Chapter was already sliced — skip entirely
        _log.info(f"Ch{ch_num}: already downloaded ({existing_outputs} slices), skipping")
        _emit(stats_callback, {"total": existing_outputs, "downloaded": existing_outputs,
                               "missing": 0, "success": True})
        return {"total": existing_outputs, "downloaded": existing_outputs,
                "missing": 0, "success": True}

    # ── 3. Create temp directory for raw downloaded images ───────────────────
    temp_dir = folder / f"_tmp_{ch_num}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    downloaded: List[Path] = []
    failed = 0
    lock = threading.Lock()

    def _dl(idx: int, url: str):
        nonlocal failed
        # Derive filename from URL path to preserve original ordering
        url_path = urlparse(url).path
        fname = os.path.basename(url_path)
        # Prefix with zero-padded index to guarantee sort order
        dest = temp_dir / f"{idx+1:03d}_{fname}"

        ok = download_image(url, dest)

        with lock:
            if ok:
                # Re-glob: download_image may have changed the extension
                actual = _find_file(temp_dir, f"{idx+1:03d}_")
                if actual:
                    downloaded.append(actual)
                else:
                    downloaded.append(dest)  # fallback
            else:
                failed += 1

        dl_count = len(downloaded)
        _emit(stats_callback, {"total": total, "downloaded": dl_count,
                               "missing": total - dl_count - failed})

    # ── 4. Parallel download with independent sessions per thread ─────────────
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = [pool.submit(_dl, i, url) for i, url in enumerate(real_urls)]
        for f in as_completed(futs):
            f.result()   # propagate exceptions (none expected, errors are silent)

    downloaded_count = len(downloaded)
    missing = total - downloaded_count

    if not downloaded:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"total": total, "downloaded": 0, "missing": total, "success": False}

    # ── 5. Slice downloaded images into 2000px output chunks ─────────────────
    _emit(stats_callback, {"total": total, "downloaded": downloaded_count,
                           "missing": missing, "status": "baking"})

    folder.mkdir(parents=True, exist_ok=True)
    slices = _slice_and_save(sorted(downloaded), folder)

    shutil.rmtree(temp_dir, ignore_errors=True)

    # Chapter succeeds if we downloaded ≥ 70% of pages and produced ≥ 1 slice
    min_ok = max(1, int(total * 0.70)) if total > 3 else total
    success = downloaded_count >= min_ok and slices > 0

    if success:
        return {"total": slices, "downloaded": slices, "missing": missing, "success": True}
    return {"total": total, "downloaded": downloaded_count, "missing": missing, "success": False}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _emit(cb, data: dict):
    if cb:
        try:
            cb(data)
        except Exception:
            pass


def _existing_output_count(folder: Path) -> int:
    """Returns number of valid image slices already in folder (ignoring temp dirs)."""
    if not folder.exists():
        return 0
    count = 0
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("_"):
            count += 1
    return count


def _find_file(directory: Path, prefix: str) -> Optional[Path]:
    """Find first file in directory matching the given prefix."""
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith(prefix):
            return p
    return None


def _slice_and_save(pages: List[Path], output_dir: Path) -> int:
    """
    Composites all downloaded pages into one tall vertical strip, then slices
    it into CHUNK_HEIGHT-pixel tall output images.

    Returns the number of slices saved.
    """
    output_dir = Path(output_dir)
    images = []
    source_exts = []

    for p in pages:
        try:
            img = Image.open(p)
            img.verify()
            img = Image.open(p)
            # Reject banners/ads: width more than 3× height = horizontal strip
            if img.width > img.height * 3.0:
                continue
            images.append(img)
            source_exts.append(p.suffix.lower())
        except Exception:
            continue

    if not images:
        return 0

    # Pick output format: use unanimous source format, fallback to JPEG
    unique_exts = set(source_exts) - {".bin"}
    if len(unique_exts) == 1:
        out_ext = unique_exts.pop()
        fmt_map = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
                   ".webp": "WEBP", ".avif": "AVIF", ".gif": "GIF", ".bmp": "BMP"}
        pil_fmt = fmt_map.get(out_ext, "JPEG")
        if out_ext == ".jpeg":
            out_ext = ".jpg"
    else:
        out_ext, pil_fmt = ".jpg", "JPEG"

    # Convert colour modes
    if pil_fmt == "JPEG":
        images = [i.convert("RGB") for i in images]
    elif pil_fmt in ("PNG", "WEBP"):
        images = [i.convert("RGBA") if i.mode in ("P", "LA") else i for i in images]

    widths, heights = zip(*(i.size for i in images))
    max_w   = max(widths)
    total_h = sum(heights)

    bg_mode  = "RGBA" if pil_fmt in ("PNG", "WEBP") else "RGB"
    bg_color = (255, 255, 255, 255) if bg_mode == "RGBA" else (255, 255, 255)
    canvas   = Image.new(bg_mode, (max_w, total_h), bg_color)

    y = 0
    for im in images:
        if im.mode != bg_mode:
            im = im.convert(bg_mode)
        canvas.paste(im, ((max_w - im.width) // 2, y))
        y += im.height

    save_kwargs = {}
    if pil_fmt == "JPEG":
        save_kwargs = {"quality": 90, "optimize": True}
    elif pil_fmt == "WEBP":
        save_kwargs = {"quality": 90, "method": 4}
    elif pil_fmt == "PNG":
        save_kwargs = {"optimize": True}

    output_dir.mkdir(parents=True, exist_ok=True)
    count = 1
    for top in range(0, total_h, CHUNK_HEIGHT):
        bottom = min(top + CHUNK_HEIGHT, total_h)
        if bottom - top < 50 and count > 1:
            break
        crop = canvas.crop((0, top, max_w, bottom))
        crop.save(output_dir / f"{count:03d}{out_ext}", pil_fmt, **save_kwargs)
        count += 1

    return count - 1


# ─── API Session helper (exported for scraper.py) ────────────────────────────

def make_api_session() -> requests.Session:
    """Returns a requests.Session configured for OmegaScans API calls."""
    s = requests.Session()
    s.headers.update(_API_HEADERS)
    return s
