import os
import re
import time
import random
import logging
import json
import shutil
import sys
import difflib
import urllib.parse
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
from bs4 import BeautifulSoup
from PIL import Image
from core.paths import PathAuthority, get_system_script

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

Image.MAX_IMAGE_PIXELS = None  # Allow processing huge strips
CHUNK_HEIGHT = 2000           # As per user script

# ─────────────────────────────────────────────────────────────────────────────
# Colors & Logging
# ─────────────────────────────────────────────────────────────────────────────


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

    IMAGE_DELAY = 0.7  # Balanced delay for speed and accuracy
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

    def resolve_canonical_url(self, url: str) -> Optional[str]:
        """
        Intelligently resolves mistyped slugs or stale deployment hashes on AsuraScans
        by searching the site and matching the closest series slug.
        Example:
          surviving-the-game-as-barbarian-7ba78ec7 -> surviving-the-game-as-a-barbarian-7ba78ec7
          surviving-the-game-as-a-barbarian-ab39de10 -> surviving-the-game-as-a-barbarian-7ba78ec7
        """
        if not HAS_CURL_CFFI:
            return None
        try:
            m = re.search(r'(/comics/([^/?#]+))', url)
            if not m:
                return None
            raw_slug = m.group(2)
            # Remove trailing 8-character hex hash if present (e.g. -7ba78ec7, -ab39de10)
            clean_slug = re.sub(r'-[0-9a-fA-F]{8}$', '', raw_slug)
            query = clean_slug.replace('-', ' ').strip()
            if not query:
                return None

            search_url = f"https://{self.domain}/?s={urllib.parse.quote_plus(query)}"
            r = cffi_requests.get(search_url, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                return None

            soup = BeautifulSoup(r.text, 'lxml')
            candidates = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/comics/' in href and '/chapter/' not in href:
                    cand_slug = href.split('/comics/')[-1].strip('/')
                    cand_clean = re.sub(r'-[0-9a-fA-F]{8}$', '', cand_slug)
                    candidates.append((cand_clean, href))

            if not candidates:
                return None

            best_match = None
            best_score = 0.0
            clean_words = set(clean_slug.lower().split('-'))
            for cand_clean, href in candidates:
                cand_words = set(cand_clean.lower().split('-'))
                seq_ratio = difflib.SequenceMatcher(None, clean_slug.lower(), cand_clean.lower()).ratio()
                overlap_ratio = len(clean_words & cand_words) / max(len(clean_words), 1)
                score = (seq_ratio * 0.5) + (overlap_ratio * 0.5)
                if score > best_score:
                    best_score = score
                    best_match = href

            if best_match and best_score >= 0.65:
                resolved = urllib.parse.urljoin(f"https://{self.domain}", best_match)
                if '/chapter/' in url:
                    ch_part = url.split('/chapter/')[-1]
                    resolved = f"{resolved.rstrip('/')}/chapter/{ch_part}"
                return resolved
        except Exception as e:
            logging.debug(f"[AsuraScans] resolve_canonical_url failed for {url}: {e}")
        return None

    def get_soup(self, url: str) -> BeautifulSoup:
        # Fast-path: curl_cffi with Chrome 124 TLS impersonation (bypasses Cloudflare Turnstile instantly)
        if HAS_CURL_CFFI:
            try:
                r = cffi_requests.get(url, impersonate="chrome124", timeout=20)
                if r.status_code == 200 and "challenges.cloudflare.com" not in r.text:
                    return BeautifulSoup(r.text, "lxml")
                elif r.status_code == 404:
                    # Attempt intelligent auto-resolution for mistyped or stale hash slugs
                    resolved_url = self.resolve_canonical_url(url)
                    if resolved_url and resolved_url != url:
                        logging.info(f"[AsuraScans] Auto-resolved stale or mistyped slug: {url} -> {resolved_url}")
                        self.url = resolved_url
                        r_res = cffi_requests.get(resolved_url, impersonate="chrome124", timeout=20)
                        if r_res.status_code == 200 and "challenges.cloudflare.com" not in r_res.text:
                            return BeautifulSoup(r_res.text, "lxml")
                    raise RuntimeError(f"404 Not Found: '{url}' does not exist on AsuraScans. Please verify the comic title/slug.")
                elif r.status_code == 200:
                    logging.debug(f"[AsuraScans] Cloudflare challenge detected on {url}")
            except RuntimeError:
                raise
            except Exception as e:
                logging.debug(f"[AsuraScans] curl_cffi request failed for {url}: {e}")

        # Secondary fallback: Headless Playwright extractor
        try:
            import subprocess
            script_path = get_system_script("playwright_extractor.py")
            if script_path and Path(script_path).exists():
                cmd = [sys.executable, str(script_path), url]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if "JSON_RESULT:" in res.stdout:
                    out_json = res.stdout.split("JSON_RESULT:")[-1].strip()
                    data = json.loads(out_json)
                    html_content = data.get("html", "")
                    if html_content:
                        return BeautifulSoup(html_content, "lxml")
        except Exception as e:
            logging.debug(f"[AsuraScans] playwright_extractor fallback failed for {url}: {e}")

        # Final fallback: Standard requests session
        for attempt in range(2):
            try:
                r = self.session.get(url, timeout=20)
                r.raise_for_status()
                content = r.content.decode("utf-8", errors="replace")
                return BeautifulSoup(content, "lxml")
            except Exception:
                time.sleep(1 + attempt)
        raise RuntimeError(f"Failed page: {url}")

    def download_image(self, src: str, path: Path, referer: str = None) -> int:
        """Download a single image, preserving its original format.
        Returns 1 on success, -1 on dead/fake link or retriable failure."""
        if not src or not isinstance(src, str) or not src.strip().startswith("http"):
            return -1

        src = src.strip()
        time.sleep(self.IMAGE_DELAY + random.uniform(0, 0.2))
        for attempt in range(2):
            try:
                headers = HEADERS.copy()

                # Attempt 1: Base domain referer
                headers["Referer"] = f"https://{self.domain}/"
                r = self.session.get(src, stream=True, timeout=(8, 15), headers=headers)

                if r.status_code == 403 and referer:
                    # Attempt 2: Chapter page as referer
                    headers["Referer"] = referer
                    r = self.session.get(src, stream=True, timeout=(8, 15), headers=headers)

                if r.status_code == 403:
                    # Attempt 3: No referer
                    headers.pop("Referer", None)
                    r = self.session.get(src, stream=True, timeout=(8, 15), headers=headers)

                if r.status_code == 403 and HAS_CURL_CFFI:
                    # Attempt 4: curl_cffi Chrome impersonation
                    headers["Referer"] = referer or f"https://{self.domain}/"
                    r = cffi_requests.get(src, stream=True, impersonate="chrome124", timeout=(8, 15), headers=headers)

                if r.status_code in (400, 403, 404, 410, 422, 500, 502, 503, 504):
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

                if path.stat().st_size < 1500:
                    path.unlink(missing_ok=True)
                    return -1

                self.consecutive_failures = 0
                return 1
            except Exception:
                if path.exists():
                    path.unlink(missing_ok=True)
                if attempt == 0:
                    time.sleep(0.5)

        return -1

    def download_cover(self, folder: Path):
        """Download cover image, ensuring binary magic-byte integrity and universal preview compatibility."""
        cover_url = getattr(self, "cover_url", None)
        if not cover_url:
            try:
                from core.cover_utils import extract_cover_url
                soup = self.get_soup(self.url)
                cover_url = extract_cover_url(soup, self.url)
            except Exception:
                pass

        if not cover_url:
            return

        # Recognise any existing cover regardless of extension
        if folder.exists() and list(folder.glob("cover.*")):
            return

        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)

        from core.paths import PathAuthority
        temp_root = PathAuthority().get_temp_root()
        temp_root.mkdir(parents=True, exist_ok=True)
        raw_temp = temp_root / f"asura_cover_{int(time.time() * 1000)}.tmp"

        for attempt in range(1, 4):
            try:
                headers = HEADERS.copy()
                headers["Referer"] = f"https://{self.domain}/"
                r = self.session.get(cover_url, stream=True, timeout=(10, 25), headers=headers)
                if r.status_code == 403:
                    headers.pop("Referer", None)
                    r = self.session.get(cover_url, stream=True, timeout=(10, 25), headers=headers)
                if r.status_code == 403 and HAS_CURL_CFFI:
                    headers["Referer"] = f"https://{self.domain}/"
                    r = cffi_requests.get(cover_url, stream=True, impersonate="chrome124", timeout=(10, 25), headers=headers)

                if r.status_code == 200:
                    with open(raw_temp, "wb") as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            if chunk:
                                f.write(chunk)

                    if raw_temp.exists() and raw_temp.stat().st_size > 500:
                        header_bytes = raw_temp.read_bytes()[:16]
                        real_format = None
                        if header_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                            real_format = "PNG"
                        elif header_bytes.startswith(b"\xff\xd8\xff"):
                            real_format = "JPEG"
                        elif header_bytes.startswith(b"RIFF") and b"WEBP" in header_bytes:
                            real_format = "WEBP"
                        elif header_bytes.startswith(b"GIF8"):
                            real_format = "GIF"

                        try:
                            with Image.open(raw_temp) as im:
                                if real_format == "PNG" or raw_temp.stat().st_size > 1_500_000 or real_format not in ("JPEG", "WEBP"):
                                    target_cover = folder / "cover.jpg"
                                    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                                        bg = Image.new("RGB", im.size, (255, 255, 255))
                                        bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                                        bg.save(target_cover, "JPEG", quality=95, optimize=True)
                                    else:
                                        im.convert("RGB").save(target_cover, "JPEG", quality=95, optimize=True)
                                    logging.info("Cover: Saved as optimized JPEG")
                                    return
                                elif real_format == "WEBP":
                                    target_cover = folder / "cover.webp"
                                    shutil.copy2(raw_temp, target_cover)
                                    logging.info("Cover: Saved as WebP")
                                    return
                                else:
                                    target_cover = folder / "cover.jpg"
                                    shutil.copy2(raw_temp, target_cover)
                                    logging.info("Cover: Saved as JPEG")
                                    return
                        except Exception as e:
                            logging.debug(f"PIL cover processing failed: {e}, falling back to copy")
                            ext_final = ".png" if real_format == "PNG" else (".webp" if real_format == "WEBP" else ".jpg")
                            shutil.copy2(raw_temp, folder / f"cover{ext_final}")
                            logging.info("Cover: Saved")
                            return
            except Exception as e:
                logging.debug(f"Cover attempt {attempt} failed: {e}")
            finally:
                if raw_temp.exists():
                    raw_temp.unlink(missing_ok=True)

            if attempt < 3:
                time.sleep(2)

        logging.error("Cover: Failed after 3 tries")

    def process_chapter_multi(self, img_urls: List[str], folder: Path, ch_num: str, ch_url: str, live=None, stats_callback=None) -> dict:
        self.consecutive_failures = 0
        safe_num = re.sub(r"[^\w.-]", "_", str(ch_num))
        temp_dir = PathAuthority().get_temp_root() / f"asura_ch_{safe_num}_{int(time.time() * 1000)}"
        temp_dir.mkdir(exist_ok=True, parents=True)
        paths = []
        try:
        
            clean_urls = [u for u in img_urls if u and isinstance(u, str) and u.strip().startswith("http")]
            total_pages = len(clean_urls)
        
            if total_pages == 0:
                return {"total": 0, "downloaded": 0, "missing": 0, "success": False}
        
            # Fire initial callback so UI knows total pages immediately
            if stats_callback:
                stats_callback({"total": total_pages, "downloaded": 0, "missing": 0})
        
            def dl_task(idx, src):
                p = temp_dir / f"{idx+1:03d}.bin"
                res = self.download_image(src, p, referer=ch_url)
                if res == 1:
                    candidates = list(temp_dir.glob(f"{idx+1:03d}.*"))
                    actual_p = candidates[0] if candidates else p
                    return (1, actual_p)
                return (-1, None)

            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
                futures = [executor.submit(dl_task, i, src) for i, src in enumerate(clean_urls)]
                valid_pages = total_pages
                for future in as_completed(futures):
                    res_code, p = future.result()
                    if res_code == 1: 
                        paths.append(p)
                    else:
                        valid_pages -= 1
                    
                    if stats_callback:
                        stats_callback({"total": valid_pages, "downloaded": len(paths), "missing": max(0, valid_pages - len(paths))})
        
            missing = max(0, valid_pages - len(paths))
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

            min_ok = max(1, int(total_pages * 0.70)) if total_pages > 3 else 1
            success = (len(paths) >= valid_pages and len(paths) > 0) or (len(paths) >= min_ok and final_chunks > 0)
            
        
            if success and final_chunks:
                return {"total": final_chunks, "downloaded": final_chunks, "missing": missing, "success": success}
            return {"total": valid_pages, "downloaded": len(paths), "missing": missing, "success": success}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
