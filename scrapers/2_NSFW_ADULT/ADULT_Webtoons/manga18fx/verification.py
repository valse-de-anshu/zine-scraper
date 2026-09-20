import os
import shutil
from pathlib import Path
from typing import List, Tuple, Any

def verify_chapters(folder: Path, chapters: List[Tuple[str, str]], tracker: Any, url: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    verified_nums = []
    to_process = []

    for num, link in chapters:
        chapter_path = folder / f"Chapter{num}"

        # Check for legacy naming ch{num} and migrate if present
        try:
            val = float(num)
            old_c_num = str(int(val)) if val == int(val) else str(val)
        except Exception:
            old_c_num = str(num)

        old_chapter_path = folder / f"ch{old_c_num}"
        if old_chapter_path.exists() and not chapter_path.exists():
            try:
                old_chapter_path.rename(chapter_path)
            except Exception:
                pass

        is_in_history = tracker.is_downloaded(url, num) if hasattr(tracker, "is_downloaded") else False

        has_files = chapter_path.exists() and (
            any(chapter_path.glob("*.jpg")) or
            any(chapter_path.glob("*.png")) or
            any(chapter_path.glob("*.webp")) or
            any(chapter_path.glob("*.avif")) or
            any(chapter_path.glob("*.jpeg"))
        )

        if is_in_history and not has_files:
            if hasattr(tracker, "unmark_downloaded"):
                tracker.unmark_downloaded(url, num)
            is_in_history = False

        if is_in_history or has_files:
            if not is_in_history and hasattr(tracker, "mark_downloaded"):
                tracker.mark_downloaded(url, num)
            verified_nums.append(num)
        else:
            to_process.append((num, link))

    return verified_nums, to_process
