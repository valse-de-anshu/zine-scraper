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
        range_str = theme_input(f"[info]Enter track range (e.g. 1-{len(videos)} or count): [/info]").strip()
        if not range_str:
            return "ALL", videos
        try:
            if "-" in range_str:
                parts = range_str.split("-", 1)
                start_s = parts[0].strip()
                end_s = parts[1].strip()
                start = max(1, int(start_s)) if start_s else 1
                end = min(len(videos), int(end_s)) if end_s else len(videos)
                selected = videos[start - 1 : end]
            elif "," in range_str:
                indices = set()
                for part in range_str.split(","):
                    p = part.strip()
                    if "-" in p:
                        s, e = p.split("-", 1)
                        indices.update(range(int(s), int(e) + 1))
                    elif p.isdigit():
                        indices.add(int(p))
                selected = [videos[i - 1] for i in sorted(indices) if 1 <= i <= len(videos)]
            else:
                count = int(range_str)
                if count <= 0:
                    selected = videos[:1]
                else:
                    if verified_ids:
                        un_downloaded = [
                            v for v in videos
                            if str(v.get("id", "")) not in verified_ids
                            and v.get("title", "") not in verified_ids
                        ]
                        if un_downloaded:
                            selected = un_downloaded[:count]
                        else:
                            selected = videos[:min(len(videos), count)]
                    else:
                        selected = videos[:min(len(videos), count)]
            return "RANGE", selected
        except Exception:
            return "ALL", videos

    if choice == "MULTI":
        multi_options = []
        for i, v in enumerate(videos):
            track_num = v.get("track_number", i + 1)
            title = v.get("title", "Track")
            artist = v.get("artist", "")
            duration = v.get("duration_string") or ""
            multi_options.append({
                "name": f"{track_num:02d}. {title}",
                "desc": artist,
                "right_text": duration,
                "video": v,
                "size_bytes": 0,
            })
        multi_options.append({
            "name": "Back",
            "desc": "Cancel selection",
            "right_text": "",
            "is_action": True,
            "action": "BACK"
        })
        selected_items = MultiSelector(multi_options, "Select Tracks").select()
        if not selected_items or any(item.get("action") == "BACK" for item in selected_items):
            return "BACK", []
        chosen_videos = [item["video"] for item in selected_items if "video" in item]
        if not chosen_videos:
            return "BACK", []
        return "MULTI", chosen_videos

    return "ALL", videos
