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

def get_track_selection(
    videos: List[Dict[str, Any]],
    is_vacuum: bool = False,
    is_batch: bool = False,
    verified_ids: Optional[Any] = None
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Zero-friction track selector for YouTube Music.
    Directly returns all tracks automatically without blocking on interactive menus.
    """
    return "ALL", videos

