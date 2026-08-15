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

def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any, batch_path: Optional[Path] = None, is_batch: bool = False, custom_thumb_path: Optional[Path] = None):
    is_music = getattr(scraper, "scraper_type", "manga") == "music"
    
    metadata_error = None
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
            title = metadata.get("Channel/Series", "Unknown")
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
            message.append("\n  Metadata Extraction Failed  \n\n", style="bold #f7768e")
            message.append("The scraper was unable to retrieve information for this track.\n", style="#7dcfff")
            message.append("This typically occurs because the track is a ", style="#565f89")
            message.append("SoundCloud GO+ premium exclusive ", style="warning")
            message.append("(protected by DRM encryption), or it may be geoblocked in your region.\n\n", style="#565f89")
            message.append("Only standard, public tracks are supported.\n", style="bold #9ece6a")
            
            panel = Panel(
                Align.center(message),
                border_style="#f7768e",
                padding=(1, 2)
            )
            console.print("")
            console.print(panel)
            console.input("\n[info]Press Enter to return to the URL field...[/info]") if __import__("sys").stdin.isatty() else None
        else:
            console.print(f"[error]Skipping: {metadata_error}[/error]")
            time.sleep(1.5)
        return

    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_path:
        return
        
    save_url_to_file(url, title, silent=False)
    platform_id = str(info.get("uploader_id") or info.get("id") or scraper.url)
    is_vacuum = getattr(scraper, "get_link_type", lambda: "")() in ["playlist", "album", "artist"] or getattr(scraper, "is_playlist", False)
    if is_vacuum:
        folder = resolve_folder_collision(target_path, title, platform_id)
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
        
        # Lazy load full metadata for this specific track if the playlist didn't provide it
        if not vid_thumb_url or str(vid_title).startswith("Track "):
            try:
                import requests
                from bs4 import BeautifulSoup
                resp = requests.get(vid_url, timeout=5)
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                meta_title = soup.find('meta', property='og:title')
                if meta_title: vid_title = meta_title['content']
                
                meta_image = soup.find('meta', property='og:image')
                if meta_image: vid_thumb_url = meta_image['content']
            except Exception:
                pass

        
        resolved_file_path, is_in_verified = tracker.resolve_download_path(folder, str(vid_id), vid_title, ext_str)
        display_name = resolved_file_path.name
        
        if is_in_verified:
            tracker.mark_downloaded(scraper.url, str(vid_id))
            console.print(f"  [unselected]File exists: {display_name}[/unselected]")
            continue
            
        track_cover_path = None
        if custom_thumb_path and custom_thumb_path.exists():
            track_cover_path = custom_thumb_path
        elif vid_thumb_url:
            try:
                temp_thumb = folder / f"temp_{vid_id}.jpg"
                resp = requests.get(vid_thumb_url, timeout=10)
                resp.raise_for_status()
                temp_thumb.write_bytes(resp.content)
                track_cover_path = temp_thumb
            except Exception:
                track_cover_path = None
        else:
            track_cover_path = None
            
        progress_data = {
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "done": False,
            "success": False,
            "status": "Starting..."
        }
        
        from rich.tree import Tree
        from rich.live import Live
        from core.ui import set_active_live, align_header
        
        def render_video_tree() -> Tree:
            tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
            tree.add(align_header("Current", vid_title))
            res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

            if not progress_data["done"]:
                if progress_data.get("baking"):
                    blink_state = int(time.time() * 6) % 3
                    if blink_state == 0:
                        ball_style = "success"
                    elif blink_state == 1:
                        ball_style = "warning"
                    else:
                        ball_style = "unselected"
                    
                    status_text = "Almost done with baking..." if not progress_data.get("total_bytes") else "Baking metadata..."
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] {status_text}")
                else:
                    blink_state = int(time.time() * 3) % 2
                    ball_style = "warning" if blink_state == 0 else "unselected"
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
            else:
                success = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text = "Complete" if success else f"Failed ({progress_data.get('status', 'Error')})"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
            return tree
            
        global _LIVE_INSTANCE
        with Live(render_video_tree(), console=console, refresh_per_second=12, transient=True) as live:
            _LIVE_INSTANCE = live
            from core.ui import set_active_live
            set_active_live(live)
            
            live_active = [True]
            import threading
            def refresh_loop():
                while live_active[0]:
                    try:
                        live.update(render_video_tree())
                    except Exception:
                        pass
                    time.sleep(0.1)
                    
            refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
            refresh_thread.start()
            
            def stats_callback(stats):
                progress_data.update(stats)
                if stats.get("status") == "finished":
                    progress_data["baking"] = True
                try:
                    live.update(render_video_tree())
                except Exception:
                    pass
                    
            for attempt in range(1, 4):
                if attempt > 1:
                    time.sleep(2)
                
                # Let yt-dlp extract the real title if we only have a generic placeholder
                actual_fixed_title = None if vid_title.startswith("Track ") else vid_title
                
                try:
                    success = scraper.engine.download_video(
                        vid_url, folder, stats_callback,
                        is_audio=is_music,
                        custom_thumbnail=track_cover_path,
                        fixed_title=actual_fixed_title,
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
            live_active[0] = False
                    
        _LIVE_INSTANCE = None
        set_active_live(None)
        
        # If we let yt-dlp determine the real title dynamically, update the display name
        if actual_fixed_title is None and progress_data.get("success"):
            for f in folder.iterdir():
                if f.is_file() and f"[{vid_id}]" in f.name:
                    display_name = f.name
                    break
                    
        res_color = "success" if progress_data.get("success") else "error"
        console.print(f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]")
        time.sleep(CHAPTER_DELAY)
        
    if success_count > 0:
        console.print(f"\n[success]✦[/success] Finalized: {success_count}/{len(videos)} items saved\n")
    else:
        console.print(f"\n[error]✘[/error] Failed: No items saved\n")
        
    if not is_batch:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None