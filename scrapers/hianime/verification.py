from pathlib import Path
from typing import List, Any


def verify_videos(folder: Path, videos: List[dict], ext_str: str, tracker: Any, url: str) -> List[str]:
    """Delegate to the tracker's two-step verification (history + disk existence)."""
    return tracker.sync_local_history(folder, videos, ext_str, url)
