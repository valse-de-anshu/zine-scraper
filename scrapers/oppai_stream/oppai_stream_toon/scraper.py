import re
import json
import logging
import requests
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class OppaiStreamToonScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return "/page?m=" in self.url

    def get_title_and_chapters(self):
        # Base Series URL looks like: https://read.oppai.stream/manhwa?m=the-father-in-law-fucks-them-all
        series_url = self.url
        if self.is_chapter_link():
            match = re.search(r'm=([^&]+)', self.url)
            if match:
                series_url = f"https://read.oppai.stream/manhwa?m={match.group(1)}"

        soup = self.get_soup(series_url)
        
        # Description
        self.description = ""
        desc_div = soup.find('div', class_='description') or soup.find('p', class_='description') or soup.find('div', class_='synopsis')
        if desc_div:
            self.description = re.sub(r"\s+", " ", desc_div.get_text(strip=True))

        # Title
        title = "Unknown Manhwa"
        h1 = soup.find('h1')
        if h1:
            title = h1.text.strip()
            title = re.sub(r'(?i)Read\s+', '', title)
            title = re.sub(r'(?i)\s*Manhwa\s+on\s+Oppai\s+for\s+Free!.*', '', title).strip()
            title = re.sub(r'(?i)\s*\bBy\b\s+.*', '', title).strip()

        # Chapters
        chapters = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/page?m=" in href and "&c=" in href:
                c_match = re.search(r'&c=([\d\.]+)', href)
                if c_match:
                    num = c_match.group(1)
                    ep_url = href if href.startswith('http') else urljoin('https://read.oppai.stream', href)
                    chapters.append((float(num), num, ep_url))
        
        # If it is a single chapter link, filter the list to only that chapter!
        if self.is_chapter_link():
            target_c_match = re.search(r'&c=([\d\.]+)', self.url)
            if target_c_match:
                target_num = target_c_match.group(1)
                chapters = [c for c in chapters if c[1] == target_num]
        
        # Deduplicate and Sort
        seen = set()
        final_chapters = []
        for c in chapters:
            if c[2] not in seen:
                final_chapters.append(c)
                seen.add(c[2])
        
        final_chapters.sort(key=lambda x: x[0])
        self.title = title
        
        # Tags
        if not hasattr(self, "tags"): self.tags = []
        if not hasattr(self, "genres"): self.genres = []
        
        return title, [(n, u) for _, n, u in final_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        img_urls = []
        
        # OppaiStream Manhwa fetches the total image count via AJAX
        match_m = re.search(r'm=([^&]+)', ch_url)
        match_c = re.search(r'c=([\d\.]+)', ch_url)
        if match_m and match_c:
            m = match_m.group(1)
            c = match_c.group(1)
            import time
            for attempt in range(3):
                try:
                    api_url = f"https://myspacecat.pictures/manhwa/images.php?f-m={m}&c={c}"
                    r = self.session.get(api_url, timeout=30, headers={"Referer": "https://read.oppai.stream/"})
                    if r.status_code == 200 and r.text.strip().isdigit():
                        total_images = int(r.text.strip())
                        
                        # Test which extension is valid
                        base_img_url = f"https://myspacecat.pictures/manhwa/{m}/{c}/"
                        ext = ".jpg" # fallback default
                        for test_ext in [".jpg", ".webp", ".png"]:
                            try:
                                test_r = self.session.head(base_img_url + "1" + test_ext, timeout=15)
                                if test_r.status_code == 200:
                                    ext = test_ext
                                    break
                            except:
                                pass
                            
                        for i in range(1, total_images + 1):
                            img_urls.append(f"{base_img_url}{i}{ext}")
                        break # Break retry loop if successful
                except Exception as e:
                    if attempt == 2:
                        logging.warning(f"Failed to fetch image count for {ch_url} after 3 tries: {e}")
                    time.sleep(1)
        
        if not img_urls:
            logging.warning(f"No images found for {ch_url}")
            return {"success": False, "status": "failed", "reason": "No images found or API timeout", "downloaded": 0, "total": 0, "missing": 0}
            
        img_urls = list(dict.fromkeys(img_urls))
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
