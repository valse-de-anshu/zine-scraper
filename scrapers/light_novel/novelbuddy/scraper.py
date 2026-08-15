"""
scrapers/light_novel/novelbuddy/scraper.py
-----------------------------------------
NovelBuddy.me scraper.

URLs supported:
  - Novel page:   https://novelbuddy.me/<slug>
  - Chapter page: https://novelbuddy.me/<slug>/chapter-<num>...
"""

import re
import json
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import NBBaseEngine

logger = logging.getLogger("NovelBuddy")


class NovelBuddyScraper(NBBaseEngine):
    scraper_type = "novel"

    def is_chapter_link(self) -> bool:
        return "/chapter-" in getattr(self, "original_url", self.url).lower()

    def __init__(self, url: str):
        self.original_url = url.strip()
        
        # Normalize: chapter URL -> series URL
        match = re.search(r"novelbuddy\.(?:me|com)/([^/]+)", url)
        if match:
            self.slug = match.group(1)
            self.series_url = f"https://novelbuddy.me/{self.slug}"
        else:
            self.slug = "unknown"
            self.series_url = url.rstrip("/")

        super().__init__(self.series_url)
        self.manga_id = None
        self.build_id = None

    def get_title_and_chapters(self):
        """
        Returns (title, chapters_list) where chapters_list = [(num_str, chapter_url), ...]
        """
        soup = self.get_soup(self.series_url)
        manga = {}
        
        # Try Next.js __NEXT_DATA__
        next_script = soup.find("script", id="__NEXT_DATA__")
        if next_script and next_script.string:
            try:
                next_data = json.loads(next_script.string)
                self.build_id = next_data.get("buildId")
                props = next_data.get("props", {}).get("pageProps", {})
                manga = props.get("initialManga", {})
                self.manga_id = manga.get("id") or props.get("mangaHsid")
            except Exception as e:
                logger.warning(f"Error parsing __NEXT_DATA__: {e}")

        # 1. Title
        self.title = manga.get("name")
        if not self.title:
            t_el = soup.select_one("h1, .novel-title, .title")
            self.title = t_el.get_text(strip=True) if t_el else self.slug.replace("-", " ").title()

        # 2. Description (strip raw HTML from summary)
        desc = ""
        raw_summary = manga.get("summary") or manga.get("description") or ""
        if raw_summary:
            desc_soup = BeautifulSoup(raw_summary, "lxml")
            desc = desc_soup.get_text(separator=" ", strip=True)

        if not desc:
            meta_desc = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                desc = meta_desc["content"].strip()
        self.description = desc

        # 3. Authors
        author = ""
        authors_data = manga.get("authors", [])
        if isinstance(authors_data, list):
            author = ", ".join(a.get("name", "") if isinstance(a, dict) else str(a) 
                               for a in authors_data if (isinstance(a, dict) and a.get("name")) or isinstance(a, str))
        if not author:
            for a_tag in soup.select('a[href*="/authors/"]'):
                author = a_tag.get_text(strip=True)
                if author:
                    break
        self.author = author

        # 4. Status
        status = manga.get("status")
        if not status:
            status_tag = soup.select_one(".status, .meta-item:-soup-contains('Status')")
            status = status_tag.get_text(strip=True) if status_tag else "Unknown"
        if isinstance(status, str):
            status = status.title()
        self.status = status

        # 5. Cover URL
        cover_url = manga.get("cover") or manga.get("thumbnail") or ""
        if not cover_url:
            og_img = soup.find("meta", {"property": "og:image"})
            if og_img and og_img.get("content"):
                cover_url = og_img["content"]
        self.cover_url = cover_url

        # 6. Genres & Tags
        genres = []
        for g in manga.get("genres", []):
            name = g.get("name") if isinstance(g, dict) else str(g)
            if name and name not in genres:
                genres.append(name)
        if not genres:
            for a in soup.select('a[href*="/genres/"]'):
                gname = a.get_text(strip=True)
                if gname and gname not in genres:
                    genres.append(gname)
        self.genres = genres

        tags = []
        for t in manga.get("tags", []):
            name = t.get("name") if isinstance(t, dict) else str(t)
            if name and name not in tags:
                tags.append(name)
        self.tags = tags

        # 7. Additional Metadata (Rating, Origin Type, Alt Titles)
        self.rating = manga.get("displayRating") or str(manga.get("rating", ""))
        self.type = manga.get("type", {}).get("name") if isinstance(manga.get("type"), dict) else str(manga.get("type", ""))
        alt_names = manga.get("altNames", [])
        self.alt_titles = [a.get("name") if isinstance(a, dict) else str(a) for a in alt_names if a]

        # Fetch chapters via api.novelbuddy.me
        chapters = []
        if self.manga_id:
            api_url = f"https://api.novelbuddy.me/titles/{self.manga_id}/chapters"
            try:
                data = self.get_json(api_url)
                ch_list = data.get("data", {}).get("chapters", [])
                for ch in ch_list:
                    rel_url = ch.get("url", "")
                    full_url = f"https://novelbuddy.me{rel_url}" if rel_url.startswith("/") else rel_url
                    num_val = ch.get("number")
                    if num_val is None:
                        m = re.search(r"chapter-([\d]+(?:\.[\d]+)?)", rel_url)
                        num_str = m.group(1) if m else str(len(chapters) + 1)
                        num_val = float(num_str)
                    else:
                        num_str = str(int(num_val)) if isinstance(num_val, float) and num_val.is_integer() else str(num_val)
                    chapters.append((float(num_val), num_str, full_url))
            except Exception as e:
                logger.warning(f"API chapters fetch error: {e}")

        if not chapters:
            # Fallback to page links
            seen = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/chapter-" in href:
                    full_url = f"https://novelbuddy.me{href}" if href.startswith("/") else href
                    if full_url not in seen:
                        seen.add(full_url)
                        m = re.search(r"chapter-([\d]+(?:\.[\d]+)?)", href)
                        num = m.group(1) if m else str(len(chapters) + 1)
                        chapters.append((float(num), num, full_url))

        # Sort ascending
        chapters.sort(key=lambda x: x[0])
        return self.title, [(num, url) for _, num, url in chapters]

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
            title_tag = soup.select_one("h1, .chapter-title, .title")
            chapter_title = title_tag.get_text(strip=True) if title_tag else f"Chapter {ch_num}"

            content_div = (
                soup.select_one(".novel-tts-content")
                or soup.select_one(".content-inner")
                or soup.select_one("#chapter-content")
                or soup.select_one(".chapter-content")
                or soup.select_one(".reading-content")
                or soup.select_one(".flux-reader")
            )

            paragraphs = []
            if content_div:
                for el in content_div.select("script, style, .ad-container, .ad-unit, .adsbygoogle"):
                    el.decompose()
                for p in content_div.find_all("p"):
                    text = p.get_text(separator=" ", strip=True)
                    if text:
                        paragraphs.append(text)

            if not paragraphs:
                # Try Next.js __NEXT_DATA__ on the chapter page
                next_script = soup.find("script", id="__NEXT_DATA__")
                if next_script and next_script.string:
                    data = json.loads(next_script.string)
                    ch_obj = data.get("props", {}).get("pageProps", {}).get("initialChapter", {})
                    html_content = ch_obj.get("content", "")
                    if html_content:
                        csoup = BeautifulSoup(html_content, "lxml")
                        paragraphs = [p.get_text(strip=True) for p in csoup.find_all("p") if p.get_text(strip=True)]

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
            logger.error(f"NovelBuddy chapter {ch_num} failed: {e}")
            if stats_callback:
                stats_callback({"status": f"error: {e}", "success": False})
            return {"success": False, "words": 0}
