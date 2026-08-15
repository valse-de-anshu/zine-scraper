import re
import json
import logging
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class ProjectSukiScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
        desc_div = soup.select_one(".description")
        if desc_div:
            c = desc_div.get_text(separator=" ", strip=True)
            c = c.replace("Description:", "").strip()
            self.description = c

        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if not any(x in c.lower() for x in ["read manga", "fastest and highest", "favorite read", "scanlation team"]):
                    self.description = c
                    
        self.genres = []
        for a in soup.find_all("a", href=True):
            if "/genre/" in a["href"].lower():
                self.genres.append(a.get_text(strip=True).title())
                    
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
        
        # 1. Title from OpenGraph or Meta
        title_tag = soup.select_one('meta[property="og:title"]')
        title_text = title_tag["content"] if title_tag else "Unknown"
        title_text = title_text.split("|")[0].strip()
        
        ch_num_from_title = None
        if "/read/" in self.url:
            m = re.search(r"^(.*?)\s*-\s*Chapter\s+([\d.]+)", title_text, re.IGNORECASE)
            if m:
                title_text = m.group(1).strip()
                ch_num_from_title = m.group(2)
                
        title = re.sub(r"[^\w\s-]", "", title_text).strip().title()
        
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
                            chapters.append((float(num), num, urljoin(self.url, href)))

        # Deduplicate and Sort
        seen_nums = set()
        final_chapters = []
        # Reverse to keep the newest version of a chapter if there are duplicates (since they are usually sorted newest to oldest in table)
        # Actually, let's just keep the first one we see for each number
        for float_num, str_num, link in chapters:
            if str_num not in seen_nums:
                final_chapters.append((float_num, str_num, link))
                seen_nums.add(str_num)
        
        if ch_num_from_title and not final_chapters:
            final_chapters.append((float(ch_num_from_title), ch_num_from_title, self.url))

        final_chapters.sort(key=lambda x: x[0])
        self.title = title
        return title, [(n, u) for _, n, u in final_chapters]

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

        img_urls = list(dict.fromkeys(img_urls))
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
