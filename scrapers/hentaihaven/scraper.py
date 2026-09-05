import re
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from curl_cffi import requests
from core.base_scraper import UnifiedBaseScraper
from .engine import HentaiHavenEngine

logger = logging.getLogger(__name__)


class HentaiHavenScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HentaiHavenEngine()
        self.is_playlist = True
        self.session = requests.Session(impersonate="chrome124")
        self.title = "Unknown"
        self._folder_name = "Unknown"

    def get_link_type(self) -> str:
        return "series"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        def fetch(u: str) -> str:
            res = self.session.get(u, timeout=(10, 30))
            res.raise_for_status()
            return res.text

        html = self.retry(lambda: fetch(self.url))
        soup = BeautifulSoup(html, "html.parser")

        # Parse series_slug and ep_slug
        m = re.match(r"https?://([^/]+)/watch/([^/]+)(?:/([^/]+))?/?", self.url)
        domain = m.group(1) if m else "hentaihaven.xxx"
        series_slug = m.group(2) if m else self.url.strip("/").split("/")[-1]
        ep_slug = m.group(3) if m else None
        series_url = f"https://{domain}/watch/{series_slug}/"

        series_title = None
        cover_url = None
        ep_title = None
        upload_date = None

        # 1. Parse JSON-LD metadata
        for s in soup.select("script[type=\"application/ld+json\"]"):
            try:
                data = json.loads(s.string)
                if isinstance(data, dict):
                    graph = data.get("@graph") if isinstance(data.get("@graph"), list) else ([data] if "@type" in data else [])
                    for g in graph:
                        g_type = g.get("@type")
                        if g_type == "BreadcrumbList":
                            items = g.get("itemListElement", [])
                            if len(items) >= 3 and not series_title:
                                series_title = items[2].get("name")
                            if len(items) >= 4 and not ep_title:
                                ep_title = items[3].get("name")
                        elif g_type == "WebPage" and not ep_slug:
                            if not series_title:
                                series_title = g.get("name")
                        elif g_type == "ImageObject" and not cover_url:
                            cover_url = g.get("contentUrl") or g.get("url")
                        elif g_type == "VideoObject":
                            if not cover_url:
                                thumbs = g.get("thumbnailUrl", [])
                                if thumbs:
                                    cover_url = thumbs[0]
                            if not upload_date:
                                raw_date = g.get("uploadDate", "")
                                upload_date = raw_date[:10].replace("-", "") if raw_date else ""
            except Exception:
                pass

        # 2. Fallback for series title and episode title
        h1 = soup.select_one("h1")
        if h1:
            span = h1.select_one("span")
            if span:
                ep_title = ep_title or span.text.strip()
                span.decompose()
            if not series_title:
                series_title = h1.text.strip()

        if not series_title:
            series_title = series_slug.replace("-", " ").title()

        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        # 3. Discover all episodes and true series cover from series catalog
        series_html = html if not ep_slug else None
        if not series_html:
            try:
                series_html = self.retry(lambda: fetch(series_url))
            except Exception as e:
                logger.warning(f"Could not fetch series catalog {series_url}: {e}")
                series_html = html

        series_soup = BeautifulSoup(series_html, "html.parser")

        # Extract REAL series poster from the series catalog page
        series_cover = None
        for s in series_soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(s.string)
                graph = data.get("@graph", []) if isinstance(data.get("@graph"), list) else [data]
                for g in graph:
                    if g.get("@type") == "ImageObject":
                        cand = g.get("contentUrl") or g.get("url")
                        if cand and "img.hentaihaven.xxx" in cand:
                            series_cover = cand
                            break
                        elif cand and not series_cover:
                            series_cover = cand
            except Exception:
                pass

        if not series_cover:
            img = series_soup.select_one('img[src*="img.hentaihaven.xxx/images/"]')
            if img:
                src = img.get("src")
                series_cover = re.sub(r"/s_([^/]+)$", r"/\1", src)

        if not series_cover:
            series_cover = cover_url

        episodes_map = {}
        for a in series_soup.find_all("a", href=True):
            href = a["href"]
            if f"/watch/{series_slug}" in href:
                full = f"https://{domain}" + href if href.startswith("/") else href
                full_norm = full.rstrip("/")
                if full_norm != series_url.rstrip("/"):
                    m_ep = re.search(r"/episode-(\d+)", full_norm)
                    num = int(m_ep.group(1)) if m_ep else 999
                    raw_text = a.get_text(separator=" ", strip=True)

                    ep_thumb = None
                    img_node = a.find("img")
                    if img_node:
                        ep_thumb_src = img_node.get("src") or img_node.get("data-src")
                        if ep_thumb_src:
                            ep_thumb = ep_thumb_src.replace("s_thumbnail.", "thumbnail.")

                    if num not in episodes_map:
                        episodes_map[num] = {
                            "url": full_norm + "/",
                            "title": f"Episode {num}" if num != 999 else (raw_text or "Episode 1"),
                            "num": num,
                            "thumbnail": ep_thumb or series_cover,
                        }

        # If current URL was an episode and not in map, add it
        if ep_slug:
            m_curr = re.search(r"episode-(\d+)", ep_slug)
            curr_num = int(m_curr.group(1)) if m_curr else 1
            if curr_num not in episodes_map:
                episodes_map[curr_num] = {
                    "url": self.url.rstrip("/") + "/",
                    "title": ep_title or f"Episode {curr_num}",
                    "num": curr_num,
                    "thumbnail": cover_url or series_cover,
                }

        sorted_eps = sorted(episodes_map.values(), key=lambda x: x["num"])
        if not sorted_eps:
            sorted_eps = [{
                "url": self.url,
                "title": ep_title or "Episode 1",
                "num": 1,
                "thumbnail": series_cover,
            }]

        metadata = {
            "Channel/Series": series_title,
            "Source": "HentaiHaven",
            "Total Videos": len(sorted_eps),
            "ID": series_slug,
            "Thumbnail": series_cover,
            "Avatar URL": series_cover,
        }

        videos = []
        for idx, ep in enumerate(sorted_eps, 1):
            videos.append({
                "url": ep["url"],
                "title": ep["title"],
                "id": str(ep["num"]) if ep["num"] != 999 else str(idx),
                "uploader": "HentaiHaven",
                "thumbnail": ep.get("thumbnail") or series_cover,
                "upload_date": upload_date or "",
            })

        return metadata, videos, {"title": series_title, "url": self.url}

