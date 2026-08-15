"""
OmegaScans Scraper
==================
Handles all series/chapter metadata discovery via the OmegaScans REST API.
Downloads are delegated to engine.py.

API endpoints (reverse-engineered from the Next.js frontend):
  Series metadata : https://api.omegascans.org/series/{series_slug}
  Chapter list    : https://api.omegascans.org/chapter/query?page=1&perPage=10000&series_id={id}
  Chapter images  : https://api.omegascans.org/chapter/{series_slug}/{chapter_slug}
"""

import re
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from .engine import (
    make_api_session,
    download_chapter,
    OMEGA_API_BASE,
    urljoin,                  # re-export so workflow.py can import from here
)

_log = logging.getLogger("omegascans")


class OmegaScansScraper:
    scraper_type = "toon"

    def __init__(self, url: str):
        self.url     = url.rstrip("/")
        self.domain  = "omegascans.org"
        self.session = make_api_session()

        # Populated by get_title_and_chapters()
        self.title       = ""
        self.description = ""
        self.author      = ""
        self.tags: List[str] = []
        self.genres: List[str] = []
        self.cover_url: Optional[str] = None

    def download_cover(self, folder: Path):
        """Downloads the cover image to folder if cover_url is set."""
        if not self.cover_url:
            return
        from .engine import download_image
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        ext = Path(self.cover_url.split("?")[0]).suffix or ".jpg"
        dest = folder / f"cover{ext}"
        download_image(self.cover_url, dest)

    # ── URL inspection ────────────────────────────────────────────────────────

    def _parse_url(self) -> Tuple[str, Optional[str]]:
        """
        Returns (series_slug, chapter_slug_or_None) from self.url.
        Handles both:
          https://omegascans.org/series/{series_slug}
          https://omegascans.org/series/{series_slug}/{chapter_slug}
        """
        parts = [p for p in self.url.split("/") if p]
        if "series" not in parts:
            raise ValueError(f"Not an OmegaScans series URL: {self.url}")
        idx = parts.index("series")
        if idx + 1 >= len(parts):
            raise ValueError(f"Missing series slug in: {self.url}")
        series_slug  = parts[idx + 1]
        chapter_slug = parts[idx + 2] if idx + 2 < len(parts) else None
        return series_slug, chapter_slug

    def is_chapter_link(self) -> bool:
        _, ch = self._parse_url()
        return ch is not None

    # ── Metadata & chapter list ───────────────────────────────────────────────

    def get_title_and_chapters(self) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Returns (title, [(ch_num_str, full_chapter_url), ...]) sorted oldest→newest.
        If the URL points directly at a chapter, returns only that chapter.
        """
        series_slug, chapter_slug = self._parse_url()

        # If URL is already a specific chapter, skip the full chapter list
        if chapter_slug:
            r = self.session.get(f"{OMEGA_API_BASE}/series/{series_slug}", timeout=15)
            r.raise_for_status()
            meta = r.json()
            self._apply_meta(meta)
            m = re.search(r"(\d+(?:\.\d+)?)", chapter_slug)
            num = m.group(1) if m else "1"
            return self.title, [(num, self.url)]

        # Full series: fetch metadata + chapter list
        r = self.session.get(f"{OMEGA_API_BASE}/series/{series_slug}", timeout=15)
        r.raise_for_status()
        meta = r.json()
        self._apply_meta(meta)
        series_id = meta.get("id")
        if not series_id:
            raise RuntimeError(f"No series ID returned for '{series_slug}'")

        # OmegaScans returns chapters newest-first; we sort oldest-first
        r2 = self.session.get(
            f"{OMEGA_API_BASE}/chapter/query"
            f"?page=1&perPage=10000&series_id={series_id}",
            timeout=15,
        )
        r2.raise_for_status()
        raw_chapters = r2.json().get("data", [])

        chapters = []
        seen_nums = set()
        seen_urls = set()

        for ch in raw_chapters:
            ch_slug = ch.get("chapter_slug", "")
            ch_name = ch.get("chapter_name", "")
            if not ch_slug:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)", ch_name) or re.search(r"(\d+(?:\.\d+)?)", ch_slug)
            num = m.group(1) if m else ch_slug
            full_url = f"https://omegascans.org/series/{series_slug}/{ch_slug}"
            if num not in seen_nums and full_url not in seen_urls:
                chapters.append((float(num), num, full_url))
                seen_nums.add(num)
                seen_urls.add(full_url)

        chapters.sort(key=lambda x: x[0])     # oldest first
        final = [(num_str, link) for _, num_str, link in chapters]

        if not final:
            _log.warning(f"No chapters found for {self.url}")

        return self.title, final

    def _apply_meta(self, meta: dict):
        self.title       = meta.get("title", "")
        self.description = meta.get("description", "") or ""
        self.author      = meta.get("author", "") or meta.get("studio", "") or ""
        self.tags        = [t.get("name") for t in meta.get("tags", []) if t.get("name")]
        self.cover_url   = meta.get("thumbnail")

    # ── Chapter image fetching ────────────────────────────────────────────────

    def _get_image_urls(self, ch_url: str) -> List[str]:
        """
        Fetches the image URL list for a chapter from the OmegaScans API.
        Returns a deduplicated list of image URLs in page order.
        """
        parts = [p for p in ch_url.split("/") if p]
        if "series" not in parts:
            raise ValueError(f"Not a chapter URL: {ch_url}")
        idx          = parts.index("series")
        series_slug  = parts[idx + 1]
        chapter_slug = parts[idx + 2] if idx + 2 < len(parts) else None
        if not chapter_slug:
            raise ValueError(f"No chapter slug in: {ch_url}")

        r = self.session.get(
            f"{OMEGA_API_BASE}/chapter/{series_slug}/{chapter_slug}",
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        ch_info = data.get("chapter", {})
        ch_dat  = ch_info.get("chapter_data", {})
        imgs    = ch_dat.get("images", [])

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for url in imgs:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)

        return unique

    # ── Main entry point called by workflow.py ────────────────────────────────

    def process_chapter(
        self,
        ch_url: str,
        folder,
        ch_num: str,
        live=None,
        stats_callback=None,
    ) -> dict:
        """
        Downloads one chapter and returns a result dict:
          {"total": int, "downloaded": int, "missing": int, "success": bool}

        `folder` may be a Path or a ZineFolder wrapper — we coerce to Path.
        """
        dest = Path(folder) if not isinstance(folder, Path) else folder

        try:
            img_urls = self._get_image_urls(ch_url)
        except Exception as e:
            _log.error(f"Ch{ch_num}: failed to get image URLs — {e}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        if not img_urls:
            _log.warning(f"Ch{ch_num}: API returned 0 images")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return download_chapter(
            img_urls     = img_urls,
            folder       = dest,
            ch_num       = ch_num,
            ch_url       = ch_url,
            stats_callback = stats_callback,
        )
