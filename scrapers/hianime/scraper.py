import re
import requests
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Any, List
from urllib.parse import urlparse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

from scrapers.hianime.engine import HianimeEngine


class HianimeScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        # Resolve the actual host from the URL so any mirror domain works transparently
        parsed = urlparse(url)
        self._host = f"{parsed.scheme}://{parsed.netloc}"
        self.engine = HianimeEngine()

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _is_watch_url(self) -> bool:
        """True when the URL is an episode watch page (e.g. /watch/anime-slug/ep-1)."""
        return "/watch/" in self.url

    def _is_anime_url(self) -> bool:
        """True when the URL is a category/overview page (e.g. /anime/anime-slug)."""
        return "/anime/" in self.url and "/watch/" not in self.url

    def _category_url_from_watch(self, soup: BeautifulSoup):
        """
        Given a watch-page soup, try to extract the canonical /anime/ link for the
        series so we can fetch rich metadata from the overview page.
        """
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href.startswith("/anime/"):
                return self._host + href
        return None

    def _extract_episodes_from_watch_page(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        The episode list lives in the watch page inside <a class="ssl-item ep-item">.
        Each <a> carries href="/watch/<slug>/ep-<n>" and data-num="<n>".
        """
        episodes = []
        for a in soup.select("a.ssl-item.ep-item"):
            href = a.get("href", "").strip()
            if not href:
                continue
            ep_url = self._host + href if href.startswith("/") else href
            ep_num = a.get("data-num", "?")

            ep_title_el = a.select_one(".ep-name")
            ep_label = ""
            if ep_title_el:
                ep_label = (ep_title_el.get("title") or ep_title_el.text or "").strip()
            
            if ep_label:
                ep_label = f"Ep {ep_num} - {ep_label}"
            else:
                ep_label = f"Ep {ep_num}"

            episodes.append({
                "url": ep_url,
                "title": "",          # filled in below when we know the series title
                "id": ep_url,
                "upload_date": "Unknown",
                "_ep_num": ep_num,
                "_ep_label": ep_label,
            })
        return episodes

    def _extract_metadata_from_overview(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Pull all sidebar metadata from the /anime/ overview page."""
        title_el = soup.select_one(".film-name, h2.film-name, h1.film-name")
        title = title_el.text.strip() if title_el else ""

        cover_el = soup.select_one(".film-poster img, .anisc-poster img")
        cover = ""
        if cover_el:
            cover = (cover_el.get("data-src") or cover_el.get("src") or "").strip()

        desc_el = soup.select_one(".film-description .text, .anisc-detail .film-description")
        description = desc_el.get_text(separator=" ").strip() if desc_el else ""

        # ── Sidebar info blocks ───────────────────────────────────────────────
        # Structure: <div class="item item-title"> or <div class="item item-list">
        #   <span class="item-head">Label:</span>
        #   <span class="name">Value</span>   OR   <a href="...">Value</a>
        sidebar = {}
        for block in soup.select("div.item"):
            head = block.select_one("span.item-head")
            if not head:
                continue
            label = head.get_text(strip=True).rstrip(":").strip()
            # Collect all <a> text nodes first (multi-value fields like Genres/Studios)
            links = [a.get_text(strip=True) for a in block.select("a") if a.get_text(strip=True)]
            if links:
                sidebar[label] = links
            else:
                # Single value via <span class="name">
                val_el = block.select_one("span.name")
                if val_el:
                    sidebar[label] = val_el.get_text(strip=True)

        genres    = sidebar.get("Genres", [])
        studios   = sidebar.get("Studios", [])
        producers = sidebar.get("Producers", [])

        return {
            "title":      title,
            "cover":      cover,
            "description": description,
            "genres":     genres if isinstance(genres, list) else [genres],
            "aired":      sidebar.get("Aired", ""),
            "premiered":  sidebar.get("Premiered", "").strip(),
            "duration":   sidebar.get("Duration", ""),
            "status":     sidebar.get("Status", ""),
            "mal_score":  sidebar.get("MAL Score", ""),
            "studios":    studios if isinstance(studios, list) else [studios],
            "producers":  producers if isinstance(producers, list) else [producers],
            "japanese":   sidebar.get("Japanese", ""),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        h = HEADERS.copy()
        h["Referer"] = self._host

        # Step 1 – fetch the page we were given
        r = requests.get(self.url, headers=h, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Step 2 – if we landed on a category page, convert it to a watch URL
        #           so we can use the watch page's episode list
        if self._is_anime_url():
            watch_btn = soup.select_one("a[href*='/watch/']")
            if watch_btn:
                href = watch_btn.get("href", "")
                watch_url = self._host + href if href.startswith("/") else href
                r = requests.get(watch_url, headers=h, timeout=15)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")

        # Step 3 – extract episode list from the watch page
        episodes_raw = self._extract_episodes_from_watch_page(soup)

        # Step 4 – get rich metadata from the /anime/ overview page
        meta_raw: Dict[str, Any] = {}
        category_url = self._category_url_from_watch(soup)
        if category_url:
            try:
                r_meta = requests.get(category_url, headers=h, timeout=15)
                r_meta.raise_for_status()
                meta_raw = self._extract_metadata_from_overview(BeautifulSoup(r_meta.text, "lxml"))
            except Exception:
                pass

        # Fallback: parse title from the watch page itself
        if not meta_raw.get("title"):
            title_el = soup.select_one(".film-name, h2.film-name, h1")
            meta_raw["title"] = title_el.text.strip() if title_el else "Unknown Series"

        title = meta_raw["title"]

        # Step 5 – attach the series title to each episode dict
        for ep in episodes_raw:
            ep["title"] = f"{ep['_ep_label']} - {title}"

        # Step 6 – extract server info from the watch page (all three tabs: sub/dub/hsub)
        # server_items is used by the engine to know which CDN URLs to try
        server_items = []
        for a in soup.select("a.btn.server-video.server"):
            server_items.append({
                "name": a.text.strip(),
                "url": a.get("data-video", ""),
                "tab": a.get("data-tab", ""),
            })

        # Step 7 – build the public metadata dict
        metadata = {
            "Channel/Series": title,
            "Description":    meta_raw.get("description", ""),
            "Thumbnail":      meta_raw.get("cover", ""),
            "Genres":         ", ".join(meta_raw.get("genres", [])),
            "Aired":          meta_raw.get("aired", ""),
            "Premiered":      meta_raw.get("premiered", ""),
            "Duration":       meta_raw.get("duration", ""),
            "Status":         meta_raw.get("status", ""),
            "MAL Score":      meta_raw.get("mal_score", ""),
            "Studios":        ", ".join(meta_raw.get("studios", [])),
            "Producers":      ", ".join(meta_raw.get("producers", [])),
            "Japanese":       meta_raw.get("japanese", ""),
            "Source":         "HiAnime",
            "Total Videos":   len(episodes_raw),
        }

        return metadata, episodes_raw, {"server_items": server_items}
