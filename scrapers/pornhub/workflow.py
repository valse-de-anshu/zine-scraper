"""
scrapers/pornhub/workflow.py
-----------------------------
PornHub download orchestrator.

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
    MinimalPulseBar,
    console, align_header, MbpsColumn,
    CustomDownloadColumn, CustomTimeRemainingColumn,
    set_active_live, get_theme_input_ansi, active_status,
)
from core.history import HistoryLayer
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn

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
    Main download orchestrator for PornHub.

    target_root  → e.g. .../Zine/Vacuum/pornhub  or .../Zine/Quick grab/pornhub
    creator_root → e.g. .../Vacuum/pornhub/miulio  (resolved collision-free)
    sub_folder   → same as creator_root for vacuum; target_root for quick grab single files
    """
    from core.paths import resolve_folder_collision

    title = metadata.get("Channel/Series", "Unknown")
    # Use the safe filesystem name (apostrophes/entities cleaned) if available
    folder_name = getattr(scraper, '_folder_name', None) or title
    platform_id = str(info.get("id") or info.get("uploader_id") or scraper.url)

    if is_vacuum:
        # Vacuum: create creator subfolder, then a Videos/ subfolder inside it
        creator_root = resolve_folder_collision(target_root, folder_name, platform_id)
        creator_root.mkdir(parents=True, exist_ok=True)
        sub_folder = creator_root / "Videos"
        sub_folder.mkdir(parents=True, exist_ok=True)
    else:
        # Quick grab: dump directly into target_root, no creator subfolder
        creator_root = target_root
        sub_folder = target_root
        sub_folder.mkdir(parents=True, exist_ok=True)

    is_quick_grab = not is_vacuum

    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return

    # ── Save metadata.json + cover.png (Vacuum only) ─────────────────────
    if is_vacuum:
        try:
            avatar_url = metadata.get("Avatar URL") or ""
            scraper.engine.save_metadata(
                root_dir=creator_root,
                info=info,
                source="PornHub",
                model_name=title,
                avatar_url=avatar_url,
                videos=videos,
                skip_cover=False,
            )
        except Exception as e:
            logger.error(f"Failed to save PornHub metadata/cover: {e}")

    # ── Part cleaner (remove leftover .part / format-chunk files) ────────
    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(sub_folder, videos, tracker, scraper.url)
    except Exception as e:
        logger.error(f"Failed to run butler part cleaner: {e}")

    # ── Chronological numbering (oldest = 1, newest = last) ─────────────
    # yt-dlp returns PH playlists newest-first. After enrichment upload_date
    # may be populated — sort ascending if available, else just reverse the list.
    # Always cast to str since yt-dlp can return date as int OR str.
    if len(videos) > 1:
        have_dates = [v for v in videos if v.get("upload_date")]
        if have_dates and len(have_dates) == len(videos):
            try:
                videos.sort(key=lambda v: str(v.get("upload_date") or ""))
            except Exception:
                videos.reverse()  # fallback: PH is newest-first → reverse = oldest first
        else:
            # No/partial dates — PH is newest-first, so reverse → oldest first
            videos.reverse()

    for idx, video in enumerate(videos, 1):
        raw_title = video.get("title") or f"Video {idx}"
        # Strip any existing leading "N. " prefix to avoid double-numbering on resume
        if raw_title and raw_title[0:1].isdigit() and ". " in raw_title[:6]:
            raw_title = raw_title.split(". ", 1)[-1]
        video["title"] = f"{idx}. {raw_title}"


    ext = "mp4"
    verified_ids = verify_videos(sub_folder, videos, ext, scraper.url, tracker)

    # ── Metadata summary tree ────────────────────────────────────────────
    root_tree = render_metadata_tree(
        title, sub_folder, metadata, len(verified_ids), is_vacuum, creator_root
    )
    console.print(root_tree)
    console.print("")

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
    # Keep a persistent outer Live so the Revolt Ctrl+R listener is never
    # deaf between videos (the listener requires _LIVE_INSTANCE != None).
    from rich.text import Text
    console.print(" ")
    console.print(" ")

    with Live(Text(""), console=console, refresh_per_second=4, transient=False) as _outer_live:
        set_active_live(_outer_live)

        for idx, video in enumerate(videos, 1):
            vid_id    = str(video.get("id") or idx)
            vid_title = video.get("title") or f"Video {idx}"
            vid_url   = video.get("url") or ""

            if not vid_url:
                logger.warning(f"Skipping video {idx} — no URL")
                continue

            # Resolve target file path (collision-free title → id)
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

            progress_bar = Progress(
                MinimalPulseBar(bar_width=50),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                transient=False,
            )
            task_id = progress_bar.add_task("Downloading", total=None)

            def render_video_tree() -> Tree:
                tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
                tree.add(align_header("Current", vid_title))
                tree.add(align_header("Retry",   f"[warning]{progress_data['retry']}[/warning]"))
                res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

                if not progress_data["done"]:
                    total      = progress_data["total_bytes"]
                    downloaded = progress_data["downloaded_bytes"]

                    if progress_data.get("baking"):
                        blink_state = int(time.time() * 6) % 3
                        ball_style  = ["success", "warning", "unselected"][blink_state]
                        res_branch.add(f"[{ball_style}]●[/{ball_style}] Almost done with baking...")
                    else:
                        progress_bar.update(
                            task_id,
                            total       = total or None,
                            completed   = downloaded,
                            description = progress_data["status"],
                            speed       = progress_data.get("speed", 0),
                            eta         = progress_data.get("eta"),
                        )
                        res_branch.add(progress_bar)
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
                    downloaded_now                    = d.get("downloaded_bytes", 0)
                    total_now                         = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    completed_files[filename]         = {"downloaded": downloaded_now, "total": total_now}
                    progress_data["downloaded_bytes"] = sum(f["downloaded"] for f in completed_files.values())
                    progress_data["total_bytes"]      = sum(f["total"]      for f in completed_files.values())
                    progress_data["speed"]            = d.get("speed", 0)
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
                            success = scraper.engine.download_pornhub_video(
                                vid_url,
                                sub_folder,
                                active_hook,
                                quality=quality,
                                fixed_title=resolved_file_path.stem,
                            )
                        except Exception as download_exc:
                            err_str = str(download_exc).lower()
                            if "403" in err_str or "forbidden" in err_str:
                                logger.warning(f"403 Forbidden for {vid_url} — skipping")
                                progress_data["done"]    = True
                                progress_data["success"] = False
                                success = False
                                break
                            raise
                        finally:
                            live_active[0] = False

                    # Restore outer live so Revolt listener stays active between videos
                    set_active_live(_outer_live)

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
                set_active_live(_outer_live)
                ui._REVOLT_LISTENER_ACTIVE = False

            if download_error:
                console.print(f"[error]Download failed: {download_error}[/error]")

            res_color = "success" if progress_data.get("success") else "error"
            hist_log  = f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]"
            console.print(hist_log)
            completed_history.append(hist_log)
            time.sleep(0.3)

            # ── Revolt shutdown check (per-video, after each download) ────────
            if ui._REVOLT_ACTIVE:
                if ui._REVOLT_LIMIT == 0:
                    console.print("[warning]● Revolt shutdown triggered. Exiting cleanly...[/warning]\n")
                    sys.exit(0)
                else:
                    ui._REVOLT_LIMIT -= 1

    set_active_live(None)
    console.print(f"\n[success]✦[/success] Done\n")
