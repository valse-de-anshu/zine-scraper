import requests
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from core.base_scraper import UnifiedBaseScraper
from .engine import HanimeEngine

class HanimeScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HanimeEngine()
        self.is_playlist = True  # We always fetch the whole franchise
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://hanime.tv/",
            "Accept": "application/json"
        })
        self.title = "Unknown"
        self._folder_name = "Unknown"
        self.franchise_structure = "flat"

    def get_link_type(self) -> str:
        return "model"

    def get_slug(self) -> str:
        pattern = self.config.get("patterns", {}).get("slug_from_url", "([^/]+)/?$")
        match = re.search(pattern, self.url)
        if match:
            return match.group(1).split("?")[0]
        return self.url.split("/")[-1].split("?")[0]

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        slug = self.get_slug()
        
        # Scrape data directly from HTML since guest API is blocked by Cloudflare/Turnstile
        html_res = self.session.get(self.url, timeout=15)
        html_res.raise_for_status()
        
        import bs4
        import re
        soup = bs4.BeautifulSoup(html_res.text, "html.parser")
        
        # Title
        title_tag = soup.find("h1")
        raw_title = title_tag.text.strip() if title_tag else slug
        
        # Split raw title (e.g. "Series Name 4") into series and episode
        m = re.search(r'^(.*?)\s+(\d+)$', raw_title)
        if m:
            series_title = m.group(1).strip()
            ep_title = f"Episode {m.group(2)}"
        else:
            series_title = raw_title
            ep_title = raw_title
        
        # Cover
        og_img = soup.find("meta", property="og:image")
        franchise_cover = og_img["content"] if og_img and og_img.get("content") else ""
        
        # Description
        desc_div = soup.find("div", {"data-expand-content": True})
        description = desc_div.text.strip() if desc_div else ""
        
        # Tags and Studio
        tags = []
        studios = ""
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/browse/tags/" in href:
                tags.append(a.text.strip())
            elif "/browse/brands/" in href:
                # the studio name is usually inside a <strong> tag
                strong = a.find("strong")
                studios = strong.text.strip() if strong else a.text.replace("Studio", "").strip()

        # Deduplicate tags
        tags = list(dict.fromkeys(tags))
        
        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()
        
        metadata = {
            "Channel/Series": series_title,
            "Source": "Hanime.tv",
            "Total Videos": 1, # will be updated below
            "ID": slug,
            "Thumbnail": franchise_cover,
            "Avatar URL": franchise_cover,
            "Studio": studios,
            "Tags": ", ".join(tags) if tags else "None",
            "Description": description[:150] + "..." if len(description) > 150 else description
        }

        # Franchise / Playlist videos
        # Hanime shows related videos in the same franchise as links matching /videos/hentai/
        # but we also need to include the current video.
        videos = []
        slugs_found = []
        
        # Add current video first
        videos.append({
            "url": self.url,
            "title": ep_title,
            "id": slug,
            "uploader": "Hanime",
            "thumbnail": franchise_cover,
            "upload_date": "20260101"
        })
        slugs_found.append(slug)
        
        # Find other episodes in the franchise (they are usually rendered below the player)
        franchise_container = None
        for h2 in soup.find_all("h2"):
            if "More from" in h2.text:
                franchise_container = h2.parent
                break
                
        if franchise_container:
            for a in franchise_container.find_all("a", href=True):
                href = a["href"]
                if href.startswith("/videos/hentai/") and href != f"/videos/hentai/{slug}":
                    ep_slug = href.split("/")[-1].split("?")[0]
                    if ep_slug not in slugs_found:
                        slugs_found.append(ep_slug)
                        
                        # Try to find a title. Usually it's in a span or img alt
                        img = a.find("img")
                        ep_title_raw = img["alt"].replace("thumbnail", "").strip() if img and img.get("alt") else ep_slug
                        
                        # Parse episode title cleanly
                        m2 = re.search(r'^(.*?)\s+(\d+)$', ep_title_raw)
                        if m2:
                            parsed_ep_title = f"Episode {m2.group(2)}"
                        else:
                            parsed_ep_title = ep_title_raw
                        
                        videos.append({
                            "url": f"https://{self.config['primary_domain']}/videos/hentai/{ep_slug}",
                            "title": parsed_ep_title,
                            "id": ep_slug,
                            "uploader": "Hanime",
                            "thumbnail": franchise_cover,
                            "upload_date": "20260101"
                        })
                        
        metadata["Total Videos"] = len(videos)
        
        # Sort videos by title to ensure Ep 1, Ep 2 order
        videos.sort(key=lambda x: x["title"])

        return metadata, videos, {}
