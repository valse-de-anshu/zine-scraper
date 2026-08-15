import time
import logging
import requests
from pathlib import Path
from typing import Dict, Any, List
from core.ui import (
    console, format_bytes, MbpsColumn, set_active_live,
    clear_lines, MinimalPulseBar
)
from core.cache import save_url_to_file
from core.history import HistoryLayer
from core.storage import StorageLayer
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn, DownloadColumn, TimeRemainingColumn
from .verification import verify_videos
from .progress import render_metadata_tree, custom_align

logger = logging.getLogger(__name__)
CHAPTER_DELAY = 1.0

def run_workflow(
    url: str,
    tracker: HistoryLayer,
    location_manager: StorageLayer,
    scraper: Any,
    target_path: Path,
    metadata: Dict[str, Any],
    videos: List[Dict[str, Any]],
    info: Dict[str, Any]
):
    """Orchestrates the high-level workflow download loop for Idagio tracks."""
    title = metadata.get("Channel/Series", "Unknown")
    
    try:
        save_url_to_file(url, title, silent=True)
        is_vacuum = getattr(scraper, "get_link_type", lambda: "")() in ["playlist", "album", "artist"] or getattr(scraper, "is_playlist", False)
        if is_vacuum:
            folder = target_path / title
            location_manager.create_directory(folder)
            try:
                cover_url = metadata.get("Thumbnail")
                scraper.engine.save_metadata(folder, info, metadata.get("Source", "Unknown"), cover_url=cover_url)
            except Exception as e:
                logger.error(f"Failed to save metadata/cover: {e}")
        else:
            folder = target_path
            location_manager.create_directory(folder)
        
        cover_url = metadata.get("Thumbnail")
        from urllib.parse import urlparse
        ext = Path(urlparse(cover_url).path).suffix or ".jpg" if cover_url else ".jpg"
        cover_path = folder / f"cover{ext}"
        is_music = getattr(scraper, "scraper_type", "manga") == "music"
        ext = ".flac" if is_music else ".mp4"
        
        # 2-Step Verification using decoupled verification layer
        verified_ids = verify_videos(folder, videos, ext, scraper.url, tracker, is_music)

        # Render metadata summary using progress layer
        root_tree = render_metadata_tree(title, folder, metadata, verified_ids, cover_path)
        console.print(root_tree)
        console.print("")

        if not videos:
            console.print(f"[warning]No videos found for {url}[/warning]")
            return

        success_count = 0
        for idx, video in enumerate(videos, 1):
            vid_id = video.get("id")
            vid_title = video.get("title")
            vid_url = video.get("url")
            vid_thumb_url = video.get("thumbnail")
            
            display_name = f"{vid_title}{ext}"
            is_in_verified = str(vid_id) in verified_ids
            
            if is_in_verified:
                console.print(f"  [success]●[/success] [unselected]{display_name} (Already exists)[/unselected]")
                continue

            track_cover_path = cover_path if cover_path.exists() else None

            progress_data = {
                "total_bytes": 0,
                "downloaded_bytes": 0,
                "done": False,
                "success": False,
                "status": "Starting..."
            }

            def render_video_tree() -> Tree:
                tree = Tree(f"[menu]⬢ {display_name}[/menu]")
                prog_branch = tree.add("[menu]◆ Progress[/menu]")
                prog_branch.add(custom_align("Current", f"Item {idx}"))
                prog_branch.add(custom_align("Title", vid_title))
                
                res_branch = tree.add("[menu]⬡ Result[/menu]")
                if not progress_data["done"]:
                    import time as _t
                    blink = int(_t.time() * 3) % 2
                    col = "warning" if blink == 0 else "unselected"
                    res_branch.add(f"[{col}]●[/{col}] {progress_data['status']}....")
                else:
                    success = progress_data.get("success", False)
                    res_color = "success" if success else "error"
                    res_text = "Complete" if success else "Failed"
                    res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
                return tree

            def yt_dlp_hook(d):
                if d['status'] == 'downloading':
                    progress_data['status'] = "Downloading"
                    progress_data['downloaded_bytes'] = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    if total > progress_data['total_bytes']:
                        progress_data['total_bytes'] = total
                elif d['status'] == 'finished':
                    progress_data['status'] = "Baking Metadata"
                    progress_data['downloaded_bytes'] = progress_data['total_bytes']
                elif d['status'] == 'error':
                    progress_data['status'] = "Error"
                
                pass

            with Live(get_renderable=render_video_tree, console=console, refresh_per_second=12, transient=True) as live:
                set_active_live(live)
                
                try:
                    raw_stream_url = None
                    if hasattr(scraper, "get_raw_stream_and_headers"):
                        raw_stream_url, extra_headers = scraper.get_raw_stream_and_headers(vid_url)
                        scraper.engine.headers.update(extra_headers)
                        
                    success = scraper.engine.download_video(
                        vid_url, folder, yt_dlp_hook, 
                        raw_stream_url=raw_stream_url, 
                        is_audio=is_music,
                        custom_thumbnail=track_cover_path,
                        fixed_title=vid_title,
                        fixed_artist=video.get('upload_date') if is_music else None
                    )
                    if success:
                        tracker.mark_downloaded(scraper.url, str(vid_id))
                        progress_data["success"] = True
                        success_count += 1
                except Exception as e:
                    logger.error(f"Video process error: {e}")
                finally:
                    if track_cover_path and track_cover_path != cover_path:
                        location_manager.delete_file(track_cover_path)
                    
                progress_data["done"] = True
                try:
                    live.update(render_video_tree())
                except Exception:
                    pass
            set_active_live(None)
                
            res_color = "success" if progress_data.get("success") else "error"
            console.print(f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]")
            time.sleep(CHAPTER_DELAY)

        if success_count > 0:
            console.print(f"\n[success]✦[/success] Finalized: {success_count}/{len(videos)} items saved\n")
        else:
            console.print(f"\n[error]✘[/error] Failed: No items were saved. (Possible 403 Forbidden or Network Block)\n")
        time.sleep(CHAPTER_DELAY)
        
    except Exception as e:
        console.print(f"[error]Video Extraction Failed: {e}[/error]")
