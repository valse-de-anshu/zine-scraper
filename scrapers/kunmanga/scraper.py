import re
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("KunManga")

class KunMangaScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        # Extract info (will need soup)
        soup = getattr(self, "soup", None) or self.get_soup(self.url)
        self.description = ""
        for selector in ["#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"]:
            el = soup.select_one(selector)
            if el:
                desc = re.sub(r"\s+", " ", el.get_text(strip=True))
                if "is a popular title in the" not in desc.lower() and "readers can easily explore" not in desc.lower():
                    self.description = desc
                    break
                    
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                c = re.sub(r"\s+", " ", c)
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower() and "is a popular title in the" not in c.lower() and "readers can easily explore" not in c.lower():
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
        # Get series slug
        series_slug = self.url.rstrip("/").split("/")[-1]
        
        # 1. Fetch Title
        soup = self.get_soup(self.url)
        title_tag = soup.select_one("div.post-title h1, h1")
        title_text = title_tag.get_text(strip=True) if title_tag else "Unknown"
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", title_text)
        title = re.sub(r"[^\w\s-]", "", title).strip().title()
        
        # 2. Fetch Chapters via new API (Paginated)
        chapters = []
        try:
            # We need to loop through pages. Start with page 1 to find total pages.
            current_page = 1
            last_page = 1
            
            while current_page <= last_page:
                api_url = f"https://www.kunmanga.co.uk/api/comics/{series_slug}/chapters?page={current_page}"
                # Add simple retry for API
                for attempt in range(3):
                    try:
                        r = self.session.get(api_url, timeout=45)
                        if r.status_code == 200:
                            data = r.json()
                            if data.get("success") and "data" in data:
                                ch_list = data["data"].get("chapters", [])
                                for ch in ch_list:
                                    num_str = str(ch["chapter_num"])
                                    slug = ch["chapter_slug"]
                                    ch_url = f"https://www.kunmanga.co.uk/manga/{series_slug}/{slug}"
                                    chapters.append((float(num_str), num_str, ch_url))
                                
                                last_page = data["data"].get("last_page", 1)
                                current_page += 1
                                break # Success
                        elif r.status_code == 429: # Rate limit
                            time.sleep(5)
                    except Exception:
                        if attempt == 2: raise
                        time.sleep(2)
                else:
                    break
        except Exception as e:
            logger.warning(f"API fetch failed for {series_slug}: {e}")

        # Fallback to HTML if API failed
        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                if "/chapter-" in href or "/ch-" in href:
                    m = re.search(r"/(?:chapter|ch)-([\d.]+)", href)
                    if m:
                        num_str = m.group(1)
                        chapters.append((float(num_str), num_str, urljoin(self.url, a["href"])))
        
        # Deduplicate and sort from oldest to newest
        seen_urls = set()
        final_chapters = []
        chapters.sort(key=lambda x: x[0])

        for float_num, str_num, link in chapters:
            if link not in seen_urls:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
        
        self.title = title
        

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


        return title, final_chapters

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        imgs = soup.select("div.read-container img, div.page-break img, img.wp-manga-chapter-img, div.reading-content img")
        if not imgs: imgs = soup.find_all("img")
        img_urls = []
        for img in imgs:
            src = ""
            for attr in ["data-src", "src", "data-lazy-src", "data-cdn"]:
                val = img.get(attr)
                if val:
                    src = val.strip()
                    if src: break
            
            if src and not any(x in src.lower() for x in ["logo", "banner", "avatar", "icon", "ads"]):
                img_urls.append(urljoin(ch_url, src))
        
        img_urls = list(dict.fromkeys(img_urls))
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
