import re
import logging
from urllib.parse import urlparse
from typing import Tuple, List, Dict, Any, Optional

from .engine import BaseScraper

logger = logging.getLogger("MangaDex")

LANGUAGE_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "es-la": "Spanish (LATAM)",
    "pt": "Portuguese",
    "pt-br": "Portuguese (Brazil)",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "ru": "Russian",
    "pl": "Polish",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "zh": "Chinese (Simp)",
    "zh-hk": "Chinese (Trad)",
    "ko": "Korean",
    "ar": "Arabic",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ms": "Malay",
    "tl": "Tagalog",
    "hi": "Hindi",
    "cs": "Czech",
    "hu": "Hungarian",
    "ro": "Romanian",
    "nl": "Dutch",
    "el": "Greek",
    "bg": "Bulgarian",
    "sv": "Swedish",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "he": "Hebrew",
    "fa": "Persian",
    "bn": "Bengali",
    "my": "Burmese",
    "mn": "Mongolian",
}

class MangaDexScraper(BaseScraper):
    def __init__(self, url: str):
        super().__init__(url)
        self.title = ""
        self.cover_url = ""
        self.author = ""
        self.artist = ""
        self.description = ""
        self.status = ""
        self.tags = []
        self.genres = []
        self.available_languages = []
        self.chosen_language = "en"
        self.manga_id: Optional[str] = None
        self.single_chapter_id: Optional[str] = None
        self.is_chapter = False

        self._parse_url()

    def _parse_url(self):
        """Identifies whether URL is a manga title or single chapter."""
        clean = self.url.lower()

        # Match Chapter UUID
        ch_match = re.search(r"/chapter/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", self.url)
        if ch_match:
            self.single_chapter_id = ch_match.group(1)
            self.is_chapter = True
            return

        # Match Manga / Title UUID
        manga_match = re.search(r"/(?:title|manga)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", self.url)
        if manga_match:
            self.manga_id = manga_match.group(1)
            return

        # Fallback regex for loose UUIDs
        loose_uuid = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", self.url)
        if loose_uuid:
            if "chapter" in clean:
                self.single_chapter_id = loose_uuid.group(1)
                self.is_chapter = True
            else:
                self.manga_id = loose_uuid.group(1)

    def is_chapter_link(self) -> bool:
        return self.is_chapter

    def get_title_and_chapters(self, fetch_chapters: bool = False, lang: Optional[str] = None) -> Tuple[str, List[Tuple[str, str]]]:
        """Fetches full series metadata and available languages from MangaDex API."""
        # 1. If starting from a chapter URL, resolve parent manga first
        if self.single_chapter_id and not self.manga_id:
            ch_data = self.api.get_chapter(self.single_chapter_id)
            if ch_data:
                ch_attr = ch_data.get("attributes", {})
                self.chosen_language = ch_attr.get("translatedLanguage", "en")
                for rel in ch_data.get("relationships", []):
                    if rel.get("type") == "manga":
                        self.manga_id = rel.get("id")
                        break

        if not self.manga_id:
            raise RuntimeError(f"Could not extract MangaDex UUID from URL: {self.url}")

        # 2. Fetch Manga Metadata
        manga_data = self.api.get_manga(self.manga_id)
        if not manga_data:
            raise RuntimeError(f"Failed to fetch metadata for MangaDex ID: {self.manga_id}")

        attr = manga_data.get("attributes", {})
        
        # Available translated languages
        self.available_languages = attr.get("availableTranslatedLanguages", []) or []

        # Resolve Title - strictly prioritize English, then fall back to primary original language
        title_dict = attr.get("title", {}) or {}
        alt_titles = attr.get("altTitles", []) or []
        orig_lang = attr.get("originalLanguage") or ""

        # 1. Primary or alt English title
        raw_title = title_dict.get("en")
        if not raw_title:
            for alt in alt_titles:
                if isinstance(alt, dict) and "en" in alt and alt["en"].strip():
                    raw_title = alt["en"].strip()
                    break

        # 2. Fallback to the primary original language used (romanized or native)
        if not raw_title and orig_lang:
            ro_key = f"{orig_lang}-ro"
            if ro_key in title_dict and title_dict[ro_key].strip():
                raw_title = title_dict[ro_key].strip()
            elif orig_lang in title_dict and title_dict[orig_lang].strip():
                raw_title = title_dict[orig_lang].strip()
            else:
                for alt in alt_titles:
                    if isinstance(alt, dict):
                        if ro_key in alt and alt[ro_key].strip():
                            raw_title = alt[ro_key].strip()
                            break
                        elif orig_lang in alt and alt[orig_lang].strip():
                            raw_title = alt[orig_lang].strip()
                            break

        # 3. Fallback to generic romanized titles
        if not raw_title:
            for ro_key in ("ja-ro", "ko-ro", "zh-ro"):
                if ro_key in title_dict and title_dict[ro_key].strip():
                    raw_title = title_dict[ro_key].strip()
                    break

        # 4. Fallback to first available title dictionary value
        if not raw_title and title_dict:
            raw_title = list(title_dict.values())[0]

        # 5. Fallback to first available alternative title
        if not raw_title:
            for alt in alt_titles:
                if isinstance(alt, dict) and alt:
                    first_val = list(alt.values())[0]
                    if isinstance(first_val, str) and first_val.strip():
                        raw_title = first_val.strip()
                        break

        if not raw_title:
            raw_title = "Unknown Manga"

        # Sanitize title for filesystem safety across platforms
        self.title = re.sub(r'[\\/:*?"<>|]', "", raw_title).strip()
        self.status = (attr.get("status") or "").title()

        # Description
        desc_dict = attr.get("description", {})
        self.description = desc_dict.get("en") or (list(desc_dict.values())[0] if desc_dict else "")

        # Authors, Artists, Cover
        authors = []
        artists = []
        cover_filename = None
        for rel in manga_data.get("relationships", []):
            rel_type = rel.get("type")
            rel_attr = rel.get("attributes", {})
            name = rel_attr.get("name")
            if rel_type == "author" and name:
                authors.append(name)
            elif rel_type == "artist" and name:
                artists.append(name)
            elif rel_type == "cover_art":
                cover_filename = rel_attr.get("fileName")

        if authors:
            self.author = ", ".join(list(dict.fromkeys(authors)))
        if artists:
            self.artist = ", ".join(list(dict.fromkeys(artists)))

        if cover_filename:
            self.cover_url = f"https://uploads.mangadex.org/covers/{self.manga_id}/{cover_filename}"

        # Tags & Genres
        for tag_obj in attr.get("tags", []):
            tag_name = tag_obj.get("attributes", {}).get("name", {}).get("en")
            tag_group = tag_obj.get("attributes", {}).get("group")
            if tag_name:
                if tag_group == "genre":
                    self.genres.append(tag_name)
                else:
                    self.tags.append(tag_name)

        # 3. If single chapter URL provided, isolate to that chapter
        if self.single_chapter_id:
            ch_data = self.api.get_chapter(self.single_chapter_id)
            ch_num = "1"
            if ch_data:
                ch_num = ch_data.get("attributes", {}).get("chapter") or "1"
            ch_url = f"https://mangadex.org/chapter/{self.single_chapter_id}"
            return self.title, [(ch_num, ch_url)]

        if not fetch_chapters:
            return self.title, []

        # Default chapter list in requested or English language
        init_lang = lang or ("en" if "en" in self.available_languages else (self.available_languages[0] if self.available_languages else ""))
        chapters = self.get_chapters_for_language(init_lang)
        return self.title, chapters

    def get_chapters_for_language(self, lang: str = "en") -> List[Tuple[str, str]]:
        """Fetches paginated chapter feed for a specific language and deduplicates releases."""
        self.chosen_language = lang
        chapters_raw = []
        limit = 500
        offset = 0

        feed_resp = self.api.get_feed(self.manga_id, lang=lang, limit=limit, offset=offset)
        total = feed_resp.get("total", 0) if feed_resp else 0

        # If language returned 0, fallback to all languages
        if total == 0 and lang:
            feed_resp = self.api.get_feed(self.manga_id, lang="", limit=limit, offset=0)
            total = feed_resp.get("total", 0) if feed_resp else 0

        if feed_resp and "data" in feed_resp:
            chapters_raw.extend(feed_resp["data"])

        offset += limit
        while offset < total:
            next_resp = self.api.get_feed(self.manga_id, lang=lang, limit=limit, offset=offset)
            if not next_resp or "data" not in next_resp or not next_resp["data"]:
                break
            chapters_raw.extend(next_resp["data"])
            offset += limit

        # Deduplicate multiple scanlation groups by chapter number (pick highest page count)
        by_chapter_num: Dict[str, Dict[str, Any]] = {}

        for ch in chapters_raw:
            ch_attr = ch.get("attributes", {})
            pages = ch_attr.get("pages", 0)
            ext_url = ch_attr.get("externalUrl")
            
            # Skip external link redirects with 0 pages (e.g. MangaPlus stubs)
            if ext_url and pages == 0:
                continue
            if pages == 0:
                continue

            raw_num = ch_attr.get("chapter") or "0"
            num_clean = raw_num.strip()
            ch_id = ch.get("id")
            ch_full_url = f"https://mangadex.org/chapter/{ch_id}"

            if num_clean not in by_chapter_num or pages > by_chapter_num[num_clean]["pages"]:
                by_chapter_num[num_clean] = {
                    "num": num_clean,
                    "url": ch_full_url,
                    "pages": pages,
                    "id": ch_id,
                }

        parsed_chapters = []
        for num_str, item in by_chapter_num.items():
            try:
                f_val = float(num_str)
            except ValueError:
                m = re.search(r"([\d.]+)", num_str)
                f_val = float(m.group(1)) if m else 99999.0
            parsed_chapters.append((f_val, num_str, item["url"]))

        parsed_chapters.sort(key=lambda x: x[0])
        return [(str_num, link) for _, str_num, link in parsed_chapters]

    def process_chapter(self, ch_url: str, folder, ch_num: str, live=None, stats_callback=None) -> dict:
        """Downloads all images for a specific chapter via MangaDex@Home."""
        if stats_callback:
            stats_callback({"status": "loading"})
        ch_id_match = re.search(r"/chapter/([0-9a-fA-F\-]{36})", ch_url)
        if not ch_id_match:
            logger.error(f"Cannot extract chapter UUID from {ch_url}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        chapter_id = ch_id_match.group(1)
        athome = self.api.get_athome_server(chapter_id)
        if not athome:
            logger.error(f"Failed to obtain MangaDex@Home node for chapter {chapter_id}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        base_url = athome.get("baseUrl")
        ch_meta = athome.get("chapter", {})
        ch_hash = ch_meta.get("hash")
        page_files = ch_meta.get("data", [])

        if not base_url or not ch_hash or not page_files:
            logger.warning(f"No image files listed for chapter {chapter_id}")
            return {"total": 0, "downloaded": 0, "missing": 0, "success": False}

        img_urls = [f"{base_url}/data/{ch_hash}/{img_file}" for img_file in page_files]
        return self.process_chapter_multi(img_urls, folder, ch_num, ch_url, live=live, stats_callback=stats_callback)
