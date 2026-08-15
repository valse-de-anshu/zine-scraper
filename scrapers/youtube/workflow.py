import time
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from core.ui import (
    console, align_header, MbpsColumn, MinimalPulseBar,
    CustomDownloadColumn, CustomTimeRemainingColumn,
    set_active_live, get_theme_input_ansi, active_status
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
    mode: str,
    custom_thumb_path: Optional[Path] = None,
    quality: Optional[str] = None,
    audio_format: Optional[str] = None,
    is_multi: bool = False,
    is_batch_mode: bool = False
):
    title  = metadata.get("Channel/Series", "Unknown")
    is_music = "music" in mode
    
    is_shorts = "/shorts" in scraper.url.lower() or "/shorts" in info.get("webpage_url", "").lower()
    is_playlist_link = scraper.get_link_type() == "playlist"
    is_channel_link = scraper.get_link_type() == "channel"

    is_multi = (
        is_multi
        or metadata.get("Total Videos", 0) > 1
        or scraper.is_playlist
        or scraper.get_link_type() in ["playlist", "channel"]
        or len(videos) > 1
    )

    if not is_multi:
        folder = target_root
        sub_folder = target_root
        sub_folder.mkdir(parents=True, exist_ok=True)
    else:
        target_root_cat = target_root
        platform_id = str(info.get("id") or info.get("channel_id") or scraper.url)
        from core.paths import resolve_folder_collision
        folder = resolve_folder_collision(target_root_cat, title, platform_id)
        folder.mkdir(parents=True, exist_ok=True)

        if is_shorts:
            sub_folder = folder / "short"
        elif is_playlist_link:
            playlist_name = info.get('title') or "Unknown Playlist"
            safe_playlist_name = "".join([c for c in playlist_name if c.isalnum() or c in " .-_()"]).strip()
            if not safe_playlist_name:
                safe_playlist_name = "Unknown Playlist"
            sub_folder = folder / "playlist" / safe_playlist_name
        elif is_channel_link:
            if is_music:
                sub_folder = folder / "song"
            else:
                sub_folder = folder / "video"
        elif is_music:
            sub_folder = folder / "song"
        else:
            sub_folder = folder
            
        sub_folder.mkdir(parents=True, exist_ok=True)

    try:
        is_quick_grab = "Quick grab" in sub_folder.parts or "Quick grab" in str(sub_folder)
        if not is_quick_grab:
            skip_cover = not is_multi or bool(custom_thumb_path)
            scraper.engine.save_metadata(sub_folder, info, metadata.get("Source", "Unknown"), skip_cover=skip_cover, channel_root=folder)
    except Exception as e:
        logger.error(f"Failed to save metadata/cover: {e}")

    ext_str = audio_format.lower() if ("music" in mode and audio_format) else \
              "flac" if "music" in mode else "mp4"

    # Fetch upload dates in parallel to populate history files
    if videos:
        with active_status("[info]Fetching upload dates...[/info]", spinner="dots"):
            import requests
            import re
            from concurrent.futures import ThreadPoolExecutor
            
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            })
            
            def fetch_date(vid):
                try:
                    r = session.get(vid["url"], timeout=10)
                    if r.status_code == 200:
                        m = re.search(r'itemprop="datePublished"\s+content="([^"T]+)', r.text)
                        if m:
                            vid["upload_date"] = m.group(1)
                except Exception:
                    pass
                return vid
                
            with ThreadPoolExecutor(max_workers=10) as executor:
                videos = list(executor.map(fetch_date, videos))
              
    # Ensure chronological numbering (oldest is 1, newest is last)
    if len(videos) > 1:
        d1 = videos[0].get("upload_date") or ""
        d2 = videos[-1].get("upload_date") or ""
        if d1 and d2 and d1 > d2:
            videos.reverse()
            
    for idx, video in enumerate(videos, 1):
        video["title"] = f"{idx}. {video.get('title', f'Video {idx}')}"

    # Categorize videos into subfolders
    videos_by_folder = {}
    for video in videos:
        current_sub = sub_folder
        if is_channel_link:
            raw_url = video.get("raw_url", "").lower()
            if "/shorts" in raw_url:
                current_sub = folder / "short"
            elif is_music:
                current_sub = folder / "song"
            else:
                current_sub = folder / "video"
                
        video["_target_folder"] = current_sub
        if current_sub not in videos_by_folder:
            videos_by_folder[current_sub] = []
        videos_by_folder[current_sub].append(video)

    # Verification using decoupled verification layer per folder
    verified_ids = []
    for sf, folder_videos in videos_by_folder.items():
        sf.mkdir(parents=True, exist_ok=True)
        verified_ids.extend(verify_videos(sf, folder_videos, ext_str, scraper.url, tracker))

    # Progress tree display using progress layer
    root_tree = render_metadata_tree(title, sub_folder, metadata, len(verified_ids), custom_thumb_path, is_multi, folder)
    console.print(root_tree)
    console.print("")

    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return

    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(sub_folder, videos, tracker, scraper.url)
    except Exception as e:
        logger.error(f"Failed to run butler part cleaner: {e}")

    completed_history = []
    
    from butler.whistleblower import set_tui_callback
    def tui_reconstruct():
        from core.ui import startup_clear, print_banner
        import core.ui as ui_module
        startup_clear()
        print_banner()
        
        menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        channel_name = metadata.get('Channel/Series', 'Unknown')
        console.print(f"[menu]{'Channel':<12}:[/menu] [title]{channel_name}[/title]")
        if "Playlist" in metadata:
            console.print(f"[menu]{'Playlist':<12}:[/menu] [title]{metadata['Playlist']}[/title]")
            
        mode_options = [
            ("Video", "video"), ("Song", "music"),
            ("Custom Video with Thumbnail", "custom_video"),
            ("Custom Song with Thumbnail", "custom_music")
        ]
        mode_label = next((opt[0] for opt in mode_options if opt[1] == mode), mode)
        console.print(f"[menu]{'Type':<12}:[/menu] [site]{mode_label}[/site]")
        if quality:
            console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")
        if audio_format:
            console.print(f"[menu]{'Format':<12}:[/menu] [site]{audio_format}[/site]")
        if custom_thumb_path:
            console.print(f"[menu]{'Thumbnail':<12}:[/menu] [site]{custom_thumb_path.name}[/site]")
            
        console.print(root_tree)
        console.print("")
        
        for hist in completed_history:
            console.print(hist)
            
        username = __import__('getpass').getuser()
        console.print(f"  [error]✘ Connection lost! I've got your back, {username}... pausing download queue.[/error]")
        console.print(f"  [success]● Connection restored, starting the engine please wait...[/success]")
        
        if ui_module._LIVE_INSTANCE:
            console.print(" ")
            console.print(" ")
            try:
                if hasattr(ui_module._LIVE_INSTANCE, "_live_render"):
                    ui_module._LIVE_INSTANCE._live_render._shape = None
                ui_module._LIVE_INSTANCE.start()
            except Exception:
                pass
                
    set_tui_callback(tui_reconstruct)
    
    console.print(" ")
    console.print(" ")
    for idx, video in enumerate(videos, 1):
        vid_id    = video.get("id")
        vid_title = video.get("title")
        vid_url   = video.get("url")
        current_sub = video.get("_target_folder", sub_folder)

        resolved_file_path, is_downloaded = tracker.resolve_download_path(current_sub, str(vid_id), vid_title, ext_str, date_str=video.get("upload_date"))
        display_name = resolved_file_path.name

        if is_downloaded:
            tracker.mark_downloaded(scraper.url, str(vid_id))
            hist_log = f"  [unselected]●[/unselected] [unselected]File exists: {display_name}[/unselected]"
            console.print(hist_log)
            completed_history.append(hist_log)
            continue

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
            "alerts":  [],
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
                    
                    status_text = "Almost done with baking..." if not is_small_file else "Baking metadata..."
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] {status_text}")
                else:
                    if is_small_file:
                        blink_state = int(time.time() * 3) % 2
                        ball_style = "warning" if blink_state == 0 else "unselected"
                        res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
                    else:
                        progress_bar.update(
                            task_id,
                            total       = total or None,
                            completed   = progress_data["downloaded_bytes"],
                            description = progress_data["status"],
                            speed       = progress_data.get("speed", 0),
                            eta         = progress_data.get("eta"),
                        )
                        res_branch.add(progress_bar)
            else:
                success    = progress_data.get("success", False)
                res_color  = "success" if success else "error"
                res_text   = "Complete" if success else "Failed"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")

            return tree

        unbaked_tmp = resolved_file_path.parent / (resolved_file_path.stem + ".tmp" + resolved_file_path.suffix)
        unbaked_meta = resolved_file_path.with_suffix(".meta.tmp" + resolved_file_path.suffix)
        found_unbaked = None
        if unbaked_tmp.exists():
            found_unbaked = unbaked_tmp
        elif unbaked_meta.exists():
            found_unbaked = unbaked_meta

        if found_unbaked:
            if is_batch_mode or not sys.stdin.isatty():
                bake_choice = "y"
            else:
                console.print(f"\n[warning]Found unfinished/unbaked download for:[/warning] [title]{vid_title}[/title]")
                console.print(f"[menu]Do you want to continue baking metadata for this file? (y/n): [/menu]", end="")
                sys.stdout.write(get_theme_input_ansi())
                sys.stdout.flush()
                try:
                    bake_choice = input().strip().lower()
                except EOFError:
                    bake_choice = "n"
                sys.stdout.write("\033[0m")
                sys.stdout.flush()

            if bake_choice in ["y", "yes"]:
                progress_data["status"] = "Baking metadata..."
                progress_data["baking"] = True
                with Live(render_video_tree(), console=console, refresh_per_second=10, transient=True) as live:
                    try:
                        custom_cover = folder / "cover.jpg" if (folder / "cover.jpg").exists() else None
                        if custom_thumb_path:
                            custom_cover = custom_thumb_path

                        if found_unbaked == unbaked_tmp and custom_thumb_path:
                            success = scraper.engine._apply_custom_thumbnail(unbaked_tmp, custom_cover, resolved_file_path, "music" in mode)
                        else:
                            success = True
                            scraper.engine._apply_custom_metadata(found_unbaked, custom_cover, "music" in mode, resolved_file_path.stem)
                            if not resolved_file_path.exists() and found_unbaked.exists():
                                found_unbaked.rename(resolved_file_path)

                        if success and resolved_file_path.exists():
                            tracker.mark_downloaded(scraper.url, str(vid_id))
                            progress_data["success"] = True
                            if unbaked_tmp.exists():
                                try: unbaked_tmp.unlink()
                                except: pass
                            if unbaked_meta.exists():
                                try: unbaked_meta.unlink()
                                except: pass
                    except Exception as e:
                        logger.error(f"Bake recovery failed: {e}")

                    progress_data["done"] = True
                    live.update(render_video_tree())

                res_color = "success" if progress_data.get("success") else "error"
                hist_log = f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]"
                console.print(hist_log)
                completed_history.append(hist_log)
                time.sleep(0.5)
                continue

        completed_files: dict = {}

        def yt_dlp_hook(d):
            filename = d.get("filename")
            if d["status"] == "downloading":
                progress_data["status"]    = "Downloading"
                downloaded = d.get("downloaded_bytes", 0)
                total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                completed_files[filename]  = {"downloaded": downloaded, "total": total}

                progress_data["downloaded_bytes"] = sum(f["downloaded"] for f in completed_files.values())
                progress_data["total_bytes"]      = sum(f["total"]      for f in completed_files.values())
                progress_data["speed"] = d.get("speed", 0)
                progress_data["eta"]   = d.get("eta")

            elif d["status"] == "finished":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if filename not in completed_files:
                    completed_files[filename] = {"downloaded": total, "total": total}
                else:
                    if completed_files[filename]["total"] == 0:
                        completed_files[filename]["total"] = total
                    completed_files[filename]["downloaded"] = completed_files[filename]["total"]
                
                total_all = sum(f["total"] for f in completed_files.values())
                current = progress_data.get("downloaded_bytes", 0)
                if total_all > 0 and current < total_all:
                    steps = 10
                    step_size = (total_all - current) / steps
                    for i in range(1, steps + 1):
                        progress_data["downloaded_bytes"] = int(current + step_size * i)
                        progress_data["total_bytes"] = total_all
                        try:
                            live.update(render_video_tree())
                        except Exception:
                            pass
                        time.sleep(0.05)
                
                progress_data["downloaded_bytes"] = total_all
                progress_data["total_bytes"]      = total_all
                progress_data["speed"] = 0
                progress_data["eta"]   = 0
                progress_data["status"] = "Almost done with baking..."
                progress_data["baking"] = True

            elif d["status"] == "error":
                progress_data["status"] = "Error"

        download_error = None
        import core.ui as ui
        ui._REVOLT_LISTENER_ACTIVE = True
        try:
            attempt = 0
            while True:
                progress_data["retry"] = attempt
                if attempt > 0:
                    progress_data["status"] = "Resuming..."
                    progress_data["baking"] = False
                    progress_data["done"] = False
                    progress_data["success"] = False
                    completed_files.clear()
                    
                with Live(render_video_tree(), console=console, refresh_per_second=10, transient=True) as live:
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
                    
                    def active_hook(d):
                        yt_dlp_hook(d)
                        try:
                            live.update(render_video_tree())
                        except Exception:
                            pass
                            
                    try:
                        success = scraper.engine.download_youtube(
                            vid_url, current_sub, active_hook,
                            mode=mode,
                            custom_thumbnail=custom_thumb_path,
                            quality=quality,
                            audio_format=audio_format,
                            fixed_title=resolved_file_path.stem
                        )
                    finally:
                        live_active[0] = False
                    
                set_active_live(None)
                if success:
                    tracker.mark_downloaded(scraper.url, str(vid_id))
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
            console.print(f"[error]Download failed with error: {download_error}[/error]")
            import traceback
            traceback.print_exc()
            
        res_color = "success" if progress_data.get("success") else "error"
        hist_log = f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]"
        console.print(hist_log)
        completed_history.append(hist_log)
        time.sleep(0.5)

        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT == 0:
                console.print("[warning]● Revolt shutdown triggered. Exiting cleanly...[/warning]\n")
                sys.exit(0)
            else:
                ui._REVOLT_LIMIT -= 1
 
    console.print(f"\n[success]✦[/success] Done\n")
