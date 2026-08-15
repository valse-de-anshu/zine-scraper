import re
import time
import logging
import json
from pathlib import Path
from typing import Dict, Any, List
from core.ui import (
    MinimalPulseBar,
    console, align_header, MbpsColumn,
    CustomDownloadColumn, CustomTimeRemainingColumn,
    set_active_live
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn
from .verification import verify_pins
from .progress import render_progress_tree

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None


def _safe_folder_name(name: str) -> str:
    """Strip characters that are illegal in directory names on any major OS."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name or "Unnamed"


def _download_pin(pin, board_folder, board_url, scraper, tracker, state, storage_layer, console):
    """
    Download a single pin into board_folder.
    Returns True if newly downloaded, False if skipped/failed.
    """
    import time as _time
    pin_id = pin["id"]
    pin_title = pin["title"]
    direct_url = pin.get("direct_url") or ""
    pin_page_url = pin.get("url", "")

    if not direct_url and not pin_page_url:
        return False

    is_video = pin.get("is_video", False)
    if is_video and pin_page_url:
        pin_url = pin_page_url
    else:
        pin_url = direct_url or pin_page_url

    clean_title = "".join([c for c in pin_title if c.isalnum() or c in " .-_()"]).strip()
    if not clean_title:
        clean_title = f"pin_{pin_id}"

    if is_video:
        ext = ".mp4"
    elif ".png" in direct_url.lower():
        ext = ".png"
    elif ".gif" in direct_url.lower():
        ext = ".gif"
    elif ".webp" in direct_url.lower():
        ext = ".webp"
    else:
        ext = ".jpg"

    pin_path, is_downloaded = tracker.resolve_download_path(board_folder, str(pin_id), clean_title, ext)
    filename = pin_path.name

    if is_downloaded:
        tracker.mark_downloaded(board_url, str(pin_id))
        console.print(f"  [unselected]File exists: {filename}[/unselected]")
        return False

    state["current_pin"] = filename
    state["progress"] = {
        "total_bytes": 0,
        "downloaded_bytes": 0,
        "done": False,
        "success": False,
    }

    import threading
    start_time = _time.time()

    with Live(render_progress_tree(state), console=console, refresh_per_second=10, transient=True) as live:
        set_active_live(live)

        live_active = [True]

        def refresh_loop():
            while live_active[0]:
                try:
                    live.update(render_progress_tree(state))
                except Exception:
                    pass
                _time.sleep(0.1)

        threading.Thread(target=refresh_loop, daemon=True).start()

        def stats_hook(s):
            elapsed = _time.time() - start_time
            downloaded = s.get("downloaded_bytes", 0)
            total = s.get("total_bytes", 0)
            speed = downloaded / elapsed if elapsed > 0 else 0
            eta = (total - downloaded) / speed if (speed > 0 and total > downloaded) else None
            s_copy = s.copy()
            s_copy.update({"speed": speed, "eta": eta})
            state["progress"].update(s_copy)

        success = False
        try:
            success = scraper.download_asset(pin_url, str(pin_path), stats_callback=stats_hook, is_video=is_video)
            if success:
                tracker.mark_downloaded(board_url, str(pin_id))
                state["progress"]["success"] = True
                state["pins_downloaded"] += 1
        except Exception as e:
            logger.error(f"Download error: {e}")
        finally:
            state["progress"]["done"] = True
            live_active[0] = False

        set_active_live(None)

    res_color = "success" if state["progress"].get("success") else "error"
    console.print(f"  [{res_color}]●[/{res_color}] [unselected]{filename}[/unselected]")
    return success


def _download_highlights(
    pins: List[Dict],
    board_folder: Path,         # e.g. <root>/<profile>/Story Highlights/
    board_url: str,
    profile_name: str,
    scraper,
    tracker: HistoryLayer,
    state: Dict,
    storage_layer: StorageLayer,
):
    """
    Group story frames by their highlight_group name and download each group
    into its own named subfolder inside board_folder.

    Folder structure:
        <profile>/
          Story Highlights/
            Travel/
              ig_12345.jpg
              ig_12346.mp4
            Food/
              ig_22222.jpg
            Travel (2)/      ← duplicate highlight name handled
              ...
    """
    from core.ui import startup_clear, print_banner

    # Group pins by highlight_group (fallback = "Uncategorised")
    groups: Dict[str, List[Dict]] = {}
    for pin in pins:
        group = pin.get("highlight_group") or "Uncategorised"
        groups.setdefault(group, []).append(pin)

    total_groups = len(groups)
    console.print(f"[info]Found {len(pins)} story frame(s) across {total_groups} highlight(s)[/info]\n")

    for g_idx, (group_name, group_pins) in enumerate(groups.items(), 1):
        safe_name = _safe_folder_name(group_name)
        group_folder = board_folder / safe_name
        storage_layer.create_directory(group_folder)

        startup_clear()
        print_banner()
        console.print(f"[menu]Site[/menu]         : [title]Instagram[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        console.print(f"[menu]Section[/menu]      : [info]Story Highlights ({g_idx}/{total_groups})[/info]")
        console.print(f"[menu]Highlight[/menu]    : [site]{group_name}[/site]")
        console.print(f"[menu]Frames[/menu]       : [info]{len(group_pins)} item(s)[/info]\n")

        state["board_title"] = f"Story Highlights › {group_name}"
        state["location"] = str(group_folder.resolve())
        state["pins_total"] = len(group_pins)
        state["pins_existing"] = 0
        state["pins_downloaded"] = 0
        state["status"] = "downloading"

        for pin in group_pins:
            _download_pin(pin, group_folder, board_url, scraper, tracker, state, storage_layer, console)

        state["status"] = "finished"
        console.print(render_progress_tree(state))
        time.sleep(0.3)


def run_workflow(
    selected_boards: List[Dict[str, Any]],
    tracker: HistoryLayer,
    scraper: Any,
    target_root: Path,
    storage_layer: StorageLayer,
    profile_name: str
):
    """Download loop orchestration workflow for Instagram boards."""
    from core.ui import startup_clear, print_banner
    total_boards = len(selected_boards)
    global_logs = []

    for board_idx, board in enumerate(selected_boards, 1):
        board_url   = board["url"]
        board_title = board.get("name") or board.get("title", "Unknown Board")
        is_highlights = board.get("id") == "highlights"

        is_single_pin = getattr(scraper, "get_link_type", lambda: "")() == "single"
        if is_single_pin:
            board_folder = target_root
            storage_layer.create_directory(board_folder)
        else:
            if board.get("id") == "pfp":
                board_folder = target_root / profile_name
                storage_layer.create_directory(board_folder)
            else:
                board_folder = target_root / profile_name / board_title
                storage_layer.create_directory(board_folder)

                if not is_highlights:
                    zine_dir = board_folder / ".zine"
                    storage_layer.create_directory(zine_dir)
                    meta_path = zine_dir / "metadata.json"
                    if not meta_path.exists():
                        metadata = {
                            "board_name": board_title,
                            "board_id": board.get("id") or "Unknown",
                            "profile_name": profile_name,
                            "source": "Instagram",
                            "url": board_url,
                            "total_pins": board.get("pin_count") or "Unknown",
                            "description": board.get("description") or "",
                        }
                        try:
                            storage_layer.write_file(meta_path, json.dumps(metadata, indent=2, ensure_ascii=False))
                        except Exception as e:
                            logger.error(f"Failed to write metadata for board {board_title}: {e}")

        # Initial state setup
        state: Dict[str, Any] = {
            "board_idx":       board_idx,
            "total_boards":    total_boards,
            "board_title":     board_title,
            "location":        str(board_folder.resolve()),
            "status":          "extracting",
            "pins_total":      0,
            "pins_existing":   0,
            "pins_downloaded": 0,
            "current_pin":     "",
            "progress":        None,
            "progress_bar":    None,
            "task_id":         None,
        }

        # Show live "extracting" spinner while engine scrapes
        with Live(render_progress_tree(state), console=console, refresh_per_second=10, transient=True) as live:
            live_active = [True]
            import threading

            def refresh_extract():
                import time as _t
                while live_active[0]:
                    try:
                        live.update(render_progress_tree(state))
                    except Exception:
                        pass
                    _t.sleep(0.1)

            threading.Thread(target=refresh_extract, daemon=True).start()

            try:
                meta, pins = scraper.engine.get_board_pins(board_url)
            except Exception as e:
                logger.error(f"Error extracting pins: {e}")
                pins = []
                meta = {}

            live_active[0] = False

        # Download profile picture to the creator's root directory if found
        if meta.get("profile_picture") and not is_single_pin:
            pfp_url = meta["profile_picture"]
            creator_root = target_root / profile_name
            storage_layer.create_directory(creator_root)
            pfp_path = creator_root / "profile_picture.jpg"
            if not pfp_path.exists():
                try:
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                    r = scraper.session.get(pfp_url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        with open(pfp_path, "wb") as f:
                            f.write(r.content)
                        global_logs.append(f"  [success]✔ Downloaded Profile Picture for {profile_name}[/success]")
                except Exception as e:
                    logger.debug(f"Failed to download profile picture: {e}")
            else:
                global_logs.append(f"  [unselected]Profile Picture already exists for {profile_name}[/unselected]")

        if not pins:
            state["status"] = "finished"
            console.print(render_progress_tree(state))
            time.sleep(1)
            continue

        # ── Story Highlights: grouped subfolder download ──────────────────
        if is_highlights:
            _download_highlights(
                pins, board_folder, board_url, profile_name,
                scraper, tracker, state, storage_layer
            )
            continue

        # ── Normal board download ─────────────────────────────────────────
        state["pins_total"] = len(pins)
        verified_ids = verify_pins(board_folder, pins, board_url, tracker)
        state["pins_existing"] = len(verified_ids)
        state["status"] = "downloading"

        startup_clear()
        print_banner()
        console.print(f"[menu]Title[/menu]        : [title]Instagram[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        if total_boards > 1:
            console.print(f"[menu]Section[/menu]      : [info]{board_title} ({board_idx}/{total_boards})[/info]")
        else:
            console.print(f"[menu]Section[/menu]      : [info]{board_title}[/info]")
        console.print(f"[menu]Found[/menu]        : [info]{len(pins)} Media[/info]\n")

        for pin in pins:
            # Dynamic routing: ensure strict isolation regardless of API overlaps
            actual_folder = board_folder
            if pin.get("is_reel") is True:
                actual_folder = target_root / profile_name / "Reels Tab"
            elif pin.get("is_reel") is False:
                actual_folder = target_root / profile_name / "Main Feed (Posts)"
            
            if not actual_folder.exists():
                storage_layer.create_directory(actual_folder)
                
            _download_pin(pin, actual_folder, board_url, scraper, tracker, state, storage_layer, console)

        state["status"] = "finished"
        console.print(render_progress_tree(state))
        time.sleep(0.5)

    console.print(f"\n[success]✦[/success] All Selected Boards Finished\n")
    for log_msg in global_logs:
        console.print(log_msg)
    if global_logs:
        console.print()
    console.input("[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
