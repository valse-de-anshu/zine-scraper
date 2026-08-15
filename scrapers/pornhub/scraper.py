"""
scrapers/pornhub/scraper.py
---------------------------
Scraper metadata layer for PornHub.

Key fixes (v2):
  - All names decoded with html.unescape() — no more &#039; garbage
  - Real viewkeys extracted from video URLs (not sequential indices)
  - Per-video metadata fetched in parallel (view_count, like_count, duration, upload_date)
  - Avatar extracted via <img class="avatar"> pattern, matching model's own data-userid
  - Clean model name extraction: strips HTML entities + " Porn Videos | Pornhub" suffix
"""
import re
import html as html_module
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Tuple, Optional
from .engine import PornHubEngine

logger = logging.getLogger(__name__)

# How many videos to fetch individual metadata for in parallel
_PARALLEL_META_WORKERS = 20


def _decode(raw: str) -> str:
    """Decode HTML entities and unescape backslash sequences."""
    if not raw:
        return raw
    return html_module.unescape(raw).replace("\\/", "/").replace("\\u002F", "/")


def _extract_viewkey(url: str) -> Optional[str]:
    """
    Extract the PornHub viewkey from a video URL.
    Handles both:
      - view_video.php?viewkey=abc123
      - /view_video.php?viewkey=abc123
    Returns None if not found.
    """
    m = re.search(r'viewkey=([a-zA-Z0-9]+)', url)
    return m.group(1) if m else None


def _clean_model_name(raw: str) -> str:
    """
    Clean a model name scraped from the page title or JSON.
    Removes HTML entities, trailing 's (possessive from page title format
    "ModelName's Porn Videos | Pornhub"), and surrounding whitespace.
    """
    name = _decode(raw)
    # Remove common suffixes in various orders
    suffixes = [
        r"\s*\|\s*Pornhub.*$",
        r"\s+'s\s+Porn\s+Videos.*$",
        r"\s+Porn\s+Videos.*$",
        r"\s+porn\s+videos.*$",
        r"\s*-\s*Pornhub.*$",
    ]
    for suf in suffixes:
        name = re.sub(suf, "", name, flags=re.IGNORECASE).strip()
    # Strip a remaining trailing 's (possessive artifact)
    name = re.sub(r"'s\s*$", "", name).strip()
    return name.strip()


def _safe_folder_name(name: str) -> str:
    """
    Converts a model name into a safe folder-name string.
    Preserves apostrophes and common punctuation, strips truly illegal chars.
    Uses a whitelist approach rather than stripping everything non-alnum.
    """
    # Only remove chars that are illegal in filenames on Linux/Windows/macOS
    illegal = r'[<>:"/\\|?*\x00-\x1f]'
    safe = re.sub(illegal, '', name).strip()
    # Collapse multiple spaces
    safe = re.sub(r'\s{2,}', ' ', safe)
    return safe or "Unknown"


