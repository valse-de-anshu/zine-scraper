"""
scrapers/hentaihaven/engine.py
--------------------------
HentaiHaven download engine — extends core VideoEngine with HentaiHaven-specific
quality selection (1080p priority), avatar/cover downloading, and metadata.json.

Key fixes (v2):
  - All string fields are html.unescape() decoded before writing to JSON
  - metadata.json uses real video IDs (viewkeys) as keys, not array indices
  - history.json date format is YYYY-MM-DD (from yt-dlp upload_date YYYYMMDD)
  - most_viewed / top_rated / latest / longest all use real fetched metadata
  - Geo-block detection with clear user message
"""

import re
import json
import html as html_module
import logging
import subprocess
import tempfile
import os
from curl_cffi import requests
from pathlib import Path
from typing import Dict, Any, Callable, Optional, List
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

GEO_ERROR_PATTERNS = [
    "403",
    "451",
    "not available in your country",
    "geo",
    "region",
    "access denied",
]


def _is_geo_error(error_text: str) -> bool:
    lower = error_text.lower()
    return any(p in lower for p in GEO_ERROR_PATTERNS)


def _decode(raw: str) -> str:
    """Decode HTML entities + unescape backslash sequences."""
    if not raw:
        return raw
    return html_module.unescape(raw).replace("\\/", "/").replace("\\u002F", "/")


def _fmt_date(upload_date: str) -> str:
    """
    Convert yt-dlp upload_date (YYYYMMDD string) to YYYY-MM-DD.
    Falls back to original string on any parse error.
    """
    if not upload_date:
        return ""
    d = str(upload_date).strip().replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return upload_date  # already formatted or unknown


def _clean_title(raw: str) -> str:
    """
    Clean a video title:
    - HTML-decode entities
    - Remove trailing ' - <uploader>' suffix that PH often appends
    """
    t = _decode(raw or "")
    # PH appends " - <model_name>" to titles — strip it
    # Pattern: " - miulio" at the end
    t = re.sub(r'\s*-\s*\w+\s*$', '', t).strip()
    return t or raw or "Unknown"


