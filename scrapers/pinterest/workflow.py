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

def run_workflow(
    selected_boards: List[Dict[str, Any]],
    tracker: HistoryLayer,
    scraper: Any,
    target_root: Path,
    storage_layer: StorageLayer,
    profile_name: str
):
    """Download loop orchestration workflow for Pinterest boards."""
    from core.ui import startup_clear, print_banner
    total_boards = len(selected_boards)
    global_logs = []

    for board_idx, board in enumerate(selected_boards, 1):
        board_url   = board["url"]
        board_title = board.get("name") or board.get("title", "Unknown Board")

        is_single_pin = getattr(scraper, "get_link_type", lambda: "")() in ("single", "pin")
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

                zine_dir = board_folder / ".zine"
                storage_layer.create_directory(zine_dir)
                meta_path = zine_dir / "metadata.json"
                if not meta_path.exists():
                    metadata = {
                        "board_name": board_title,
                        "board_id": board.get("id") or "Unknown",
                        "profile_name": profile_name,
                        "source": "Pinterest",
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
            "board_idx":      board_idx,
            "total_boards":   total_boards,
            "board_title":    board_title,
            "location":       str(board_folder.resolve()),
            "status":         "extracting",
            "pins_total":     0,
            "pins_existing":  0,
            "pins_downloaded": 0,
            "current_pin":    "",
            "progress":       None,
            "progress_bar":   None,
            "task_id":        None,
        }

        # Briefly show extracting status
        with Live(render_progress_tree(state), console=console, refresh_per_second=10, transient=True) as live:
            live_active = [True]
            import threading
            def refresh_extract():
                import time
                while live_active[0]:
                    try:
                        live.update(render_progress_tree(state))
                    except Exception:
                        pass
                    time.sleep(0.1)
            threading.Thread(target=refresh_extract, daemon=True).start()

            try:
                if is_single_pin:
                    pin_info = scraper.engine.get_pin_info(board_url)
                    meta = {"Title": pin_info.get("title", "Pinterest Pin")}
                    pins = [pin_info] if pin_info else []
                else:
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
                    import requests
                    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                    r = requests.get(pfp_url, headers=headers, timeout=10)
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

        state["pins_total"] = len(pins)
        verified_ids = verify_pins(board_folder, pins, board_url, tracker)
        state["pins_existing"] = len(verified_ids)
        state["status"] = "downloading"

        startup_clear()
        print_banner()
        console.print(f"[menu]Title[/menu]        : [title]Pinterest[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        if total_boards > 1:
            console.print(f"[menu]Board[/menu]        : [info]{board_title} ({board_idx}/{total_boards})[/info]")
        else:
            console.print(f"[menu]Board[/menu]        : [info]{board_title}[/info]")
        console.print(f"[menu]Found[/menu]        : [info]{len(pins)} Media[/info]\n")

        for idx, pin in enumerate(pins, 1):
            pin_id    = pin["id"]
            pin_title = pin["title"]
            direct_url = pin.get("direct_url") or ""
            pin_page_url = pin.get("url", "")

            # Skip pins with no usable URL
            if not direct_url and not pin_page_url:
                continue

            # For both videos and images, we want to use the direct_url we extracted
            is_video = pin.get("is_video", False)
            pin_url = direct_url if direct_url else pin_page_url

            clean_title = "".join([c for c in pin_title if c.isalnum() or c in " .-_()"]).strip()
            if not clean_title or clean_title.lower().startswith("pin_"):
                clean_title = f"pin_{pin_id}"
            else:
                clean_title = f"{clean_title}_{pin_id}"

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
                continue

            state["current_pin"] = filename
            state["progress"] = {
                "total_bytes":      0,
                "downloaded_bytes": 0,
                "done":    False,
                "success": False,
            }

            start_time = time.time()

            with Live(render_progress_tree(state), console=console, refresh_per_second=10, transient=True) as live:
                set_active_live(live)
                
                live_active = [True]
                import threading
                def refresh_loop():
                    import time
                    while live_active[0]:
                        try:
                            live.update(render_progress_tree(state))
                        except Exception:
                            pass
                        time.sleep(0.1)
                threading.Thread(target=refresh_loop, daemon=True).start()

                def stats_hook(s):
                    elapsed    = time.time() - start_time
                    downloaded = s.get("downloaded_bytes", 0)
                    total      = s.get("total_bytes", 0)
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    eta   = (total - downloaded) / speed if (speed > 0 and total > downloaded) else None
                    s_copy = s.copy()
                    s_copy.update({"speed": speed, "eta": eta})
                    state["progress"].update(s_copy)

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

        state["status"] = "finished"
        console.print(render_progress_tree(state))
        time.sleep(0.5)

    console.print(f"\n[success]✦[/success] All Selected Boards Finished\n")
    for log_msg in global_logs:
        console.print(log_msg)
    if global_logs:
        console.print()
    console.input("[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None

