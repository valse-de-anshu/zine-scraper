import re
import logging
from pathlib import Path
from typing import Tuple, List, Any
from urllib.parse import urljoin

from .engine import BaseScraper

logger = logging.getLogger("Topmanhua")


class TopmanhuaScraper(BaseScraper):
    @property
    def metadata(self) -> dict:
        return {
            "title": getattr(self, "title", ""),
            "author": getattr(self, "author", ""),
            "artist": getattr(self, "artist", ""),
            "description": getattr(self, "description", ""),
            "genres": getattr(self, "genres", []),
            "status": getattr(self, "status", "Unknown"),
            "rating": getattr(self, "rating", ""),
            "release": getattr(self, "release", ""),
            "cover_url": getattr(self, "cover_url", ""),
            "source_url": getattr(self, "url", ""),
        }

    def is_chapter_link(self) -> bool:
        return any(x in self.url.lower() for x in ["/chapter-", "/ch-", "/c/"])

    def _extract_cover_url(self, soup) -> str:
        cover_img = soup.select_one(
            ".summary_image img, .tab-summary img, .post-thumb img, div.post-title img"
        )
        if cover_img:
            for attr in ["data-backup", "data-src", "src", "data-lazy-src"]:
                src = cover_img.get(attr)
                if src and not src.startswith("data:"):
                    return urljoin(self.url, src.strip())
        return ""

    def get_title_and_chapters(self) -> Tuple[str, List[Tuple[str, str]]]:
        is_ch = self.is_chapter_link()
        series_url = self.url

        if is_ch:
            m = re.match(r"(https?://[^/]+/manhua/[^/]+)", self.url)
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
            ".description-summary", ".summary__content", ".manga-excerpt",
            ".panel-story-description", "div.summary-content", "div.post-content", "p.summary"
        ]:
            el = series_soup.select_one(selector)
            if el:
                desc = re.sub(r"\s+", " ", el.get_text(separator=" ", strip=True))
                desc = re.sub(r"\s*Show more\s*$", "", desc, flags=re.I).strip()
                if desc and "read manga" not in desc.lower() and "fastest and highest" not in desc.lower():
                    self.description = desc
                    break

        # 4. Authors & Artists
        self.author = ""
        authors = [a.get_text(strip=True) for a in series_soup.select('.author-content a, a[href*="/manga-author/"]') if a.get_text(strip=True)]
        if not authors:
            auth_elem = series_soup.select_one('.post-content_item:-soup-contains("Author") .summary-content')
            if auth_elem:
                authors = [t.strip() for t in auth_elem.get_text(strip=True).split(",") if t.strip()]
        if authors:
            self.author = ", ".join(authors)

        self.artist = ""
        artists = [a.get_text(strip=True) for a in series_soup.select('.artist-content a, a[href*="/manga-artist/"]') if a.get_text(strip=True)]
        if not artists:
            art_elem = series_soup.select_one('.post-content_item:-soup-contains("Artist") .summary-content')
            if art_elem:
                artists = [t.strip() for t in art_elem.get_text(strip=True).split(",") if t.strip()]
        if artists:
            self.artist = ", ".join(artists)

        # 5. Genres
        self.genres = []
        genre_tags = series_soup.select('.genres-content a, .post-content_item:-soup-contains("Genre") .summary-content a')
        if genre_tags:
            for a in genre_tags:
                gname = a.get_text(strip=True)
                if gname and gname not in self.genres:
                    self.genres.append(gname)
        else:
            gen_elem = series_soup.select_one('.post-content_item:-soup-contains("Genre") .summary-content')
            if gen_elem:
                self.genres = [g.strip() for g in gen_elem.get_text(strip=True).split(",") if g.strip()]

        # 6. Status
        self.status = "Unknown"
        status_elem = series_soup.select_one('.post-content_item:-soup-contains("Status") .summary-content, .status-content')
        if status_elem:
            self.status = status_elem.get_text(strip=True).title()

        # 7. Rating
        self.rating = ""
        rate_elem = series_soup.select_one('#averagerate, .post-total-rating .score')
        if rate_elem:
            self.rating = rate_elem.get_text(strip=True)

        # 8. Release Year
        self.release = ""
        rel_elem = series_soup.select_one('.post-content_item:-soup-contains("Release") .summary-content')
        if rel_elem:
            self.release = rel_elem.get_text(strip=True)

        # 9. Chapters
        chapters_raw = []
        for a in series_soup.select('.wp-manga-chapter a, li.wp-manga-chapter a, .listing-chapters_sub-head a'):
            ch_url = a.get("href")
            if not ch_url:
                continue
            ch_url = urljoin(series_url, ch_url)
            ch_text = a.get_text(strip=True)
            m = re.search(r"chapter[ -]*([\d]+(?:[\.-][\d]+)?)", ch_text.lower())
            if not m:
                m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", ch_url.lower())
            
            if m:
                raw_num = m.group(1).replace("-", ".")
                try:
                    num_val = float(raw_num)
                    num_str = str(int(num_val)) if num_val.is_integer() else str(num_val)
                except ValueError:
                    num_val = 99999.0
                    num_str = raw_num
            else:
                num_val = 99999.0
                num_str = "1"

            chapters_raw.append((num_val, num_str, ch_url))

        # Deduplicate preserving order
        seen = set()
        unique = []
        for num_val, num_str, ch_url in chapters_raw:
            if ch_url not in seen:
                seen.add(ch_url)
                unique.append((num_val, num_str, ch_url))

        # Sort ascending (Chapter 1 first)
        unique.sort(key=lambda x: x[0])
        return self.title, [(num_str, ch_url) for _, num_str, ch_url in unique]

    def process_chapter(
        self,
        ch_url: str,
        folder: Path,
        ch_num: str,
        live=None,
        stats_callback=None
    ) -> dict:
        chapter_soup = self.get_soup(ch_url)
        img_urls = []

        for img in chapter_soup.select('.reading-content img, .page-break img, .entry-content img, .wp-manga-chapter-img'):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("data-backup") or img.get("src")
            if src:
                src = src.strip()
                if src.startswith("//"):
                    src = "https:" + src
                if src.startswith("http") and not src.startswith("data:"):
                    img_urls.append(src)

        # Filter duplicates
        seen = set()
        filtered_imgs = []
        for s in img_urls:
            if s not in seen:
                seen.add(s)
                filtered_imgs.append(s)

        chapter_dir = folder / f"Chapter{ch_num}"
        return self.process_chapter_multi(
            filtered_imgs,
            chapter_dir,
            ch_num,
            ch_url,
            live=live,
            stats_callback=stats_callback
        )
