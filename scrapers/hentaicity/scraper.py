"""
scrapers/hentaicity/scraper.py
-------------------------------
HentaiCity scraper — handles both video pages and gallery pages.

URL patterns:
  Video  : https://www.hentaicity.com/video/<slug>.html
  Gallery: https://www.hentaicity.com/gallery/<slug>.html  (or /click/N-N/gallery/...)

For video pages, episode links in the sidebar are scraped to build the full series list.
For gallery pages, all CDN image URLs are returned as a list.
"""

import re
import requests
from pathlib import Path
from typing import Dict, Any, List, Tuple
from bs4 import BeautifulSoup
from core.base_scraper import UnifiedBaseScraper


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.hentaicity.com/",
}


class HentaicityScraper(UnifiedBaseScraper):

    def __init__(self, url: str):
        # Normalise /click/N-N/ tracker prefix so real URL is used everywhere
        url = re.sub(r"https?://www\.hentaicity\.com/click/\d+-\d+/", "https://www.hentaicity.com/", url)
        super().__init__(url, Path(__file__).parent / "site_config.json")
        from .engine import HentaicityEngine
        self.engine = HentaicityEngine()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.title = "Unknown"
        self._folder_name = "Unknown"
        self.content_type = "video"   # "video" or "gallery"
        self._detect_content_type()

    # ── Content type detection ────────────────────────────────────────────

    def _detect_content_type(self):
        if "/gallery/" in self.url:
            self.content_type = "gallery"
        else:
            self.content_type = "video"

    def get_link_type(self) -> str:
        return "model"

    # ── Shared fetch helper ───────────────────────────────────────────────

    def _fetch(self, url: str) -> BeautifulSoup:
        res = self.session.get(url, timeout=15)
        res.raise_for_status()
        return BeautifulSoup(res.text, "lxml")

    # ── Title helpers ─────────────────────────────────────────────────────

    def _slug_to_title(self, slug: str) -> str:
        """Convert a URL slug to a human-readable title."""
        # Strip the trailing random hash (e.g. wXcGYGfll4P)
        slug = re.sub(r"-[A-Za-z0-9]{10,}$", "", slug)
        # Strip -episode-N suffix if present
        slug = re.sub(r"-episode-\d+", "", slug)
        # Strip -N (number) at end (e.g. -2, -3)
        slug = re.sub(r"-\d+$", "", slug)
        return slug.replace("-", " ").title()

    # ── Video scraping ────────────────────────────────────────────────────

    def _scrape_video_page(self) -> Tuple[str, str, str, List[Dict]]:
        """
        Scrapes a video page.
        Returns: (title, series_title, thumbnail_url, episodes_list)
        Episodes list is sorted by episode number.
        """
        soup = self._fetch(self.url)

        # Title from h1 or og:title
        og_title = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        title = (og_title["content"] if og_title else (h1.text.strip() if h1 else "Unknown"))

        # Thumbnail from og:image
        og_img = soup.find("meta", property="og:image")
        thumbnail = og_img["content"] if og_img else ""

        # m3u8 URL embedded in the page
        m3u8_match = re.search(
            r"(https://hls\.hentaicity\.com/[^\"' <>]+master\.m3u8[^\"' <>]*)",
            str(soup)
        )
        m3u8 = m3u8_match.group(1).replace("&amp;", "&") if m3u8_match else ""

        # Mobile mp4 fallback
        mp4_match = re.search(
            r"(https://www\.hentaicity\.com/flv/[^\"' <>]+\.mp4)",
            str(soup)
        )
        mp4_url = mp4_match.group(1) if mp4_match else ""

        stream_url = m3u8 or mp4_url

        # Episode links from sidebar
        episodes = []
        current_ep_num = None
        for a in soup.find_all("a", href=True):
            text = a.text.strip()
            href = a["href"]
            ep_match = re.match(r"Episode\s+(\d+)", text, re.IGNORECASE)
            if ep_match and "/video/" in href:
                ep_num = int(ep_match.group(1))
                episodes.append({"text": text, "url": href, "ep_num": ep_num, "thumbnail": thumbnail})

        # Also include current page as current episode if not in sidebar
        slug_match = re.search(r"/video/([^.]+)\.html", self.url)
        if slug_match:
            ep_in_slug = re.search(r"-(\d+)-", slug_match.group(1))
            if ep_in_slug:
                current_ep_num = int(ep_in_slug.group(1))

        if not any(e["url"].rstrip("/") == self.url.rstrip("/") for e in episodes):
            # Derive episode number from title (e.g. "Household Subjugation 2")
            ep_num_in_title = re.search(r"\b(\d+)\b", title)
            ep_num = int(ep_num_in_title.group(1)) if ep_num_in_title else (current_ep_num or 1)
            episodes.append({"text": f"Episode {ep_num}", "url": self.url, "ep_num": ep_num, "thumbnail": thumbnail})

        episodes.sort(key=lambda e: e["ep_num"])

        # Derive series title from the slug (strip episode number words)
        slug = slug_match.group(1) if slug_match else ""
        series_title = self._slug_to_title(slug)
        
        # --- Extract metadata ---
        studio = ""
        upload_date = ""
        
        # Try JSON-LD first
        import json
        ld_json = soup.find("script", type="application/ld+json")
        if ld_json:
            try:
                data = json.loads(ld_json.string)
                studio = data.get("author", "")
                upload_date = data.get("uploadDate", "")
                if upload_date and "T" in upload_date:
                    upload_date = upload_date.split("T")[0]
            except Exception:
                pass

        tags_list = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "/tags/video/" in href:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            elif "/profile/" in href and not studio:
                # Fallback to profile link
                t = a.text.strip()
                if t: studio = t
        tags_str = ", ".join(tags_list)
        
        # Description & Real Title
        summary = ""
        b_tag = soup.find('b', style='font-weight: bold')
        if b_tag and b_tag.parent and b_tag.parent.parent:
            real_series = b_tag.text.strip()
            if len(real_series) > 3 and len(real_series) < 100:
                series_title = real_series
            
            desc_raw = b_tag.parent.parent.text.strip()
            # Split off the episode buttons at the bottom
            summary = re.split(r'\n\s*Episode 1\b', desc_raw, 1)[0].strip()
            if summary.startswith(real_series):
                summary = re.sub(r'^' + re.escape(real_series) + r'\n*', '', summary).strip()
        else:
            # Fallback
            for d in soup.find_all('div'):
                if not d.find('div') and len(d.text.strip()) > 100:
                    t = d.text.strip()
                    if "website contains age-restricted" not in t and "Video Categories" not in t:
                        summary = re.sub(r'^(?:[^\n]+)\n+', '', t).strip()
                        break

        # Attach m3u8 to the current episode
        for ep in episodes:
            if ep["url"].rstrip("/") == self.url.rstrip("/"):
                ep["stream_url"] = stream_url
                ep["thumbnail"] = thumbnail
                ep["upload_date"] = upload_date

        return title, series_title, thumbnail, episodes, stream_url, studio, tags_str, summary, upload_date

    # ── Gallery scraping ──────────────────────────────────────────────────

    def _scrape_gallery_page(self) -> Tuple[str, str, List[str]]:
        """
        Scrapes a gallery page.
        Returns: (title, thumbnail, image_urls)
        """
        soup = self._fetch(self.url)

        og_title = soup.find("meta", property="og:title")
        h1 = soup.find("h1")
        title = (og_title["content"] if og_title else (h1.text.strip() if h1 else "Unknown Gallery"))

        # CDN image links
        imgs = [
            img["src"] for img in soup.find_all("img", src=True)
            if "cdn" in img["src"] and "galleries" in img["src"]
        ]
        # Deduplicate while preserving order
        seen = set()
        unique_imgs = []
        for img in imgs:
            if img not in seen:
                seen.add(img)
                unique_imgs.append(img)

        # Strip -t thumbnail suffix → get full-resolution images
        # e.g.  .../abc123-t.jpg  →  .../abc123.jpg
        full_imgs = [re.sub(r"-t(\.\w+)$", r"\1", u) for u in unique_imgs]

        thumbnail = full_imgs[0] if full_imgs else ""

        # --- Extract metadata ---
        studio = ""
        upload_date = ""
        
        # Try JSON-LD first
        import json
        ld_json = soup.find("script", type="application/ld+json")
        if ld_json:
            try:
                data = json.loads(ld_json.string)
                studio = data.get("author", "")
                upload_date = data.get("uploadDate", "")
                if upload_date and "T" in upload_date:
                    upload_date = upload_date.split("T")[0]
            except Exception:
                pass

        tags_list = []
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if "/tags/" in href:
                t = a.text.strip()
                if t and t not in tags_list:
                    tags_list.append(t)
            elif "/profile/" in href and not studio:
                # Fallback to profile link
                t = a.text.strip()
                if t: studio = t
        tags_str = ", ".join(tags_list)
        
        # Description & Real Title
        summary = ""
        b_tag = soup.find('b', style='font-weight: bold')
        if b_tag and b_tag.parent and b_tag.parent.parent:
            real_series = b_tag.text.strip()
            if len(real_series) > 3 and len(real_series) < 100:
                title = real_series
            
            desc_raw = b_tag.parent.parent.text.strip()
            # Split off any buttons at the bottom if present
            summary = re.split(r'\n\s*Episode 1\b', desc_raw, 1)[0].strip()
            if summary.startswith(real_series):
                summary = re.sub(r'^' + re.escape(real_series) + r'\n*', '', summary).strip()
        else:
            # Fallback
            for d in soup.find_all('div'):
                if not d.find('div') and len(d.text.strip()) > 100:
                    t = d.text.strip()
                    if "website contains age-restricted" not in t and "Video Categories" not in t:
                        summary = re.sub(r'^(?:[^\n]+)\n+', '', t).strip()
                        break

        return title, thumbnail, full_imgs, studio, tags_str, summary, upload_date

    # ── Main metadata entry point ─────────────────────────────────────────

    def get_metadata_and_videos(self, playlist_limit=None, playlist_start=None, enrich_metadata=True):

        if self.content_type == "gallery":
            title, thumbnail, images, studio, tags_str, summary, upload_date = self._scrape_gallery_page()
            self.title = title
            clean = re.sub(r'[<>:"/\\|?*]', "", title).strip()
            self._folder_name = clean or "Gallery"

            metadata = {
                "Channel/Series": title,
                "Source": "HentaiCity",
                "Total Videos": len(images),
                "Content Type": "gallery",
                "Thumbnail": thumbnail,
                "Avatar URL": thumbnail,
                "Studio": studio,
                "Tags": tags_str,
                "Description": summary,
                "URL": self.url
            }
            # Represent gallery images as "videos" list so workflow can iterate them
            videos = [
                {
                    "url": img_url,
                    "title": f"Image {idx:03d}",
                    "id": str(idx),
                    "uploader": "HentaiCity",
                    "thumbnail": thumbnail,
                    "upload_date": upload_date,
                    "content_type": "image",
                }
                for idx, img_url in enumerate(images, 1)
            ]
            return metadata, videos, {"title": title, "url": self.url}

        else:
            # Video
            title, series_title, thumbnail, episodes, current_stream_url, studio, tags_str, summary, upload_date = self._scrape_video_page()
            self.title = series_title
            clean = re.sub(r'[<>:"/\\|?*]', "", series_title).strip()
            self._folder_name = clean or "Series"
            self._current_stream_url = current_stream_url  # for engine to reuse without re-fetching

            metadata = {
                "Channel/Series": series_title,
                "Source": "HentaiCity",
                "Total Videos": len(episodes),
                "Content Type": "video",
                "Thumbnail": thumbnail,
                "Avatar URL": thumbnail,
                "Studio": studio,
                "Tags": tags_str,
                "Description": summary,
                "URL": self.url
            }

            videos = [
                {
                    "url": ep["url"],
                    "title": ep["text"],
                    "id": str(ep["ep_num"]),
                    "uploader": "HentaiCity",
                    "thumbnail": ep.get("thumbnail") or thumbnail,
                    "upload_date": ep.get("upload_date") or upload_date,
                    "content_type": "video",
                    # Attach the already-extracted stream URL for the current episode
                    "stream_url": ep.get("stream_url", ""),
                }
                for ep in episodes
            ]

            return metadata, videos, {"title": series_title, "url": self.url}
