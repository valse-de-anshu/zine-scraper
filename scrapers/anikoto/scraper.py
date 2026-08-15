"""
scrapers/anikoto/scraper.py
----------------------------
Anikoto scraper — supports anikototv.to, anikoto.cz, anikoto.me,
anikoto.net, anikototv.se

Pipeline:
  1. Load the watch page → extract title, cover, genres, synopsis, anime_id
  2. Hit AJAX /ajax/episode/list/{id} → get full episode list with data_ids
  3. For each episode: hit /ajax/server/list → get embed server URLs
  4. Use Playwright interceptor to load embed → intercept getSources → get m3u8
  5. Return m3u8 + referer so VideoEngine/yt-dlp can download it
"""

import logging
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Tuple, Optional
from core.video_engine import VideoEngine

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'X-Requested-With': 'XMLHttpRequest',
}


def _normalize_host(url: str) -> str:
    """Return the Anikoto host from any supported variant."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class AnikotoScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self._host = _normalize_host(url)
        self.engine = VideoEngine()  # required by workflow.py for download + header injection

    # ------------------------------------------------------------------
    # Public API (matches the contract expected by workflow.py / tui.py)
    # ------------------------------------------------------------------

    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Returns:
          metadata  — series-level info dict
          videos    — list of episode dicts (url, title, id, upload_date)
          info      — raw info dict (yt-dlp compatible keys where possible)
        """
        base_url = self.url.split('/ep-')[0]
        h = HEADERS.copy()
        h['Referer'] = self.url

        # ── Step 1: Page metadata ─────────────────────────────────────
        r = requests.get(base_url, headers=h)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        title_el = soup.select_one('h1.title')
        title = title_el.text.strip() if title_el else "Anikoto Anime"

        cover_el = soup.select_one('.poster img')
        cover = cover_el['src'] if cover_el else None

        synopsis_el = soup.select_one('.synopsis .content')
        synopsis = synopsis_el.text.strip() if synopsis_el else ""

        genres = [a.text.strip() for a in soup.select('.bmeta .meta a[href*="/genre/"]')]

        watch_main = soup.select_one('#watch-main')
        anime_id = watch_main['data-id'] if watch_main else None

        metadata = {
            "Channel/Series": title,
            "Source": "Anikoto",
            "Genres": ", ".join(genres) if genres else "Unknown",
            "Description": synopsis,
            "Thumbnail": cover,
            "ID": anime_id or "Unknown",
        }

        # ── Step 2: Episode list via AJAX ─────────────────────────────
        videos = []
        if anime_id:
            try:
                ajax_url = f"{self._host}/ajax/episode/list/{anime_id}"
                r_ajax = requests.get(ajax_url, headers=h)
                eps_html = r_ajax.json().get('result', '')
                ep_soup = BeautifulSoup(eps_html, 'lxml')
                eps = ep_soup.select('ul.ep-range li a')

                for ep in eps:
                    ep_num = ep.get('data-num', '?')
                    ep_id = ep.get('data-id', '')
                    ep_title_el = ep.select_one('.d-title')
                    ep_title = ep_title_el.text.strip() if ep_title_el else f"Episode {ep_num}"
                    data_ids = ep.get('data-ids', '')

                    videos.append({
                        "url": f"{base_url}/ep-{ep_num}",
                        "title": f"Ep {ep_num} - {ep_title}",
                        "id": ep_id,
                        "data_ids": data_ids,
                        "upload_date": 'UnknownDate',
                    })
            except Exception as e:
                logger.error(f"[Anikoto] Failed to fetch episode list: {e}")

        if not videos:
            videos.append({
                "url": self.url,
                "title": title,
                "id": anime_id or "Unknown",
                "data_ids": "",
                "upload_date": 'UnknownDate',
            })

        metadata["Total Videos"] = len(videos)

        info = {
            "id": anime_id,
            "title": title,
            "description": synopsis,
            "thumbnail": cover,
        }

        return metadata, videos, info

    def resolve_episode_stream(self, episode: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Given an episode dict (with 'data_ids' key), resolves the actual
        video stream URL using Playwright interception.

        Returns a dict: {m3u8_url, referer, subtitles, intro, outro}
        or None on failure.
        """
        data_ids = episode.get("data_ids", "")
        watch_url = episode.get("url", self.url)

        if not data_ids:
            logger.warning("[Anikoto] No data_ids for episode, cannot resolve stream.")
            return None

        from core.playwright_interceptor import get_stream
        embed_urls = self._get_all_embed_urls(data_ids, watch_url)
        
        for embed_url in embed_urls:
            stream = get_stream(embed_url)
            if stream and stream.get("m3u8_url"):
                return stream

        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_all_embed_urls(self, data_ids: str, watch_url: str) -> list[str]:
        """Try each server in the server list and return all available embed URLs."""
        h = HEADERS.copy()
        h['Referer'] = watch_url
        urls = []

        try:
            r = requests.get(
                f"{self._host}/ajax/server/list?servers={data_ids}", headers=h
            )
            html = r.json().get('result', '')
            soup = BeautifulSoup(html, 'lxml')

            # Prefer sub servers, fall back to all
            sub_servers = soup.select('.servers .type[data-type="sub"] li[data-link-id]')
            if not sub_servers:
                sub_servers = soup.select('li[data-link-id]')

            for server_el in sub_servers:
                link_id = server_el['data-link-id']
                r2 = requests.get(f"{self._host}/ajax/server?get={link_id}", headers=h)
                result = r2.json().get('result', {})
                url = result.get('url', '')
                if url:
                    logger.info(f"[Anikoto] Found server [{server_el.text.strip()}]: {url[:60]}...")
                    urls.append(url)
        except Exception as e:
            logger.error(f"[Anikoto] Server resolution error: {e}")

        return urls
