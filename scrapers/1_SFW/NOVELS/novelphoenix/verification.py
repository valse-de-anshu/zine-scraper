"""
scrapers/light_novel/novelphoenix/verification.py
-------------------------------------------------
Chapter verification for NovelPhoenix.
"""

from pathlib import Path
from typing import List, Tuple, Any


def verify_chapters(folder: Path, chapters: List[Tuple[str, str]], tracker: Any, url: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    verified_nums = []
    to_process = []

    for num, link in chapters:
        ch_file = folder / "novel chapter" / f"chapter_{num.zfill(4)}.txt"
        alt_file = folder / f"chapter_{num.zfill(4)}.txt"

        is_in_history = tracker.is_downloaded(url, num)
        has_file = ch_file.exists() or alt_file.exists()

        if is_in_history and not has_file:
            tracker.unmark_downloaded(url, num)
            is_in_history = False

        if is_in_history or has_file:
            if not is_in_history:
                tracker.mark_downloaded(url, num)
            verified_nums.append(num)
        else:
            to_process.append((num, link))

    return verified_nums, to_process
