import re
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class Hentai20Scraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.domain = "hentai20.io"

    def get_title_and_chapters(self) -> tuple[str, list[tuple[str, str]]]:
        soup = self.get_soup(self.url)

        title = soup.find("h1", class_="entry-title")
        if not title:
            title = soup.find("h1")
        title = title.get_text(strip=True) if title else "Unknown Title"
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", title).strip()

        desc_div = soup.select_one("div.entry-content")
        if desc_div:
            self.description = desc_div.get_text(strip=True)

        self.genres = []
        for a in soup.select("div.seriestugenre a"):
            t = a.get_text(strip=True).title()
            if t and t not in self.genres:
                self.genres.append(t)
                
        self.tags = []
        for a in soup.select(".mgen a[href*='tag']"):
            t = a.get_text(strip=True).title()
            if t and t not in self.tags:
                self.tags.append(t)

        self.author = ""
        for tr in soup.select("table.infotable tr"):
            th = tr.find("th")
            td = tr.find("td")
            if th and td and "Author" in th.get_text(strip=True):
                self.author = td.get_text(strip=True)
                break

        final_chapters = []
        chlist = soup.select("div.eplister li a, div#chapterlist li a")
        for a in chlist:
            href = a["href"]
            c_num_match = re.search(r"chapter-?(\d+(\.\d+)?)", href, re.I)
            if c_num_match:
                final_chapters.append((float(c_num_match.group(1)), str(c_num_match.group(1)), href))
        
        # fallback
        if not final_chapters:
            for a in soup.select("div.eplister li a, div#chapterlist li a"):
                name = a.select_one(".chapternum")
                name = name.get_text(strip=True) if name else a.get_text(strip=True)
                c_num_match = re.search(r"(\d+(\.\d+)?)", name)
                if c_num_match:
                    final_chapters.append((float(c_num_match.group(1)), str(c_num_match.group(1)), a["href"]))

        # Remove duplicates
        seen = set()
        unique_chapters = []
        for sort_val, num_str, url in final_chapters:
            if num_str not in seen:
                seen.add(num_str)
                unique_chapters.append((sort_val, num_str, url))

        unique_chapters.sort(key=lambda x: x[0])
        self.title = title
        return title, [(n, u) for _, n, u in unique_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        import logging
        soup = self.get_soup(ch_url)
        imgs = soup.select("div#readerarea img")

        img_urls = []
        for img in imgs:
            src = ""
            for attr in ["data-src", "src", "data-original", "data-lazy-src"]:
                val = img.get(attr)
                if val:
                    src = val.strip().replace("\n", "").replace("\r", "").replace("\t", "")
                    if src:
                        break
            if src:
                full_src = urljoin(ch_url, src)
                if not any(x in full_src.lower() for x in ["logo", "banner", "avatar", "icon", "ads", "button", "loader"]):
                    img_urls.append(full_src)

        img_urls = list(dict.fromkeys(img_urls))

        if not img_urls:
            logging.warning(f"No images found for chapter {ch_num} at {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)

