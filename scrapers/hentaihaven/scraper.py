from curl_cffi import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from core.base_scraper import UnifiedBaseScraper
from .engine import HentaiHavenEngine

class HentaiHavenScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HentaiHavenEngine()
        self.is_playlist = True
        self.session = requests.Session(impersonate="chrome124")
        self.title = "Unknown"
        self.title = "Unknown"
        self._folder_name = "Unknown"

    def get_link_type(self) -> str:
        return "model"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        def fetch(url):
            res = self.session.get(url, timeout=15)
            res.raise_for_status()
            return res.text
            
        html = self.retry(lambda: fetch(self.url))
        soup = BeautifulSoup(html, "html.parser")
        
        title_sel = self.get_selector("title")
        title_node = soup.select_one(title_sel) if title_sel else None
        series_title = title_node.text.strip() if title_node else self.url.split("/")[-2].title()

        self.title = series_title
        import re
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        cover_sel = self.get_selector("cover_url")
        cover_node = soup.select_one(cover_sel) if cover_sel else None
        cover_url = cover_node.get("src") or cover_node.get("data-src") if cover_node else None

        # Episode links
        ep_sel = self.get_selector("episode_list")
        ep_nodes = soup.select(ep_sel) if ep_sel else []
        
        # Typically Madara returns episodes in reverse order (newest first)
        ep_nodes = list(reversed(ep_nodes))
        
        # Fallback to current URL if no episodes found (maybe it's a single episode link)
        if not ep_nodes:
            import re
            series_url_match = re.search(r'(https?://[^/]+/watch/[^/]+/)', self.url)
            if series_url_match:
                series_url = series_url_match.group(1)
                if series_url != self.url and series_url != self.url + "/":
                    try:
                        series_html = self.retry(lambda: fetch(series_url))
                        series_soup = BeautifulSoup(series_html, "html.parser")
                        ep_nodes = series_soup.select(ep_sel) if ep_sel else []
                        ep_nodes = list(reversed(ep_nodes))
                        
                        if not cover_url and cover_sel:
                            c_node = series_soup.select_one(cover_sel)
                            if c_node:
                                cover_url = c_node.get("src") or c_node.get("data-src")
                        if title_sel:
                            t_node = series_soup.select_one(title_sel)
                            if t_node:
                                series_title = t_node.text.strip()
                                self.title = series_title
                                self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()
                    except Exception:
                        pass

        if not ep_nodes:
            ep_nodes = [{"href": self.url, "text": series_title}]

        metadata = {
            "Channel/Series": series_title,
            "Source": "HentaiHaven",
            "Total Videos": len(ep_nodes),
            "ID": series_title.lower().replace(" ", "-"),
            "Thumbnail": cover_url,
            "Avatar URL": cover_url
        }

        videos = []
        for idx, node in enumerate(ep_nodes, 1):
            href = node.get("href", node["href"] if isinstance(node, dict) else "")
            if not href:
                continue
                
            # If href is relative, make it absolute
            if href.startswith("/"):
                href = f"https://{self.config['primary_domain']}{href}"
                
            videos.append({
                "url": href,
                "title": f"Episode {idx}",
                "id": str(idx),
                "uploader": "HentaiHaven",
                "thumbnail": cover_url,
                "upload_date": ""
            })

        return metadata, videos, {"title": series_title, "url": self.url}
