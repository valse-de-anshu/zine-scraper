import requests
import re
from bs4 import BeautifulSoup
from typing import Tuple, Dict, Any, List
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.5'}

from scrapers.anitaku.engine import AnitakuEngine

class AnitakuScraper:
    def __init__(self, url: str):
        self.url = url
        self.scraper_type = "video"
        self._host = "https://anitaku.online"
        self.engine = AnitakuEngine()
        
    def get_metadata_and_videos(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        h = HEADERS.copy()
        h["Referer"] = self._host
        
        r = requests.get(self.url, headers=h)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        
        # If episode page, grab category link to get proper metadata
        if "-episode-" in self.url:
            anime_link = soup.select_one(".anime-info a")
            if anime_link:
                self.url = self._host + anime_link.get("href")
                r = requests.get(self.url, headers=h)
                soup = BeautifulSoup(r.text, "lxml")
            else:
                for a in soup.select("a"):
                    if "/category/" in a.get("href", ""):
                        self.url = self._host + a.get("href")
                        r = requests.get(self.url, headers=h)
                        soup = BeautifulSoup(r.text, "lxml")
                        break
                        
        title_el = soup.select_one(".anime_info_body_bg h1")
        title = title_el.text.strip() if title_el else "Unknown Series"
        
        cover_img = soup.select_one(".anime_info_body_bg img")
        cover = cover_img.get("src") if cover_img else ""
        
        extracted = {}
        for span in soup.select(".anime_info_body_bg p.type span"):
            key = span.text.strip().replace(":", "")
            p = span.parent
            val = p.text.replace(span.text, "").strip()
            if not val:
                parts = []
                node = p.next_sibling
                while node and (not hasattr(node, "name") or node.name != "p"):
                    if hasattr(node, "text"):
                        parts.append(node.text.strip())
                    elif isinstance(node, str):
                        parts.append(node.strip())
                    node = node.next_sibling
                val = " ".join([x for x in parts if x])
            val = re.sub(r"\s+", " ", val).strip()
            extracted[key] = val
        
        metadata = {
            "Channel/Series": title,
            "Description": extracted.get("Plot Summary", "No description available."),
            "Genres": extracted.get("Genre", ""),
            "Total Videos": int(extracted.get("Episodes", 0)) if extracted.get("Episodes", "").isdigit() else 0,
            "Thumbnail": cover,
            "Source": "Anitaku"
        }
        # Add the remaining attributes dynamically so they are captured
        for k, v in extracted.items():
            if k not in ["Plot Summary", "Genre", "Episodes"]:
                metadata[k] = v
        
        videos = []
        eps = soup.select("#episode_related li a")
        for ep in eps:
            ep_url = ep.get("href", "").strip()
            if ep_url.startswith("/"):
                ep_url = self._host + ep_url
                
            ep_num = ep.select_one(".name")
            ep_name = ep_num.text.strip() if ep_num else "Unknown"
            
            videos.append({
                "url": ep_url,
                "title": f"{ep_name} - {title}",
                "id": ep_url,
                "upload_date": "Unknown"
            })
            
        if videos:
            metadata["Total Videos"] = len(videos)
            
        return metadata, videos, {}
