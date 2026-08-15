"""
scrapers/youtube/yt_music/tui.py
--------------------------------
TUI entry point and interactive selectors for YouTube Music.
Delegates orchestration to workflow.py.
"""

import sys
from typing import List, Dict, Any, Tuple, Optional
from core.ui import Selector, MultiSelector

def handle_tui(
    url: str,
    tracker: Any,
    location_manager: Any,
    scraper: Any,
    batch_path: Optional[Any] = None,
    is_batch: bool = False
):
    """
    Standard site TUI entrypoint called by core.funnel.
    Delegates presentation and download logic to workflow.py.
    """
    from .workflow import run_workflow
    run_workflow(url, tracker, location_manager, scraper, batch_path=batch_path, is_batch=is_batch)

def get_track_selection(videos: List[Dict[str, Any]], is_vacuum: bool = False, is_batch: bool = False) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Interactive TUI selector for YouTube Music tracks.
    Correctly recognizes Quick Grab (single track) vs Vacuum (playlist/album) modes.
    Guarded with TTY and batch checks.
    """
    if is_batch or not sys.stdin.isatty():
        return "ALL", videos

    if not is_vacuum and len(videos) == 1:
        # Quick Grab: Single track format menu
        options = [
            ("Song (FLAC Lossless)", "SINGLE"),
            ("Custom Song with Thumbnail", "CUSTOM_THUMB"),
            ("Back", "BACK")
        ]
        choice = Selector(options, "Format").select()
        if choice == "BACK":
            return "BACK", []
        return choice, videos

    # Vacuum: Multiple tracks (Playlist / Album)
    options = [
        (f"Download All ({len(videos)} tracks in FLAC)", "ALL"),
        ("Select Range (e.g. 1-10)", "RANGE"),
        ("Select Individual Tracks", "MULTI"),
        ("First Track Only", "FIRST"),
        ("Back", "BACK")
    ]
    choice = Selector(options, "Download Mode").select()

    if choice == "BACK":
        return "BACK", []

    if choice == "ALL":
        return "ALL", videos

    if choice == "FIRST":
        return "FIRST", videos[:1]

    if choice == "RANGE":
        from core.ui import theme_input
        range_str = theme_input(f"[info]Enter track range (1-{len(videos)}): [/info]").strip()
        try:
            if "-" in range_str:
                start_s, end_s = range_str.split("-", 1)
                start = max(1, int(start_s))
                end = min(len(videos), int(end_s))
                selected = videos[start - 1 : end]
            else:
                idx = int(range_str)
                selected = [videos[idx - 1]]
            return "RANGE", selected
        except Exception:
            return "ALL", videos

    if choice == "MULTI":
        multi_options = [
            (f"{v.get('track_number', i+1):02d}. {v.get('title', 'Track')[:45]} ({v.get('artist', '')[:20]})", v)
            for i, v in enumerate(videos)
        ]
        selected_items = MultiSelector(multi_options, "Select Tracks").select()
        if not selected_items:
            return "BACK", []
        return "MULTI", selected_items

    return "ALL", videos
