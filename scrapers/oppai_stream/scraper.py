import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import OppaiStreamEngine
import logging
logger = logging.getLogger(__name__)

class OppaiStreamScraper:
    def __init__(self, url: str):
        self.url = url
        self.engine = OppaiStreamEngine()
        
    def get_metadata_and_videos(self):
        # 1. Base URL / Slug logic
        import urllib.parse
        from bs4 import BeautifulSoup
        
        is_watch_url = "/watch?e=" in self.url
        base_slug = ""
        if is_watch_url:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.url).query)
            if "e" in qs:
                slug = qs["e"][0]
                import re
                base_slug = re.sub(r'-\d+$', '', slug)
        
        r = self.engine.session.get(self.url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        # Find Title
        if is_watch_url:
            h1 = soup.find('h1')
            if h1:
                title = re.sub(r'(?i)\s*Ep\s*\d+.*', '', h1.text.strip())
            else:
                title_tag = soup.find('title')
                title = title_tag.text.split('Series on')[0].strip() if title_tag else "Unknown Series"
                title = re.sub(r'(?i)Watch\s+', '', title)
                title = re.sub(r'(?i)\s*EP\s*\d+\s*in\s*HD.*', '', title)
        else:
            title_tag = soup.find('title')
            title = title_tag.text.split('Series on')[0].strip() if title_tag else "Unknown Series"

        # Find Thumbnail
        thumbnail = ""
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if 'thumbnail' in src or 'cover' in src or 'poster' in src or base_slug in src:
                thumbnail = src
                break
        if not thumbnail and soup.find('img'):
            thumbnail = soup.find('img').get('src', '')

        if thumbnail and not thumbnail.startswith('http'):
            thumbnail = urllib.parse.urljoin('https://oppai.stream', thumbnail)

        # 3. Extract videos
        videos = []
        seen = set()
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/watch?e=' in href:
                # If we are on a watch URL, only scrape links that match our base slug!
                if is_watch_url and base_slug and f"e={base_slug}" not in href:
                    continue
                
                ep_url = href if href.startswith('http') else urllib.parse.urljoin('https://oppai.stream', href)
                
                # Strip additional query parameters like &for=...
                clean_url = ep_url.split('&')[0]
                
                if clean_url not in seen:
                    seen.add(clean_url)
                    import re
                    match = re.search(r'-(\d+)$', clean_url.split('/')[-1])
                    ep_num = match.group(1) if match else "1"
                    videos.append({
                        "id": ep_num,
                        "title": f"Episode {ep_num}",
                        "url": clean_url
                    })

        # Sort by episode number (they appear in reverse order on the site)
        videos.sort(key=lambda x: int(x["id"]) if x["id"].isdigit() else 0)

        # Tags and Studio
        tags_list = []
        studio = ""
        for a in soup.find_all('a', href=True):
            if '/category/' in a['href'] or '/tag/' in a['href']:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            elif 'search?studio=' in a['href'] and not studio:
                studio = a.text.strip()
                
        # Description
        desc = ""
        desc_div = soup.find('div', class_='description') or soup.find('p', class_='description') or soup.find('div', class_='synopsis')
        if desc_div:
            desc = desc_div.text.strip()
        else:
            for p in soup.find_all('p'):
                if len(p.text.strip()) > 50:
                    desc = p.text.strip()
                    break
                    
        # If tags are empty because we are on a series page, fetch the first episode to get the tags!
        if not tags_list and videos:
            try:
                first_ep_url = videos[0]['url']
                ep_r = self.engine.session.get(first_ep_url, timeout=15)
                ep_r.raise_for_status()
                ep_soup = BeautifulSoup(ep_r.text, 'lxml')
                for a in ep_soup.find_all('a', href=True):
                    if '/category/' in a['href'] or '/tag/' in a['href']:
                        t = a.text.strip()
                        if t and t not in tags_list:
                            tags_list.append(t)
            except Exception as e:
                logger.warning(f"OppaiStream: failed to fetch tags from first episode: {e}")
        
        # Cover Image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            thumbnail = og_img['content']

        # Encode thumbnail if it has spaces
        import urllib.parse
        if thumbnail:
            parsed = urllib.parse.urlparse(thumbnail)
            encoded_path = urllib.parse.quote(parsed.path)
            thumbnail = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, encoded_path, parsed.params, parsed.query, parsed.fragment))

        meta = {
            "Channel/Series": title,
            "Source": "OppaiStream",
            "Total Videos": len(videos),
            "Thumbnail": thumbnail,
            "Avatar URL": thumbnail,
            "Studio": studio,
            "Tags": ", ".join(tags_list),
            "Description": desc,
            "URL": self.url
        }
        
        info = {"Total Videos": len(videos)}
        return meta, videos, info
