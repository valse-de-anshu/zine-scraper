"""
scrapers/pornhub/engine.py
--------------------------
PornHub download engine — extends core VideoEngine with PornHub-specific
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
import requests
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


def _fmt_date(upload_date: Any) -> str:
    """
    Convert yt-dlp upload_date (YYYYMMDD string) to YYYY-MM-DD.
    Falls back to original string on any parse error.
    """
    if not upload_date:
        return ""
    d = str(upload_date).strip().replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return str(upload_date)  # already formatted or unknown


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


class PornHubEngine(VideoEngine):
    """
    Download engine for PornHub content.
    Wraps yt-dlp with PornHub-specific format selection and cover logic.
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
            "Referer":         "https://www.pornhub.com/",
        })

    # ─── Single video info ────────────────────────────────────────────────

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        """
        Returns yt-dlp info dict for a single PornHub video.
        Raises RuntimeError with a clear VPN message if geo-blocked.
        """
        import yt_dlp
        from yt_dlp.networking.impersonate import ImpersonateTarget
        opts = self.common_ydl_opts.copy()
        opts.update({
            "quiet": True, 
            "no_warnings": True,
            "impersonate": ImpersonateTarget(client="chrome"),
            "legacy_server_connect": True
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False) or {}
        except Exception as e:
            err = str(e)
            if _is_geo_error(err):
                raise RuntimeError(
                    "🌐 PornHub appears to be geo-blocked in your region.\n"
                    "   Please enable a VPN set to an unrestricted country (e.g. US, CA, GB)\n"
                    "   and try again. Zine cannot bypass geo-restrictions automatically."
                ) from e
            raise

    def extract_playlist_info(self, url: str, playlist_limit: Optional[int] = None, playlist_start: Optional[int] = None) -> Dict[str, Any]:
        """
        Extract playlist info for a PornHub channel/model.
        Overrides core method to inject impersonate target to bypass Cloudflare.
        """
        import yt_dlp
        from yt_dlp.networking.impersonate import ImpersonateTarget
        
        ydl_opts = self.common_ydl_opts.copy()
        ydl_opts.update({
            'quiet': True,
            'extract_flat': True,
            'dump_single_json': True,
            'ignoreconfig': True,
            'impersonate': ImpersonateTarget(client="chrome"),
            'legacy_server_connect': True
        })
        
        if playlist_limit is None:
            try:
                from core.config import ConfigLayer
                from core.paths import PathAuthority
                from core.storage import StorageLayer
                config = ConfigLayer(PathAuthority(), StorageLayer())
                playlist_limit = config.get("playlist_max_items", 100)
            except Exception:
                playlist_limit = 100

        if playlist_limit and playlist_limit > 0:
            ydl_opts['playlistend'] = playlist_limit

        if playlist_start and playlist_start > 0:
            ydl_opts['playliststart'] = playlist_start

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False) or {}
        except Exception as e:
            err = str(e)
            if _is_geo_error(err):
                raise RuntimeError(
                    "🌐 PornHub appears to be geo-blocked in your region.\n"
                    "   Please enable a VPN set to an unrestricted country (e.g. US, CA, GB)\n"
                    "   and try again. Zine cannot bypass geo-restrictions automatically."
                ) from e
            raise

    # ─── Avatar download ─────────────────────────────────────────────────

    def download_avatar(self, avatar_url: str, dest: Path) -> bool:
        """Downloads the model profile picture and saves as cover.png."""
        if not avatar_url:
            return False
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            import subprocess
            cmd = ["curl", "-sSL", "--connect-timeout", "20", "--retry", "3", "-o", str(dest), avatar_url]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                logger.info(f"PornHub cover saved to {dest}")
                return True
            else:
                logger.error(f"Failed to download PornHub avatar via curl. Return code: {res.returncode}")
                return False
        except Exception as e:
            logger.error(f"Failed to download PornHub avatar from {avatar_url}: {e}")
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
        def _safe_num(val: Any) -> float:
            if val is None:
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        def _entry(v: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id":          str(v.get("id") or ""),
                "title":       _decode(str(v.get("title") or "")),
                "upload_date": str(_fmt_date(v.get("upload_date") or "")),
                "view_count":  _safe_num(v.get("view_count")),
                "like_count":  _safe_num(v.get("like_count")),
                "duration":    _safe_num(v.get("duration")),
                "url":         str(v.get("url") or ""),
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

        logger.info(f"PornHub metadata saved to {meta_path}")

        # ── Download cover.png ────────────────────────────────────────
        if not skip_cover and avatar_url:
            # Save next to metadata dir (inside creator root), not inside .zine
            cover_path = root_dir / "cover.png"
            if not cover_path.exists():
                self.download_avatar(avatar_url, cover_path)

    # ─── Video download ──────────────────────────────────────────────────

    def download_pornhub_video(
        self,
        url: str,
        output_dir: Path,
        progress_hook: Callable,
        quality: str = "1080p",
        fixed_title: Optional[str] = None,
    ) -> bool:
        """
        Downloads a single PornHub video using yt-dlp subprocess.
        Quality preference: 1080p → 720p → 480p → best available.
        Returns True on success.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        if fixed_title:
            # Use the pre-cleaned title (no HTML entities, no garbage chars)
            clean_title = "".join(
                c for c in fixed_title if c.isalnum() or c in " .-_()'"
            ).strip()
            # Final safety: replace illegal filesystem chars
            clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip()
            if not clean_title:
                clean_title = "video"
        else:
            clean_title = "%(title)s [%(id)s]"

        outtmpl = str(output_dir / f"{clean_title}.%(ext)s")

        # Format string: prefer mp4 at target height
        height_map = {"1080p": "1080", "720p": "720", "480p": "480", "360p": "360"}
        h = height_map.get(quality, "1080")
        fmt = (
            f"bestvideo[height<={h}][ext=mp4]+bestaudio/"
            f"bestvideo[height<={h}]+bestaudio/"
            f"best[height<={h}]/"
            f"best"
        )

        temp_batch = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt", encoding="utf-8"
        )
        try:
            temp_batch.write(url + "\n")
            temp_batch.close()

            import shutil
            # Prefer venv yt-dlp, then system-wide
            ytdlp_bin = (
                shutil.which("venv/bin/yt-dlp")
                or shutil.which("yt-dlp")
                or "yt-dlp"
            )
            cmd = [
                ytdlp_bin,
                "--batch-file", temp_batch.name,
                "-o", outtmpl,
                "-f", fmt,
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--all-subs",
                "--embed-subs",
                "--embed-metadata",
                "--embed-thumbnail",
                "--retries", "10",
                "--fragment-retries", "10",
                "--downloader", "m3u8:native",
                "--downloader", "dash:native",
                "--concurrent-fragments", "16",
                "--no-check-certificate",
                "--no-warnings",
                "--socket-timeout", "10",
                "--impersonate", "chrome",
                "--legacy-server-connect",
            ]
            for k, v in self.headers.items():
                cmd.extend(["--add-header", f"{k}:{v}"])

            result_path = output_dir / f"{clean_title}.mp4" if fixed_title else None
            return self._run_ytdlp_subprocess(
                cmd, progress_hook, str(result_path) if result_path else str(output_dir)
            )

        except Exception as e:
            err = str(e)
            if _is_geo_error(err):
                logger.error(
                    "PornHub geo-block detected during download. "
                    "Please enable a VPN and retry."
                )
            else:
                logger.error(f"PornHub download failed for {url}: {e}")
            return False
        finally:
            if os.path.exists(temp_batch.name):
                try:
                    os.unlink(temp_batch.name)
                except Exception:
                    pass
