import time
import requests
from pathlib import Path
from typing import Optional, Tuple, List, Any
from core.ui import console, startup_clear, print_banner, active_status
from core.cache import save_url_to_file
from core.paths import resolve_folder_collision

from .location import get_save_path
from .verification import verify_videos
from .progress import render_completion_tree

_LIVE_INSTANCE = None
CHAPTER_DELAY = 1.0

def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any, batch_path: Optional[Path] = None, is_batch: bool = False):
    is_music = getattr(scraper, "scraper_type", "manga") == "music"
    
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
            title = metadata.get("Channel/Series", "Unknown")
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_path:
        return
        
    save_url_to_file(url, title, silent=False)
    is_vacuum = getattr(scraper, "get_link_type", lambda: "")() in ["playlist", "channel"] or getattr(scraper, "is_playlist", False)
    if is_vacuum:
        folder = resolve_folder_collision(target_path, title, getattr(scraper, "domain", "ytdlp"))
        location_manager.create_directory(folder)
        try:
            cover_url = metadata.get("Thumbnail")
            scraper.engine.save_metadata(folder, info, metadata.get("Source", "Unknown"), cover_url=cover_url)
        except Exception:
            pass
    else:
        folder = target_path
        location_manager.create_directory(folder)
        
    cover_exists = any(folder.glob("cover.*"))
    
    ext_str = "flac" if is_music else "mp4"
    verified_ids = verify_videos(folder, videos, ext_str, tracker, scraper.url)
    
    startup_clear()
    print_banner()
    if is_batch:
        console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    cat_display = f"{target_path.parts[-2]} / {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
    console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
    console.print(f"[menu]Folder[/menu]       : [sexy_pink]{target_path.resolve()}[/sexy_pink]")
    console.print("")
    
    render_completion_tree(title, folder, metadata, verified_ids, cover_exists)
    
    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return
        
    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(folder, videos, tracker, scraper.url)
    except Exception:
        pass
        
    success_count = 0
    for idx, video in enumerate(videos, 1):
        vid_id = video.get("id")
        vid_title = video.get("title")
        vid_url = video.get("url")
        vid_thumb_url = video.get("thumbnail")
        
        resolved_file_path, is_in_verified = tracker.resolve_download_path(folder, str(vid_id), vid_title, ext_str)
        display_name = resolved_file_path.name
        
        if is_in_verified:
            tracker.mark_downloaded(scraper.url, str(vid_id))
            console.print(f"  [unselected]File exists: {display_name}[/unselected]")
            continue
            
        track_cover_path = None
        if vid_thumb_url:
            try:
                temp_thumb = folder / f"temp_{vid_id}.jpg"
                resp = requests.get(vid_thumb_url, timeout=10)
                resp.raise_for_status()
                temp_thumb.write_bytes(resp.content)
                track_cover_path = temp_thumb
            except Exception:
                track_cover_path = cover_path if cover_path.exists() else None
        else:
            track_cover_path = cover_path if cover_path.exists() else None
            
        progress_data = {
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "done": False,
            "success": False,
            "status": "Starting..."
        }
        
        from rich.tree import Tree
        from rich.live import Live
        from rich.progress import Progress, TextColumn, TaskProgressColumn, DownloadColumn, TimeRemainingColumn
        from core.ui import MinimalPulseBar, set_active_live
        from rich.progress import BarColumn
        from core.ui import MbpsColumn
        
        progress_bar = Progress(
            TextColumn("[progress.description]{task.description}"),
            MinimalPulseBar(bar_width=40),
            TaskProgressColumn(),
            DownloadColumn(binary_units=False),
            MbpsColumn(),
            TimeRemainingColumn(),
            transient=False,
        )
        task_id = progress_bar.add_task("Downloading", total=None)
        
        def render_video_tree() -> Tree:
            tree = Tree(f"[menu]⬢ {vid_title}[/menu]")
            res_branch = tree.add("[menu]⬡ Result[/menu]")
            if not progress_data["done"]:
                if progress_data["total_bytes"] > 0:
                    progress_bar.update(task_id, total=progress_data["total_bytes"], completed=progress_data["downloaded_bytes"])
                else:
                    progress_bar.update(task_id, completed=progress_data["downloaded_bytes"])
                res_branch.add(progress_bar)
            else:
                success = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text = "Complete" if success else f"Failed ({progress_data.get('status', 'Error')})"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
            return tree
            
        global _LIVE_INSTANCE
        with Live(render_video_tree(), console=console, refresh_per_second=12, transient=True) as live:
            _LIVE_INSTANCE = live
            from core.ui import MinimalPulseBar, set_active_live
            set_active_live(live)
            
            def stats_callback(stats):
                progress_data.update(stats)
                try:
                    live.update(render_video_tree())
                    
                except Exception:
                    pass
                    
            for attempt in range(1, 4):
                if attempt > 1:
                    time.sleep(2)
                try:
                    success = scraper.engine.download_video(
                        vid_url, folder, stats_callback,
                        is_audio=is_music,
                        custom_thumbnail=track_cover_path,
                        fixed_title=vid_title,
                        fixed_artist=None
                    )
                    if success:
                        tracker.mark_downloaded(scraper.url, str(vid_id))
                        progress_data["success"] = True
                        progress_data["done"] = True
                        success_count += 1
                        break
                except Exception as e:
                    progress_data["status"] = str(e)
                    from core.video_engine import handle_internet_loss

                    if not handle_internet_loss():
                        break
                        
            progress_data["done"] = True
            try:
                live.update(render_video_tree())
            except Exception:
                pass
                
            if track_cover_path and track_cover_path != cover_path:
                try:
                    track_cover_path.unlink()
                except Exception:
                    pass
                    
        _LIVE_INSTANCE = None
        set_active_live(None)
        
        res_color = "success" if progress_data.get("success") else "error"
        console.print(f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]")
        time.sleep(CHAPTER_DELAY)
        
    if success_count > 0:
        console.print(f"\n[success]✦[/success] Finalized: {success_count}/{len(videos)} items saved\n")
    else:
        console.print(f"\n[error]✘[/error] Failed: No items saved\n")
        
    if not is_batch:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None