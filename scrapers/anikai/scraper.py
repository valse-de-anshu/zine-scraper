import re
import urllib.parse
from bs4 import BeautifulSoup
import requests
from typing import Tuple, Dict, Any, List
from urllib.parse import urlparse
from .engine import AnikaiEngine

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

class AnikaiScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        parsed = urlparse(url)
        self._host = f"{parsed.scheme}://{parsed.netloc}"
        self.engine = AnikaiEngine()
        self.is_playlist = False

    def get_metadata_and_videos(self) -> tuple[dict, list[dict], dict]:
        h = HEADERS.copy()
        
        try:
            r = requests.get(self.url, headers=h, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch Anikai page: {e}")

        effective_url = r.url

        # ── Metadata ──────────────────────────────────────────────────────────
        metadata = {"Source": "Anikai"}
        
        # Title
        title_el = soup.select_one('h1.d-title, h2.d-title, .title')
        title_text = title_el.text.strip() if title_el else "Unknown Series"
        metadata["Channel/Series"] = title_text
        
        # Cover
        cover_img = soup.select_one('div.poster img')
        if cover_img and cover_img.get('src'):
            metadata["Thumbnail"] = cover_img.get('src')
            
        # Description
        desc_el = soup.select_one('.desc, .synopsis, #synopsis, .info-desc, .description')
        if desc_el:
            metadata["Description"] = desc_el.text.strip()
            
        # Other metadata
        for item in soup.select('.info-item, .item, .detail-item, div'):
            text = item.text.strip()
            if ':' in text and len(text) < 100:
                parts = text.split(':', 1)
                key = parts[0].strip()
                val = parts[1].strip()
                if key in ['Type', 'Status', 'Studios', 'Duration', 'Genres', 'Scores', 'Premiered']:
                    metadata[key] = val

        # ── Episodes ──────────────────────────────────────────────────────────
        videos = []
        base = self._host
        eps_els = soup.select('div.eplist a')
        for el in eps_els:
            ep_url = urllib.parse.urljoin(base, el.get('href', ''))
            
            parts = el.text.strip().split('\n')
            ep_title = parts[-1].strip() if parts else "Episode"
            
            videos.append({
                "id": ep_url,
                "title": f"{title_text} - {ep_title}",
                "url": ep_url,
                "duration": None
            })

        if not videos:
            videos.append({
                "id": effective_url,
                "title": title_text,
                "url": effective_url,
                "duration": None
            })

        metadata["Total Videos"] = len(videos)

        # ── Servers for current episode ───────────────────────────────────────
        server_items = []
        for s in soup.select('.server, .ep-server, .server-item, [data-video], [data-server], iframe'):
            vid_url = s.get('data-video') or s.get('data-server') or s.get('src')
            if vid_url and vid_url.startswith('http'):
                tab_name = 'tab_0'
                server_items.append({
                    "name": s.text.strip() or "Server",
                    "url": vid_url,
                    "tab": tab_name
                })
        
        info = {"server_items": server_items}

        return metadata, videos, info
