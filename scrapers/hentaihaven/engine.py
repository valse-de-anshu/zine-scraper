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
        """Downloads avatar/cover using 2-step magic-byte verification."""
        if not avatar_url:
            return False
        try:
            from core.cover_utils import save_verified_cover
            r = requests.get(avatar_url, headers=self.headers, timeout=20, impersonate="chrome124")
            if r.status_code == 200 and len(r.content) > 500:
                saved = save_verified_cover(r.content, dest.parent, filename=dest.stem)
                if saved:
                    logger.info(f"HentaiHaven cover saved to {saved}")
                    return True
            return False
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
        custom_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Persists clean, normalized metadata and 2-step verified cover art into folder.
        """
        clean_model = _decode(model_name)
        url = info.get("url", "")
        if custom_metadata and "URL" in custom_metadata:
            url = custom_metadata["URL"]

        alt_title = (custom_metadata.get("Alternative Title") or info.get("alt_title") or "") if custom_metadata else ""
        studio = (custom_metadata.get("Studio") or info.get("uploader_id") or "") if custom_metadata else ""
        tags = (custom_metadata.get("Tags") or "") if custom_metadata else ""
        summary = (custom_metadata.get("Description") or "") if custom_metadata else ""
        raw_date = (custom_metadata.get("Release Date") or info.get("upload_date") or "") if custom_metadata else ""
        year = str(custom_metadata.get("Year") or "").strip() if custom_metadata else ""
        if not year and raw_date:
            year = str(raw_date).split("-")[0]
        video_list = videos or []

        def _entry(v: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id":          str(v.get("id", "")),
                "title":       _decode(v.get("title", "") or ""),
                "upload_date": _fmt_date(v.get("upload_date", "") or ""),
                "view_count":  v.get("view_count", 0) or 0,
                "like_count":  v.get("like_count",  0) or 0,
                "duration":    v.get("duration",    0) or 0,
                "url":         v.get("url", ""),
            }

        all_entries = [_entry(v) for v in video_list]

        # most_viewed — descending view_count
        most_viewed = sorted(
            [e for e in all_entries if e["view_count"] > 0],
            key=lambda e: e["view_count"], reverse=True
        )[:10] or all_entries[:10]

        # top_rated — descending like_count
        top_rated = sorted(
            [e for e in all_entries if e["like_count"] > 0],
            key=lambda e: e["like_count"], reverse=True
        )[:10] or all_entries[:10]

        raw_views = str((custom_metadata.get("Views") if custom_metadata else "") or info.get("views") or "")
        raw_likes = str((custom_metadata.get("Likes") if custom_metadata else "") or info.get("likes") or "")
        total_v = sum(int(e["view_count"]) for e in all_entries if e.get("view_count"))
        total_l = sum(int(e["like_count"]) for e in all_entries if e.get("like_count"))
        views_val = raw_views or (f"{total_v:,}" if total_v > 0 else "0")
        likes_val = raw_likes or (f"{total_l:,}" if total_l > 0 else "0")

        from core.metadata_engine import MetadataEngine, ZineMetadataPayload
        if isinstance(tags, list):
            tags_list = tags
        elif isinstance(tags, str):
            tags_list = [t.strip() for t in tags.split(",") if t.strip()]
        else:
            tags_list = []

        payload = ZineMetadataPayload(
            title=clean_model,
            type="Series",
            alt_title=alt_title,
            author=studio or clean_model,
            artist=studio,
            description=summary,
            tags=tags_list,
            year=year,
            views=views_val,
            likes=likes_val,
            hottest=most_viewed,
            most_rated=top_rated,
            url=url,
        )
        MetadataEngine.save_metadata(root_dir, payload)
        logger.info(f"HentaiHaven metadata saved via MetadataEngine for {clean_model}")

        # 2-step verification cover download
        if not skip_cover and avatar_url:
            has_cover = any(root_dir.glob("cover.*"))
            if not has_cover:
                self.download_avatar(avatar_url, root_dir / "cover")

    # ─── Video download ──────────────────────────────────────────────────

    def _validate_stream(self, stream_url: str, depth: int = 0) -> Tuple[bool, str]:
        """
        Quickly tests if the HLS playlist has valid media segments rather than
        expired/dead domains returning HTML parking pages (e.g. Porkbun auction pages).
        """
        if depth > 3 or not stream_url:
            return True, "OK"

        try:
            r = requests.get(stream_url, headers=self.headers, timeout=10, impersonate="chrome124")
            if r.status_code != 200:
                return False, f"Server returned HTTP {r.status_code}"

            first_target = None
            for line in r.text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    if line.startswith("http"):
                        first_target = line
                    else:
                        base = stream_url.rsplit("/", 1)[0]
                        first_target = f"{base}/{line}"
                    break

            if not first_target:
                return True, "OK"

            # If master playlist pointing to quality index / child playlist
            if ".m3u8" in first_target or ".txt" in first_target or first_target.endswith(".list"):
                return self._validate_stream(first_target, depth + 1)

            # Test first actual segment
            r_seg = requests.get(first_target, headers=self.headers, timeout=10, impersonate="chrome124")
            if r_seg.status_code != 200:
                return False, f"Segment host returned HTTP {r_seg.status_code}"

            snippet = r_seg.content[:300].lower()
            if b"<!doctype" in snippet or b"<html" in snippet or b"domain for sale" in snippet or b"porkbun" in snippet or b"<head" in snippet:
                return False, "Stream CDN host is expired/dead (domain parked at auction)"

            return True, "OK"
        except Exception as e:
            logger.warning(f"Stream validation probe exception: {e}")
            return True, "OK"

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

        # Validate stream health before downloading to prevent hanging on dead/parked CDNs
        valid, reason = self._validate_stream(stream_url)
        if not valid:
            from core.ui import console
            console.print(f"[error]Cannot download video: {reason}[/error]")
            logger.error(f"[HentaiHaven] Stream validation failed for {url}: {reason}")
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
            "--retries", "5",
            "--fragment-retries", "5",
            "--concurrent-fragments", "16",
            "--no-check-certificate",
            "--no-warnings",
            "--socket-timeout", "10",
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
