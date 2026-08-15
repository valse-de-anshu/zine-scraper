"""
scrapers/hentaimama/workflow.py
-----------------------------
Hentaimama download orchestrator.

Modes:
  Vacuum    → model/channel URL → scrape ALL videos, save metadata.json, cover.png, .zine/history.json
  Quick grab → single video URL → download video only, no metadata, no folder creation for creator

Key guarantees:
  - Two-step verification (history + disk) before every download to prevent re-downloads
  - Connects to butler/part_cleaner.py to handle leftover .part/.f*.mp4 chunks
  - Never creates a duplicate folder for the same creator (resolve_folder_collision)
  - No hardcoded paths (PathAuthority handles everything)
  - Geo-block detection surfaces a clean error message to the user
"""

import time
import logging
import sys
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.ui import (
    console, align_header, MbpsColumn,
    CustomDownloadColumn, CustomTimeRemainingColumn,
    set_active_live, get_theme_input_ansi, active_status,
)
from core.history import HistoryLayer
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn

from .verification import verify_videos
from .progress import render_metadata_tree

logger = logging.getLogger(__name__)


def run_workflow(
    url: str,
    tracker: HistoryLayer,
    target_root: Path,
    metadata: Dict[str, Any],
    videos: List[Dict[str, Any]],
    info: Dict[str, Any],
    scraper: Any,
    quality: str = "1080p",
    is_vacuum: bool = False,
    is_batch_mode: bool = False,
):
    """
    Main download orchestrator for Hentaimama.

    target_root  → e.g. .../Zine/Vacuum/hentaimama  or .../Zine/Quick grab/hentaimama
    creator_root → e.g. .../Vacuum/hentaimama/miulio  (resolved collision-free)
    sub_folder   → same as creator_root for vacuum; target_root for quick grab single files
    """
    from core.paths import resolve_folder_collision

    title = metadata.get("Channel/Series", "Unknown")
    # Use the safe filesystem name (apostrophes/entities cleaned) if available
    folder_name = getattr(scraper, '_folder_name', None) or title
    platform_id = str(info.get("id") or info.get("uploader_id") or scraper.url)

    if is_vacuum:
        # Vacuum: create creator subfolder using SAFE folder name (no HTML entities, no illegal chars)
        creator_root = resolve_folder_collision(target_root, folder_name, platform_id)
        creator_root.mkdir(parents=True, exist_ok=True)
        sub_folder = creator_root
    else:
        # Quick grab: dump directly into target_root, no creator subfolder
        creator_root = target_root
        sub_folder = target_root
        sub_folder.mkdir(parents=True, exist_ok=True)

    is_quick_grab = not is_vacuum

    # ── Save metadata.json + cover.png (Vacuum only) ─────────────────────
    if is_vacuum:
        try:
            avatar_url = metadata.get("Avatar URL") or ""
            scraper.engine.save_metadata(
                root_dir=creator_root,
                info=info,
                source="Hentaimama",
                model_name=title,
                avatar_url=avatar_url,
                videos=videos,
                skip_cover=False,
                custom_metadata=metadata,
            )
        except Exception as e:
            logger.error(f"Failed to save Hentaimama metadata/cover: {e}")

    # ── Part cleaner (remove leftover .part / format-chunk files) ────────
    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(sub_folder, videos, tracker, scraper.url)
    except Exception as e:
        logger.error(f"Failed to run butler part cleaner: {e}")

    # ── Two-step verification (history + disk) ───────────────────────────
    ext = "mp4"
    verified_ids = verify_videos(sub_folder, videos, ext, scraper.url, tracker)

    # ── Metadata summary tree ────────────────────────────────────────────
    root_tree = render_metadata_tree(
        title, sub_folder, metadata, len(verified_ids), is_vacuum, creator_root
    )
    console.print(root_tree)
    console.print("")

    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return

    # ── TUI Reconstructor (for internet reconnect) ────────────────────────
    from butler.whistleblower import set_tui_callback
    completed_history = []

    def tui_reconstruct():
        from core.ui import startup_clear, print_banner
        import core.ui as ui_module
        startup_clear()
        print_banner()

        menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_vacuum else "Quick Grab")
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Channel':<12}:[/menu] [title]{title}[/title]")
        console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")
        console.print(root_tree)
        console.print("")

        for hist in completed_history:
            console.print(hist)

        username = __import__("getpass").getuser()
        console.print(f"  [error]✘ Connection lost! I've got your back, {username}... pausing download queue.[/error]")
        console.print(f"  [success]● Connection restored, starting the engine please wait...[/success]")

        if ui_module._LIVE_INSTANCE:
            console.print(" ")
            try:
                if hasattr(ui_module._LIVE_INSTANCE, "_live_render"):
                    ui_module._LIVE_INSTANCE._live_render._shape = None
                ui_module._LIVE_INSTANCE.start()
            except Exception:
                pass

    set_tui_callback(tui_reconstruct)

    # ── Main download loop ────────────────────────────────────────────────
    console.print(" ")
    console.print(" ")

    for idx, video in enumerate(videos, 1):
        vid_id    = str(video.get("id") or idx)
        vid_title = video.get("title") or f"Video {idx}"
        vid_url   = video.get("url") or ""
        import re
        clean_title = "".join(c for c in vid_title if c.isalnum() or c in " .-_()'")
        clean_title = re.sub(r'[<>:"/\\|?*]', '', clean_title).strip() or vid_id

        if not vid_url:
            logger.warning(f"Skipping video {idx} — no URL")
            continue

        # Resolve target file path (collision-free title → id)
        # ── Step 1 + 2 check: already done? ─────────────────────────────
        if is_vacuum:
            if getattr(scraper, "franchise_structure", "flat") == "nested":
                sub_folder = creator_root / clean_title
                sub_folder.mkdir(parents=True, exist_ok=True)
            else:
                sub_folder = creator_root
                
        resolved_file_path, is_downloaded = tracker.resolve_download_path(
            sub_folder, vid_id, vid_title, ext,
            date_str=video.get("upload_date")
        )
        display_name = resolved_file_path.name

        # ── Step 1 + 2 check: already done? ─────────────────────────────
        if is_downloaded:
            tracker.mark_downloaded(scraper.url, vid_id)
            hist_log = f"  [unselected]●[/unselected] [unselected]File exists: {display_name}[/unselected]"
            console.print(hist_log)
            completed_history.append(hist_log)
            continue

        # ── Progress data ────────────────────────────────────────────────
        progress_data = {
            "total_bytes":      0,
            "downloaded_bytes": 0,
            "done":    False,
            "success": False,
            "status":  "Starting...",
            "baking":  False,
            "speed":   0,
            "eta":     None,
            "retry":   0,
        }



        def render_video_tree() -> Tree:
            tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
            tree.add(align_header("Current", vid_title))
            if is_vacuum:
                tree.add(align_header("Folder", f"[site]{sub_folder.name}[/site]"))
            tree.add(align_header("Retry",   f"[warning]{progress_data['retry']}[/warning]"))
            res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

            if not progress_data["done"]:
                total      = progress_data["total_bytes"]
                downloaded = min(progress_data["downloaded_bytes"], total) if total > 0 else progress_data["downloaded_bytes"]
                is_small_file = (total < 30 * 1024 * 1024) if total > 0 else (downloaded < 30 * 1024 * 1024)
                
                is_100_percent = (total > 0 and downloaded >= total)
                is_90_percent = (total > 0 and downloaded >= total * 0.9)

                if progress_data.get("baking") or is_100_percent:
                    blink_state = int(time.time() * 6) % 3
                    if blink_state == 0:
                        ball_style = "success"
                    elif blink_state == 1:
                        ball_style = "white"
                    else:
                        ball_style = "unselected"
                    
                    status_text = "Almost done with baking..." if not is_small_file else "Baking metadata..."
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] {status_text}")
                elif is_90_percent:
                    blink_state = int(time.time() * 6) % 3
                    if blink_state == 0:
                        ball_style = "success"
                    elif blink_state == 1:
                        ball_style = "white"
                    else:
                        ball_style = "unselected"
                    
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading (Almost done)...")
                else:
                    blink_state = int(time.time() * 3) % 2
                    ball_style = "warning" if blink_state == 0 else "unselected"
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
            else:
                success   = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text  = "Complete" if success else "Failed"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")

            return tree

        # ── yt-dlp progress hook ─────────────────────────────────────────
        completed_files: dict = {}

        def yt_dlp_hook(d):
            filename = d.get("filename")
            if d["status"] == "downloading":
                progress_data["status"]           = "Downloading"
                downloaded_now                    = d.get("downloaded_bytes") or 0
                total_now                         = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                completed_files[filename]         = {"downloaded": downloaded_now, "total": total_now}
                progress_data["downloaded_bytes"] = sum((f.get("downloaded") or 0) for f in completed_files.values())
                progress_data["total_bytes"]      = sum((f.get("total") or 0) for f in completed_files.values())
                progress_data["speed"]            = d.get("speed") or 0
                progress_data["eta"]              = d.get("eta")

            elif d["status"] == "finished":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if filename not in completed_files:
                    completed_files[filename] = {"downloaded": total, "total": total}
                else:
                    if completed_files[filename]["total"] == 0:
                        completed_files[filename]["total"] = total
                    completed_files[filename]["downloaded"] = completed_files[filename]["total"]
                progress_data["downloaded_bytes"] = sum(f["downloaded"] for f in completed_files.values())
                progress_data["total_bytes"]      = sum(f["total"]      for f in completed_files.values())
                progress_data["speed"]  = 0
                progress_data["eta"]    = 0
                progress_data["status"] = "Almost done with baking..."
                progress_data["baking"] = True

            elif d["status"] == "error":
                progress_data["status"] = "Error"

        # ── Download with retry loop ─────────────────────────────────────
        download_error = None
        import core.ui as ui
        ui._REVOLT_LISTENER_ACTIVE = True

        try:
            attempt = 0
            while True:
                progress_data["retry"] = attempt
                if attempt > 0:
                    progress_data["status"]  = "Resuming..."
                    progress_data["baking"]  = False
                    progress_data["done"]    = False
                    progress_data["success"] = False
                    completed_files.clear()

                with Live(render_video_tree(), console=console, refresh_per_second=10, transient=True) as live:
                    set_active_live(live)

                    live_active = [True]

                    def refresh_loop():
                        while live_active[0]:
                            try:
                                live.update(render_video_tree())
                            except Exception:
                                pass
                            time.sleep(0.1)

                    refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
                    refresh_thread.start()

                    def active_hook(d):
                        yt_dlp_hook(d)
                        try:
                            live.update(render_video_tree())
                        except Exception:
                            pass

                    try:
                        engine = scraper.engine
                        success = engine.download_hentaimama_video(
                            url=vid_url,
                            output_dir=sub_folder,
                            progress_hook=active_hook,
                            quality=quality,
                            fixed_title=resolved_file_path.stem
                        )
                    finally:
                        live_active[0] = False

                set_active_live(None)

                if success:
                    tracker.mark_downloaded(scraper.url, vid_id)
                    progress_data["success"] = True
                    break
                else:
                    from core.video_engine import handle_internet_loss
                    if not handle_internet_loss():
                        break
                attempt += 1

        except (Exception, KeyboardInterrupt) as e:
            progress_data["done"] = True
            if isinstance(e, KeyboardInterrupt):
                raise
            download_error = e
        finally:
            progress_data["done"] = True
            set_active_live(None)
            ui._REVOLT_LISTENER_ACTIVE = False

        if download_error:
            console.print(f"[error]Download failed: {download_error}[/error]")
            import traceback
            traceback.print_exc()

        res_color = "success" if progress_data.get("success") else "error"
        hist_log  = f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]"
        console.print(hist_log)
        completed_history.append(hist_log)
        time.sleep(0.3)

        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT == 0:
                console.print("[warning]● Revolt shutdown triggered. Exiting cleanly...[/warning]\n")
                sys.exit(0)
            else:
                ui._REVOLT_LIMIT -= 1

    console.print(f"\n[success]✦[/success] Done\n")
