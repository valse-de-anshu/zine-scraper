import requests
from pathlib import Path
from typing import Dict, Any, List, Tuple
from core.base_scraper import UnifiedBaseScraper
from .engine import HanimeRedEngine

class HanimeRedScraper(UnifiedBaseScraper):
    def __init__(self, url: str):
        super().__init__(url, Path(__file__).parent / "site_config.json")
        self.engine = HanimeRedEngine()
        self.is_playlist = True
        self.title = "Unknown"
        self._folder_name = "Unknown"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        })

    def get_link_type(self) -> str:
        return "series"

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        # Use yt-dlp to grab metadata for the main requested video
        info = self.engine.extract_video_info(self.url)
        
        # Try to extract base series name from URL (e.g. enjo-kouhai-episode-11 -> enjo-kouhai)
        import re
        from bs4 import BeautifulSoup
        
        slug_match = re.search(r'/([^/]+)/?$', self.url)
        slug = slug_match.group(1) if slug_match else ""
        
        base_slug = slug
        if "-episode-" in slug:
            base_slug = slug.split("-episode-")[0]
            
        series_title = info.get("title", "HanimeRed Video")
        series_title = re.sub(r'(?i)\s*-?\s*episode\s*\d+.*', '', series_title).strip()
            
        self.title = series_title
        self._folder_name = re.sub(r'[<>:"/\\|?*]', '', series_title).strip()
        
        cover_url = info.get("thumbnail")
        
        studio = ""
        summary = ""
        tags_str = ""
        html_date = ""

        # Fetch the page to find other episodes and missing cover
        try:
            res = self.session.get(self.url, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            if not cover_url:
                og_img = soup.find('meta', property='og:image')
                if og_img and og_img.get('content'):
                    cover_url = og_img['content']
                else:
                    post_img = soup.find('img', class_='wp-post-image')
                    if post_img and post_img.get('src'):
                        cover_url = post_img['src']
                        
            # --- Extract additional metadata ---
            for label in soup.find_all(string=lambda text: text and "Brand" in text and "Uploads" not in text):
                if label.parent and label.parent.find_next_sibling():
                    studio = label.parent.find_next_sibling().text.strip()
                    break
                    
            for label in soup.find_all(string=lambda text: text and "Release Date" in text):
                if label.parent and label.parent.find_next_sibling():
                    html_date = label.parent.find_next_sibling().text.strip()
                    break
                    
            for p in soup.find_all('p'):
                text = p.text.strip()
                if len(text) > 50:
                    summary = text
                    break
                    
            tags_list = []
            tag_links = soup.find_all('a', href=lambda h: h and '/tag/' in h.lower())
            for a in tag_links:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            tags_str = ", ".join(tags_list)
            
            links = soup.find_all("a", href=True)
            
            ep_urls = set()
            for a in links:
                href = a["href"]
                if f"/{base_slug}-episode-" in href:
                    ep_urls.add(href)
            
            # If the current URL is not in the set, add it
            ep_urls.add(self.url)
            
            # Find the max episode number
            max_ep = 1
            for u in ep_urls:
                m = re.search(r'-episode-(\d+)', u)
                if m:
                    max_ep = max(max_ep, int(m.group(1)))
            
            # Fill in the gaps (if the related list truncated some episodes)
            base_url_pattern = self.url
            if "-episode-" in self.url:
                base_url_pattern = re.sub(r'-episode-\d+', '-episode-{}', self.url)
                for i in range(1, max_ep + 1):
                    ep_urls.add(base_url_pattern.format(i))
                    
            ep_urls = list(ep_urls)
            
            # Sort by episode number
            def extract_ep_num(u):
                m = re.search(r'-episode-(\d+)', u)
                return int(m.group(1)) if m else 999
                
            ep_urls.sort(key=extract_ep_num)
        except Exception:
            ep_urls = [self.url]

        metadata = {
            "Channel/Series": series_title,
            "Source": "HanimeRed",
            "Total Videos": len(ep_urls),
            "ID": info.get("id", "unknown"),
            "Thumbnail": cover_url,
            "Avatar URL": cover_url,
            "Studio": studio,
            "Tags": tags_str,
            "Description": summary
        }

        videos = []
        for idx, u in enumerate(ep_urls, 1):
            import re
            m = re.search(r'-episode-(\d+)', u)
            ep_num = m.group(1) if m else str(idx)
            
            videos.append({
                "url": u,
                "title": f"Episode {ep_num}",
                "id": str(ep_num),
                "uploader": "HanimeRed",
                "thumbnail": cover_url,
                "upload_date": info.get("upload_date") or html_date
            })

        return metadata, videos, {"title": series_title, "url": self.url}
