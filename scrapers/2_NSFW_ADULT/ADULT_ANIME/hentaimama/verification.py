"""
scrapers/hentaimama/verification.py
---------------------------------
Two-step verification for Hentaimama downloads:

Step 1 — History check  : has the video ID been recorded in global history and .zine/history.json?
Step 2 — Disk check     : does the corresponding .mp4 file physically exist on disk?

Both steps must pass for a video to be considered "already downloaded".
This prevents both unnecessary re-downloads AND silent history-only mismatches.
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
    """
    Performs two-step verification and returns list of verified (already downloaded) IDs.
    Delegates the full sync logic to tracker.sync_local_history, which:
      1. Checks the local .zine/history.json  →  Step 1
      2. Verifies the file exists on disk      →  Step 2
    If both pass, the video ID is added to the verified list.
    """
    return tracker.sync_local_history(sub_folder, videos, ext, url)
