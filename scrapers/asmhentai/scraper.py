import re
import logging
from pathlib import Path
from bs4 import BeautifulSoup
from .engine import BaseScraper

logger = logging.getLogger("AsmHentai")


class AsmHentaiScraper(BaseScraper):
    scraper_type = "toon"

    def is_chapter_link(self) -> bool:
        # asmhentai.com/gallery/659361/1/ — page within a gallery
        return bool(re.search(r"/gallery/\d+/\d+/?$", self.url))

    def __init__(self, url: str):
        # Normalize to gallery root: /g/<id>/ or /gallery/<id>/
        match = re.search(r"asmhentai\.com/(?:g|gallery)/(\d+)", url)
        if match:
            self.gallery_id = match.group(1)
            url = f"https://asmhentai.com/g/{self.gallery_id}/"
        else:
            self.gallery_id = None
        super().__init__(url)
        
        # AsmHentai 404s without a trailing slash, and BaseScraper strips it.
        if not self.url.endswith("/"):
            self.url += "/"

    def _build_image_urls(self, gallery_id: str, dir_id: str, num_pages: int) -> list:
        """
        AsmHentai uses URLs like:
          https://images.asmhentai.com/018/659361/1.jpg
        The dir_id is extracted from the hidden input#load_dir.
        We try .jpg first, then .png, .webp for each page.
        """
        urls = []
        base = f"https://images.asmhentai.com/{dir_id}/{gallery_id}"
        for i in range(1, num_pages + 1):
            # Primary attempt: jpg — fallback extensions handled in download_with_retry
            urls.append((i, f"{base}/{i}.jpg"))
        return urls

    def get_title_and_chapters(self):
        soup = self.get_soup(self.url)

        # Title — h1 in .info
        h1 = soup.select_one("div.info h1") or soup.select_one("div.right h1")
        title_text = h1.get_text(strip=True) if h1 else "Unknown"

        # Clean title for filesystem
        title = re.sub(r"[^\w\s\-]", "", title_text).strip()
        if not title:
            title = f"Gallery {self.gallery_id}"
        self.title = title

        # Tags / genres
        self.tags = []
        self.genres = []
        self.author = ""
        for div in soup.select("div.tags"):
            header = div.select_one("h3")
            section_name = header.get_text(strip=True).lower().rstrip(":") if header else ""
            for span in div.select("span.badge.tag"):
                text = span.get_text(strip=True)
                # Strip the count "(123,456)" suffix
                text = re.sub(r"\s*\(\d[\d,]*\)\s*$", "", text).strip()
                if not text:
                    continue
                if section_name in ("tags",):
                    self.tags.append(text.title())
                elif section_name in ("artists", "groups"):
                    if not self.author:
                        self.author = text.title()
                    elif text.title() not in self.author:
                        self.author += f", {text.title()}"
                elif section_name in ("category", "categories"):
                    self.genres.append(text.title())
                elif section_name == "languages":
                    self.tags.append(f"lang:{text}")

        # Cover URL — lazy-loaded img inside div.cover
        cover_img = soup.select_one("div.cover img")
        if cover_img:
            self.cover_url = (cover_img.get("data-src") or cover_img.get("src") or "").strip()
            if self.cover_url.startswith("//"):
                self.cover_url = "https:" + self.cover_url

        # Page count
        pages_h3 = soup.select_one("div.pages h3")
        self.num_pages = 0
        if pages_h3:
            m = re.search(r"(\d+)", pages_h3.get_text())
            if m:
                self.num_pages = int(m.group(1))

        # Dir ID (for image URL construction)
        self.dir_id = "000"
        load_dir = soup.select_one("input#load_dir")
        if load_dir and load_dir.get("value"):
            self.dir_id = load_dir["value"].zfill(3)
        else:
            # Fallback: extract from thumbnail URLs in the page source
            m = re.search(rf"images\.asmhentai\.com/(\w+)/{self.gallery_id}/", str(soup))
            if m:
                self.dir_id = m.group(1)

        self.description = ""

        # Return title + single "chapter" = the gallery itself
        return title, [("1", self.url)]

    def process_chapter(self, ch_url, folder, ch_num, live=None, stats_callback=None) -> dict:
        # Re-fetch gallery page if needed to get dir_id and num_pages
        if not hasattr(self, "dir_id") or not self.dir_id or not self.num_pages:
            soup = self.get_soup(ch_url)
            load_dir = soup.select_one("input#load_dir")
            self.dir_id = load_dir["value"].zfill(3) if load_dir and load_dir.get("value") else "000"
            pages_h3 = soup.select_one("div.pages h3")
            if pages_h3:
                m = re.search(r"(\d+)", pages_h3.get_text())
                self.num_pages = int(m.group(1)) if m else 0

        if not self.gallery_id or not self.num_pages:
            logger.error("Missing gallery_id or num_pages — cannot download")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        return self._download_with_retry(
            self.gallery_id, self.dir_id, self.num_pages,
            folder, ch_num, ch_url,
            live=live, stats_callback=stats_callback
        )

    def _download_with_retry(self, gallery_id, dir_id, num_pages, folder, ch_num, ch_url,
                              live=None, stats_callback=None) -> dict:
        """Downloads each page trying .jpg → .png → .webp extensions."""
        temp_dir = folder / f"_temp_{ch_num}"
        temp_dir.mkdir(exist_ok=True, parents=True)
        paths = []
        base = f"https://images.asmhentai.com/{dir_id}/{gallery_id}"

        for i in range(1, num_pages + 1):
            target_path = temp_dir / f"{i:03d}.jpg"
            success_page = False
            for ext in ["jpg", "png", "webp"]:
                src = f"{base}/{i}.{ext}"
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
                logger.error(f"Page {i}: Failed all extensions")

        success = False
        downloaded_count = len(paths)
        final_chunks = 0
        if paths:
            if stats_callback:
                stats_callback({"total": num_pages, "downloaded": downloaded_count, "missing": num_pages - downloaded_count, "status": "baking"})
            final_chunks = self.slice_and_save(paths, folder)
            if downloaded_count == num_pages:
                success = True

        import shutil as _shutil
        _shutil.rmtree(temp_dir, ignore_errors=True)

        missing = num_pages - downloaded_count
        if success and final_chunks:
            return {"total": final_chunks, "downloaded": final_chunks, "missing": missing, "success": success}
        return {"total": num_pages, "downloaded": downloaded_count, "missing": missing, "success": success}
