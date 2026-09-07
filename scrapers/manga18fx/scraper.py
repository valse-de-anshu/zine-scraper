import re
import logging
from pathlib import Path
from typing import Tuple, List, Any
from urllib.parse import urljoin

from .engine import BaseScraper

logger = logging.getLogger("Manga18fx")

class Manga18fxScraper(BaseScraper):
    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/chapter-", "/ch-", "/c/"])

    def _extract_cover_url(self, soup) -> str:
        cover_img = soup.select_one(
            ".tab-summary .summary_image img, .summary_image img, .post-thumb img, div.post-title img"
        )
        if cover_img:
            for attr in ["data-src", "src", "data-lazy-src"]:
                src = cover_img.get(attr)
                if src and not src.startswith("data:"):
                    return urljoin(self.url, src.strip())
        return ""

    def get_title_and_chapters(self) -> Tuple[str, List[Tuple[str, str]]]:
        is_ch = self.is_chapter_link()
        series_url = self.url

        if is_ch:
            m = re.match(r"(https?://[^/]+/manga/[^/]+)", self.url)
            if m:
                series_url = m.group(1)

        series_soup = self.get_soup(series_url)

        # 1. Title
        title_tag = series_soup.select_one("div.post-title h1, h1")
        raw_title = title_tag.get_text(strip=True) if title_tag else "Unknown"
        title = re.sub(r"(?i)(read|online|raw|eng|free|manga|manhua|manhwa).*", "", raw_title)
        title = re.sub(r"[^\w\s-]", "", title).strip().title()
        if not title:
            title = "Unknown"
        self.title = title

        # 2. Cover
        self.cover_url = self._extract_cover_url(series_soup)

        # 3. Description
        self.description = ""
        for selector in [
            ".panel-story-description", "#syn-target", "div.description-summary",
            "div.summary-content", "div.post-content", "div.manga-excerpt", "p.summary"
        ]:
            el = series_soup.select_one(selector)
            if el:
                desc = re.sub(r"\s+", " ", el.get_text(strip=True))
                if desc and "read manga" not in desc.lower() and "fastest and highest" not in desc.lower():
                    self.description = desc
                    break

        # 4. Authors
        author_links = []
        for a in series_soup.select('.author-content a, a[href*="/authors/"], a[href*="/author/"], a[href*="/artist/"]'):
            t = a.get_text(strip=True)
            if t and t.lower() not in ["author", "artist", "authors", "artists"]:
                author_links.append(t)
        self.author = ", ".join(list(dict.fromkeys(author_links)))

        # 5. Genres
        self.genres = []
        for a in series_soup.select('.genres-content a, a[href*="/genre/"]'):
            t = a.get_text(strip=True).title()
            if t and t not in self.genres:
                self.genres.append(t)

        # 6. Chapters
        if is_ch:
            m_ch = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", self.url.lower())
            if m_ch:
                ch_num = m_ch.group(1).replace("-", ".")
            else:
                parts = [p for p in self.url.strip("/").split("/") if p]
                ch_num = parts[-1] if parts else "1"
                ch_num = re.sub(r"[^\d.]", "", ch_num) or "1"
            return title, [(ch_num, self.url)]

        raw_chapters = []
        container = series_soup.select_one("ul.row-content-chapter, ul.version-chap, .wp-manga-chapter")
        links = container.find_all("a", href=True) if container else series_soup.find_all("a", href=True)

        for a in links:
            href = a["href"].lower()
            if "/chapter-" in href or "/ch-" in href:
                m_ch = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", href)
                if m_ch:
                    num_str = m_ch.group(1).replace("-", ".")
                    full_link = urljoin(series_url, a["href"])
                    try:
                        raw_chapters.append((float(num_str), num_str, full_link))
                    except ValueError:
                        raw_chapters.append((0.0, num_str, full_link))

        seen = set()
        final_chapters = []
        raw_chapters.sort(key=lambda x: x[0])
        for _, num_str, link in raw_chapters:
            if link not in seen:
                final_chapters.append((num_str, link))
                seen.add(link)

        return title, final_chapters

    def process_chapter(self, ch_url: str, folder: Path, ch_num: str, live=None, stats_callback=None) -> dict:
        soup = self.get_soup(ch_url)
        imgs = soup.select("div.read-content img, div.page-break img, div.reading-content img, div.container-chapter-reader img")
        if not imgs:
            imgs = soup.find_all("img")

        bad_keywords = (
            "logo", "banner", "avatar", "icon", "ads", "advert", "sponsor",
            "spinner", "loading", "placeholder", "pixel", "tracker", "adzerk",
            "doubleclick", "adsterra", "exoclick", "juicyads", "trafficjunky",
            "donate", "patreon", "discord_banner", "promo", "bookmark"
        )

        img_urls = []
        for img in imgs:
            src = ""
            for attr in ["data-src", "src", "data-lazy-src", "data-cdn"]:
                val = img.get(attr)
                if val:
                    src = val.strip()
                    if src:
                        break

            if not src or src.startswith("data:"):
                continue

            full_src = urljoin(ch_url, src)
            if not full_src.startswith("http"):
                continue

            src_low = full_src.lower()
            if any(x in src_low for x in bad_keywords):
                continue

            img_urls.append(full_src)

        img_urls = list(dict.fromkeys(img_urls))
        if not img_urls:
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
