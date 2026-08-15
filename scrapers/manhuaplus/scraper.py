import re
import json
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class ManhuaPlusScraper(BaseScraper):
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
        title_tag = soup.select_one("div.post-title h1, h1")
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", title_tag.get_text(strip=True) if title_tag else "Unknown")
        title = re.sub(r"[^\w\s-]", "", title).strip().title()

        chapters = []
        # Target the specific dynamic script if available
        scripts = soup.find_all("script")
        for s in scripts:
            if s.string and "wp-manga-chapter" in s.string:
                pass

        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            # Standard link extraction
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                if "/chapter-" in href:
                    m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", href)
                    num = m.group(1).replace("-", ".").replace("-", ".") if m else "0"
                    chapters.append((float(num), num, urljoin(self.url, a["href"])))
        
        # Deduplicate and Sort
        seen = set()
        final_chapters = []
        for c in chapters:
            if c[2] not in seen:
                final_chapters.append(c)
                seen.add(c[2])
        
        final_chapters.sort(key=lambda x: x[0])
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
            elif "tag" in href:
                if text not in self.tags: self.tags.append(text)


        return title, [(n, u) for _, n, u in final_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        img_data = [] # List of (index, url)
        
        # 1. Try to find CHAPTER_ID and fetch via AJAX
        ch_id_match = re.search(r"const\s+CHAPTER_ID\s*=\s*(\d+)", str(soup))
        if ch_id_match:
            ch_id = ch_id_match.group(1)
            try:
                ajax_url = f"https://manhuaplus.org/ajax/image/list/chap/{ch_id}"
                headers = {"X-Requested-With": "XMLHttpRequest", "Referer": ch_url}
                r = self.session.post(ajax_url, headers=headers, timeout=30)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status"):
                        ajax_soup = BeautifulSoup(data["html"], "lxml")
                        containers = ajax_soup.select("div.separator")
                        for div in containers:
                            idx_str = div.get("data-index")
                            a = div.select_one("a.readImg")
                            img = div.select_one("img")
                            
                            # On ManhuaPlus AJAX, 'src' usually has the real link
                            src = ""
                            if a and a.get("href") and not a.get("href").startswith("#"):
                                src = a["href"]
                            elif img:
                                src = (img.get("src") or img.get("data-src") or "").strip()
                            
                            if src and "loading" not in src.lower() and idx_str is not None:
                                img_data.append((int(idx_str), urljoin(ch_url, src)))
            except Exception as e:
                logging.warning(f"AJAX image fetch failed for {ch_url}: {e}")

        # 2. Sort images by index
        img_data.sort(key=lambda x: x[0])
        img_urls = [url for _, url in img_data]

        # 3. Fallback if AJAX returned nothing
        if not img_urls:
            imgs = soup.select("div.page-break img, div.read-container img, div#chapterContent img")
            for img in imgs:
                src = (img.get("data-src") or img.get("src") or "").strip()
                if src and "loading" not in src.lower() and "logo" not in src.lower():
                    img_urls.append(urljoin(ch_url, src))
        
        img_urls = list(dict.fromkeys(img_urls))
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
