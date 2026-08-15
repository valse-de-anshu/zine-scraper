"""
scrapers/light_novel/lightnovelworld/scraper.py
------------------------------------------------
LightNovelWorld.org scraper.

URLs supported:
  - Novel page:   https://lightnovelworld.org/novel/<slug>/
  - Chapter page: https://lightnovelworld.org/novel/<slug>/chapter/<num>/

Metadata extracted:
  title, author, genres, description, status, cover_url, total_chapters

Chapter list fetched from: /novel/<slug>/chapters/
Chapter text fetched from: /novel/<slug>/chapter/<num>/
"""

import re
import json
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import LNWBaseEngine

logger = logging.getLogger("LightNovelWorld")


class LightNovelWorldScraper(LNWBaseEngine):
    scraper_type = "novel"

    def is_chapter_link(self) -> bool:
        return "/chapter/" in getattr(self, "original_url", self.url).lower()

    def __init__(self, url: str):
        self.original_url = url
        # Normalize: chapter URL → series URL
        match = re.search(r"(lightnovelworld\.org/novel/[^/]+)", url)
        if match:
            self.series_url = "https://" + match.group(1).rstrip("/") + "/"
        else:
            self.series_url = url.rstrip("/") + "/"

        super().__init__(self.series_url)

        # Extract novel slug
        slug_match = re.search(r"/novel/([^/]+)", self.series_url)
        self.slug = slug_match.group(1) if slug_match else "unknown"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_title_and_chapters(self):
        """
        Returns (title, chapters_list) where chapters_list = [(num_str, chapter_url), ...]
        Chapter URLs are fetched from the /chapters/ listing page.
        """
        soup = self._fetch_novel_page()
        title = self._extract_title(soup)
        self.title = title
        self._extract_metadata(soup)

        chapters = self._fetch_chapter_list()
        return title, chapters

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
            title_tag = soup.select_one("h1.chapter-title, .chapter-title")
            chapter_title = title_tag.get_text(strip=True) if title_tag else f"Chapter {ch_num}"

            # Extract main text from div.chapter-text or div.chapter-content
            content_div = (
                soup.select_one("div.chapter-text")
                or soup.select_one("div.chapter-content")
                or soup.select_one("#chapterText")
            )

            if not content_div:
                logger.warning(f"No content found for chapter {ch_num}")
                return {"success": False, "words": 0}

            # Remove ad containers and script tags
            for el in content_div.select("div.chapter-ad-container, script, style, .ad-unit"):
                el.decompose()

            # Extract text paragraph by paragraph
            paragraphs = []
            for p in content_div.find_all("p"):
                text = p.get_text(separator=" ", strip=True)
                if text:
                    paragraphs.append(text)

            if not paragraphs:
                # Fallback: get all text
                raw = content_div.get_text(separator="\n", strip=True)
                paragraphs = [line.strip() for line in raw.splitlines() if line.strip()]

            word_count = sum(len(p.split()) for p in paragraphs)

            if stats_callback:
                stats_callback({"status": "saving", "words": word_count})

            # Build output file
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
            logger.error(f"Chapter {ch_num} failed: {e}")
            if stats_callback:
                stats_callback({"status": f"error: {e}", "success": False})
            return {"success": False, "words": 0}

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_novel_page(self) -> BeautifulSoup:
        return self.get_soup(self.series_url)

    def _extract_title(self, soup: BeautifulSoup) -> str:
        # Try LD+JSON first (most reliable)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "Book" and data.get("name"):
                    return data["name"].strip()
            except Exception:
                pass

        # HTML fallback
        tag = soup.select_one("h1.novel-title, .novel-title h1, h1")
        return re.sub(r"\s+", " ", tag.get_text(strip=True)) if tag else "Unknown"

    def _extract_metadata(self, soup: BeautifulSoup):
        """Populates self.author, self.description, self.genres, self.tags, self.status, self.cover_url."""
        self.author = ""
        self.description = ""
        self.genres = []
        self.tags = []
        self.status = "Unknown"
        self.cover_url = ""
        self.novel_id = ""

        # ── LD+JSON (most complete) ──────────────────────────────────────────
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "Book":
                    author_data = data.get("author", {})
                    if isinstance(author_data, dict):
                        self.author = author_data.get("name", "")
                    self.description = re.sub(r"\s+", " ", data.get("description", "")).strip()
                    genres = data.get("genre", [])
                    self.genres = [g.strip() for g in (genres if isinstance(genres, list) else [genres])]
                    self.status = data.get("status", "Unknown")
                    break
            except Exception:
                pass

        # ── HTML fallbacks ───────────────────────────────────────────────────
        if not self.author:
            a_tag = soup.select_one("a.author-link, p.novel-author a")
            if a_tag:
                self.author = a_tag.get_text(strip=True)

        if not self.description:
            div = soup.select_one("div.summary-content")
            if div:
                self.description = re.sub(r"\s+", " ", div.get_text(separator=" ", strip=True))

        # Cover image
        cover = soup.select_one("img.novel-cover, .novel-cover-container img")
        if cover:
            src = cover.get("src") or cover.get("data-src") or ""
            if src and not src.startswith("http"):
                src = f"https://lightnovelworld.org{src}"
            self.cover_url = src

        # Novel ID from meta tag
        meta_id = soup.find("meta", {"name": "novel-id"})
        if meta_id:
            self.novel_id = meta_id.get("content", "")

        # Status from badge
        status_badge = soup.select_one("span.status-badge")
        if status_badge:
            self.status = status_badge.get_text(strip=True)

    def _fetch_chapter_list(self) -> list:
        """
        Fetch all chapters from /novel/<slug>/chapters/
        Returns [(ch_num_str, url), ...] sorted ascending.
        """
        chapters_url = f"https://lightnovelworld.org/novel/{self.slug}/chapters/"
        chapters = []

        try:
            soup = self.get_soup(chapters_url)
            
            # First, check if we can get the total chapters from the text description
            import re
            text = soup.get_text()
            m = re.search(r"total of (\d+) chapters", text)
            if m:
                total_ch = int(m.group(1))
                for num in range(1, total_ch + 1):
                    full_url = f"https://lightnovelworld.org/novel/{self.slug}/chapter/{num}"
                    chapters.append((float(num), str(num), full_url))
            else:
                # Fallback to extracting from any visible links or divs
                for el in soup.find_all(lambda tag: tag.has_attr("href") or tag.has_attr("onclick")):
                    href = el.get("href") or ""
                    if not href and el.has_attr("onclick"):
                        onclick_val = el["onclick"]
                        href_match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick_val)
                        if href_match:
                            href = href_match.group(1)
                            
                    if href:
                        # Pattern: /novel/<slug>/chapter/<num>/
                        m2 = re.search(r"/chapter/(\d+(?:\.\d+)?)", href)
                        if m2:
                            num = m2.group(1)
                            full_url = f"https://lightnovelworld.org{href}" if href.startswith("/") else href
                            chapters.append((float(num), num, full_url.rstrip("/")))
        except Exception as e:
            logger.warning(f"Chapter list fetch failed: {e}")

        # Deduplicate by URL
        seen = set()
        unique = []
        for val, num, url in chapters:
            if url not in seen:
                unique.append((val, num, url))
                seen.add(url)

        unique.sort(key=lambda x: x[0])
        return [(num, url) for _, num, url in unique]
