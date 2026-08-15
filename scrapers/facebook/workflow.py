import sys
import re
import time
import logging
import json
from pathlib import Path
from typing import Dict, Any, List
from core.ui import (
    console, align_header, set_active_live
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from rich.live import Live
from .verification import verify_pins
from .progress import render_progress_tree

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None


def _safe_folder_name(name: str) -> str:
    """Strip characters that are illegal in directory names on any major OS."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name or "Unnamed"


def _download_item(item, board_folder, board_url, scraper, tracker, state, storage_layer, console):
    """
    Download a single Facebook media item into board_folder.
    Returns True if newly downloaded, False if skipped/failed.
    """
    import time as _time
    item_id = item["id"]
    item_title = item["title"]
    direct_url = item.get("direct_url") or ""
    item_page_url = item.get("url", "")

    if not direct_url and not item_page_url:
        return False

    is_video = item.get("is_video", False)
    item_url = item_page_url if is_video and item_page_url else (direct_url or item_page_url)

    clean_title = "".join([c for c in item_title if c.isalnum() or c in " .-_()"]).strip()
    if not clean_title:
        clean_title = f"fb_{item_id}"

    if is_video:
        ext = ".mp4"
    else:
        ext = ".jpg"  # Real extension corrected post-download by magic byte sniffing

    item_path, is_downloaded = tracker.resolve_download_path(board_folder, str(item_id), clean_title, ext)
    filename = item_path.name

    if is_downloaded:
        tracker.mark_downloaded(board_url, str(item_id))
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
            if s.get("status") == "downloading":
                state["progress"]["total_bytes"] = s.get("total_bytes") or 0
                state["progress"]["downloaded_bytes"] = s.get("downloaded_bytes") or 0

        try:
            ok = scraper.download_asset(item_url, str(item_path), stats_callback=stats_hook, is_video=is_video)
            state["progress"]["done"] = True
            state["progress"]["success"] = ok
            if ok:
                tracker.mark_downloaded(board_url, str(item_id))
                state["pins_downloaded"] += 1
                return True
            else:
                p_obj = Path(item_path)
                if p_obj.exists():
                    p_obj.unlink()
                return False
        except Exception as e:
            logger.error(f"Download failed for {item_id}: {e}")
            state["progress"]["done"] = True
            state["progress"]["success"] = False
            p_obj = Path(item_path)
            if p_obj.exists():
                p_obj.unlink()
            return False
        finally:
            live_active[0] = False
            set_active_live(None)


def run_workflow(
    boards: List[Dict[str, Any]],
    tracker: HistoryLayer,
    scraper: Any,
    target_root: Path,
    storage_layer: StorageLayer,
    profile_name: str
):
    total_boards = len(boards)

    for idx, board in enumerate(boards, start=1):
        board_url = board["url"]
        raw_board_title = board["title"]

        clean_title = _safe_folder_name(raw_board_title)
        board_folder = target_root / profile_name / clean_title
        board_folder.mkdir(parents=True, exist_ok=True)

        state = {
            "board_title": raw_board_title,
            "board_idx": idx,
            "total_boards": total_boards,
            "location": str(board_folder),
            "status": "extracting",
            "pins_total": 0,
            "pins_existing": 0,
            "pins_downloaded": 0,
            "current_pin": None,
            "progress": None,
        }

        with Live(render_progress_tree(state), console=console, refresh_per_second=10, transient=True) as live:
            set_active_live(live)
            meta, items = scraper.engine.get_board_pins(board_url)

            state["status"] = "downloading"
            state["pins_total"] = len(items)
            set_active_live(None)

        if not items:
            console.print(f"[warning]No media items found in section '{raw_board_title}'[/warning]")
            continue

        existing_ids = verify_pins(board_folder, items, board_url, tracker)
        state["pins_existing"] = len(existing_ids)

        items_to_download = [p for p in items if str(p["id"]) not in existing_ids]

        if not items_to_download:
            console.print(f"[success]All {len(items)} items in '{raw_board_title}' are already downloaded![/success]")
            continue

        for item in items_to_download:
            _download_item(item, board_folder, board_url, scraper, tracker, state, storage_layer, console)

        state["status"] = "finished"
        state["current_pin"] = None
        console.print(render_progress_tree(state))

    console.print(f"\n[success]✓ Finished processing all selected Facebook sections for {profile_name}![/success]")

    # OS System Notification Dispatch
    try:
        from butler.notify import send_os_notification
        send_os_notification(f"Facebook: {profile_name}", f"Successfully downloaded media for {profile_name}!", is_success=True)
    except Exception as e:
        logger.debug(f"Failed to send notification: {e}")

    # Enter key confirmation prompt guard (Interactive TTY only; bypassed in batch mode)
    if not getattr(scraper, "is_batch", False) and sys.stdin.isatty():
        console.input("\n[info]Download finished. Press Enter to return...[/info]")
