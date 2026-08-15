import re
import json
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin

class MangaKScraper(BaseScraper):
    scraper_type = "toon"

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
        for selector in ["#syn-target", "div.description-summary", "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary", "p.line-clamp-3", "p.text-fg-muted"]:
            el = soup.select_one(selector)
            if el:
                self.description = el.get_text(strip=True)
                break
        if not self.description:
            meta = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta and meta.get("content"):
                c = meta.get("content").strip()
                if not any(x in c.lower() for x in ["read manga", "fastest and highest", "mangabuddy", "website dedicated to fans"]):
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
        script = soup.find("script", id="__NEXT_DATA__")
        if not script: return "Unknown", []
        
        data = json.loads(script.string)
        manga = data["props"]["pageProps"]["initialManga"]
        title = manga.get("name", "Unknown").strip().title()
        manga_id = manga.get("id")
        
        if self.is_chapter_link():
            m = re.search(r"(?:chapter|ch)-([\d.]+)", self.url, re.IGNORECASE)
            num = m.group(1) if m else "1"
            self.title = title
            return title, [(num, self.url)]
        
        self.genres = []
        if manga.get("genres"):
            for g in manga["genres"]:
                if "name" in g:
                    self.genres.append(g["name"].title())
                    
        # Check if actual description is in JSON
        if manga.get("description"):
            desc = str(manga["description"]).strip()
            if not any(x in desc.lower() for x in ["mangabuddy", "website dedicated to fans"]):
                self.description = desc
                
        # Clean up mangabuddy SEO garbage injected around the real plot
        if self.description:
            if "Main Plot" in self.description and "Why should you read" in self.description:
                start = self.description.find("Main Plot") + len("Main Plot")
                end = self.description.find("Why should you read")
                self.description = self.description[start:end]
            elif "Welcome to mangabuddy" in self.description:
                self.description = ""
            
            # Flatten to plain text (remove newlines and excessive whitespace)
            self.description = re.sub(r"\s+", " ", self.description).strip()
        
        chapters = []
        if manga_id:
            page = 1
            while True:
                try:
                    api_url = f"https://api.mangak.io/titles/{manga_id}/chapters?limit=500&page={page}"
                    resp = self.session.get(api_url, timeout=15)
                    resp_data = resp.json()
                    
                    if not resp_data.get("success") or not resp_data.get("data", {}).get("chapters"):
                        break
                        
                    for ch in resp_data["data"]["chapters"]:
                        api_num = str(ch.get("chapter_number", "0"))
                        name = ch.get("name", "")
                        path = ch.get("url")
                        
                        # Extract real number from name (e.g., "Chapter 2" -> "2")
                        # Priority: "Chapter X" > "Ch. X" > first number found
                        num_match = re.search(r"(?i)Chapter\s+([\d.]+)", name) or re.search(r"([\d.]+)", name)
                        num = num_match.group(1) if num_match else api_num
                        
                        # Filter out chapters with decimals (e.g., 1.1, 101.3, or Extra. Hiatus)
                        if "." in name or "." in num:
                            continue
                            
                        if path:
                            chapters.append((float(num), num, urljoin("https://mangak.io", path)))
                    
                    pagination = resp_data.get("data", {}).get("pagination", {})
                    if not pagination.get("has_next"):
                        break
                    
                    page += 1
                except Exception as e:
                    break
        
        # Fallback to initial data if API fails
        if not chapters and not (hasattr(self, 'is_chapter_link') and self.is_chapter_link()):
            for ch in manga.get("chapters", []):
                api_num = str(ch.get("chapterNumber", "0"))
                name = ch.get("name", "")
                path = ch.get("url")
                
                # Extract real number from name
                num_match = re.search(r"(?i)Chapter\s+([\d.]+)", name) or re.search(r"([\d.]+)", name)
                num = num_match.group(1) if num_match else api_num

                # Filter out chapters with decimals
                if "." in name or "." in num:
                    continue
                    
                if path: chapters.append((float(num), num, urljoin("https://mangak.io", path)))
        
        # Remove exact duplicates while preserving order
        unique_chapters = []
        seen = set()
        for ch in chapters:
            if ch[2] not in seen:
                unique_chapters.append(ch)
                seen.add(ch[2])
                
        unique_chapters.sort(key=lambda x: x[0])
        self.title = title
        return title, [(n, u) for _, n, u in unique_chapters]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        script = soup.find("script", id="__NEXT_DATA__")
        if not script: return {"total": 0, "downloaded": 0, "missing": 0, "success": False}
        
        data = json.loads(script.string)
        raw_text = json.dumps(data)
        
        # Extract all image URLs
        img_urls = re.findall(r'https?://[^"]*\.(?:jpg|jpeg|png|webp|avif)', raw_text)
        
        # Filter to only allow MangaK CDNs (rx.qvzr*, resmk.org, etc.)
        img_urls = [u for u in img_urls if "rx.qvzr" in u or "resmk.org" in u]
        
        # Deduplicate
        img_urls = list(dict.fromkeys(img_urls))
        
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
