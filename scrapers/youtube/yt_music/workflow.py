import os
import sys
import time
import logging
import threading
from pathlib import Path
from typing import Optional, Tuple, List, Any, Dict

from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn

from core.ui import (
    console, startup_clear, print_banner, active_status, set_active_live,
    align_header, MbpsColumn, MinimalPulseBar, CustomDownloadColumn,
    CustomTimeRemainingColumn, get_theme_input_ansi
)
from core.cache import save_url_to_file

from .location import get_save_path
from .verification import verify_videos
from .progress import render_metadata_tree
from .tui import get_track_selection

logger = logging.getLogger(__name__)
_LIVE_INSTANCE = None
TRACK_DELAY = 0.5

def run_workflow(
    url: str,
    tracker: Any,
    location_manager: Any,
    scraper: Any,
    batch_path: Optional[Path] = None,
    is_batch: bool = False,
    custom_thumb_path: Optional[Path] = None
):
    """
    Main orchestration workflow for YouTube Music.
    Adopts the authentic Zine & YouTube dynamic Tree logging system with 30MB pulse progress bars.
    """
    metadata_error = None
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
            title = metadata.get("Title") or metadata.get("Album") or metadata.get("Channel/Series", "YouTube Music")
            scraper.metadata = metadata
            scraper.title = title
        except Exception as e:
            metadata_error = e

    if metadata_error:
        if not is_batch:
            startup_clear()
            print_banner()
            from rich.panel import Panel
            from rich.align import Align
            from rich.text import Text
            
            message = Text()
            message.append("\n  YouTube Music Extraction Failed  \n\n", style="error")
            message.append("The scraper was unable to retrieve metadata for this URL.\n", style="info")
            message.append(f"Error: {metadata_error}\n\n", style="warning")
            message.append("Please verify that the track, album, or playlist is public and accessible.\n", style="success")
            
            panel = Panel(
                Align.center(message),
                border_style="error",
                padding=(1, 2)
            )
            console.print("")
            console.print(panel)
            if sys.stdin.isatty():
                console.input("\n[info]Press Enter to return...[/info]")
        else:
            console.print(f"[error]Skipping {url}: {metadata_error}[/error]")
            time.sleep(1.5)
        return

    target_path = get_save_path(url, scraper, is_batch, batch_path, location_manager=location_manager)
    if not target_path:
        return

    folder = target_path
    location_manager.create_directory(folder)
    save_url_to_file(url, title, silent=False)

    artist = metadata.get("Artist") or "Unknown Artist"
    album = metadata.get("Album") or ""
    link_type = getattr(scraper, "get_link_type", lambda: "")()
    is_vacuum = getattr(scraper, "is_playlist", False) or link_type in ["playlist", "album", "artist"] or len(videos) > 1

    first_track_id = videos[0].get("id") if videos else None

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    poop_dir = project_root / "💩"
    poop_dir.mkdir(parents=True, exist_ok=True)

    # In Vacuum mode: save cover.jpg directly into album directory
    # In Quick Grab: only download cover to temporary 💩 directory for embedding into FLAC (never pollute Quick grab folder)
    if is_vacuum:
        cover_file = scraper.engine.download_cover_art(
            folder,
            thumbnails=info.get("thumbnails"),
            track_id=first_track_id,
            cover_url=metadata.get("Thumbnail")
        )
    else:
        cover_file = scraper.engine.download_cover_art(
            poop_dir,
            thumbnails=info.get("thumbnails"),
            track_id=first_track_id,
            cover_url=metadata.get("Thumbnail")
        )

    verified_ids = verify_videos(folder, videos, "flac", tracker, scraper.url)

    menu_label = "Batch" if is_batch else ("Vacuum" if is_vacuum else "Quick Grab")

    # Standard YouTube / Zine Header & Metadata Tree
    startup_clear()
    print_banner()
    console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
    console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
    console.print(f"[menu]{'Artist':<12}:[/menu] [title]{artist}[/title]")
    if album and album != "Single":
        console.print(f"[menu]{'Album':<12}:[/menu] [title]{album}[/title]")
    console.print(f"[menu]{'Type':<12}:[/menu] [site]Song (FLAC Lossless)[/site]")

    root_tree = render_metadata_tree(title, folder, metadata, len(verified_ids), custom_thumb_path or cover_file, is_vacuum)
    console.print(root_tree)
    console.print("")

    if not videos:
        console.print(f"[warning]No tracks found for {url}[/warning]")
        return

    choice, selected_videos = get_track_selection(videos, is_vacuum=is_vacuum, is_batch=is_batch)
    if choice == "BACK":
        return

    # Handle custom thumbnail selection
    custom_thumb = custom_thumb_path or cover_file
    if choice == "CUSTOM_THUMB" and not is_batch:
        from core.ui import theme_input
        custom_t = theme_input("[info]Enter path to custom cover image: [/info]").strip()
        custom_t = custom_t.strip("'\"")
        if custom_t and Path(custom_t).exists():
            custom_thumb = Path(custom_t)

    # Clean previous part files if any
    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(folder, videos, tracker, scraper.url)
    except Exception:
        pass

    completed_history = []

    # Whistleblower TUI reconstruction hook for network drops
    from butler.whistleblower import set_tui_callback
    def tui_reconstruct():
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Artist':<12}:[/menu] [title]{artist}[/title]")
        if album and album != "Single":
            console.print(f"[menu]{'Album':<12}:[/menu] [title]{album}[/title]")
        console.print(f"[menu]{'Type':<12}:[/menu] [site]Song (FLAC Lossless)[/site]")
        console.print(root_tree)
        console.print("")
        for hist in completed_history:
            console.print(hist)

        username = __import__('getpass').getuser()
        console.print(f"  [error]✘ Connection lost! I've got your back, {username}... pausing download queue.[/error]")
        console.print(f"  [success]● Connection restored, starting the engine please wait...[/success]")
        
        global _LIVE_INSTANCE
        if _LIVE_INSTANCE:
            console.print(" ")
            console.print(" ")
            try:
                if hasattr(_LIVE_INSTANCE, "_live_render"):
                    _LIVE_INSTANCE._live_render._shape = None
                _LIVE_INSTANCE.start()
            except Exception:
                pass

    set_tui_callback(tui_reconstruct)

    for track_idx, track in enumerate(selected_videos, 1):
        vid_id = str(track.get("id", ""))
        vid_title = track.get("title", f"Track {track_idx}")
        track_artist = track.get("artist") or artist
        track_album = track.get("album") or album
        track_num = track.get("track_number", track_idx) if is_vacuum else None

        # Resolve clean file path
        if hasattr(tracker, "resolve_download_path"):
            resolved_file_path, is_in_verified = tracker.resolve_download_path(folder, str(vid_id), vid_title, "flac")
        else:
            filename = f"{track_num:02d}. {vid_title}.flac" if track_num else f"{vid_title}.flac"
            resolved_file_path = folder / filename
            is_in_verified = resolved_file_path.exists()

        display_name = resolved_file_path.name

        if is_in_verified or (vid_id in verified_ids) or (vid_title in verified_ids):
            if hasattr(tracker, "mark_downloaded"):
                tracker.mark_downloaded(scraper.url, str(vid_id), vid_title)
            hist_line = f"  [unselected]File exists: {display_name}[/unselected]"
            console.print(hist_line)
            completed_history.append(hist_line)
            continue

        progress_data: Dict[str, Any] = {
            "status": "Starting...",
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "speed": 0,
            "eta": None,
            "retry": 0,
            "done": False,
            "success": False,
            "baking": False,
        }

        progress_bar = Progress(
            TextColumn("[progress.description]{task.description}"),
            MinimalPulseBar(bar_width=40),
            TaskProgressColumn(),
            CustomDownloadColumn(),
            MbpsColumn(),
            CustomTimeRemainingColumn(),
            transient=False,
        )
        task_id = progress_bar.add_task("Downloading", total=None)

        def render_video_tree() -> Tree:
            tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
            tree.add(align_header("Current", vid_title))
            tree.add(align_header("Retry", f"[warning]{progress_data['retry']}[/warning]"))
            res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

            if not progress_data["done"]:
                total = progress_data["total_bytes"]
                downloaded = progress_data["downloaded_bytes"]
                is_small_file = (total < 30 * 1024 * 1024) if total > 0 else (downloaded < 30 * 1024 * 1024)

                if progress_data.get("baking"):
                    blink_state = int(time.time() * 6) % 3
                    if blink_state == 0:
                        ball_style = "success"
                    elif blink_state == 1:
                        ball_style = "warning"
                    else:
                        ball_style = "unselected"

                    status_text = "Almost done with baking..." if not is_small_file else "Baking metadata & lyrics..."
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] {status_text}")
                else:
                    if is_small_file:
                        blink_state = int(time.time() * 3) % 2
                        ball_style = "warning" if blink_state == 0 else "unselected"
                        res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
                    else:
                        progress_bar.update(
                            task_id,
                            total=total or None,
                            completed=progress_data["downloaded_bytes"],
                            description=progress_data["status"],
                            speed=progress_data.get("speed", 0),
                            eta=progress_data.get("eta"),
                        )
                        res_branch.add(progress_bar)
            else:
                success = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text = "Complete" if success else "Failed"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")

            return tree

        def yt_dlp_hook(d):
            if d.get("status") == "downloading":
                progress_data["status"] = "Downloading"
                downloaded = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                progress_data["downloaded_bytes"] = downloaded
                progress_data["total_bytes"] = total
                progress_data["speed"] = d.get("speed", 0)
                progress_data["eta"] = d.get("eta", None)
            elif d.get("status") == "finished":
                progress_data["status"] = "Baking metadata & lyrics..."
                progress_data["baking"] = True

        with Live(render_video_tree(), console=console, refresh_per_second=10, transient=True) as live:
            _LIVE_INSTANCE = live
            set_active_live(live)

            live_active = [True]
            def refresh_loop():
                while live_active[0]:
                    try:
                        live.update(render_video_tree())
                    except Exception:
                        pass
                    time.sleep(0.1)

            ref_t = threading.Thread(target=refresh_loop, daemon=True)
            ref_t.start()

            for attempt in range(1, 4):
                if attempt > 1:
                    progress_data["retry"] = attempt - 1
                    time.sleep(2)

                try:
                    success = scraper.engine.download_video(
                        url=track["url"],
                        output_dir=folder,
                        progress_hook=yt_dlp_hook,
                        is_audio=True,
                        custom_thumbnail=custom_thumb,
                        fixed_title=vid_title,
                        fixed_artist=track_artist,
                        fixed_album=track_album,
                        track_number=track_num,
                        track_id=vid_id,
                        attempt=attempt
                    )

                    if success:
                        if tracker and hasattr(tracker, "mark_downloaded"):
                            try:
                                tracker.mark_downloaded(scraper.url, str(vid_id), vid_title)
                            except Exception:
                                pass
                        verified_ids.add(vid_id)
                        progress_data["success"] = True
                        progress_data["done"] = True
                        break
                except Exception as e:
                    progress_data["status"] = str(e)
                    from core.video_engine import handle_internet_loss
                    if not handle_internet_loss():
                        break

            progress_data["done"] = True
            live_active[0] = False
            try:
                live.update(render_video_tree())
            except Exception:
                pass
            time.sleep(0.2)

        _LIVE_INSTANCE = None
        set_active_live(None)

        res_color = "success" if progress_data.get("success") else "error"
        hist_log = f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]"
        console.print(hist_log)
        completed_history.append(hist_log)

        # Global Revolt shutdown check
        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT <= 0:
                ui.clean_exit_revolt()
            else:
                ui._REVOLT_LIMIT -= 1

        time.sleep(0.1)

    # Clean up temporary cover from 💩 if created for Quick Grab
    if not is_vacuum and cover_file and cover_file.parent == poop_dir:
        try:
            cover_file.unlink(missing_ok=True)
        except Exception:
            pass

    console.print("")
    if not is_batch and sys.stdin.isatty():
        console.input("[info]Press Enter to return...[/info]")
