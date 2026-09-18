"""
scrapers/hentaicity/verification.py
-------------------------------------
Two-step download verification for HentaiCity.
"""
from typing import List, Dict, Any
from pathlib import Path
from core.history import HistoryLayer


def verify_videos(
    sub_folder: Path,
    videos: List[Dict[str, Any]],
    ext: str,
    url: str,
    tracker: HistoryLayer,
) -> List[str]:
    return tracker.sync_local_history(sub_folder, videos, ext, url)
