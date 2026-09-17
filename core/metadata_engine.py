"""
core/metadata_engine.py
───────────────────────
Unified metadata engine for Zine Scraper and Hwaran (Android).
Standardizes schema, ensures strict 'type'/'box_purpose' emission,
and protects Quick Grab directories from unwanted metadata files.
"""

from dataclasses import dataclass, field, asdict
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

from core.history import _is_quick_grab_dir

import html
import re

logger = logging.getLogger(__name__)


def _smart_quotes(text: str) -> str:
    """
    Normalizes straight double quotes to typographical curly quotes (“ and ”)
    and removes backslash-escaped quote artifacts (\").
    This ensures JSON serialization emits clean text without backslash artifacts.
    """
    if not text:
        return ""
    text = text.replace(r'\"', '"')
    # Opening quote: at start of string or following whitespace, dash, or opening bracket
    text = re.sub(r'(^|[\s(\[{<—–-])"', r'\1“', text)
    # Closing quote: any remaining straight double quotes
    text = re.sub(r'"', '”', text)
    return text


def _clean_str(text: Optional[str]) -> str:
    """Unescapes HTML entities, strips HTML tags, and cleans quote artifacts from single-line text fields."""
    if not text:
        return ""
    text = text.replace(r'\"', '"')
    cleaned = html.unescape(str(text))
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    return _smart_quotes(cleaned.strip())


