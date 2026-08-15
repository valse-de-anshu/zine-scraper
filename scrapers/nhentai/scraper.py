import re
import logging
import json
import codecs
import time
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import BaseScraper, urljoin, GREEN, YELLOW, RED, RESET

logger = logging.getLogger("NHentai")

class NHentaiScraper(BaseScraper):
    scraper_type = "toon"

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])


    def __init__(self, url: str):
        # Normalize URL to gallery root
        match = re.search(r"nhentai\.net/g/(\d+)", url)
        if match:
            self.gallery_id = match.group(1)
            url = f"https://nhentai.net/g/{self.gallery_id}"
        super().__init__(url)
        self.gallery_data = None

    def _fetch_gallery_data(self, soup):
        """Attempts to get gallery metadata from API or HTML."""
        # 1. Try API first (most reliable for extensions)
        try:
            api_url = f"https://nhentai.net/api/gallery/{self.gallery_id}"
            r = self.session.get(api_url, timeout=20)
            if r.status_code == 200:
                self.gallery_data = r.json()
                return self.gallery_data
        except Exception as e:
            logger.debug(f"API fetch failed: {e}")

        # 2. Try HTML scraping (Plan B)
        script_tag = soup.find("script", string=re.compile(r"window\._gallery|JSON\.parse"))
        if script_tag:
            # More robust regex for JSON.parse
            json_match = re.search(r"JSON\.parse\(['\"](.*?)['\"]\)", script_tag.string)
            if json_match:
                try:
                    raw_json = json_match.group(1)
                    # Handle double-escaped characters in JS strings
                    decoded_json = raw_json.encode().decode('unicode_escape').encode('latin1').decode('utf-8')
                    self.gallery_data = json.loads(decoded_json)
                    return self.gallery_data
                except Exception as e:
                    logger.debug(f"JSON extraction failed: {e}")
        
        # 3. Try SvelteKit fetched JSON (Plan C)
        for script in soup.find_all("script", type="application/json"):
            if "data-sveltekit-fetched" in script.attrs:
                try:
                    data = json.loads(script.string)
                    body_str = data.get("body")
                    if body_str:
                        body_data = json.loads(body_str) if isinstance(body_str, str) else body_str
                        if isinstance(body_data, dict) and "media_id" in body_data:
                            self.gallery_data = body_data
                            return self.gallery_data
                except Exception as e:
                    logger.debug(f"SvelteKit JSON parse failed: {e}")

        return None

    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)
        self.description = ""
                    
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
        data = self._fetch_gallery_data(soup)
        
        title_text = "Unknown"
        self.cover_url = None

        if data:
            titles = data.get("title", {})
            # Story priority: English -> Pretty -> Japanese
            title_text = titles.get("english") or titles.get("pretty") or titles.get("japanese") or "Unknown"
            
            # Extract media_id and cover type
            media_id = data.get("media_id")
            if "cover" in data and "path" in data["cover"]:
                self.cover_url = f"https://t.nhentai.net/{data['cover']['path']}"
            else:
                cover_type = data.get("images", {}).get("cover", {}).get("t", "j")
                ext = "jpg" if cover_type == "j" else "png" if cover_type == "p" else "webp"
                if media_id:
                    self.cover_url = f"https://t.nhentai.net/galleries/{media_id}/cover.{ext}"
        else:
            title_tag = soup.select_one("h1.title")
            if title_tag:
                title_text = title_tag.get_text(strip=True)
            
            cover_tag = soup.select_one("#cover img")
            if cover_tag:
                self.cover_url = cover_tag.get("data-src") or cover_tag.get("src")
        
        title = re.sub(r"[^\w\s-]", "", title_text).strip().title()
        self.title = title
        
        self.tags = []
        self.genres = []
        if data and "tags" in data:
            for t in data["tags"]:
                t_type = t.get("type")
                t_name = t.get("name")
                if not t_name: continue
                if t_type == "tag":
                    self.tags.append(t_name.title())
                elif t_type == "category":
                    self.genres.append(t_name.title())
                    
        return title, [("1", self.url)]



    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        data = self._fetch_gallery_data(soup)
        
        img_urls = []
        ext_map = {"j": "jpg", "p": "png", "w": "webp", "g": "gif"}

        if data:
            media_id = data.get("media_id")
            images = data.get("images", {}).get("pages", [])
            if media_id and images:
                for i, img in enumerate(images, 1):
                    ext = ext_map.get(img.get("t"), "jpg")
                    img_urls.append(f"https://i.nhentai.net/galleries/{media_id}/{i}.{ext}")
            elif "pages" in data:
                # New SvelteKit format
                for img in data["pages"]:
                    path = img.get("path")
                    if path:
                        img_urls.append(f"https://i.nhentai.net/{path}")
        
        if not img_urls:
            # Plan C: Exhaustive Search (Try every extension if metadata fails)
            logger.warning("Metadata failed. Switching to exhaustive extension search (Slower but accurate)")
            thumbs = soup.select("div.thumb-container img")
            if not thumbs:
                logger.error(f"FATAL: No images found at all for {ch_url}")
                return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

            # Extract media_id from thumbnails
            first_thumb = thumbs[0].get("data-src") or thumbs[0].get("src")
            media_match = re.search(r"galleries/(\d+)/", first_thumb)
            if not media_match: return {"total": 0, "downloaded": 0, "missing": 0, "success": False}
            media_id = media_match.group(1)

            num_pages = len(thumbs)
            return self._download_with_retry(media_id, num_pages, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)

    def _download_with_retry(self, media_id, num_pages, folder, ch_num, ch_url, live=None, stats_callback=None) -> dict:
        """Special downloader that tries multiple extensions if the exact one is unknown."""
        temp_dir = folder / f"_temp_{ch_num}"
        temp_dir.mkdir(exist_ok=True, parents=True)
        paths = []
        for i in range(1, num_pages + 1):
            target_path = temp_dir / f"{i:03d}.jpg"
            success_page = False
            for ext in ["jpg", "png", "webp"]:
                src = f"https://i.nhentai.net/galleries/{media_id}/{i}.{ext}"
                if self.download_image(src, target_path, referer=ch_url) == 1:
                    paths.append(target_path)
                    success_page = True
                    break
            if stats_callback:
                stats_callback({
                    "total": num_pages,
                    "downloaded": len(paths),
                    "missing": num_pages - len(paths)
                })
            if not success_page:
                logger.error(f"    - Page {i}: Failed all extensions")

        success = False
        downloaded_count = len(paths)
        if paths:
            self.slice_and_save(paths, folder)
            if downloaded_count == num_pages:
                success = True

        missing = num_pages - downloaded_count
        shutil.rmtree(temp_dir, ignore_errors=True)
        return {"total": num_pages, "downloaded": downloaded_count, "missing": missing, "success": success}

