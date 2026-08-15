"""
scrapers/hentaicity/engine.py
------------------------------
Download engine for HentaiCity.

Handles two content types:
  video   → Extracts 1080p m3u8 from HLS master playlist, downloads via yt-dlp + aria2c
  gallery → Downloads all JPG images concurrently via ThreadPoolExecutor
"""

import re
import sys
import json
import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional

from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.hentaicity.com/",
}


class HentaicityEngine(VideoEngine):

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        # Pool size raised to 20 so 16 concurrent gallery threads never wait for a connection slot
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(HEADERS)

    # ── Metadata / cover ─────────────────────────────────────────────────

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        if not avatar_url:
            return False
        try:
            r = self.session.get(avatar_url, timeout=20)
            r.raise_for_status()
            
            ct = r.headers.get("Content-Type", "").lower().split(";")[0].strip()
            mime_map = {
                "image/jpeg": ".jpg", "image/jpg": ".jpg",
                "image/png": ".png", "image/webp": ".webp",
                "image/avif": ".avif", "image/gif": ".gif"
            }
            real_ext = mime_map.get(ct, dest.suffix or ".jpg")
            if dest.suffix.lower() != real_ext:
                dest = dest.with_suffix(real_ext)
                
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
        except Exception:
            return False

    def save_metadata(self, root_dir: Path, info: Dict[str, Any], source: str,
                      model_name: str, avatar_url: Optional[str] = None,
                      videos: Optional[list] = None, skip_cover: bool = False,
                      custom_metadata: Optional[Dict[str, Any]] = None):
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        video_list = videos or []
        url = info.get("url", "")
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]
            
        studio = custom_metadata.get("Studio", "") if custom_metadata else ""
        tags = custom_metadata.get("Tags", "") if custom_metadata else ""
        summary = custom_metadata.get("Description", "") if custom_metadata else ""

        metadata_content = {
            "Series": model_name,
            "Source": source,
            "URL": url,
            "Total Videos": len(video_list),
            "Studio": studio,
            "Tags": tags,
            "Summary": summary,
            "videos": video_list
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_content, f, indent=2, ensure_ascii=False)

        if not skip_cover and avatar_url:
            cover_path = root_dir / "cover.jpg"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

    # ── HLS quality selection ─────────────────────────────────────────────

    def download_hentaicity_image(self, img_url: str, path: Path) -> bool:
        """
        Downloads a single gallery image.
        Uses 3 attempts with increasing timeouts.
        """
        import time
        import random
        # Tiny random jitter so threads don't blast CDN in perfect sync
        time.sleep(random.uniform(0, 0.08))
        for attempt, timeout in enumerate([20, 30, 45], 1):
            try:
                r = self.session.get(img_url, timeout=timeout, stream=True)
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=131072):
                        f.write(chunk)
                return True
            except Exception as e:
                if attempt == 3:
                    logger.warning(f"HentaiCity gallery image failed after {attempt} attempts: {e}")
                    return False
                time.sleep(1)
        return False

    def _pick_best_quality(self, master_m3u8_url: str) -> str:
        """
        Parses a HentaiCity master.m3u8 and returns the URL of the
        highest-bandwidth variant stream (usually 1080p).
        """
        try:
            res = self.session.get(master_m3u8_url, timeout=10)
            if res.status_code != 200:
                return master_m3u8_url

            lines = res.text.strip().splitlines()
            best_bw = -1
            best_url = ""
            base = master_m3u8_url.rsplit("master.m3u8", 1)[0]

            i = 0
            while i < len(lines):
                line = lines[i]
                if line.startswith("#EXT-X-STREAM-INF"):
                    bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                    bw = int(bw_match.group(1)) if bw_match else 0
                    if i + 1 < len(lines):
                        variant_url = lines[i + 1].strip()
                        if not variant_url.startswith("http"):
                            variant_url = base + variant_url
                        if bw > best_bw:
                            best_bw = bw
                            best_url = variant_url
                    i += 2
                else:
                    i += 1

            return best_url or master_m3u8_url
        except Exception as e:
            logger.warning(f"Could not parse master m3u8: {e}")
            return master_m3u8_url

    # ── Stream URL extraction ─────────────────────────────────────────────

    def extract_stream_url(self, page_url: str) -> str:
        """
        Fetches the video page and extracts the 1080p HLS stream URL.
        Falls back to the mobile mp4 URL if HLS is unavailable.
        """
        try:
            res = self.session.get(page_url, timeout=15)
            res.raise_for_status()
            html = res.text

            m3u8_match = re.search(
                r"(https://hls\.hentaicity\.com/[^\"' <>]+master\.m3u8[^\"' <>]*)",
                html
            )
            if m3u8_match:
                master_url = m3u8_match.group(1).replace("&amp;", "&")
                best = self._pick_best_quality(master_url)
                logger.info(f"HentaiCity: Using HLS stream: {best[:80]}")
                return best

            # Fallback: direct mp4
            mp4_match = re.search(
                r"(https://www\.hentaicity\.com/flv/[^\"' <>]+\.mp4)",
                html
            )
            if mp4_match:
                logger.info(f"HentaiCity: HLS not found, falling back to mobile.mp4")
                return mp4_match.group(1)

        except Exception as e:
            logger.error(f"HentaiCity stream extraction failed for {page_url}: {e}")

        return ""

    # ── Video download ────────────────────────────────────────────────────

    def download_hentaicity_video(
        self,
        page_url: str,
        output_dir: Path,
        progress_hook=None,
        is_audio: bool = False,
        custom_thumbnail=None,
        fixed_title: str = "",
        fixed_artist: str = "",
        pre_extracted_stream: str = "",
        **kwargs,
    ) -> bool:
        """
        Downloads a HentaiCity video at maximum quality.
        Uses pre_extracted_stream if already known (avoids re-fetching the page).
        """
        stream_url = pre_extracted_stream or self.extract_stream_url(page_url)
        if not stream_url:
            logger.error(f"HentaiCity: No stream URL found for {page_url}")
            return False

        try:
            return self.download_video(
                url=page_url,
                output_dir=output_dir,
                progress_hook=progress_hook or (lambda d: None),
                raw_stream_url=stream_url,
                is_audio=is_audio,
                fixed_title=fixed_title,
                fixed_artist=fixed_artist,
            )
        except Exception as e:
            logger.error(f"HentaiCity download_video failed: {e}")
            return False

    # ── Gallery image download ────────────────────────────────────────────

    def download_gallery_images(
        self,
        image_urls: list,
        output_dir: Path,
        progress_callback=None,
        max_workers: int = 8,
    ) -> int:
        """
        Downloads all images in a gallery concurrently.
        Returns the number of successfully downloaded images.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = 0
        total = len(image_urls)

        def _dl(idx: int, url: str):
            ext = url.rsplit(".", 1)[-1].split("?")[0] or "jpg"
            path = output_dir / f"{idx:04d}.{ext}"
            if path.exists():
                return True
            try:
                r = self.session.get(url, timeout=20, stream=True)
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
                return True
            except Exception as e:
                logger.warning(f"HentaiCity gallery image {idx} failed: {e}")
                return False

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_dl, idx, url): idx for idx, url in enumerate(image_urls, 1)}
            for future in as_completed(futures):
                if future.result():
                    downloaded += 1
                if progress_callback:
                    progress_callback({"downloaded": downloaded, "total": total})

        return downloaded
