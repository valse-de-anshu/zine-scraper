import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from core.base_scraper import UnifiedBaseScraper

class HentaiHavenCoScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        from .engine import HentaiHavenCoEngine
        self.engine = HentaiHavenCoEngine()
        self.is_playlist = True
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self.title = "Unknown"
        self._folder_name = "Unknown"

    def get_link_type(self) -> str:
        return "model"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        def fetch(url):
            res = self.session.get(url, timeout=15)
            res.raise_for_status()
            return res.text
            
        import re
        # Parse slug from URL (e.g. enjo-kouhai-episode-11)
        slug_match = re.search(r'/watch/([^/]+)', self.url)
        if not slug_match:
            slug_match = re.search(r'/series/([^/]+)', self.url)
        
        slug = slug_match.group(1) if slug_match else "unknown"
        
        # Remove -episode-X to get series slug
        series_slug = re.sub(r'-episode-\d+.*', '', slug).strip('-')
        series_title = series_slug.replace('-', ' ').title()
        
        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()

        ep_nodes = []
        cover_url = None

        if self.is_playlist:
            try:
                # Search for all episodes of the series
                search_url = f"https://hentaihaven.co/search/?q={series_title.replace(' ', '+')}"
                html = self.retry(lambda: fetch(search_url))
                soup = BeautifulSoup(html, "html.parser")
                
                # Extract all video items
                for a in soup.select('a.a_item'):
                    href = a.get('href', '')
                    if 'episode' in href and series_slug in href:
                        v_title = a.select_one('.video_title')
                        v_title_text = v_title.text.strip() if v_title else "Video"
                        
                        v_img = a.select_one('img.lazy')
                        img_src = v_img.get('data-src') if v_img else None
                        
                        if img_src and not img_src.startswith('http'):
                            img_src = f"https://hentaihaven.co{img_src}"
                            
                        if not cover_url and img_src:
                            cover_url = img_src
                            
                        if not href.startswith('http'):
                            href = f"https://hentaihaven.co{href}"
                            
                        # Extract episode number for sorting
                        ep_match = re.search(r'episode-(\d+)', href)
                        ep_num = int(ep_match.group(1)) if ep_match else 0
                        
                        ep_nodes.append({
                            "href": href,
                            "text": v_title_text,
                            "ep_num": ep_num,
                            "img": img_src
                        })
                
                # Sort episodes by episode number ascending (1, 2, 3...)
                ep_nodes.sort(key=lambda x: x["ep_num"])
            except Exception as e:
                pass

        if not ep_nodes:
            ep_nodes = [{"href": self.url, "text": series_title, "ep_num": 1, "img": None}]

        # Fetch the series page to get tags/summary if we are on a single episode
        series_url = f"https://hentaihaven.co/series/{series_slug}/"
        try:
            series_html = fetch(series_url)
            series_soup = BeautifulSoup(series_html, "html.parser")
        except:
            series_soup = None
            
        tags_list = []
        summary = ""
        
        # Try finding tags/summary on the current page first
        try:
            current_html = fetch(self.url)
            current_soup = BeautifulSoup(current_html, "html.parser")
            
            for a in current_soup.find_all('a', href=True):
                if '/tag/' in a['href'] or '/studio/' in a['href']:
                    t = a.text.strip()
                    if t and t not in tags_list:
                        tags_list.append(t)
                        
            for p in current_soup.find_all('p'):
                if p.text.strip() and len(p.text.strip()) > 50:
                    summary = p.text.strip()
                    break
        except:
            pass

        metadata = {
            "Channel/Series": series_title,
            "Source": "HentaiHavenCo",
            "Total Videos": len(ep_nodes),
            "ID": series_slug,
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Studio": "",
            "Tags": ", ".join(tags_list),
            "Description": summary,
            "URL": self.url
        }

        videos = []
        for idx, node in enumerate(ep_nodes, 1):
            ep_num = node["ep_num"] or idx
            videos.append({
                "url": node["href"],
                "title": f"Episode {ep_num}",
                "id": str(ep_num),
                "uploader": "HentaiHavenCo",
                "thumbnail": node["img"] or cover_url,
                "upload_date": ""
            })

        return metadata, videos, {"title": series_title, "url": self.url}
