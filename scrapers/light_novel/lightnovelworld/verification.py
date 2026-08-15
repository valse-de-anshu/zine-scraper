"""
scrapers/light_novel/lightnovelworld/verification.py
-----------------------------------------------------
Chapter verification: checks both download history and disk for .txt files.
"""

from pathlib import Path
from typing import List, Tuple, Any


def verify_chapters(folder: Path, chapters: List[Tuple[str, str]], tracker: Any, url: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Returns (verified_nums, to_process).
    A chapter is considered done if it exists in tracker history AND the .txt file is on disk.
    """
    verified_nums = []
    to_process = []

    for num, link in chapters:
        # Expected file path for this chapter
        ch_file = folder / f"chapter_{num.zfill(4)}.txt"

        # Also check old naming convention for resilience
        alt_file = folder / f"chapter_{num}.txt"

        is_in_history = tracker.is_downloaded(url, num)
        has_file = ch_file.exists() or alt_file.exists()

        # Stale history: tracker says done but file is gone
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
