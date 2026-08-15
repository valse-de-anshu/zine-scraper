import re
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

logger = logging.getLogger("WeebCentral")

class WeebCentralScraper(BaseScraper):

    def get_title_and_chapters(self):
        original_url = self.url
        # Extract info (will need soup)
        soup = getattr(self, "soup", None) or self.get_soup(self.url)
        self.description = ""
        for strong in soup.find_all("strong"):
            if "Description" in strong.get_text(strip=True):
                p = strong.find_next_sibling("p")
                if p:
                    self.description = p.get_text(strip=True)
                    break

        if not self.description:
            for selector in ["#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"]:
                el = soup.select_one(selector)
                if el:
                    self.description = el.get_text(strip=True)
                    break
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if "read manga" not in c.lower() and "fastest and highest" not in c.lower() and "weeb central" not in c.lower():
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
        # 1. Handle Chapter URL to Series URL conversion
        if "/chapters/" in self.url:
            soup = self.get_soup(self.url)
            # Find the link that has the series name, usually in the reader nav
            series_a = soup.select_one("main a[href*='/series/'], a.overflow-hidden[href*='/series/']")
            if series_a:
                self.url = urljoin("https://weebcentral.com", series_a["href"])
                logger.info(f"Converted chapter link to series: {self.url}")

        # 2. Get Title and Cover from Series Page
        soup = self.get_soup(self.url)
        title_tag = soup.select_one("h1")
        title_text = title_tag.get_text(strip=True) if title_tag else "Unknown"
        title = re.sub(r"[^\w\s-]", "", title_text).strip().title()
        
        # Extract cover
        cover_tag = soup.select_one("section picture source[srcset*='/cover/normal/'], section picture img[src*='/cover/']")
        if cover_tag:
            raw_cov = cover_tag.get("srcset") or cover_tag.get("src")
            if raw_cov: self.cover_url = urljoin(self.url, raw_cov)
            if self.cover_url and "," in self.cover_url: # Handle srcset multiple URLs
                self.cover_url = self.cover_url.split(",")[0].split()[0]
        else:
            # Fallback to og:image
            og_img = soup.select_one("meta[property='og:image']")
            if og_img:
                self.cover_url = urljoin(self.url, og_img.get("content"))

        # 3. Get Series ID to fetch full chapter list
        series_id_match = re.search(r"/series/([^/]+)", self.url)
        if not series_id_match:
            return title, []
        series_id = series_id_match.group(1)

        # 4. Fetch Full Chapter List
        chapters = []
        full_list_url = f"https://weebcentral.com/series/{series_id}/full-chapter-list"
        try:
            r = self.session.get(full_list_url, timeout=30)
            if r.status_code == 200:
                list_soup = BeautifulSoup(r.text, "lxml")
                # Look for chapter links
                for a in list_soup.find_all("a", href=True):
                    if "/chapters/" in a["href"]:
                        # Extract chapter number from text
                        # Usually "Chapter X" or just "X"
                        text = a.get_text(strip=True)
                        m = re.search(r"Chapter\s*([\d.]+)", text)
                        if not m:
                            m = re.search(r"([\d.]+)", text)
                        
                        if m:
                            num_str = m.group(1)
                            ch_url = urljoin("https://weebcentral.com", a["href"])
                            chapters.append((float(num_str), num_str, ch_url))
        except Exception as e:
            logger.error(f"Failed to fetch full chapter list: {e}")

        # Fallback to current page if full list failed
        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            for a in soup.find_all("a", href=True):
                if "/chapters/" in a["href"]:
                    text = a.get_text(strip=True)
                    m = re.search(r"Chapter\s*([\d.]+)", text)
                    if m:
                        num_str = m.group(1)
                        chapters.append((float(num_str), num_str, urljoin("https://weebcentral.com", a["href"])))

        # Deduplicate and sort
        seen_urls = set()
        final_chapters = []
        chapters.sort(key=lambda x: x[0])
        
        for float_num, str_num, link in chapters:
            if link not in seen_urls:
                final_chapters.append((str_num, link))
                seen_urls.add(link)
                
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

        self.title = title
        
        if "/chapters/" in original_url:
            filtered = [ch for ch in final_chapters if ch[1].strip("/") == original_url.strip("/")]
            if filtered:
                return title, filtered
                
        return title, final_chapters

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        # Extract Chapter ID
        ch_id_match = re.search(r"/chapters/([^/]+)", ch_url)
        if not ch_id_match:
            return False
        ch_id = ch_id_match.group(1)

        # 1. Fetch Image List via AJAX
        img_urls = []
        ajax_url = f"https://weebcentral.com/chapters/{ch_id}/images?is_prev=False&current_page=1&reading_style=long_strip"
        try:
            r = self.session.get(ajax_url, timeout=30)
            if r.status_code == 200:
                ajax_soup = BeautifulSoup(r.text, "lxml")
                imgs = ajax_soup.find_all("img")
                for img in imgs:
                    src = (img.get("src") or img.get("data-src") or "").strip()
                    if src and not src.endswith("broken_image.jpg"):
                        img_urls.append(urljoin(ch_url, src))
        except Exception as e:
            logger.error(f"Failed to fetch images for {ch_url}: {e}")

        img_urls = list(dict.fromkeys(img_urls))
        if not img_urls:
            logger.warning(f"No images found for ch {ch_num} at {ch_url}")
            return False

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
