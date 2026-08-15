import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import HentaimamaEngine
import logging

logger = logging.getLogger(__name__)

class HentaimamaScraper:
    def __init__(self, url: str):
        self.url = url
        self.engine = HentaimamaEngine()
        
    def get_metadata_and_videos(self):
        series_url = self.url
        if "/episodes/" in self.url:
            try:
                r = self.engine.session.get(self.url, timeout=15)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'lxml')
                
                # e.g. /episodes/kyou-wa-yubiwa-o-hazusu-kara-episode-1/ -> kyou-wa-yubiwa-o-hazusu-kara
                slug_match = re.search(r'/episodes/(.*?)-episode-', self.url)
                expected_slug = slug_match.group(1) if slug_match else ""
                
                for a in soup.find_all('a', href=True):
                    if f'/tvshows/{expected_slug}' in a['href']:
                        series_url = a['href']
                        if not series_url.startswith('http'):
                            series_url = urllib.parse.urljoin('https://hentaimama.io', series_url)
                        break
            except Exception as e:
                logger.error(f"Hentaimama: failed to resolve watch URL to series URL: {e}")

        r = self.engine.session.get(series_url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'lxml')

        title_tag = soup.find('title')
        if title_tag:
            title = re.sub(r'(?i)Stream\s+', '', title_tag.text)
            title = re.sub(r'(?i)\s*hentai\s+with\s+English.*', '', title).strip()
            title = re.sub(r'(?i)\s*Episode\s*\d+\s*with\s+English.*', '', title).strip()
        else:
            title = series_url.strip('/').split('/')[-1].replace('-', ' ').title()

        thumbnail = ""
        expected_slug = series_url.strip('/').split('/')[-1]
        
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if 'base64' in src.lower():
                continue
            alt = img.get('alt', '')
            if (alt and alt.lower() == title.lower()) or ('tvshows' in src) or (expected_slug in src):
                thumbnail = src
                break
                
        if not thumbnail:
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'base64' in src.lower():
                    continue
                if 'wp-content/uploads' in src and 'poster' not in src.lower():
                    thumbnail = src
                    break
        
        if not thumbnail and soup.find('img'):
            thumbnail = soup.find('img').get('src', '')
            
        if thumbnail and not thumbnail.startswith('http'):
            thumbnail = urllib.parse.urljoin('https://hentaimama.io', thumbnail)

        videos = []
        seen = set()
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/episodes/' in href and expected_slug in href:
                # Strip query params like ?player=...
                clean_url = href.split('?')[0]
                ep_url = clean_url if clean_url.startswith('http') else urllib.parse.urljoin('https://hentaimama.io', clean_url)
                if ep_url not in seen:
                    seen.add(ep_url)
                    
                    # Try to extract episode number, e.g. /episodes/campus-episode-1/
                    match = re.search(r'-(\d+)/?$', ep_url)
                    ep_num = match.group(1) if match else str(len(videos) + 1)
                    
                    videos.append({
                        "id": ep_num,
                        "title": f"Episode {ep_num}",
                        "url": ep_url
                    })

        # Sort by episode number
        videos.sort(key=lambda x: int(x["id"]) if x["id"].isdigit() else 0)

        # Tags and Studio
        tags_list = []
        studio = ""
        for a in soup.find_all('a', href=True):
            if '/genre/' in a['href']:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            elif '/studio/' in a['href'] and not studio:
                studio = a.text.strip()
                
        # Description
        desc = ""
        desc_div = soup.find('div', class_='wp-content') or soup.find(class_='description')
        if desc_div:
            desc = desc_div.text.strip()

        meta = {
            "Channel/Series": title,
            "Source": "Hentaimama",
            "Total Videos": len(videos),
            "Thumbnail": thumbnail,
            "Avatar URL": thumbnail,
            "Studio": studio,
            "Tags": ", ".join(tags_list),
            "Description": desc,
            "URL": series_url
        }
        
        info = {"Total Videos": len(videos)}
        return meta, videos, info
