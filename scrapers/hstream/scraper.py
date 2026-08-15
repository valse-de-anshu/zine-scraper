import re
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import HstreamEngine

class HstreamScraper:
    def __init__(self, url: str):
        self.url = url.strip("/")
        self.engine = HstreamEngine()
        
        # If url has -X at the end (an episode URL), trim it to get the series base URL
        # e.g. https://hstream.moe/hentai/reika-wa-karei-na-boku-no-joou-the-animation-4 -> https://hstream.moe/hentai/reika-wa-karei-na-boku-no-joou-the-animation
        self.base_url = re.sub(r"-\d+$", "", self.url)

    def get_metadata_and_videos(self):
        r = self.engine.session.get(self.base_url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        h1 = soup.find('h1')
        title = h1.text.strip() if h1 else self.base_url.split('/')[-1].replace('-', ' ').title()

        thumbnail = ""
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if 'cover-' in src:
                thumbnail = f"https://hstream.moe{src}" if src.startswith('/') else src
                break

        # If base url 404s or we didn't get episodes, try original URL
        if not thumbnail and not h1:
            self.base_url = self.url
            r = self.engine.session.get(self.base_url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'lxml')
            h1 = soup.find('h1')
            title = h1.text.strip() if h1 else self.base_url.split('/')[-1].replace('-', ' ').title()

        videos = []
        seen = set()
        
        # Look for episode links
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Only match links that start with our base URL slug
            slug = self.base_url.split('/')[-1]
            if f"/hentai/{slug}" in href:
                # Ensure it has a -N suffix (it's a video episode)
                match = re.search(r"-(\d+)$", href)
                if match:
                    ep_num = match.group(1)
                    ep_url = href if href.startswith('http') else f"https://hstream.moe{href}"
                    
                    if ep_url not in seen:
                        seen.add(ep_url)
                        videos.append({
                            "id": ep_num,
                            "title": f"Episode {ep_num}",
                            "url": ep_url,
                        })

        # Sort by episode number
        videos.sort(key=lambda x: int(x["id"]))

        # If we couldn't find any episode links (maybe it's a standalone movie), use the base url as video 1
        if not videos:
            videos.append({
                "id": "1",
                "title": "Movie",
                "url": self.base_url
            })

        tags_list = []
        studio = ""
        summary = ""
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'tags%5B0%5D=' in href:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            elif 'studios%5B0%5D=' in href and not studio:
                studio = a.text.strip()
                
        for p in soup.find_all('p'):
            if p.text.strip() and len(p.text.strip()) > 30:
                summary = p.text.strip()
                break

        meta = {
            "Channel/Series": title,
            "Source": "Hstream",
            "Total Videos": len(videos),
            "Thumbnail": thumbnail,
            "Avatar URL": thumbnail,
            "Studio": studio,
            "Tags": ", ".join(tags_list),
            "Description": summary,
            "URL": self.base_url
        }
        
        info = {"Total Videos": len(videos)}
        return meta, videos, info
