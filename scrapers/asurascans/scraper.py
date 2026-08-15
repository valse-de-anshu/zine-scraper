import re
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("AsuraScans")

class AsuraScansScraper(BaseScraper):
    scraper_type = "toon"

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
        for selector in ["#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"]:
            el = soup.select_one(selector)
            if el:
                self.description = re.sub(r"\s+", " ", el.get_text(strip=True))
                break
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower():
                    self.description = c
                    
        self.author = ""
        author_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "/authors/" in href or "/author/" in href or "/artist/" in href or "/artists/" in href:
                t = a.get_text(strip=True)
                if t and t.lower() not in ["author", "artist", "authors", "artists"]:
                    author_links.append(t)
        if author_links:
            self.author = ", ".join(list(dict.fromkeys(author_links)))
        # Asura typically uses h1.entry-title or similar
        title_tag = soup.select_one("h1.entry-title, h1")
        title_text = title_tag.get_text(strip=True) if title_tag else "Unknown"
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", title_text)
        title = re.sub(r"[^\w\s-]", "", title).strip().title()
        
        chapters = []
        # Target all links on the series page
        links = soup.find_all("a", href=True)
        for a in links:
            href = a["href"].lower()
            # Match pattern like /comics/series-slug/chapter/1
            # Or /chapter/1
            if "/chapter/" in href:
                m = re.search(r"/chapter/([\d.]+)", href)
                if m:
                    num_str = m.group(1)
                    # Handle relative URLs
                    full_url = urljoin("https://asurascans.com", a["href"])
                    chapters.append((float(num_str), num_str, full_url))
        
        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            logger.warning(f"No chapters discovered for {self.url}. Structure might have changed.")

        seen_urls = set()
        seen_nums = set()
        final_chapters = []
        
        # Sort by number oldest to newest
        chapters.sort(key=lambda x: x[0])

        for float_num, str_num, link in chapters:
            if link not in seen_urls and str_num not in seen_nums:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
                seen_nums.add(str_num)
        
        self.title = title
        
        original_url = getattr(self, "url", "")
        if "/chapter/" in original_url.lower():
            m = re.search(r"/chapter/([\d.]+)", original_url.lower())
            if m:
                return title, [(m.group(1), original_url)]

        if not hasattr(self, "tags"): self.tags = []
        if not hasattr(self, "genres"): self.genres = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            text = a.get_text(strip=True).title()
            if not text or len(text) > 40: continue
            
            bad_parent = False
            for p in a.parents:
                if p.name in ["nav", "aside", "header", "footer"]:
                    bad_parent = True
                    break
                if p.get("id") in ["sidebar", "menu"] or "sidebar" in p.get("class", []):
                    bad_parent = True
                    break
            
            if bad_parent: continue
            
            if "genre" in href:
                if text not in self.genres: self.genres.append(text)
            elif "tag" in href:
                if text not in self.tags: self.tags.append(text)

        return title, final_chapters

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        
        # Asura Scans often embeds images in a JSON object for Astro
        # or uses standard <img> tags.
        img_urls = []
        
        # Method 1: Look for images in the HTML
        imgs = soup.find_all("img")
        for img in imgs:
            src = (img.get("data-src") or img.get("src") or img.get("data-lazy-src") or "").strip()
            if src and "asura-images/chapters" in src:
                # Clean up query params if any
                clean_src = src.split('?')[0]
                img_urls.append(urljoin(ch_url, clean_src))
        
        # Method 2: Extract from JSON structure if available (fallback)
        if not img_urls:
            # pages&quot;:[1,[[0,{&quot;url&quot;:[0,&quot;https://...&quot;]
            json_matches = re.findall(r'&quot;url&quot;:\[\d+,&quot;(https?://[^&]+)&quot;\]', str(soup))
            for match in json_matches:
                if "asura-images/chapters" in match:
                    img_urls.append(match.replace("\\/", "/"))

        img_urls = list(dict.fromkeys(img_urls))
        if not img_urls:
            logger.warning(f"No images found for ch {ch_num} at {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
