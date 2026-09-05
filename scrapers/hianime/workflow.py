"""
scrapers/hianime/workflow.py
────────────────────────────
Full download orchestrator for HiAnime. Mirrors anitaku/workflow.py but is
fully self-contained — no shared execution logic leaks out to core/shared_loops.py.

Flow:
  1. Fetch metadata + episode list
  2. Prompt: whole series vs single episode (interactive only)
  3. Launch Anime Import Wizard (category/folder/quality selection)
  4. Save cover.jpg + .zine/metadata.json in the series root
  5. Verify existing downloads
  6. Download loop with per-episode Live progress tree
"""

import os
import sys
import re
import json
import time
import signal
import logging
import threading
from pathlib import Path
from typing import Optional, List, Any
from urllib.parse import urljoin, urlparse

import requests
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn, DownloadColumn
import core.ui as ui
from core.ui import (
    console, startup_clear, print_banner, active_status,
    Selector, MinimalPulseBar, MbpsColumn, set_active_live, clean_exit
)
from core.import_tui import CategoryImportTUI
from core.anime_categories import CATEGORIES
from butler.part_cleaner import clean_part_files
from core.video_engine import handle_internet_loss
from core.cache import save_url_to_file
from core.paths import resolve_folder_collision, PathAuthority

from .verification import verify_videos
from .progress import render_completion_tree

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None
CHAPTER_DELAY = 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_library_root() -> Path:
    paths = PathAuthority()
    library_root = paths.get_downloads_root()
    config_file = paths.get_config_file()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_base = data.get("download_base")
                if custom_base:
                    library_root = Path(custom_base)
        except Exception:
            pass
    return library_root


def _safe_title(raw: str) -> str:
    return "".join(c for c in raw if c.isalnum() or c in " .-_()").strip() or "Unknown Anime"


def _find_existing_series_folder(hianime_root: Path, title: str) -> Optional[Path]:
    """Prevents duplicate folders when re-scraping the same series from a different mirror."""
    def norm(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower())

    target = norm(title)
    if hianime_root.exists():
        for d in hianime_root.iterdir():
            if d.is_dir() and norm(d.name) == target:
                return d
    return None


def _download_subtitles(subtitles: list, video_path: Path, headers: dict):
    """
    Downloads subtitle .vtt tracks into a Subtitles/ subdirectory beside the episode.
    Compatible with mpv (--sub-file-paths=Subtitles), VLC, Jellyfin, Kodi.
    """
    sub_dir = video_path.parent / "Subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)
    for sub in subtitles:
        sub_url = sub.get("url", "")
        label   = sub.get("label", "unknown").lower().replace(" ", "-")
        if not sub_url:
            continue
        try:
            ext = ".vtt" if ".vtt" in sub_url else ".srt"
            sub_path = sub_dir / f"{video_path.stem}.{label}{ext}"
            r = requests.get(sub_url, headers=headers, timeout=15)
            r.raise_for_status()
            sub_path.write_bytes(r.content)
        except Exception as e:
            logger.warning(f"[HiAnime] Failed to download subtitle '{label}': {e}")


