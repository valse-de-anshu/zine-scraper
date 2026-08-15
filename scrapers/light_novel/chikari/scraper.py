"""
scrapers/light_novel/chikari/scraper.py
---------------------------------------
Chikari.moe scraper supporting web novels, light novels, and series.

URLs supported:
  - Novel page:    https://chikari.moe/novels/<slug>
  - Novel chapter: https://chikari.moe/novels/<slug>/<chapter_num>
  - Series page:   https://chikari.moe/series/<slug>
  - Series chapter:https://chikari.moe/series/<slug>/<chapter_num>
"""

import re
import time
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import ChikariBaseEngine

logger = logging.getLogger("Chikari")


class ChikariScraper(ChikariBaseEngine):
    scraper_type = "novel"

    def is_chapter_link(self) -> bool:
        norm = getattr(self, "original_url", self.url).rstrip("/")
        match = re.search(r"chikari\.moe/(?:novels|series)/[^/]+/([\d]+(?:\.[\d]+)?)$", norm)
        return bool(match)

    def __init__(self, url: str):
        self.original_url = url.strip()
        
        # Detect whether it's novels or series
        if "/novels/" in url:
            self.endpoint_type = "novels"
            match = re.search(r"chikari\.moe/novels/([^/]+)", url)
            self.slug = match.group(1) if match else "unknown"
            self.series_url = f"https://chikari.moe/novels/{self.slug}"
        else:
            self.endpoint_type = "series"
            match = re.search(r"chikari\.moe/series/([^/]+)", url)
            self.slug = match.group(1) if match else "unknown"
            self.series_url = f"https://chikari.moe/series/{self.slug}"

        super().__init__(self.series_url)

    def get_title_and_chapters(self):
        """
        Returns (title, chapters_list) where chapters_list = [(num_str, chapter_url), ...]
        """
        # Try detected endpoint type first, fallback to the other if 404
        endpoints_to_try = [self.endpoint_type, "novels" if self.endpoint_type == "series" else "series"]
        data = None
        used_endpoint = self.endpoint_type

        for ep in endpoints_to_try:
            api_url = f"https://chikari.moe/api/{ep}/{self.slug}"
            try:
                r = self.session.get(api_url, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    used_endpoint = ep
                    self.endpoint_type = ep
                    break
            except Exception as e:
                logger.warning(f"Error trying {api_url}: {e}")

        if data:
            self.title = data.get("title") or self.slug.replace("-", " ").title()
            self.description = data.get("description", "")
            self.status = data.get("status", "Unknown").title() if data.get("status") else "Unknown"
            self.cover_url = data.get("cover_url", "")
            self.rating = str(data.get("rating", "")) if data.get("rating") is not None else ""
            self.type = data.get("type", "")
            self.alt_titles = data.get("alt_titles", [])

            authors = data.get("authors", [])
            if authors:
                self.author = ", ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in authors if a)
            else:
                self.author = ""

            genres = data.get("genres", [])
            self.genres = [g.get("name", "") if isinstance(g, dict) else str(g) for g in genres if g]

            tags = data.get("tags", [])
            self.tags = [t.get("name", "") if isinstance(t, dict) else str(t) for t in tags if t]
        else:
            soup = self.get_soup(self.series_url)
            h1 = soup.find("h1")
            self.title = h1.get_text(strip=True) if h1 else self.slug.replace("-", " ").title()
            self.author = ""
            self.description = ""
            self.status = "Unknown"
            self.cover_url = ""
            self.genres = []
            self.tags = []

        # Fetch chapters list via paginated API
        chapters = []
        offset = 0
        limit = 500

        while True:
            ch_api = f"https://chikari.moe/api/{used_endpoint}/{self.slug}/chapters?limit={limit}&offset={offset}"
            try:
                r = self.session.get(ch_api, timeout=20)
                if r.status_code != 200:
                    break
                ch_data = r.json()
                items = ch_data.get("items", [])
                if not items:
                    break

                for item in items:
                    num_val = item.get("number")
                    if num_val is None:
                        continue
                    num_str = str(int(num_val)) if isinstance(num_val, float) and num_val.is_integer() else str(num_val)
                    ch_url = f"https://chikari.moe/{used_endpoint}/{self.slug}/{num_str}"
                    chapters.append((float(num_val), num_str, ch_url))

                if len(items) < limit:
                    break
                offset += len(items)
            except Exception as e:
                logger.warning(f"Error fetching chapters at offset {offset}: {e}")
                break

        # Fallback to series page DOM if API returned nothing
        if not chapters:
            try:
                soup = self.get_soup(self.series_url)
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    m = re.search(rf"/(?:novels|series)/{self.slug}/([\d]+(?:\.[\d]+)?)$", href)
                    if m:
                        num = m.group(1)
                        full = href if href.startswith("http") else f"https://chikari.moe{href}"
                        chapters.append((float(num), num, full))
            except Exception:
                pass

        # Deduplicate and sort ascending
        seen = set()
        unique = []
        for val, num_str, u in chapters:
            if u not in seen:
                unique.append((val, num_str, u))
                seen.add(u)

        unique.sort(key=lambda x: x[0])
        return self.title, [(num, u) for _, num, u in unique]

    def process_chapter(self, ch_url: str, folder: Path, ch_num: str,
                        live=None, stats_callback=None) -> dict:
        """
        Download one chapter. Handles text novel chapters and comic strip pages.
        Returns {"success": bool, "words": int}
        """
        if stats_callback:
            stats_callback({"status": "fetching"})

        try:
            # 1. Try novel read API endpoint: /api/novels/<slug>/chapters/<num>/read
            if self.endpoint_type == "novels":
                api_url = f"https://chikari.moe/api/novels/{self.slug}/chapters/{ch_num}/read"
                try:
                    r = self.session.get(api_url, timeout=20)
                    if r.status_code == 200:
                        data = r.json()
                        chapter_title = data.get("title") or f"Chapter {ch_num}"
                        body_text = data.get("body", "")
                        if body_text:
                            paragraphs = [p.strip() for p in body_text.splitlines() if p.strip()]
                            word_count = sum(len(p.split()) for p in paragraphs)

                            if stats_callback:
                                stats_callback({"status": "saving", "words": word_count})

                            prefix = f"{self.title}_" if "Quick grab" in str(folder) else ""
                            chapters_dir = folder / "novel chapter"
                            chapters_dir.mkdir(parents=True, exist_ok=True)
                            out_file = chapters_dir / f"{prefix}chapter_{ch_num.zfill(4)}.txt"

                            content = f"{chapter_title}\n{'─' * len(chapter_title)}\n\n"
                            content += "\n\n".join(paragraphs)
                            content += f"\n\n[Words: {word_count}]\n"

                            out_file.write_text(content, encoding="utf-8")

                            if stats_callback:
                                stats_callback({"status": "done", "words": word_count, "success": True})

                            return {"success": True, "words": word_count}
                except Exception as e:
                    logger.warning(f"Failed novel read API for chapter {ch_num}: {e}")

            # 2. Try series API endpoint: /api/series/<slug>/chapters/<num>
            api_url = f"https://chikari.moe/api/{self.endpoint_type}/{self.slug}/chapters/{ch_num}"
            try:
                r = self.session.get(api_url, timeout=20)
                data = r.json() if r.status_code == 200 else {}
            except Exception:
                data = {}

            # Case A: Comic pages
            pages = data.get("pages", [])
            if pages:
                if stats_callback:
                    stats_callback({"status": "saving_images", "words": len(pages)})
                ch_dir = folder / f"Chapter {ch_num}"
                ch_dir.mkdir(parents=True, exist_ok=True)
                for idx, page_url in enumerate(pages, 1):
                    # Check if already downloaded with any extension
                    exists = any((ch_dir / f"{str(idx).zfill(3)}{ext}").exists() for ext in [".jpg", ".png", ".webp", ".jpeg", ".avif"])
                    if not exists:
                        for attempt in range(3):
                            try:
                                img_r = self.session.get(page_url, timeout=25)
                                if img_r.status_code == 200 and len(img_r.content) > 100:
                                    from .engine import detect_image_extension
                                    ext = detect_image_extension(img_r.content[:32])
                                    p_file = ch_dir / f"{str(idx).zfill(3)}{ext}"
                                    p_file.write_bytes(img_r.content)
                                    break
                            except Exception:
                                time.sleep(1)
                if stats_callback:
                    stats_callback({"status": "done", "words": len(pages), "success": True})
                return {"success": True, "words": len(pages)}

            # Case B: Plain text in data
            text_body = data.get("text", "") or data.get("body", "")
            paragraphs = []
            chapter_title = data.get("title") or f"Chapter {ch_num}"

            if text_body:
                paragraphs = [line.strip() for line in text_body.splitlines() if line.strip()]

            if not paragraphs:
                # Fallback: HTML DOM
                soup = self.get_soup(ch_url)
                title_tag = soup.select_one("h1, .chapter-title, .title")
                if title_tag:
                    chapter_title = title_tag.get_text(strip=True)
                
                content_div = soup.select_one(".chapter-content, .content, .reader-content, .novel-text, article, main")
                if content_div:
                    for el in content_div.select("script, style, .ad-container, .ad-unit"):
                        el.decompose()
                    paragraphs = [p.get_text(strip=True) for p in content_div.find_all("p") if p.get_text(strip=True)]

            if not paragraphs:
                logger.warning(f"No content found for chapter {ch_num}")
                return {"success": False, "words": 0}

            word_count = sum(len(p.split()) for p in paragraphs)

            if stats_callback:
                stats_callback({"status": "saving", "words": word_count})

            prefix = f"{self.title}_" if "Quick grab" in str(folder) else ""
            chapters_dir = folder / "novel chapter"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            out_file = chapters_dir / f"{prefix}chapter_{ch_num.zfill(4)}.txt"

            content = f"{chapter_title}\n{'─' * len(chapter_title)}\n\n"
            content += "\n\n".join(paragraphs)
            content += f"\n\n[Words: {word_count}]\n"

            out_file.write_text(content, encoding="utf-8")

            if stats_callback:
                stats_callback({"status": "done", "words": word_count, "success": True})

            return {"success": True, "words": word_count}

        except Exception as e:
            logger.error(f"Chikari chapter {ch_num} failed: {e}")
            if stats_callback:
                stats_callback({"status": f"error: {e}", "success": False})
            return {"success": False, "words": 0}
