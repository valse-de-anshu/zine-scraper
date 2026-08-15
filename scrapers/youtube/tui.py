"""
scrapers/youtube/tui.py
-----------------------
Site-specific TUI layer for YouTube.
Handles only user selections and settings configuration, conforming to the decoupled 7-file structure.
"""

import time
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.ui import (
    console, startup_clear, print_banner, Selector,
    get_theme_input_ansi, active_status
)
from core.history import HistoryLayer
from core.storage import StorageLayer
from .scraper import YoutubeScraper
from .location import get_save_path
from .workflow import run_workflow

logger = logging.getLogger(__name__)

def handle_youtube_tui(
    url: str,
    tracker: HistoryLayer,
    library_root: Path,
    storage_layer: StorageLayer,
    scraper: Any,
    is_multi: bool = True,
    is_batch_mode: bool = False,
    batch_path: Optional[Path] = None
):
    """
    Dedicated TUI flow for YouTube URLs.
    Stage 1 Selection menus.
    """
    startup_clear()
    print_banner()

    from core.paths import PathAuthority
    from core.cache import CacheLayer
    import json
    cache_layer = CacheLayer(PathAuthority(), storage_layer)
    cache_key = f"yt_meta_{url}"
    
    metadata, videos, info = None, None, None
    link_type = scraper.get_link_type()
    is_batch = is_batch_mode or not sys.stdin.isatty()
    # In batch mode, cap initial scan to 201 to avoid blocking on huge channels (e.g. Netflix 10k+)
    # but still allow downloading a reasonable chunk (up to 200 videos).
    if is_batch and link_type in ["channel", "playlist"]:
        initial_limit = 201
    else:
        initial_limit = 201 if link_type in ["channel", "playlist"] else None
    
    with active_status("[info]Loading metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos(playlist_limit=initial_limit)
        except Exception as e:
            cached_str = cache_layer.read_cache_text(cache_key, suffix=".json")
            if cached_str:
                try:
                    cached_data = json.loads(cached_str)
                    metadata = cached_data["metadata"]
                    videos = cached_data["videos"]
                    info = cached_data["info"]
                    console.print("[success]● Rate-limited or Forbidden. Loaded cached metadata fallback.[/success]")
                    time.sleep(1.5)
                except Exception:
                    pass
            
            if not metadata:
                console.print(f"[error]Failed to load metadata: {e}[/error]")
                time.sleep(2)
                return

    if getattr(scraper, "_batch_quick_grab", False):
        if videos:
            videos = videos[:1]
            metadata["Total Videos"] = 1
        is_multi = False

    # Check if channel/playlist exceeds 200 videos and prompt the user
    if link_type in ["channel", "playlist"] and videos and len(videos) > 200:
        if is_batch or not sys.stdin.isatty():
            # In batch mode: don't scan the whole channel — cap at first 200
            # to avoid infinite yt-dlp loops on massive channels (e.g. Netflix)
            videos = videos[:200]
            metadata["Total Videos"] = len(videos)
            choice = ""  # skip the scan loop below
        else:
            console.print(f"\n[warning]Found more than [selected]200[/selected] videos in this {link_type} (201+)[/warning]")
            console.print("[menu]If you want to grab everything, type [sexy_pink]\"all\"[/sexy_pink] (pray it only takes an hour lol!)[/menu]")
            console.print("[menu]Otherwise, just press [bold]Enter[/bold] and I've got your back with the first [selected]200[/selected][/menu]")
            console.print("[menu]❯ [/menu]", end="")
            sys.stdout.write(get_theme_input_ansi())
            pass
            try:
                choice = input().strip().lower()
            except EOFError:
                choice = ""
            sys.stdout.write("\033[0m")
            pass
        
        if choice == "all":
            current_start = 201
            if not is_batch:
                console.print("\n[success]● Running total: 200 videos found so far[/success]")
            while True:
                playlist_start = current_start
                playlist_limit = current_start + 199
                next_videos = []
                
                with active_status(f"[info]Scanning next 200 videos (starting at #{current_start})...[/info]", spinner="dots"):
                    try:
                        _, next_videos, _ = scraper.get_metadata_and_videos(playlist_limit=playlist_limit, playlist_start=playlist_start)
                    except Exception as e:
                        console.print(f"[error]Failed to scan from index {current_start}: {e}[/error]")
                        break
                        
                if not next_videos:
                    console.print("[info]● Reached the end of the channel.[/info]")
                    break
                    
                videos.extend(next_videos)
                metadata["Total Videos"] = len(videos)
                
                # Write back cache immediately
                try:
                    cached_data = {
                        "metadata": metadata,
                        "videos": videos,
                        "info": info
                    }
                    cache_layer.write_cache_text(cache_key, json.dumps(cached_data), suffix=".json")
                except Exception:
                    pass
                    
                console.print(f"[success]● Found another {len(next_videos)} videos (Total found so far: {len(videos)})[/success]")
                
                if len(next_videos) < 200:
                    if not is_batch:
                        console.print("[info]● Reached the end of the channel.[/info]")
                    break
                    
                if is_batch or not sys.stdin.isatty():
                    keep_going = "y"
                else:
                    console.print("\n[menu]Do you want me to keep going? (y/n)[/menu]")
                    console.print("> ", end="")
                    sys.stdout.write(get_theme_input_ansi())
                    pass
                    try:
                        keep_going = input().strip().lower()
                    except EOFError:
                        keep_going = "n"
                    sys.stdout.write("\033[0m")
                    pass
                
                if keep_going in ["n", "no"]:
                    if not is_batch:
                        console.print("[info]● Stopping scan and starting download queue with what was found...[/info]")
                    break
                    
                current_start += 200
        else:
            videos = videos[:200]
            metadata["Total Videos"] = 200

    # Save to cache
    try:
        cached_data = {
            "metadata": metadata,
            "videos": videos,
            "info": info
        }
        cache_layer.write_cache_text(cache_key, json.dumps(cached_data), suffix=".json")
    except Exception:
        pass

    channel_name = metadata.get("Channel/Series", "Unknown")

    # Force multi-mode when the target is a channel / playlist / multi-video
    is_multi = (
        is_multi
        or scraper.is_playlist
        or scraper.get_link_type() in ["playlist", "channel"]
        or len(videos) > 1
        or metadata.get("Total Videos", 0) > 1
    )

    menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")

    if is_multi:
        mode_options = [
            ("Video", "video"),
            ("Song",  "music"),
            ("Back",  "BACK")
        ]
    else:
        mode_options = [
            ("Video",                     "video"),
            ("Song",                      "music"),
            ("Custom Video with Thumbnail", "custom_video"),
            ("Custom Song with Thumbnail",  "custom_music"),
            ("Back",                      "BACK")
        ]

    quality_options = [
        ("2K  (Ultra Clear  / Maximum details / Huge size)",    "2K"),
        ("1080p (Very Sharp / High definition / Large size)",   "1080p"),
        ("720p  (Sharp / Good details / Medium size)",          "720p"),
        ("480p  (Standard definition / Standard size)",         "480p"),
        ("360p  (Low definition / Best for slow internet)",     "360p"),
        ("240p  (Very Low definition / Low data usage)",        "240p"),
        ("144p  (Lowest definition / Extremely small size)",    "144p"),
        ("Back", "BACK")
    ]

    format_options = [
        ("FLAC (Highest quality audio / Studio master sound)",           "FLAC"),
        ("OPUS (Highly optimized sound / Great for slow internet)",      "OPUS"),
        ("MP3  (Standard quality audio / Works on all players)",         "MP3"),
        ("M4A  (Apple optimized sound / Clean and crisp)",               "M4A"),
        ("AAC  (High quality audio / Standard internet streaming sound)", "AAC"),
        ("Back", "BACK")
    ]

    state = 0
    mode = None
    mode_label = None
    quality = None
    audio_format = None
    custom_thumb_path = None
    target_root = None

    def draw_yt_header():
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu_label}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Channel':<12}:[/menu] [title]{channel_name}[/title]")
        if "Playlist" in metadata:
            console.print(f"[menu]{'Playlist':<12}:[/menu] [title]{metadata['Playlist']}[/title]")

    while True:
        if state == 0:
            if is_multi:
                mode_options = [
                    ("Video", "video"),
                    ("Song",  "music"),
                    ("Back",  "BACK")
                ]
            else:
                mode_options = [
                    ("Video",                     "video"),
                    ("Song",                      "music"),
                    ("Custom Video with Thumbnail", "custom_video"),
                    ("Custom Song with Thumbnail",  "custom_music"),
                    ("Back",                      "BACK")
                ]
            draw_yt_header()
            if is_batch or not sys.stdin.isatty():
                mode = "video"
            else:
                mode = Selector(mode_options, "Type", vertical=not is_multi, align_width=12).select()
            
            if mode == "BACK":
                return
            if mode == "toggle":
                is_multi = not is_multi
                scraper.is_playlist = is_multi
                menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")
                continue
            mode_label = next((opt[0] for opt in mode_options if opt[1] == mode), mode)
            state = 1
            
        elif state == 1:
            draw_yt_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{mode_label}[/site]")
            
            if mode in ["video", "custom_video"]:
                if is_batch or not sys.stdin.isatty():
                    quality = "1080p"
                else:
                    quality = Selector(quality_options, "Quality", vertical=True, align_width=12).select()
                if quality == "BACK":
                    state = 0
                    continue
                if quality == "toggle":
                    is_multi = not is_multi
                    scraper.is_playlist = is_multi
                    menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")
                    continue
                console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")
            elif mode in ["music", "custom_music"]:
                if is_batch or not sys.stdin.isatty():
                    audio_format = "FLAC"
                else:
                    audio_format = Selector(format_options, "Format", vertical=True, align_width=12).select()
                if audio_format == "BACK":
                    state = 0
                    continue
                if audio_format == "toggle":
                    is_multi = not is_multi
                    scraper.is_playlist = is_multi
                    menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")
                    continue
                console.print(f"[menu]{'Format':<12}:[/menu] [site]{audio_format}[/site]")
                
            state = 2
            
        elif state == 2:
            if "custom" in mode:
                draw_yt_header()
                console.print(f"[menu]{'Type':<12}:[/menu] [site]{mode_label}[/site]")
                if quality:
                    console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")
                if audio_format:
                    console.print(f"[menu]{'Format':<12}:[/menu] [site]{audio_format}[/site]")
                
                console.print("[menu]Paste Picture Path (Empty to go back): [/menu]", end="")
                if is_batch or not sys.stdin.isatty():
                    path_str = ""
                else:
                    sys.stdout.write(get_theme_input_ansi())
                    pass
                    try:
                        path_str = input().strip()
                    except EOFError:
                        path_str = ""
                    sys.stdout.write("\033[0m")
                    pass
                
                if not path_str:
                    state = 1
                    continue
                
                p_path = Path(path_str)
                if p_path.exists() and p_path.is_file():
                    custom_thumb_path = p_path
                    state = 3
                else:
                    console.print("[error]File does not exist or is not a file.[/error]")
                    time.sleep(1.5)
                    continue
            else:
                custom_thumb_path = None
                state = 3
                
        elif state == 3:
            draw_yt_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{mode_label}[/site]")
            if quality:
                console.print(f"[menu]{'Quality':<12}:[/menu] [site]{quality}[/site]")
            if audio_format:
                console.print(f"[menu]{'Format':<12}:[/menu] [site]{audio_format}[/site]")
            if custom_thumb_path:
                console.print(f"[menu]{'Thumbnail':<12}:[/menu] [site]{custom_thumb_path.name}[/site]")
                
            if batch_path is not None:
                target_root = Path(batch_path)
            else:
                scraper.is_music = ("music" in mode) if mode else False
                from core.paths import get_container_root
                default_container = get_container_root(url, scraper, is_batch_mode)
                target_root = get_save_path(url, scraper, is_batch_mode, batch_path, default_container, storage_layer)
                
            if not target_root:
                state = 2 if "custom" in mode else 1
                continue
                
            if target_root == "toggle":
                is_multi = not is_multi
                scraper.is_playlist = is_multi
                menu_label = "Batch" if is_batch_mode else ("Vacuum" if is_multi else "Quick Grab")
                continue
                
            break

    # Call run_workflow in workflow.py
    run_workflow(
        url, tracker, target_root, metadata, videos, info, scraper,
        mode, custom_thumb_path, quality=quality, audio_format=audio_format,
        is_multi=is_multi, is_batch_mode=is_batch_mode
    )
    
    if not is_batch_mode:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
        pass
        try:
            input()
        except EOFError:
            pass

def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    """Unified handshake wrapper for YouTube TUI."""
    link_type = scraper.get_link_type()
    is_multi = (link_type != "single")
    
    from core.paths import PathAuthority
    library_root = PathAuthority().get_downloads_root()
    
    handle_youtube_tui(
        url, tracker, library_root, location_manager, scraper,
        is_multi=is_multi, is_batch_mode=is_batch, batch_path=batch_path
    )