class HentaiHavenEngine(VideoEngine):
    """
    Download engine for HentaiHaven content.
    Wraps yt-dlp with HentaiHaven-specific format selection and cover logic.
    """

    def __init__(self):
        super().__init__(headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept":          "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer":         "https://www.hentaihaven.com/",
        })

    # ─── Single video info ────────────────────────────────────────────────

    def extract_stream_url(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extracts (stream_url, title, cover_url) from an episode page without Playwright.
        """
        if ".m3u8" in url or ".mp4" in url:
            return url, None, None

        try:
            from bs4 import BeautifulSoup
            r = requests.get(url, headers=self.headers, timeout=15, impersonate="chrome124")
            r.raise_for_status()
            html = r.text
            soup = BeautifulSoup(html, "html.parser")

            stream_url = None
            title = None
            cover_url = None

            for s in soup.select('script[type="application/ld+json"]'):
                try:
                    data = json.loads(s.string)
                    if isinstance(data, dict):
                        if data.get("@type") == "VideoObject":
                            stream_url = data.get("contentUrl")
                            title = data.get("name")
                            thumbs = data.get("thumbnailUrl", [])
                            if thumbs:
                                cover_url = thumbs[0]
                        elif "@graph" in data:
                            graph = data.get("graph") if isinstance(data.get("graph"), list) else data.get("@graph", [])
                            for g in graph:
                                if g.get("@type") == "VideoObject":
                                    stream_url = g.get("contentUrl")
                                    title = g.get("name")
                                    thumbs = g.get("thumbnailUrl", [])
                                    if thumbs:
                                        cover_url = thumbs[0]
                except Exception:
                    pass

            if not stream_url:
                source_tag = soup.select_one("source[src*='.m3u8'], source[src*='.mp4'], video source[src]")
                if source_tag and source_tag.get("src"):
                    stream_url = source_tag["src"]

            if not stream_url:
                m3u_match = re.search(r'https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*', html)
                if m3u_match:
                    stream_url = m3u_match.group(0)

            return stream_url, title, cover_url
        except Exception as e:
            logger.error(f"[HentaiHaven] Failed to extract stream URL from {url}: {e}")
            return None, None, None

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        """
        Returns info dict for a single HentaiHaven video.
        """
        stream_url, title, cover = self.extract_stream_url(url)
        return {
            "id": url.strip("/").split("/")[-1],
            "title": title or url.strip("/").split("/")[-1],
            "webpage_url": url,
            "url": stream_url or url,
            "thumbnail": cover,
            "upload_date": "20260101",
            "view_count": 0,
            "like_count": 0,
            "duration": 0,
        }

    # ─── Avatar download ─────────────────────────────────────────────────

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        """Downloads the model profile picture and saves as cover.png."""
        if not avatar_url:
            return False
        try:
            r = requests.get(avatar_url, headers=self.headers, timeout=20, impersonate="chrome124")
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
            logger.info(f"HentaiHaven cover saved to {dest}")
            return True
        except Exception as e:
            logger.error(f"Failed to download HentaiHaven avatar from {avatar_url}: {e}")
            return False

    # ─── metadata.json writer ────────────────────────────────────────────

    def save_metadata(
        self,
        root_dir: Path,
        info: Dict[str, Any],
        source: str,
        model_name: str,
        avatar_url: Optional[str] = None,
        videos: Optional[List[Dict[str, Any]]] = None,
        skip_cover: bool = False,
    ):
        """
        Writes .zine/metadata.json with:
          - Clean model name (HTML decoded)
          - sorted lists: most_viewed, top_rated, latest, longest
          - All titles HTML decoded, no garbage
        Also downloads cover.png if not already present.
        """
        zine_dir = root_dir / ".zine"
        zine_dir.mkdir(parents=True, exist_ok=True)
        meta_path = zine_dir / "metadata.json"

        video_list = videos or []

        # ── Sort lists (use real metadata, skip entries with zero values) ─
        def _entry(v: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id":          v.get("id", ""),
                "title":       _decode(v.get("title", "") or ""),
                "upload_date": _fmt_date(v.get("upload_date", "") or ""),
                "view_count":  v.get("view_count", 0) or 0,
                "like_count":  v.get("like_count",  0) or 0,
                "duration":    v.get("duration",    0) or 0,
                "url":         v.get("url", ""),
            }

        all_entries = [_entry(v) for v in video_list]

        # most_viewed — descending view_count (only entries that have counts)
        most_viewed = sorted(
            [e for e in all_entries if e["view_count"] > 0],
            key=lambda e: e["view_count"], reverse=True
        )[:10] or all_entries[:10]

        # top_rated — descending like_count
        top_rated = sorted(
            [e for e in all_entries if e["like_count"] > 0],
            key=lambda e: e["like_count"], reverse=True
        )[:10] or all_entries[:10]

        # latest — descending upload_date (ISO string, lexicographic sort works)
        latest = sorted(
            [e for e in all_entries if e["upload_date"]],
            key=lambda e: e["upload_date"], reverse=True
        )[:10]

        # longest — descending duration in seconds
        longest = sorted(
            [e for e in all_entries if e["duration"] > 0],
            key=lambda e: e["duration"], reverse=True
        )[:10] or all_entries[:10]

        # ── Build clean metadata dict ─────────────────────────────────
        metadata_content = {
            "model_name":   _decode(model_name),
            "source":       source,
            "url":          info.get("webpage_url") or info.get("original_url") or info.get("url") or "",
            "total_videos": len(video_list),
            "most_viewed":  most_viewed,
            "top_rated":    top_rated,
            "latest":       latest,
            "longest":      longest,
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata_content, f, indent=2, ensure_ascii=False)

        logger.info(f"HentaiHaven metadata saved to {meta_path}")

        # ── Download cover.png ────────────────────────────────────────
        if not skip_cover:
            cover_path = root_dir / "cover.png"
            if not cover_path.exists() and avatar_url:
                self.download_avatar(avatar_url, cover_path)

    # ─── Video download ──────────────────────────────────────────────────

    def download_hentaihaven_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook: Callable,
        quality: str = "1080p",
        fixed_title: Optional[str] = None,
    ) -> bool:
        """
        Downloads a single HentaiHaven video using direct stream extraction and yt-dlp native HLS.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        if fixed_title:
            clean_title = "".join(
                c for c in fixed_title if c.isalnum() or c in " .-_()'"
            ).strip()
            clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip()
            if not clean_title:
                clean_title = "video"
        else:
            clean_title = "video"

        stream_url = url
        if not (".m3u8" in url or ".mp4" in url):
            stream_url, _, _ = self.extract_stream_url(url)

        if not stream_url:
            logger.error(f"[HentaiHaven] Could not extract stream URL for {url}")
            return False

        result_path = output_dir / f"{clean_title}.mp4"
        outtmpl = str(output_dir / f"{clean_title}.%(ext)s")

        import shutil
        yt_dlp_path = shutil.which("yt-dlp") or "yt-dlp"

        m_domain = re.search(r"https?://([^/]+)", url)
        domain = m_domain.group(1) if m_domain else "hentaihaven.xxx"
        referer = f"https://{domain}/"

        cmd = [
            yt_dlp_path,
            stream_url,
            "-o", outtmpl,
            "--hls-prefer-native",
            "--add-header", f"Referer:{referer}",
            "--add-header", f"Origin:{referer.rstrip('/')}",
            "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--merge-output-format", "mp4",
            "-f", "bestvideo+bestaudio/best",
            "--retries", "10",
            "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "--no-check-certificate",
            "--no-warnings",
            "--socket-timeout", "15",
        ]

        try:
            success = self._run_ytdlp_subprocess(
                cmd, progress_hook, str(result_path)
            )

            if success and result_path.exists() and result_path.stat().st_size > 1000:
                return True

            for candidate in output_dir.glob(f"{clean_title}.*"):
                if candidate.suffix.lower() in [".mp4", ".mkv", ".webm"] and candidate.stat().st_size > 1000:
                    if candidate.suffix.lower() != ".mp4":
                        candidate.rename(result_path)
                    return True

            return False
        except Exception as e:
            err = str(e)
            if _is_geo_error(err):
                logger.error(
                    "HentaiHaven geo-block detected during download. "
                    "Please enable a VPN and retry."
                )
            else:
                logger.error(f"HentaiHaven download failed for {url}: {e}")
            return False
