import re
import json
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class ProjectSukiScraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.series_url = None
        self.title = ""
        self.title_display = ""
        self.alt_title = ""
        self.author = ""
        self.artist = ""
        self.status = ""
        self.origin = ""
        self.media_type = "Manhwa"
        self.year = ""
        self.views = ""
        self.rating = ""
        self.genres = []
        self.tags = []
        self.description = ""
        self.cover_url = None

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])

    def get_title_and_chapters(self):
        target_url = self.url
        ch_num_from_title = None

        if self.is_chapter_link():
            m_book = re.search(r"/read/(\d+)", self.url)
            if m_book:
                self.series_url = f"https://projectsuki.com/book/{m_book.group(1)}"
                target_url = self.series_url

        soup = self.get_soup(target_url)

        # 1. Title
        title_h = soup.find("h2", {"itemprop": "title"}) or soup.find(["h1", "h2"])
        raw_title = title_h.get_text(strip=True) if title_h else ""
        if not raw_title:
            title_tag = soup.select_one('meta[property="og:title"]')
            raw_title = title_tag["content"] if title_tag and title_tag.get("content") else ""
            raw_title = raw_title.split("|")[0].strip()

        if "/read/" in self.url:
            m = re.search(r"^(.*?)\s*-\s*Chapter\s+([\d.]+)", raw_title, re.IGNORECASE)
            if m:
                raw_title = m.group(1).strip()
                ch_num_from_title = m.group(2)

        self.title_display = raw_title.strip()
        title_folder = re.sub(r"[^\w\s-]", "", self.title_display).strip().title()
        self.title = title_folder or self.title_display

        # 2. Key-Value Rows
        self.alt_title = ""
        self.author = ""
        self.artist = ""
        self.status = ""
        self.origin = ""
        self.year = ""
        self.views = ""
        self.rating = ""
        self.genres = []

        for row in soup.find_all("div", class_="row"):
            cols = row.find_all("div", recursive=False)
            if len(cols) >= 2:
                label = cols[0].get_text(strip=True).rstrip(":").lower()
                val_div = cols[1]

                if "alt" in label and "title" in label:
                    self.alt_title = val_div.get_text(" ", strip=True)
                elif "author" in label:
                    a_tags = val_div.find_all("a")
                    if a_tags:
                        self.author = ", ".join([a.get_text(strip=True) for a in a_tags if a.get_text(strip=True)])
                    else:
                        self.author = val_div.get_text(" ", strip=True)
                elif "artist" in label:
                    a_tags = val_div.find_all("a")
                    if a_tags:
                        self.artist = ", ".join([a.get_text(strip=True) for a in a_tags if a.get_text(strip=True)])
                    else:
                        self.artist = val_div.get_text(" ", strip=True)
                elif "status" in label:
                    self.status = val_div.get_text(" ", strip=True)
                elif "origin" in label:
                    self.origin = val_div.get_text(" ", strip=True)
                elif "year" in label or "release" in label:
                    self.year = val_div.get_text(" ", strip=True)
                elif "view" in label:
                    self.views = val_div.get_text(" ", strip=True).replace(",", "")
                elif "rating" in label or "ratings" in label:
                    stars = val_div.find_all("i", class_=lambda c: c and "fa-star" in c and "text-warning" in c)
                    if stars:
                        self.rating = str(len(stars))
                elif "genre" in label:
                    for a in val_div.find_all("a"):
                        g = a.get_text(strip=True).title()
                        if g and g not in self.genres:
                            self.genres.append(g)

        # Origin to Media Type
        if "japan" in self.origin.lower():
            self.media_type = "Manga"
        elif "china" in self.origin.lower():
            self.media_type = "Manhua"
        else:
            self.media_type = "Manhwa"

        # Genres fallback
        if not self.genres:
            for a in soup.find_all("a", href=True):
                if "/genre/" in a["href"].lower():
                    g = a.get_text(strip=True).title()
                    if g and g not in self.genres:
                        self.genres.append(g)

        self.tags = list(dict.fromkeys(self.genres))

        # Description
        self.description = ""
        desc_div = soup.find(id="descriptionCollapse") or soup.select_one(".description")
        if desc_div:
            c = desc_div.get_text(separator=" ", strip=True)
            c = re.sub(r"^Description:\s*", "", c, flags=re.IGNORECASE).strip()
            c = re.sub(r"-\s*Show\s+Less\s*-\s*$", "", c, flags=re.IGNORECASE).strip()
            self.description = c

        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if not any(x in c.lower() for x in ["read manga", "fastest and highest", "favorite read", "scanlation team"]):
                    self.description = c

        # Cover URL
        img_tag = soup.find("img", class_=lambda c: c and "img-thumbnail" in c) or soup.select_one(".col-sm-5 img, .col-xl-3 img")
        if img_tag:
            srcset = img_tag.get("srcset", "")
            cover_src = ""
            if srcset:
                parts = [p.strip().split() for p in srcset.split(",") if p.strip()]
                if parts:
                    cover_src = parts[-1][0]
            if not cover_src:
                cover_src = img_tag.get("src", "")
            if cover_src:
                self.cover_url = urljoin(target_url, cover_src)

        chapters = []
        # ProjectSuki uses a table for chapters
        table = soup.find("table")
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 2: continue
                
                lang = cells[1].get_text(strip=True).lower()
                if "english" not in lang:
                    continue

                links = row.find_all("a", href=True)
                if links:
                    a = links[0]
                    name = a.get_text(strip=True)
                    href = a["href"]
                    
                    if "/read/" in href:
                        num_match = re.search(r"(?i)Chapter\s+([\d.]+)", name) or re.search(r"([\d.]+)", name)
                        if num_match:
                            num = num_match.group(1)
                            if "." in num: continue
                            chapters.append((float(num), num, urljoin(target_url, href)))

        # Deduplicate and Sort
        seen_nums = set()
        final_chapters = []
        for float_num, str_num, link in chapters:
            if str_num not in seen_nums:
                final_chapters.append((float_num, str_num, link))
                seen_nums.add(str_num)
        
        if ch_num_from_title and not final_chapters:
            final_chapters.append((float(ch_num_from_title), ch_num_from_title, self.url))

        final_chapters.sort(key=lambda x: x[0])
        return self.title, [(n, u) for _, n, u in final_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        # ProjectSuki loads images via an API call /callpage
        # Extract book_id and chapter_id from URL: https://projectsuki.com/read/202689/39571/1
        parts = ch_url.rstrip("/").split("/")
        if len(parts) < 6:
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}
            
        book_id = parts[parts.index("read") + 1]
        chapter_id = parts[parts.index("read") + 2]
        
        img_urls = []
        
        # 1. Initial page image (Page 1)
        soup = self.get_soup(ch_url)
        # The first image is in .strip-reader or similar
        first_img = soup.select_one(".strip-reader img")
        if first_img:
            img_urls.append(urljoin(ch_url, first_img["src"]))
        
        # 2. Call API for remaining pages
        try:
            api_url = "https://projectsuki.com/callpage"
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "Referer": ch_url,
                "X-Requested-With": "XMLHttpRequest"
            }
            data = {"bookid": book_id, "chapterid": chapter_id, "first": True}
            r = self.session.post(api_url, json=data, headers=headers, timeout=30)
            if r.status_code == 200:
                resp_data = r.json()
                api_soup = BeautifulSoup(resp_data.get("src", ""), "lxml")
                for img in api_soup.find_all("img"):
                    src = img.get("src")
                    if src:
                        img_urls.append(urljoin(ch_url, src))
        except Exception as e:
            logging.warning(f"ProjectSuki API failed: {e}")

        bad_keywords = (
            "logo", "banner", "avatar", "icon", "ads", "advert", "sponsor",
            "spinner", "loading", "placeholder", "pixel", "tracker", "promo"
        )
        filtered_urls = []
        for u in img_urls:
            if not u or u.startswith("data:"):
                continue
            if not u.startswith("http"):
                continue
            if any(kw in u.lower() for kw in bad_keywords):
                continue
            filtered_urls.append(u)

        filtered_urls = list(dict.fromkeys(filtered_urls))
        return self.process_chapter_multi(filtered_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
