import json
import subprocess
from pathlib import Path
from .engine import OhentaiEngine
import logging

logger = logging.getLogger(__name__)

class OhentaiScraper:
    def __init__(self, url: str):
        self.url = url
        self.engine = OhentaiEngine()
        
    def get_metadata_and_videos(self):
        # ohentai.org is behind Cloudflare, but yt-dlp natively supports it and bypasses/extracts it.
        # We will use yt-dlp -j to get the metadata directly.
        
        videos = []
        meta = {
            "Channel/Series": "Ohentai Video",
            "Total Videos": 1,
            "Thumbnail": ""
        }
        info = {"Total Videos": 1}

        try:
            from bs4 import BeautifulSoup
            import re
            
            script_path = Path(__file__).parent.parent / "playwright_extractor.py"
            cmd = ["python3", str(script_path), self.url]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            # The script outputs "JSON_RESULT:{...}" at the end
            out_str = result.stdout
            json_str = out_str.split('JSON_RESULT:')[-1]
            data = json.loads(json_str)
            html = data.get("html", "")
            
            title = data.get('title', 'Unknown Title')
            
            soup = BeautifulSoup(html, 'lxml')
            
            # Series name is usually in an h1 or boldly formatted, but since title is "Series - Episode X" we can just split it
            series_name = title
            if " - " in title:
                series_name = title.split(" - ")[0]
                
            meta["Channel/Series"] = series_name
            
            # Tags
            tags = []
            for a in soup.find_all('a', href=True):
                if 'tagsearch.php?tag=' in a['href']:
                    t = a.text.strip()
                    if t and t not in tags:
                        tags.append(t)
            meta["Tags"] = ", ".join(tags)
            
            # Description
            desc = ""
            for elem in soup.find_all(string=lambda x: x and 'Description:' in x):
                desc_text = elem.parent.parent.text.strip()
                desc_text = desc_text.replace('Description:', '').strip()
                if desc_text:
                    desc = desc_text
                    break
            meta["Description"] = desc
            
            # Cover Image
            for img in soup.find_all('img'):
                src = img.get('src', '')
                if 'cover' in src:
                    if not src.startswith('http'):
                        src = f"https://ohentai.org/{src}"
                    meta["Thumbnail"] = src
                    meta["Avatar URL"] = src
                    break
                    
            # Episodes
            ep_nodes = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if 'detail.php?vid=' in href:
                    ep_text = a.text.strip()
                    # Ohentai displays other series at the bottom. The series episodes are literal "Episode1", "Episode 2"
                    if re.match(r'^Episode\s*\d+$', ep_text, re.IGNORECASE):
                        if ep_text not in [ep['title'] for ep in ep_nodes]:
                            ep_nodes.append({
                                "title": ep_text,
                                "href": href if href.startswith('http') else f"https://ohentai.org/{href}"
                            })
            
            # Add current episode if it wasn't in the list
            if not any(ep['href'] == self.url for ep in ep_nodes):
                # Try to figure out current episode number from title
                ep_text = "Episode 1"
                if " - Episode " in title:
                    ep_text = "Episode " + title.split(" - Episode ")[1].split()[0]
                ep_nodes.append({"title": ep_text, "href": self.url})
                
            # Sort episodes naturally by their Episode number
            import re
            def extract_ep_num(ep):
                m = re.search(r'Episode\s*(\d+)', ep['title'], re.IGNORECASE)
                return int(m.group(1)) if m else 0
            ep_nodes.sort(key=extract_ep_num)
            
            for idx, ep in enumerate(ep_nodes, 1):
                ep_num = extract_ep_num(ep) or idx
                videos.append({
                    "id": str(ep_num),
                    "title": f"Episode {ep_num}",
                    "url": ep['href']
                })
            
        except Exception as e:
            logger.error(f"Ohentai: failed to extract metadata via yt-dlp: {e}")
            videos.append({
                "id": "1",
                "title": "Ohentai Video",
                "url": self.url
            })

        return meta, videos, info