def _fetch_hls_qualities(master_url: str, headers: dict) -> list:
    """
    Returns available quality dicts sorted highest-first:
    [{'label': '1080p', 'bandwidth': N, 'resolution': 'WxH', 'url': '...'}, ...]
    """
    try:
        r = requests.get(master_url, headers=headers, timeout=10)
        r.raise_for_status()
        if "#EXT-X-STREAM-INF" not in r.text:
            return []
        streams = []
        lines = r.text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                bw_m  = re.search(r'BANDWIDTH=(\d+)', line)
                res_m = re.search(r'RESOLUTION=(\d+x\d+)', line)
                bandwidth  = int(bw_m.group(1))  if bw_m  else 0
                resolution = res_m.group(1)       if res_m else ""
                if i + 1 < len(lines):
                    uri = lines[i + 1].strip()
                    height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                    label  = f"{height}p" if height else f"{bandwidth // 1000}kbps"
                    streams.append({
                        "label": label, "bandwidth": bandwidth,
                        "resolution": resolution,
                        "url": urljoin(master_url, uri),
                    })
        return sorted(streams, key=lambda s: s["bandwidth"], reverse=True)
    except Exception as e:
        logger.debug(f"[HiAnime] Could not fetch HLS qualities: {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Main workflow
# ──────────────────────────────────────────────────────────────────────────────

def run_workflow(
    url: str, tracker: Any, location_manager: Any, scraper: Any,
    batch_path: Optional[Path] = None, is_batch: bool = False
):
    # ── Metadata fetch ────────────────────────────────────────────────────────
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, _info = scraper.get_metadata_and_videos()
            title = metadata.get("Channel/Series", "Unknown")
            scraper.title = title
            scraper.metadata = metadata
            if hasattr(tracker, "set_title") and title and title != "Unknown":
                tracker.set_title(scraper.url, title)
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if sys.stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    # ── Whole series vs. single episode ──────────────────────────────────────
    is_single_episode = False
    
    # Auto-detect if URL specifies a single episode (contains /ep- or ?ep=)
    is_single_ep_url = False
    if "/ep-" in url or "?ep=" in url:
        is_single_ep_url = True

    def _draw_header(menu="Anime"):
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{menu}[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Series':<12}:[/menu] [title]{title}[/title]")
        console.print(f"[menu]{'Episodes':<12}:[/menu] [info]{len(videos)}[/info]")
        console.print("")

    if not is_batch and sys.stdin.isatty():
        _draw_header("Anime")
        if len(videos) > 1:
            choice = Selector(
                [("Download whole series", "whole"), ("Download single episode", "single")],
                title="Mode", vertical=True
            ).select()
        else:
            choice = Selector(
                [("Download single episode", "single"), ("Download whole series", "whole")],
                title="Mode", vertical=True
            ).select()

        if choice == "single":
            # Try to match the episode from the URL slug (e.g. /ep-3 or ?ep=3)
            ep_match = re.search(r'(?:[?&]ep=|/ep-|/episode-|-episode-)(\d+)', url)
            if ep_match:
                ep_num = ep_match.group(1)
                ep_pattern = re.compile(r'(?:[?&]ep=|/ep-|/episode-|-episode-)' + re.escape(ep_num) + r'(?:[?&#/]|\Z)')
                target = [v for v in videos if ep_pattern.search(v.get("url", "")) or str(v.get("id", "")).endswith(f"_ep{ep_num}") or str(v.get("id", "")) == ep_num]
                if target:
                    videos = target
            if len(videos) > 1:
                _draw_header("Anime")
                options = [(v.get("title", f"Episode {i+1}"), v) for i, v in enumerate(videos)]
                selected = Selector(options, title="Select Episode", vertical=True).select()
                if selected:
                    videos = [selected]
            metadata["Total Videos"] = len(videos)
            scraper.is_playlist = False
            is_single_episode = True
        elif choice == "whole":
            scraper.is_playlist = True
            is_single_episode = False
        else:
            return
    else:
        # Headless, batch, or redirected stdin mode
        if getattr(scraper, "_batch_quick_grab", False):
            if is_single_ep_url:
                target_videos = []
                ep_match = re.search(r'(?:[?&]ep=|/ep-|/episode-|-episode-)(\d+)', url)
                if ep_match:
                    ep_num = ep_match.group(1)
                    ep_pattern = re.compile(r'(?:[?&]ep=|/ep-|/episode-|-episode-)' + re.escape(ep_num) + r'(?:[?&#/]|\Z)')
                    target_videos = [v for v in videos if ep_pattern.search(v.get("url", "")) or str(v.get("id", "")).endswith(f"_ep{ep_num}") or str(v.get("id", "")) == ep_num]
                if target_videos:
                    videos = target_videos
            else:
                videos = videos[:1]
            metadata["Total Videos"] = len(videos)
            scraper.is_playlist = False
            is_single_episode = True
        else:
            scraper.is_playlist = True
            is_single_episode = False

    # ── Determine save folder ─────────────────────────────────────────
    library_root = _get_library_root()
    hianime_root = library_root / "Vacuum" / "Anime" / "hianime"

    if is_single_episode and not is_batch:
        folder = library_root / "Quick grab"
        location_manager.create_directory(folder)
        cover_exists = False
        verified_ids = []
        tui_rel_path = Path("Single Episode (Quick Grab)")
        chosen_quality_url = None
    else:
        # ── Phase 2 TUI: pick category & Quality ─────────────────────
        if batch_path is not None:
            hianime_root = batch_path
            tui_rel_path = Path("")
            chosen_quality_url = None
        else:
            if sys.stdin.isatty() and not is_batch:
                tui = CategoryImportTUI(CATEGORIES, title="ZINE SCRAPER · Anime Import Wizard")
                res = tui.run()
                if not res or (isinstance(res, tuple) and res[0] is None):
                    return

                if isinstance(res, tuple):
                    tui_rel_path = res[0]
                else:
                    tui_rel_path = res
            else:
                tui_rel_path = Path("TV/Season 1")
            chosen_quality_url = None

        # ── Build final folder path, reuse existing if mirror-dup ────
        safe_title = _safe_title(title)
        existing = _find_existing_series_folder(hianime_root, title)
        series_root = existing if existing else (hianime_root / safe_title)
        folder = series_root / tui_rel_path
        location_manager.create_directory(folder)

        save_url_to_file(url, title, silent=False)

        # ── Cover art ────────────────────────────────────────────────────────
        cover_url = metadata.get("Thumbnail")

        ext = ".jpg"

        if cover_url:
            ext = Path(urlparse(cover_url).path).suffix or ".jpg"

        cover_path = series_root / f"cover{ext}"

        if not cover_path.exists():
            if cover_url:
                try:
                    resp = requests.get(cover_url, timeout=15)
                    resp.raise_for_status()
                    cover_path.write_bytes(resp.content)
                except Exception:
                    pass
        cover_exists = cover_path.exists()

        # ── .zine/metadata.json ──────────────────────────────────────────────
        try:
            zine_dir = series_root / ".zine"
            zine_dir.mkdir(parents=True, exist_ok=True)
            meta_payload = {
                "title":          title,
                "description":    metadata.get("Description", ""),
                "genres":         [g.strip() for g in metadata.get("Genres", "").split(",") if g.strip()],
                "aired":          metadata.get("Aired", ""),
                "premiered":      metadata.get("Premiered", ""),
                "duration":       metadata.get("Duration", ""),
                "status":         metadata.get("Status", ""),
                "mal_score":      metadata.get("MAL Score", ""),
                "studios":        [s.strip() for s in metadata.get("Studios", "").split(",") if s.strip()],
                "producers":      [p.strip() for p in metadata.get("Producers", "").split(",") if p.strip()],
                "japanese":       metadata.get("Japanese", ""),
                "source":         "HiAnime",
                "url":            url,
                "thumbnail":      metadata.get("Thumbnail", ""),
                "total_episodes": metadata.get("Total Videos", 0),
            }
            with open(zine_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(meta_payload, f, indent=4, ensure_ascii=False)
        except Exception as e:
            console.print(f"[warning]Failed to save .zine/metadata.json: {e}[/warning]")

        verified_ids = verify_videos(folder, videos, "mp4", tracker, scraper.url)

    # ── Header log ────────────────────────────────────────────────────────────
    startup_clear()
    print_banner()
    console.print(f"[menu]Menu[/menu]         : [site]Anime[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    console.print(f"[menu]Category[/menu]     : [info]{tui_rel_path}[/info]")
    console.print("")

    if not is_single_episode:
        render_completion_tree(title, folder, metadata, verified_ids, cover_exists)
    else:
        tree = Tree(f"[title]◆ {title} (Single Episode)[/title]")
        tree.add(f"{'❖ Location':<18} : [sexy_pink]{folder}[/sexy_pink]")
        tree.add(f"{'Source':<18} : [info]HiAnime[/info]")
        console.print(tree)
        console.print("")

    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return

    try:
        clean_part_files(folder, videos, tracker, scraper.url)
    except Exception:
        pass

    success_count = 0
    skipped_count = 0

    for idx, video in enumerate(videos, 1):
        vid_id    = video.get("id")
        vid_title = video.get("title")
        vid_url   = video.get("url")

        resolved_file_path, is_in_verified = tracker.resolve_download_path(
            folder, str(vid_id), vid_title, "mp4", url=vid_url
        )
        display_name = resolved_file_path.name

        if is_in_verified:
            tracker.mark_downloaded(scraper.url, str(vid_id), title=title)
            console.print(f"  [unselected]File exists: {display_name}[/unselected]")
            skipped_count += 1
            continue

        # ── Per-episode progress state ────────────────────────────────────────
        progress_data = {
            "phase":            "resolving",
            "total_bytes":      0,
            "downloaded_bytes": 0,
            "done":             False,
            "success":          False,
            "status":           "Resolving stream...",
            "current_title":    vid_title,
            "retry":            0,
            "speed":            0.0,
        }

        pulse_bar = Progress(
            TextColumn("[progress.description]{task.description}"),
            MinimalPulseBar(bar_width=40),
            transient=False,
        )
        pulse_task = pulse_bar.add_task("", total=None)

        exact_bar = Progress(
            TextColumn("[progress.description]{task.description}"),
            MinimalPulseBar(bar_width=30),
            TaskProgressColumn(),
            DownloadColumn(binary_units=False),
            MbpsColumn(),
            transient=False,
        )
        exact_task = exact_bar.add_task("Downloading", total=None)

        def render_video_tree() -> Tree:
            tree = Tree(f"[menu]● Progress[/menu]")
            tree.add(f"[menu]Current[/menu]         : [white]{progress_data['current_title']}[/white]")
            tree.add(f"[menu]Retry[/menu]           : [info]{progress_data['retry']}[/info]")
            res_branch = tree.add("[unselected]○ Result[/unselected]")

            if not progress_data["done"]:
                phase = progress_data.get("phase", "resolving")
                
                # Blinking dot logic for indeterminate states
                if phase == "resolving":
                    blink_state = int(time.time() * 3) % 2
                    ball_style = "sexy_pink" if blink_state == 0 else "unselected"
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Resolving stream...")
                elif phase == "baking":
                    blink_state = int(time.time() * 6) % 3
                    ball_style = "success" if blink_state == 0 else "warning" if blink_state == 1 else "unselected"
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Baking metadata...")
                else:
                    blink_state = int(time.time() * 3) % 2
                    ball_style = "warning" if blink_state == 0 else "unselected"
                    res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
            else:
                ok = progress_data.get("success", False)
                res_color = "success" if ok else "error"
                res_text  = "Complete" if ok else f"Failed ({progress_data.get('status', 'Error')})"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
            return tree

        def _sigint_handler(sig, frame):
            try:
                live.stop()
            except Exception:
                pass
            clean_exit(forceful=True)

        old_sigint = signal.signal(signal.SIGINT, _sigint_handler)
        ui._REVOLT_LISTENER_ACTIVE = True

        global _LIVE_INSTANCE
        with Live(render_video_tree(), console=console, refresh_per_second=12,
                  transient=True) as live:
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
            threading.Thread(target=refresh_loop, daemon=True).start()

            def stats_callback(stats):
                progress_data.update(stats)
                if progress_data.get("total_bytes", 0) > 0:
                    if progress_data.get("phase") not in ("baking", "done"):
                        progress_data["phase"] = "downloading"
                try:
                    live.update(render_video_tree())
                except Exception:
                    pass

            domain_success  = False
            raw_stream_url  = None
            referer         = None
            stream_info     = None
            progress_data["phase"]  = "resolving"
            progress_data["status"] = "Resolving..."
            try:
                live.update(render_video_tree())
            except Exception:
                pass

            candidate_streams = []
            if hasattr(scraper.engine, "resolve_episode_streams"):
                try:
                    candidate_streams = scraper.engine.resolve_episode_streams(vid_url)
                except Exception as e:
                    pass
            elif hasattr(scraper.engine, "resolve_episode_stream"):
                try:
                    single = scraper.engine.resolve_episode_stream(vid_url)
                    if single and single.get("m3u8_url"):
                        candidate_streams = [single]
                except Exception as e:
                    pass

            if not candidate_streams:
                progress_data["status"] = "Failed to resolve"
                progress_data["done"]   = True
                try:
                    live.update(render_video_tree())
                except Exception:
                    pass
            else:
                for s_idx, stream_info in enumerate(candidate_streams):
                    if domain_success:
                        break

                    raw_stream_url = stream_info.get("m3u8_url")
                    referer = stream_info.get("embed_referer")
                    server_name = stream_info.get("server_name", f"Server {s_idx+1}")

                    if referer:
                        scraper.engine.headers["Referer"] = referer
                        scraper.engine.headers["Origin"]  = referer.rstrip("/")

                    effective_stream_url = raw_stream_url
                    if chosen_quality_url and raw_stream_url:
                        try:
                            ep_qualities = _fetch_hls_qualities(raw_stream_url, scraper.engine.headers)
                            if ep_qualities:
                                chosen_res = re.search(r'(\d{3,4})x(\d{3,4})', chosen_quality_url)
                                chosen_h   = int(chosen_res.group(2)) if chosen_res else 0
                                if chosen_h:
                                    best = next((q for q in ep_qualities if f"{chosen_h}p" == q["label"]), None)
                                    if best:
                                        effective_stream_url = best["url"]
                        except Exception:
                            pass

                    subtitles = stream_info.get("subtitles", [])

                    def baking_callback():
                        progress_data["phase"] = "baking"
                        try:
                            live.update(render_video_tree())
                        except Exception:
                            pass

                    progress_data["phase"]  = "downloading"
                    progress_data["status"] = f"Streaming {server_name}" if len(candidate_streams) > 1 else ""
                    try:
                        live.update(render_video_tree())
                    except Exception:
                        pass

                    for attempt in range(1, 3):
                        if attempt > 1:
                            progress_data["retry"] = attempt - 1
                            time.sleep(1)
                        try:
                            success = scraper.engine.download_video(
                                vid_url, folder, stats_callback,
                                raw_stream_url=effective_stream_url,
                                is_audio=False,
                                custom_thumbnail=None,
                                fixed_title=vid_title,
                                fixed_artist=None,
                                format_override="best[ext=mp4]/best",
                                baking_callback=baking_callback,
                            )
                            if success:
                                tracker.mark_downloaded(scraper.url, str(vid_id), title=title)
                                progress_data["success"] = True
                                progress_data["done"]    = True
                                success_count  += 1
                                domain_success = True
                                if subtitles:
                                    _download_subtitles(subtitles, resolved_file_path,
                                                        scraper.engine.headers)
                                break
                        except Exception as e:
                            progress_data["status"] = str(e)
                            if not handle_internet_loss():
                                break

            if not domain_success:
                if not progress_data.get("status") or progress_data.get("status") == "downloading":
                    progress_data["status"] = "All servers failed"
                progress_data["success"] = False

            live_active[0] = False
            progress_data["done"] = True
            try:
                live.update(render_video_tree())
            except Exception:
                pass

        _LIVE_INSTANCE = None
        set_active_live(None)
        ui._REVOLT_LISTENER_ACTIVE = False
        signal.signal(signal.SIGINT, old_sigint)

        res_color = "success" if progress_data.get("success") else "error"
        status_msg = f" (Error: {progress_data.get('status', 'Unknown error')})" if not progress_data.get("success") else ""
        console.print(f"  [{res_color}]●[/{res_color}] [unselected]{display_name}{status_msg}[/unselected]")
        time.sleep(CHAPTER_DELAY)

        if ui.check_revolt(title=title):
            return

    # ── Summary ───────────────────────────────────────────────────────────────
    total     = len(videos)
    attempted = total - skipped_count
    if success_count > 0 or skipped_count == total:
        console.print(
            f"\n[success]✦[/success] Finalized: "
            f"{success_count} new, {skipped_count} existing / {total} total\n"
        )
    else:
        console.print(f"\n[error]✘[/error] Failed: {success_count}/{attempted} downloaded\n")

    if not is_batch:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