def _clean_html_text(text: Optional[str]) -> str:
    """
    Cleans raw HTML descriptions by unescaping HTML entities (&rsquo;, &hellip;, etc.),
    converting <br> and <p> to natural newlines, stripping all other tags, and converting
    straight/escaped double quotes to typographical curly quotes to prevent JSON backslash artifacts.
    """
    if not text:
        return ""
    text = text.replace(r'\"', '"')
    text = html.unescape(str(text))
    text = re.sub(r'<\s*br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?\s*p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    lines = [line.strip() for line in text.splitlines()]
    cleaned = []
    prev_empty = False
    for l in lines:
        if not l:
            if not prev_empty:
                cleaned.append("")
                prev_empty = True
        else:
            cleaned.append(l)
            prev_empty = False
    full_text = "\n".join(cleaned).strip()
    return _smart_quotes(full_text)


@dataclass
class ZineMetadataPayload:
    """
    Lean, essential metadata payload designed for 100% compatibility
    with Hwaran's ZineMetadataExtractor and Description routing.
    """
    title: str
    type: str                                                         # "Manga", "Manhua", "Manhwa", "Novel", "Book", "Series", "Channel", "Song"
    alt_title: Optional[str] = ""
    author: Optional[str] = ""                                        # Author / Creator / Uploader
    artist: Optional[str] = ""                                        # Artist / Studio
    description: Optional[str] = ""
    status: Optional[str] = ""                                        # "Ongoing", "Completed", "Hiatus", etc.
    rating: Optional[str] = ""                                        # Score / Rating (e.g. "8.8" or "9.5/10")
    tags: List[str] = field(default_factory=list)                     # Normalized list of genres/tags
    year: Optional[str] = ""                                          # Release or Aired year
    url: Optional[str] = ""

    # YouTube & Pornhub channel/creator stats only:
    views: Optional[str] = ""
    likes: Optional[str] = ""
    hottest: List[Dict[str, Any]] = field(default_factory=list)       # Most viewed / hottest videos
    most_rated: List[Dict[str, Any]] = field(default_factory=list)    # Top rated videos


class MetadataEngine:
    """
    Canonical service for persisting media metadata into folder/.zine/metadata.json.
    """

    @staticmethod
    def is_quick_grab(folder: Union[str, Path]) -> bool:
        """Checks if a target directory belongs to Quick Grab."""
        f_str = str(folder).lower()
        if "quick grab" in f_str or "quick_grab" in f_str:
            return True
        return _is_quick_grab_dir(Path(folder))

    @classmethod
    def save_metadata(cls, folder: Union[str, Path], payload: ZineMetadataPayload) -> bool:
        """
        Saves metadata payload into .zine/metadata.json.
        Guarantees:
          - Early exit if folder is Quick Grab (no metadata pollution).
          - Sets both 'type' and 'box_purpose' for flawless Hwaran UI routing.
          - Sanitizes descriptions (stripping HTML tags, unescaping &rsquo;, &hellip;, etc.).
          - Sanitizes tag arrays.
          - Preserves existing keys during updates.
        """
        dest_folder = Path(folder)
        if cls.is_quick_grab(dest_folder):
            logger.debug(f"Skipping metadata persistence for Quick Grab path: {dest_folder}")
            return False

        try:
            zine_dir = dest_folder / ".zine"
            zine_dir.mkdir(parents=True, exist_ok=True)

            # Clean and unescape title
            clean_title = _clean_str(payload.title)

            # Build clean dictionary from payload
            data: Dict[str, Any] = {
                "title": clean_title,
                "type": payload.type,
                "box_purpose": payload.type.lower(),
            }

            if payload.alt_title:
                clean_alt = _clean_str(payload.alt_title)
                if clean_alt:
                    data["alt_title"] = clean_alt
                    data["altTitle"] = clean_alt

            if payload.author:
                clean_author = _clean_str(payload.author)
                if clean_author:
                    data["author"] = clean_author

            if payload.artist:
                clean_artist = _clean_str(payload.artist)
                if clean_artist:
                    data["artist"] = clean_artist

            if payload.description:
                clean_desc = _clean_html_text(payload.description)
                if clean_desc:
                    data["description"] = clean_desc

            if payload.status:
                clean_status = _clean_str(payload.status)
                if clean_status:
                    data["status"] = clean_status

            if payload.rating:
                r_str = _clean_str(str(payload.rating))
                try:
                    r_val = float(r_str)
                    r_str = f"{round(r_val, 2):g}"
                except Exception:
                    pass
                if r_str:
                    data["rating"] = r_str

            if payload.tags:
                clean_tags = []
                for t in payload.tags:
                    if isinstance(t, str):
                        for sub in t.split(","):
                            cleaned = _clean_str(sub)
                            if cleaned and cleaned not in clean_tags:
                                clean_tags.append(cleaned)
                    elif t:
                        str_t = _clean_str(str(t))
                        if str_t and str_t not in clean_tags:
                            clean_tags.append(str_t)
                if clean_tags:
                    data["tags"] = clean_tags
                    data["genres"] = clean_tags

            if payload.year:
                clean_year = _clean_str(str(payload.year))
                if clean_year:
                    data["year"] = clean_year

            if payload.url:
                data["url"] = payload.url.strip()

            # YouTube / Pornhub channel specific metrics
            if payload.views:
                data["views"] = str(payload.views)

            if payload.likes:
                data["likes"] = str(payload.likes)

            if payload.hottest:
                data["most_viewed"] = payload.hottest
                data["hottest"] = payload.hottest

            if payload.most_rated:
                data["top_rated"] = payload.most_rated
                data["most_rated"] = payload.most_rated

            primary_path = zine_dir / "metadata.json"
            legacy_path = zine_dir / "meta.json"
            existing_data: Dict[str, Any] = {}
            if primary_path.exists():
                try:
                    with open(primary_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}
            elif legacy_path.exists():
                try:
                    with open(legacy_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}

            # Merge existing data so manual fields aren't wiped
            existing_data.update(data)

            with open(primary_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)

            # Eliminate redundant legacy meta.json file
            if legacy_path.exists():
                try:
                    legacy_path.unlink()
                except Exception:
                    pass

            logger.info(f"Unified metadata saved successfully to {primary_path}")
            return True

        except Exception as e:
            logger.warning(f"Failed to save metadata to {dest_folder}: {e}")
            return False
