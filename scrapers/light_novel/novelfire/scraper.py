"""
scrapers/light_novel/novelfire/scraper.py
-----------------------------------------
NovelFire.net scraper.

URLs supported:
  - Novel page:   https://novelfire.net/book/<slug>
  - Chapter page: https://novelfire.net/book/<slug>/chapter-<num>
"""

import re
import json
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import NFBaseEngine

logger = logging.getLogger("NovelFire")


class NovelFireScraper(NFBaseEngine):
    scraper_type = "novel"

    def is_chapter_link(self) -> bool:
        return "/chapter-" in getattr(self, "original_url", self.url).lower()

    def __init__(self, url: str):
        self.original_url = url.strip()
        match = re.search(r"(novelfire\.(?:net|docs)/book/[^/]+)", url)
        if match:
            self.series_url = "https://" + match.group(1).rstrip("/")
        else:
            self.series_url = url.rstrip("/")

        super().__init__(self.series_url)

        slug_match = re.search(r"/book/([^/]+)", self.series_url)
        self.slug = slug_match.group(1) if slug_match else "unknown"

    def get_title_and_chapters(self):
        """
        Returns (title, chapters_list) where chapters_list = [(num_str, chapter_url), ...]
        """
        soup = self.get_soup(self.series_url)
        
        # Extract title
        title_el = soup.select_one("h1, .novel-title, .title, .book-title")
        self.title = title_el.get_text(strip=True) if title_el else self.slug.replace("-", " ").title()

        # Extract metadata
        desc_el = soup.select_one(".summary .content, .description, #synopsis, .novel-desc, .review-body")
        self.description = desc_el.get_text(strip=True) if desc_el else ""

        author_el = soup.select_one(".author a, .meta-item:-soup-contains('Author') a, .meta a")
        self.author = author_el.get_text(strip=True) if author_el else ""

        status_el = soup.select_one(".status, .meta-item:-soup-contains('Status')")
        self.status = status_el.get_text(strip=True) if status_el else "Unknown"

        cover_el = soup.select_one(".cover img, .novel-cover img, img[alt*='cover'], .thumb img")
        if cover_el:
            src = cover_el.get("src") or cover_el.get("data-src") or ""
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = f"https://novelfire.net{src}"
            self.cover_url = src
        else:
            self.cover_url = ""

        genres_els = soup.select(".genres a, .categories a, .tags a, .tag a")
        self.genres = [g.get_text(strip=True) for g in genres_els if g.get_text(strip=True)]

        # Fetch chapters
        chapters = self._fetch_all_chapters()
        return self.title, chapters

    def _fetch_all_chapters(self):
        """Paginate /chapters?page=X until all chapters are extracted."""
        chapters = []
        seen = set()
        page = 1
        max_pages = 500

        while page <= max_pages:
            page_url = f"{self.series_url}/chapters?page={page}"
            try:
                soup = self.get_soup(page_url)
            except Exception as e:
                logger.warning(f"Failed to fetch chapters page {page}: {e}")
                break

            links = soup.find_all("a", href=True)
            page_chapters = []

            for a in links:
                href = a["href"]
                if "/chapter-" in href:
                    full_url = href if href.startswith("http") else f"https://novelfire.net{href}"
                    if full_url in seen:
                        continue
                    seen.add(full_url)
                    m = re.search(r"chapter-([\d]+(?:\.[\d]+)?)", href)
                    if m:
                        num = m.group(1)
                        page_chapters.append((float(num), num, full_url))
                    else:
                        num = str(len(chapters) + len(page_chapters) + 1)
                        page_chapters.append((float(num), num, full_url))

            if not page_chapters:
                break

            chapters.extend(page_chapters)
            
            pagination = soup.select_one(".pagination, .pager")
            if not pagination or f"page={page+1}" not in str(pagination):
                next_btn = soup.select_one("a[rel='next'], li.next a, .pagination-next")
                if not next_btn:
                    break

            page += 1

        if not chapters:
            soup = self.get_soup(self.series_url)
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/chapter-" in href:
                    full_url = href if href.startswith("http") else f"https://novelfire.net{href}"
                    if full_url not in seen:
                        seen.add(full_url)
                        m = re.search(r"chapter-([\d]+(?:\.[\d]+)?)", href)
                        num = m.group(1) if m else str(len(chapters) + 1)
                        chapters.append((float(num), num, full_url))

        chapters.sort(key=lambda x: x[0])
        return [(num, url) for _, num, url in chapters]

    def process_chapter(self, ch_url: str, folder: Path, ch_num: str,
                        live=None, stats_callback=None) -> dict:
        """
        Download one chapter as a .txt file.
        Returns {"success": bool, "words": int}
        """
        if stats_callback:
            stats_callback({"status": "fetching"})

        try:
            soup = self.get_soup(ch_url)
            title_tag = soup.select_one("h1.chapter-title, .chapter-title, h2, h1")
            chapter_title = title_tag.get_text(strip=True) if title_tag else f"Chapter {ch_num}"

            content_div = (
                soup.select_one("#chapter-container")
                or soup.select_one(".d-chapter-content")
                or soup.select_one("#content")
                or soup.select_one("#chapterText")
                or soup.select_one(".chapter-text")
                or soup.select_one(".chapter-content")
                or soup.select_one(".box-detail")
            )

            if not content_div:
                logger.warning(f"No content found for chapter {ch_num}")
                return {"success": False, "words": 0}

            for el in content_div.select("div.chapter-ad-container, script, style, .ad-unit, .ad-container, .adsbygoogle"):
                el.decompose()

            paragraphs = []
            for p in content_div.find_all("p"):
                text = p.get_text(separator=" ", strip=True)
                if text:
                    paragraphs.append(text)

            if not paragraphs:
                raw = content_div.get_text(separator="\n", strip=True)
                paragraphs = [line.strip() for line in raw.splitlines() if line.strip()]

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
            logger.error(f"NovelFire chapter {ch_num} failed: {e}")
            if stats_callback:
                stats_callback({"status": f"error: {e}", "success": False})
            return {"success": False, "words": 0}
