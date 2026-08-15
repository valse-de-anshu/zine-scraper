import re
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class ManhwaUSScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
        for selector in ["#syn-target", "div.entry-content", "div.manga-excerpt", "div.description-summary", "div.summary-content", "div.post-content", "p.summary"]:
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
        title_tag = soup.select_one("h1.chapter-name, h1")
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", title_tag.get_text(strip=True) if title_tag else "Unknown")
        title = re.sub(r"[^\w\s-]", "", title).strip().title()
        chapters = []
        container = soup.select_one("ul.row-content-chapter, div.panel-manga-chapter")
        links = container.find_all("a", href=True) if container else soup.find_all("a", href=True)
        for a in links:
            href = a["href"].lower()
            if "/chapter-" in href:
                m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", href)
                num = m.group(1).replace("-", ".").replace("-", ".") if m else "0"
                chapters.append((float(num), num, urljoin(self.url, a["href"])))
        
        seen = set()
        final_chapters = []
        for c in chapters:
            if c[2] not in seen:
                final_chapters.append(c)
                seen.add(c[2])
                
        if not final_chapters and self.is_chapter_link():
            m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", self.url.lower())
            if m:
                num = m.group(1).replace("-", ".")
                final_chapters = [(float(num), num, self.url)]
            else:
                parts = [p for p in self.url.strip('/').split('/') if p]
                ch_num = parts[-1] if parts else "1"
                final_chapters = [(0.0, ch_num, self.url)]
                
        final_chapters.sort(key=lambda x: x[0])
        self.title = title
        

        self.genres = []
        for div in soup.find_all("div", class_="post-content_item"):
            if "genre" in div.get_text(strip=True).lower():
                for a in div.find_all("a", href=True):
                    t = a.get_text(strip=True).title()
                    if t and t not in self.genres:
                        self.genres.append(t)


        return title, [(n, u) for _, n, u in final_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        imgs = soup.select("div.container-chapter-reader img, div.read-container img, div.reading-content img")
        if not imgs: imgs = soup.find_all("img")
        img_urls = []
        for img in imgs:
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src and "logo" not in src.lower() and "banner" not in src.lower():
                img_urls.append(urljoin(ch_url, src))
        
        img_urls = list(dict.fromkeys(img_urls))
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
