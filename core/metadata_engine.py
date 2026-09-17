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

logger = logging.getLogger(__name__)


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
        Saves metadata payload into .zine/metadata.json and .zine/meta.json.
        Guarantees:
          - Early exit if folder is Quick Grab (no metadata pollution).
          - Sets both 'type' and 'box_purpose' for flawless Hwaran UI routing.
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

            # Build clean dictionary from payload
            data: Dict[str, Any] = {
                "title": payload.title,
                "type": payload.type,
                "box_purpose": payload.type.lower(),
            }

            if payload.alt_title:
                data["alt_title"] = payload.alt_title
                data["altTitle"] = payload.alt_title

            if payload.author:
                data["author"] = payload.author

            if payload.artist:
                data["artist"] = payload.artist

            if payload.description:
                data["description"] = payload.description

            if payload.status:
                data["status"] = payload.status

            if payload.rating:
                data["rating"] = payload.rating

            if payload.tags:
                clean_tags = []
                for t in payload.tags:
                    if isinstance(t, str):
                        for sub in t.split(","):
                            cleaned = sub.strip()
                            if cleaned and cleaned not in clean_tags:
                                clean_tags.append(cleaned)
                    elif t:
                        str_t = str(t).strip()
                        if str_t and str_t not in clean_tags:
                            clean_tags.append(str_t)
                data["tags"] = clean_tags
                data["genres"] = clean_tags

            if payload.year:
                data["year"] = payload.year

            if payload.url:
                data["url"] = payload.url

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

            # Write primary target: .zine/metadata.json (Hwaran preferred)
            primary_path = zine_dir / "metadata.json"
            existing_data: Dict[str, Any] = {}
            if primary_path.exists():
                try:
                    with open(primary_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                except Exception:
                    existing_data = {}

            # Merge existing data so manual fields aren't wiped
            existing_data.update(data)

            with open(primary_path, "w", encoding="utf-8") as f:
                json.dump(existing_data, f, indent=2, ensure_ascii=False)

            # Maintain secondary target: .zine/meta.json (Legacy Zine compatibility)
            legacy_path = zine_dir / "meta.json"
            try:
                with open(legacy_path, "w", encoding="utf-8") as f:
                    json.dump(existing_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

            logger.info(f"Unified metadata saved successfully to {primary_path}")
            return True

        except Exception as e:
            logger.warning(f"Failed to save metadata to {dest_folder}: {e}")
            return False
