"""
scrapers/light_novel/novelarchive/scraper.py
--------------------------------------------
NovelArchive.cc API scraper.

URLs supported:
  - Novel page:   https://novelarchive.cc/novel?id=<id>
  - Chapter page: https://novelarchive.cc/reader?novel=<id>&chapter=<num>
"""

import re
import urllib.parse
import logging
from pathlib import Path
from .engine import NABaseEngine

logger = logging.getLogger("NovelArchive")


class NovelArchiveScraper(NABaseEngine):
    scraper_type = "novel"

    def is_chapter_link(self) -> bool:
        return "/reader" in self.url.lower() and "chapter=" in self.url.lower()

    def __init__(self, url: str):
        super().__init__(url)
        self.novel_id = ""
        self.chapter_num = ""
        
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        
        if "id" in qs:
            self.novel_id = qs["id"][0]
        elif "novel" in qs:
            self.novel_id = qs["novel"][0]
            
        if "chapter" in qs:
            self.chapter_num = qs["chapter"][0]

        self.source = qs.get("source", [""])[0]
            
        if not self.novel_id:
            # Maybe path based?
            match = re.search(r"novelarchive\.cc/(?:novel|api/novels)/([^/?]+)", url)
            if match:
                self.novel_id = match.group(1)
        
        self.series_url = f"https://novelarchive.cc/novel?id={self.novel_id}"

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def get_title_and_chapters(self):
        """
        Returns (title, chapters_list) where chapters_list = [(num_str, chapter_url), ...]
        """
        api_url = f"{self.api_base}/novels/{self.novel_id}"
        data = self.get_json(api_url)
        novel = data.get("novel", {})
        
        self.title = novel.get("title", "Unknown")
        self.author = novel.get("author", "")
        self.description = novel.get("description", "")
        self.status = novel.get("release_status", novel.get("ongoing", "Unknown"))
        self.cover_url = novel.get("cover_url", novel.get("image_url", novel.get("novel_image", "")))
        if not self.source:
            self.source = novel.get("preferred_source", "")
        
        genres_raw = novel.get("genres", "")
        if isinstance(genres_raw, list):
            self.genres = genres_raw
        else:
            self.genres = [g.strip() for g in genres_raw.split(",") if g.strip()]
            
        self.tags = []
        
        chapters = []
        chapter_names = novel.get("chapter_names", [])
        for i, name in enumerate(chapter_names):
            num = i + 1
            src_param = f"&source={self.source}" if self.source else ""
            ch_url = f"https://novelarchive.cc/reader?novel={self.novel_id}&chapter={num}{src_param}"
            chapters.append((float(num), str(num), ch_url))
            
        # Deduplicate
        seen = set()
        unique = []
        for val, num_str, url in chapters:
            if url not in seen:
                unique.append((val, num_str, url))
                seen.add(url)

        unique.sort(key=lambda x: x[0])
        return self.title, [(num, url) for _, num, url in unique]

    def _get_novel_sources(self) -> list:
        """Helper to get available sources for this novel."""
        try:
            res = self.get_json(f"{self.api_base}/novels/{self.novel_id}/sources")
            return [s.get("id") for s in res.get("sources", []) if s.get("id")]
        except Exception:
            return []

    def process_chapter(self, ch_url: str, folder: Path, ch_num: str,
                        live=None, stats_callback=None) -> dict:
        """
        Download one chapter as a .txt file using the API.
        Returns {"success": bool, "words": int}
        """
        if stats_callback:
            stats_callback({"status": "fetching"})

        try:
            parsed = urllib.parse.urlparse(ch_url)
            qs = urllib.parse.parse_qs(parsed.query)
            target_ch = qs.get("chapter", [ch_num])[0]
            ch_source = qs.get("source", [self.source])[0]

            chapter_title = f"Chapter {target_ch}"
            paragraphs = []

            # 1. Try direct main chapters endpoint
            try:
                api_url = f"{self.api_base}/novels/{self.novel_id}/chapters/{target_ch}"
                data = self.get_json(api_url)
                ch_data = data.get("chapter", {})
                chapter_title = ch_data.get("name", f"Chapter {target_ch}")
                content_raw = ch_data.get("content", "")
                if content_raw:
                    paragraphs = [p.strip() for p in content_raw.splitlines() if p.strip()]
            except Exception:
                pass

            # 2. If no content, try sources endpoint
            if not paragraphs:
                candidate_sources = []
                if ch_source:
                    candidate_sources.append(ch_source)
                for s in self._get_novel_sources():
                    if s not in candidate_sources:
                        candidate_sources.append(s)

                from bs4 import BeautifulSoup
                for src in candidate_sources:
                    try:
                        src_url = f"{self.api_base}/novels/{self.novel_id}/sources/{src}/chapters/{target_ch}"
                        data = self.get_json(src_url)
                        chapter_title = data.get("title", f"Chapter {target_ch}")
                        content_html = data.get("content_html", "")
                        if content_html:
                            soup = BeautifulSoup(content_html, "lxml")
                            for el in soup.select("script, style"):
                                el.decompose()

                            # Download any illustration images into the chapter folder
                            img_count = 0
                            for img in soup.find_all("img"):
                                src = img.get("src", "")
                                if src:
                                    img_count += 1
                                    img_url = f"https://novelarchive.cc{src}" if src.startswith("/") else src
                                    img_ext = Path(urllib.parse.urlparse(img_url).path).suffix or ".jpg"
                                    chapters_dir = folder / "novel chapter"
                                    chapters_dir.mkdir(parents=True, exist_ok=True)
                                    prefix = f"{self.title}_" if "Quick grab" in str(folder) else ""
                                    img_filename = f"{prefix}chapter_{str(target_ch).zfill(4)}_img_{img_count:02d}{img_ext}"
                                    img_path = chapters_dir / img_filename
                                    try:
                                        r_img = self.session.get(img_url, timeout=30)
                                        if r_img.status_code == 200:
                                            img_path.write_bytes(r_img.content)
                                            paragraphs.append(f"[Illustration: {img_filename}]")
                                    except Exception:
                                        paragraphs.append(f"[Illustration: {img_url}]")

                            for p in soup.find_all(["p", "div"]):
                                text = p.get_text(separator=" ", strip=True)
                                if text and text not in paragraphs:
                                    paragraphs.append(text)
                            if paragraphs:
                                break
                    except Exception:
                        continue

            if not paragraphs:
                logger.warning(f"No content found for chapter {target_ch}")
                return {"success": False, "words": 0}

            word_count = sum(len(p.split()) for p in paragraphs)

            if stats_callback:
                stats_callback({"status": "saving", "words": word_count})

            # Build output file
            prefix = f"{self.title}_" if "Quick grab" in str(folder) else ""
            chapters_dir = folder / "novel chapter"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            out_file = chapters_dir / f"{prefix}chapter_{str(target_ch).zfill(4)}.txt"
            
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
