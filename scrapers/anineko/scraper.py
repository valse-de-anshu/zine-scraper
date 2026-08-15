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

from scrapers.anineko.engine import AninekoEngine


class AninekoScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        # Resolve the actual host from the URL so any mirror domain works transparently
        parsed = urlparse(url)
        self._host = f"{parsed.scheme}://{parsed.netloc}"
        self.engine = AninekoEngine()

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _is_watch_url(self) -> bool:
        """True when the URL is an episode watch page (e.g. /watch/anime-slug/ep-1)."""
        return "/ep-" in self.url

    def _is_anime_url(self) -> bool:
        """True when the URL is a category/overview page (e.g. /watch/anime-slug)."""
        return "/watch/" in self.url and "/ep-" not in self.url

    def _category_url_from_watch(self, soup: BeautifulSoup):
        """
        Given a watch-page soup, extract the overview link for the series.
        In AniNeko, the overview page is just the base /watch/slug URL.
        """
        parsed = urlparse(self.url)
        path = parsed.path
        if "/ep-" in path:
            overview_path = path.split("/ep-")[0]
            return self._host + overview_path
        return None

    def _extract_episodes_from_watch_page(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        episodes = []
        for a in soup.select("a.nv-episode-item, a.nv-info-episode-main"):
            href = a.get("href", "").strip()
            if not href:
                continue
            ep_url = self._host + href if href.startswith("/") else href
            
            # Text contains "Episode 1 Episode 1" because of the nested span, let's extract carefully
            strong = a.select_one("strong")
            ep_label = strong.text.strip() if strong else a.text.strip()
            
            # Try to extract the number from the label
            ep_num = "?"
            m = re.search(r'(?:Episode|EP)\s+(\d+)', ep_label, re.IGNORECASE)
            if m:
                ep_num = m.group(1)

            episodes.append({
                "url": ep_url,
                "title": "",          
                "id": ep_url,
                "upload_date": "Unknown",
                "_ep_num": ep_num,
                "_ep_label": ep_label,
            })
        return episodes

    def _extract_metadata_from_overview(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Pull all sidebar metadata from the watch page."""
        title_el = soup.select_one("h1")
        title = title_el.text.strip() if title_el else ""

        cover = ""
        for img in soup.select("img"):
            src = img.get("src")
            if src and "cover" in src:
                cover = src
                break

        desc_el = soup.select_one(".nv-info-main > p")
        if not desc_el:
            desc_el = soup.select_one(".nv-info-main")
        description = desc_el.text.replace(title, "").strip() if desc_el else ""

        sidebar = {}
        lst = soup.select_one(".nv-info-list")
        if lst:
            for child in lst.children:
                if child.name == "div":
                    span = child.select_one("span")
                    if span:
                        key = span.text.strip()
                        val = child.text.replace(key, "").strip()
                        sidebar[key] = val

        genres = []
        genres_el = soup.select_one(".nv-info-genres")
        if genres_el:
            genres = [span.text.strip() for span in genres_el.select("span") if span.text.strip()]

        studios = sidebar.get("Studios", "")
        if studios:
            studios = [s.strip() for s in studios.split(",")]
        else:
            studios = []
            
        producers = sidebar.get("Producers", "")
        if producers:
            producers = [p.strip() for p in producers.split(",")]
        else:
            producers = []

        return {
            "title":      title,
            "cover":      cover,
            "description": description,
            "genres":     genres,
            "aired":      sidebar.get("Release", ""),
            "premiered":  sidebar.get("Release", ""),
            "duration":   sidebar.get("Duration", ""),
            "status":     sidebar.get("Status", ""),
            "mal_score":  sidebar.get("Score", ""),
            "studios":    studios,
            "producers":  producers,
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
        #           so we can use the watch page's episode list and servers
        if self._is_anime_url():
            # AniNeko overview page contains the episode list, but NOT the server list!
            # The server list is only on the individual episode pages.
            # We will use the overview page to get metadata and episode list.
            # Then we will fetch the first episode page to get the server list.
            pass

        # Step 3 – extract episode list from the watch page
        episodes_raw = self._extract_episodes_from_watch_page(soup)

        # Step 4 - Extract metadata.
        # If we are on an episode page, we need to fetch the overview page for metadata.
        meta_raw = {}
        if self._is_watch_url():
            category_url = self._category_url_from_watch(soup)
            if category_url:
                try:
                    r_meta = requests.get(category_url, headers=h, timeout=15)
                    r_meta.raise_for_status()
                    meta_raw = self._extract_metadata_from_overview(BeautifulSoup(r_meta.text, "lxml"))
                except Exception:
                    pass
        else:
            # We are already on the overview page
            meta_raw = self._extract_metadata_from_overview(soup)

        # Fallback: parse title from the watch page itself
        if not meta_raw.get("title"):
            title_el = soup.select_one(".film-name, h2.film-name, h1")
            meta_raw["title"] = title_el.text.strip() if title_el else "Unknown Series"

        title = meta_raw["title"]

        # Step 5 – attach the series title to each episode dict
        for ep in episodes_raw:
            ep["title"] = f"{title} - {ep['_ep_label']}"

        # Step 6 – extract server info
        server_items = []
        
        # If we are on the overview page, we need to fetch an episode page to get the server list
        if self._is_anime_url() and episodes_raw:
            try:
                r_ep = requests.get(episodes_raw[0]["url"], headers=h, timeout=15)
                r_ep.raise_for_status()
                ep_soup = BeautifulSoup(r_ep.text, "lxml")
            except Exception:
                ep_soup = soup
        else:
            ep_soup = soup

        for a in ep_soup.select(".server-video.server"):
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
            "Source":         "AniNeko",
            "Total Videos":   len(episodes_raw),
        }

        return metadata, episodes_raw, {"server_items": server_items}
