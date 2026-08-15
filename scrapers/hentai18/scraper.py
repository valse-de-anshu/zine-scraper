import re
import logging
import shutil
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("Hentai18")

def clean_metadata_text(text: str) -> str:
    if not text:
        return ""
    # Replace common symbols like //, |\, \, |, / with spaces
    for sym in ["//", "|\\", "\\", "|", "/"]:
        text = text.replace(sym, " ")
    # Replace multiple spaces with a single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()

class Hentai18Scraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
        for selector in ["div.desc", "div.entry-content", "div.panel-story-info-description", "div.manga-excerpt", "div.description-summary", "#syn-target", "div.post-content", "p.summary", "div.summary-content"]:
            el = soup.select_one(selector)
            if el:
                desc_text = el.get_text(strip=True)
                self.description = clean_metadata_text(desc_text)
                break
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower():
                    self.description = clean_metadata_text(c)
                    
        self.author = ""
        author_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "/authors/" in href or "/author/" in href or "/artist/" in href or "/artists/" in href:
                t = a.get_text(strip=True)
                if t and t.lower() not in ["author", "artist", "authors", "artists"]:
                    cleaned_t = clean_metadata_text(t)
                    if cleaned_t:
                        author_links.append(cleaned_t)
        if author_links:
            self.author = ", ".join(list(dict.fromkeys(author_links)))
        title_tag = soup.select_one("div.tit h1, h1")
        text = title_tag.get_text(strip=True) if title_tag else "Unknown"
        text = clean_metadata_text(text)
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", text)
        title = re.sub(r"[^\w\s-]", "", title)
        title = re.sub(r"\s+", " ", title).strip().title()
        
        chapters = []
        all_links = soup.find_all("a", href=True)
        for a in all_links:
            href = a["href"].strip()
            # Handle links like "/read-hentai/buy-2-get-1-free-chapter-1-ch130006"
            if "/chapter-" in href.lower() or "/ch-" in href.lower():
                # Extract number using regex on the stripped href
                m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", href.lower())
                if not m:
                    m = re.search(r"ch-([\d]+(?:[\.-][\d]+)?)", href.lower())
                
                if m:
                    num = m.group(1).replace("-", ".")
                    full_url = urljoin(self.url, href)
                    chapters.append((float(num), num, full_url))
        
        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            # Try a very broad search for ANY link containing the title slug and a number
            slug = self.url.split("/")[-1]
            for a in all_links:
                href = a["href"].strip()
                if slug in href and any(char.isdigit() for char in href):
                    # Ensure it's an internal link
                    if href.startswith("/") or self.domain in href:
                        # Extract the part after the slug
                        after_slug = href.split(slug)[-1]
                        m = re.search(r"(\d+)", after_slug)
                        if m:
                            num = m.group(1).replace("-", ".")
                            full_url = urljoin(self.url, href)
                            # Final sanity check: strictly internal links only
                            if self.domain in full_url.lower() and not any(x in full_url.lower() for x in ["twitter.com", "pinterest.com", "vk.com", "google.com"]):
                                chapters.append((float(num), num, full_url))
        
        seen_urls = set()
        seen_nums = set()
        final_chapters = []
        
        # Sort by number first
        chapters.sort(key=lambda x: x[0])

        for float_num, str_num, link in chapters:
            if link not in seen_urls and str_num not in seen_nums:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
                seen_nums.add(str_num)
                
        self.title = title
        

        self.tags = []
        self.genres = []
        
        for div in soup.find_all("div", class_="line"):
            text = div.get_text(strip=True).lower()
            if "tag" in text or "genre" in text:
                for a in div.find_all("a", href=True):
                    t = a.get_text(strip=True)
                    cleaned_t = clean_metadata_text(t).title()
                    if cleaned_t and cleaned_t not in self.tags:
                        self.tags.append(cleaned_t)

        toon_keywords = {"webtoon", "manhwa", "manhua", "toon", "long strip"}
        self.is_toon = any(t.lower() in toon_keywords for t in self.tags)
        return title, final_chapters

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        
        # 1. Target real images in item-photo or common reading containers
        imgs = soup.select("div.item-photo img, div.read-container img, div.page-break img")
        if not imgs:
            imgs = soup.find_all("img")
            
        img_urls = []
        for img in imgs:
            src = ""
            for attr in ["data-src", "src", "data-original", "data-lazy-src"]:
                val = img.get(attr)
                if val:
                    src = val.strip().replace("\n", "").replace("\r", "").replace("\t", "")
                    if src: break
            
            if src:
                full_src = urljoin(ch_url, src)
                # Hentai18 real images often contain /media.hentai18.net/ or /manga/
                if "/media." in full_src.lower() or "/manga/" in full_src.lower() or "/wp-content/" in full_src.lower():
                    # Filter out non-chapter images
                    if not any(x in full_src.lower() for x in ["logo", "banner", "avatar", "icon", "ads", "button", "loader"]):
                        img_urls.append(full_src)
        
        img_urls = list(dict.fromkeys(img_urls))
        
        if not img_urls:
            logging.warning(f"No images found for chapter {ch_num} at {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
