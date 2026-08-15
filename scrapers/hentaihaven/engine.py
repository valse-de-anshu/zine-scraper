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

    def extract_video_info(self, url: str) -> Dict[str, Any]:
        """
        Returns yt-dlp info dict for a single HentaiHaven video.
        Raises RuntimeError with a clear VPN message if geo-blocked.
        """
        import sys
        import subprocess
        import json
        extractor_script = Path(__file__).parent.parent / "playwright_extractor.py"
        python_path = sys.executable
        import sys
        venv_python = sys.executable
        if venv_python.exists():
            python_path = str(venv_python)
        try:
            p = subprocess.run([python_path, str(extractor_script), url], capture_output=True, text=True)
            if p.returncode != 0:
                logger.error(f"[HentaiHaven] Playwright extractor failed with exit code {p.returncode}")
                if p.stderr:
                    logger.error(f"[HentaiHaven] Playwright stderr: {p.stderr.strip()}")
            stdout = p.stdout.strip()
            if "JSON_RESULT:" in stdout:
                json_str = stdout.split("JSON_RESULT:")[1]
            else:
                json_str = stdout
            data = json.loads(json_str)
            return {
                "id": url.strip("/").split("/")[-1],
                "title": data.get("title", "Unknown").replace(" - HentaiHaven", "").strip(),
                "webpage_url": url,
                "url": data.get("url", ""),
                "upload_date": "20260101",
                "view_count": 0,
                "like_count": 0,
                "duration": 0
            }
        except Exception as e:
            err = str(e)
            logger.error(f"[HentaiHaven] Playwright extraction crashed: {e}", exc_info=True)
            if _is_geo_error(err):
                raise RuntimeError(
                    "🌐 HentaiHaven appears to be geo-blocked in your region.\n"
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
        Downloads a single HentaiHaven video using yt-dlp subprocess.
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
            import sys
            import shutil
            import subprocess
            import json
            import sys
            from pathlib import Path
            python_path = sys.executable
            venv_python = Path(sys.executable)
            if venv_python.exists():
                python_path = str(venv_python)
            
            yt_dlp_path = shutil.which("yt-dlp")
            if not yt_dlp_path:
                raise RuntimeError("yt-dlp not found in PATH or virtual environment")

            extractor_script = Path(__file__).parent.parent / "playwright_extractor.py"
            p = subprocess.run(
                [python_path, str(extractor_script), url],
                capture_output=True, text=True
            )
            try:
                stdout = p.stdout.strip()
                if "JSON_RESULT:" in stdout:
                    json_line = stdout.split("JSON_RESULT:")[1].strip().split('\n')[0]
                else:
                    json_line = stdout
                data = json.loads(json_line)
                stream_url = data.get("url", "")
                subtitles = data.get("subtitles", [])
                
                # Manually download subtitles since we use custom HLS or direct links
                if subtitles:
                    import requests
                    for i, sub in enumerate(subtitles):
                        sub_url = sub.get("url") if isinstance(sub, dict) else sub
                        if not sub_url: continue
                        ext = ".vtt" if ".vtt" in sub_url.lower() else ".srt"
                        lang = sub.get("label", "en") if isinstance(sub, dict) else "en"
                        sub_dest = output_dir / f"{clean_title}.{lang}{ext}"
                        try:
                            r = requests.get(sub_url, headers=self.headers, timeout=10)
                            if r.status_code == 200:
                                sub_dest.write_bytes(r.content)
                        except Exception as e:
                            logger.error(f"Failed to fetch subtitle {sub_url}: {e}")
                            
            except Exception as e:
                logger.error(f"[HentaiHaven Download] Failed to parse playwright output: {e}")
                stream_url = ""

            if not stream_url or "http" not in stream_url:
                logger.error(f"Playwright could not find stream for {url}. Output was: {p.stdout.strip()}")
                return False

            if ".m3u8" in stream_url:
                result_path = output_dir / f"{clean_title}.mp4" if fixed_title else output_dir / "downloaded.mp4"
                cover_path = output_dir / "cover.png"
                
                def baking_cb():
                    progress_hook({"status": "baking", "baking": True, "done": False, "total_bytes": 1, "downloaded_bytes": 1})
                
                return self._download_custom_hls(
                    playlist_url=stream_url,
                    tmp_path=result_path,
                    progress_hook=progress_hook,
                    fixed_title=fixed_title,
                    custom_thumbnail=None,
                    baking_callback=baking_cb
                )

            temp_batch.write(stream_url + "\n")
            temp_batch.close()

            cmd = [
                yt_dlp_path,
                "--plugin-dirs", str(Path(__file__).parent.parent.parent / "plugins"),
                "--batch-file", temp_batch.name,
                "-o", outtmpl,
                "-f", fmt,
                "--impersonate", "chrome",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--all-subs",
                "--embed-subs",
                "--embed-metadata",
                "--retries", "10",
                "--fragment-retries", "10",
                "--concurrent-fragments", "4",
                "--no-check-certificate",
                "--no-warnings",
                "--socket-timeout", "10",
            ]
            for k, v in self.headers.items():
                cmd.extend(["--add-header", f"{k}:{v}"])

            result_path = output_dir / f"{clean_title}.mp4" if fixed_title else None
            success = self._run_ytdlp_subprocess(
                cmd, progress_hook, str(result_path) if result_path else str(output_dir)
            )
            
            if success and result_path and result_path.exists():
                pass
                    
            return success

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
        finally:
            if os.path.exists(temp_batch.name):
                try:
                    os.unlink(temp_batch.name)
                except Exception:
                    pass