def _parse_iso_duration(iso_str: str) -> float:
    """Parse ISO 8601 duration string like PT00H09M44S into seconds."""
    if not iso_str:
        return 0.0
    m = re.search(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', str(iso_str))
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return float(h * 3600 + mins * 60 + s)


class PornHubScraper:
    """
    Scraper for PornHub model pages and individual videos.
    Mirrors the architecture of YoutubeScraper (7-file modular structure).
    """

    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self.engine = PornHubEngine()
        self.is_playlist = False
        self.title = None           # clean model name
        self._folder_name = None    # safe filesystem name (may differ from title)

    # ─── Link type detection ───────────────────────────────────────────────

    def get_link_type(self) -> str:
        """
        Returns 'model' (full channel vacuum) or 'single' (quick grab).
        Model/pornstar/channels/user pages → 'model'
        Individual watch/viewkey URLs     → 'single'
        """
        url_lower = self.url.lower()
        if (
            "/model/" in url_lower
            or "/pornstar/" in url_lower
            or "/channels/" in url_lower
            or "/user/" in url_lower
            or "/amateur/" in url_lower
            or url_lower.rstrip("/").endswith("/videos")
        ):
            return "model"
        return "single"

    # ─── URL helpers ──────────────────────────────────────────────────────

    def _normalize_model_url(self) -> str:
        """Strips trailing /videos suffix so we always start from the root."""
        url = self.url.rstrip("/")
        if url.endswith("/videos"):
            url = url[: -len("/videos")]
        return url

    # ─── Model page scraping ──────────────────────────────────────────────

    def _scrape_model_info(self) -> Dict[str, Any]:
        """
        Fetches the model page HTML to extract:
        - Model name (HTML-entity decoded, suffix stripped)
        - Profile picture URL (first <img class="avatar..."> on page = model's own pfp)
        """
        headers = dict(self.engine.headers)
        model_url = self._normalize_model_url()
        info: Dict[str, Any] = {
            "model_name": "Unknown",
            "folder_name": "Unknown",
            "avatar_url":  None,
            "user_id":     None,
            "url":         model_url,
        }
        try:
            r = requests.get(model_url, headers=headers, timeout=15)
            if r.status_code != 200:
                logger.warning(f"PornHub model page returned {r.status_code}")
                return info
            page = r.text

            # ── Model name from <title> ────────────────────────────────
            m = re.search(r'<title>([^<]+)</title>', page)
            if not m:
                m = re.search(r'"modelName"\s*:\s*"([^"]+)"', page)
            if m:
                info["model_name"] = _clean_model_name(m.group(1))
                info["folder_name"] = _safe_folder_name(info["model_name"])

            # ── User ID (for logging only, not critical for avatar) ────
            uid_match = re.search(r'data-userid=["\'](\d+)["\']', page)
            if uid_match:
                info["user_id"] = uid_match.group(1)

            # ── Avatar: first <img class="avatar..."> on the page ─────
            avatar_url = None

            # Pattern 1: <img class="avatar..." src="...">
            m = re.search(
                r'<img[^>]+class="[^"]*avatar[^"]*"[^>]+src="(https://[^"]+phncdn[^"]+\.(?:jpg|jpeg|png|webp|gif))"',
                page
            )
            if not m:
                # Pattern 2: src before class attribute
                m = re.search(
                    r'<img[^>]+src="(https://[^"]+phncdn[^"]+\.(?:jpg|jpeg|png|webp|gif))"[^>]+class="[^"]*avatar[^"]*"',
                    page
                )

            if m:
                raw_url = m.group(1)
                avatar_url = raw_url

            if avatar_url:
                info["avatar_url"] = avatar_url

        except Exception as e:
            logger.debug(f"PornHub model page scrape failed: {e}")
        return info

    # ─── Per-video metadata enrichment ───────────────────────────────────

    def _fetch_single_video_meta(self, vid_url: str, vid_title: str) -> Dict[str, Any]:
        """
        Fetches metadata for one video URL.
        First tries ultra-fast direct HTML JSON-LD parsing (0.2s).
        Falls back to full yt-dlp extraction if HTML fetch fails.
        """
        viewkey = _extract_viewkey(vid_url)
        base = {
            "url":         vid_url,
            "id":          viewkey or "",
            "title":       _decode(vid_title),
            "view_count":  0,
            "like_count":  0,
            "duration":    0,
            "upload_date": "",
            "thumbnail":   "",
        }

        # ── Fast HTTP JSON-LD attempt ────────────────────────────────────
        try:
            r = requests.get(vid_url, headers=self.engine.headers, timeout=5)
            if r.status_code == 200:
                ld_match = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.DOTALL)
                if ld_match:
                    import json as json_mod
                    d = json_mod.loads(ld_match.group(1))
                    views_raw = str(d.get('interactionStatistic', [{}])[0].get('userInteractionCount', '0')).replace(',', '')
                    views = float(views_raw) if views_raw.isdigit() else 0.0
                    up_date = str(d.get('uploadDate', ''))[:10]
                    duration = _parse_iso_duration(d.get('duration', ''))
                    title = _decode(d.get('name', '') or vid_title)
                    thumb = d.get('thumbnailUrl', '')

                    base.update({
                        "id":          viewkey or "",
                        "title":       title,
                        "view_count":  views,
                        "like_count":  0,
                        "duration":    duration,
                        "upload_date": up_date,
                        "thumbnail":   thumb,
                    })
                    return base
        except Exception:
            pass

        # ── Fallback: full yt-dlp extraction ────────────────────────────
        try:
            info = self.engine.extract_video_info(vid_url)
            real_id = info.get("id") or viewkey or ""
            thumb = info.get("thumbnail") or ""
            if not thumb and info.get("thumbnails"):
                thumb = info["thumbnails"][-1].get("url", "")
            base.update({
                "id":          real_id,
                "title":       _decode(info.get("title") or vid_title),
                "view_count":  info.get("view_count") or 0,
                "like_count":  info.get("like_count") or 0,
                "duration":    info.get("duration") or 0,
                "upload_date": info.get("upload_date") or "",
                "thumbnail":   thumb,
                "uploader":    _decode(info.get("uploader") or info.get("channel") or ""),
            })
        except Exception as e:
            logger.debug(f"Failed to fetch metadata for {vid_url}: {e}")
        return base

    # ─── Main entry point ─────────────────────────────────────────────────

    def get_metadata_and_videos(
        self,
        playlist_limit: Optional[int] = None,
        playlist_start: Optional[int] = None,
        enrich_metadata: bool = True,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Returns (metadata_dict, video_list, raw_info_dict).

        For model pages  → flat-list all videos via yt-dlp, then optionally enrich
                           each entry with per-video metadata (view_count, etc.)
        For single URLs  → returns single-item list with full metadata.
        """
        link_type = self.get_link_type()

        # ── Single video (Quick grab) ──────────────────────────────────
        if link_type == "single":
            info = self.engine.extract_video_info(self.url)
            self.is_playlist = False

            uploader = _decode(info.get("uploader") or info.get("channel") or "Unknown")
            self.title = uploader
            self._folder_name = _safe_folder_name(uploader)

            thumb = info.get("thumbnail") or ""
            if not thumb and info.get("thumbnails"):
                thumb = info["thumbnails"][-1].get("url", "")

            vid_id = info.get("id") or _extract_viewkey(self.url) or "unknown"

            metadata = {
                "Channel/Series": uploader,
                "Source":         "PornHub",
                "Total Videos":   1,
                "ID":             vid_id,
                "Thumbnail":      thumb,
                "Upload Date":    info.get("upload_date") or "",
                "View Count":     info.get("view_count") or 0,
                "Like Count":     info.get("like_count") or 0,
                "Duration":       info.get("duration") or 0,
            }

            video_entry = {
                "url":         info.get("webpage_url") or self.url,
                "title":       _decode(info.get("title") or "Unknown Video"),
                "id":          vid_id,
                "uploader":    uploader,
                "thumbnail":   thumb,
                "upload_date": info.get("upload_date") or "",
                "view_count":  info.get("view_count") or 0,
                "like_count":  info.get("like_count") or 0,
                "duration":    info.get("duration") or 0,
            }
            return metadata, [video_entry], info

        # ── Model / channel page (Vacuum mode) ────────────────────────
        model_url = self._normalize_model_url()
        videos_url = model_url + "/videos"

        # Scrape model profile info (name, avatar) from model page HTML
        model_info = self._scrape_model_info()
        model_name = model_info["model_name"]
        self.title = model_name
        self._folder_name = model_info["folder_name"]
        self.is_playlist = True

        # yt-dlp flat-extract to get the list of video URLs + titles
        raw_info = self.engine.extract_playlist_info(
            videos_url,
            playlist_limit=playlist_limit if playlist_limit is not None else 0,
            playlist_start=playlist_start,
        )

        # Flatten nested playlist entries
        flat_entries = []
        for e in (raw_info.get("entries") or []):
            if e is None:
                continue
            if e.get("_type") == "playlist":
                flat_entries.extend([x for x in (e.get("entries") or []) if x])
            else:
                flat_entries.append(e)

        # Build initial video list from flat entries
        # The flat entry gives us: url, title (sometimes), but NO id/view_count/duration
        initial_videos: List[Dict[str, Any]] = []
        for idx, entry in enumerate(flat_entries):
            if not entry:
                continue
            vid_url = entry.get("url") or entry.get("webpage_url") or ""
            if vid_url and not vid_url.startswith("http"):
                vid_url = "https://www.pornhub.com" + vid_url
            viewkey = _extract_viewkey(vid_url)
            raw_title = entry.get("title") or f"Video {idx + 1}"
            initial_videos.append({
                "url":         vid_url,
                "title":       _decode(raw_title),
                "id":          viewkey or f"unknown_{idx}",
                "uploader":    model_name,
                "thumbnail":   entry.get("thumbnail") or "",
                "upload_date": "",
                "view_count":  0,
                "like_count":  0,
                "duration":    0,
            })

        # ── Per-video metadata enrichment (parallel) ───────────────────
        # Without this, most_viewed / top_rated / longest are all identical (all zeros).
        # We fetch individual video pages in parallel to get real counts.
        if enrich_metadata and initial_videos:
            logger.info(f"Enriching metadata for {len(initial_videos)} PornHub videos (parallel)...")
            enriched: Dict[str, Dict[str, Any]] = {}

            def _enrich(v: Dict[str, Any]) -> Dict[str, Any]:
                meta = self._fetch_single_video_meta(v["url"], v["title"])
                meta.setdefault("uploader", v["uploader"])
                return meta

            with ThreadPoolExecutor(max_workers=_PARALLEL_META_WORKERS) as ex:
                futures = {ex.submit(_enrich, v): i for i, v in enumerate(initial_videos)}
                for fut in as_completed(futures):
                    idx = futures[fut]
                    try:
                        result = fut.result()
                        enriched[idx] = result
                    except Exception as e:
                        logger.debug(f"Enrich failed for video {idx}: {e}")
                        enriched[idx] = initial_videos[idx]

            videos = [enriched.get(i, initial_videos[i]) for i in range(len(initial_videos))]
        else:
            videos = initial_videos

        # Build metadata dict
        metadata = {
            "Channel/Series": model_name,
            "Source":         "PornHub",
            "Total Videos":   len(videos),
            "Avatar URL":     model_info.get("avatar_url") or "",
            "Model URL":      model_url,
            "ID":             model_info.get("user_id") or "Unknown",
        }

        return metadata, videos, raw_info
