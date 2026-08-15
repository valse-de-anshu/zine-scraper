import re
import time
import signal
import logging
import requests
from pathlib import Path
from typing import Optional, List, Any
from core.ui import console, startup_clear, print_banner, active_status
from core.cache import save_url_to_file
from core.paths import resolve_folder_collision, PathAuthority

from .verification import verify_videos
from .progress import render_completion_tree

logger = logging.getLogger(__name__)

_LIVE_INSTANCE = None
CHAPTER_DELAY = 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_library_root() -> Path:
    """Returns the configured Zine library root (cross-platform, reads settings.json)."""
    paths = PathAuthority()
    library_root = paths.get_downloads_root()
    config_file = paths.get_config_file()
    if config_file.exists():
        try:
            import json
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_base = data.get("download_base")
                if custom_base:
                    library_root = Path(custom_base)
        except Exception:
            pass
    return library_root


def _safe_title(raw: str) -> str:
    """
    Sanitise a title for use as a folder name, keeping spaces and common
    punctuation.  This is the single canonical function — call it everywhere
    so folder names stay consistent across re-runs and mirror sites.
    """
    return "".join(c for c in raw if c.isalnum() or c in " .-_()").strip() or "Unknown Anime"


def _find_existing_series_folder(miruro_root: Path, title: str) -> Optional[Path]:
    """
    Search for an existing series folder whose normalised name matches *title*.
    This prevents duplicate folders when the same series is re-scraped from a
    different miruro mirror (e.g. mirurotv.to vs miruro.me).
    Normalised = lowercase, no spaces, no punctuation.
    """
    def norm(s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower())

    target = norm(title)
    if miruro_root.exists():
        for d in miruro_root.iterdir():
            if d.is_dir() and norm(d.name) == target:
                return d
    return None


def _fetch_hls_qualities(master_url: str, headers: dict) -> list:
    """
    Fetches a master HLS playlist and returns available quality dicts sorted
    highest-first: [{'label': '1080p', 'bandwidth': N, 'resolution': 'WxH', 'url': '...'}, ...]
    Returns [] if the URL is already a media playlist (not a master).
    """
    from urllib.parse import urljoin
    try:
        r = requests.get(master_url, headers=headers, timeout=10)
        r.raise_for_status()
        if "#EXT-X-STREAM-INF" not in r.text:
            return []
        streams = []
        lines = r.text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-STREAM-INF:"):
                bw_m = re.search(r'BANDWIDTH=(\d+)', line)
                res_m = re.search(r'RESOLUTION=(\d+x\d+)', line)
                bandwidth = int(bw_m.group(1)) if bw_m else 0
                resolution = res_m.group(1) if res_m else ""
                if i + 1 < len(lines):
                    uri = lines[i + 1].strip()
                    height = int(resolution.split('x')[1]) if 'x' in resolution else 0
                    label = f"{height}p" if height else f"{bandwidth // 1000}kbps"
                    streams.append({
                        "label": label,
                        "bandwidth": bandwidth,
                        "resolution": resolution,
                        "url": urljoin(master_url, uri),
                    })
        return sorted(streams, key=lambda s: s["bandwidth"], reverse=True)
    except Exception as e:
        logger.debug(f"[Miruro] Could not fetch HLS qualities: {e}")
        return []


def _download_subtitles(subtitles: list, video_path: Path, headers: dict):
    """
    Downloads subtitle tracks and saves them inside a 'Subtitles/' subfolder
    next to the episode file, named  {video_stem}.{lang}.vtt|srt.

    mpv  → add  --sub-file-paths=Subtitles  to ~/.config/mpv/mpv.conf
    VLC  → Preferences → Subtitles → Sub search paths → add 'Subtitles'
    Jellyfin / Kodi auto-scan subdirectories by default.
    """
    sub_dir = video_path.parent / "Subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)
    for sub in subtitles:
        sub_url = sub.get("url", "")
        label = sub.get("label", "unknown").lower().replace(" ", "-")
        if not sub_url:
            continue
        try:
            ext = ".vtt" if ".vtt" in sub_url else ".srt"
            sub_path = sub_dir / f"{video_path.stem}.{label}{ext}"
            r = requests.get(sub_url, headers=headers, timeout=15)
            r.raise_for_status()
            sub_path.write_bytes(r.content)
            logger.info(f"[Miruro] Saved subtitle: {sub_path.name}")
        except Exception as e:
            logger.warning(f"[Miruro] Failed to download subtitle '{label}': {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main workflow
# ─────────────────────────────────────────────────────────────────────────────

def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any,
                 batch_path: Optional[Path] = None, is_batch: bool = False):
    is_music = getattr(scraper, "scraper_type", "manga") == "music"

    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            metadata, videos, info = scraper.get_metadata_and_videos()
            title = metadata.get("Channel/Series", "Unknown")
        except KeyboardInterrupt:
            from core.ui import clean_exit
            clean_exit(forceful=True)
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    # ── Mode: whole series vs single episode ─────────────────────────
    is_single_episode = False
    import sys
    
    # Auto-detect if URL specifies a single episode (contains ?ep=)
    is_single_ep_url = False
    if "?ep=" in url:
        is_single_ep_url = True

    if not is_batch and sys.stdin.isatty() and len(videos) > 1:
        from core.ui import Selector
        startup_clear()
        print_banner()
        choice = Selector(
            [("Download whole series", "whole"), ("Download single episode", "single")],
            title="Mode",
            vertical=True
        ).select()
        if choice == "single":
            if "?ep=" in url:
                ep_num = url.split("?ep=")[-1]
                target_videos = [v for v in videos if v["url"].endswith(f"?ep={ep_num}")]
                if not target_videos:
                    target_videos = [v for v in scraper.get_metadata_and_videos()[1]
                              if v["url"].endswith(f"?ep={ep_num}")]
                if target_videos:
                    videos = target_videos
                    
            if len(videos) > 1:
                # If they pasted a category URL, ask them which episode to download
                startup_clear()
                print_banner()
                options = [(v.get("title", f"Episode {i+1}"), v) for i, v in enumerate(videos)]
                selected_vid = Selector(options, title="Select Episode", vertical=True).select()
                videos = [selected_vid]
                
            metadata["Total Videos"] = 1
            scraper.is_playlist = False
            is_single_episode = True
        else:
            scraper.is_playlist = True
    else:
        # Headless, batch, or redirected stdin mode
        if getattr(scraper, "_batch_quick_grab", False):
            if is_single_ep_url:
                target_videos = []
                if "?ep=" in url:
                    ep_num = url.split("?ep=")[-1].split("&")[0]
                    target_videos = [v for v in videos if f"?ep={ep_num}" in v["url"] or f"ep={ep_num}" in v["url"]]
                if target_videos:
                    videos = target_videos
            else:
                videos = videos[:1]
            metadata["Total Videos"] = 1
            scraper.is_playlist = False
            is_single_episode = True
        else:
            scraper.is_playlist = True
            is_single_episode = False

        # ── Determine save folder ─────────────────────────────────────────
    library_root = _get_library_root()
    miruro_root = library_root / "Vacuum" / "Anime" / "miruro"

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
            miruro_root = batch_path
            tui_rel_path = Path("")
            chosen_quality_url = None
        else:
            from core.import_tui import CategoryImportTUI
            from core.anime_categories import CATEGORIES

            def probe_qualities():
                probe_video = videos[0] if videos else None
                if probe_video and hasattr(scraper, 'resolve_episode_stream'):
                    try:
                        ps = scraper.resolve_episode_stream(probe_video)
                        probe_m3u8 = ps.get('m3u8_url') if ps else None
                        if probe_m3u8:
                            # Cache the probe stream so ep1 doesn't re-resolve
                            scraper._cached_probe_stream = ps
                            qualities = _fetch_hls_qualities(probe_m3u8, scraper.engine.headers)
                            if not qualities:
                                qualities = [{'label': 'Source', 'url': probe_m3u8}]
                            return qualities
                    except Exception:
                        pass
                return []

            if __import__("sys").stdin.isatty() and not is_batch:
                tui = CategoryImportTUI(CATEGORIES, title="ZINE SCRAPER · Anime Import Wizard")
                res = tui.run()
                if not res or (isinstance(res, tuple) and res[0] is None):
                    return

                if isinstance(res, tuple):
                    tui_rel_path, chosen_quality_url = res
                else:
                    tui_rel_path = res
                    chosen_quality_url = None
            else:
                tui_rel_path = Path("TV/Season 1")
                chosen_quality_url = None

        # ── Build final folder path, reuse existing if mirror-dup ────
        safe_title = _safe_title(title)
        existing = _find_existing_series_folder(miruro_root, title)
        series_root = existing if existing else (miruro_root / safe_title)
        folder = series_root / tui_rel_path
        location_manager.create_directory(folder)

        save_url_to_file(url, title, silent=False)

        # Cover in series root (not season subfolder)
        cover_url = metadata.get("Thumbnail")

        ext = ".jpg"

        if cover_url:

            from urllib.parse import urlparse

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

        # Metadata in series root .zine/
        try:
            import json
            zine_dir = series_root / ".zine"
            zine_dir.mkdir(parents=True, exist_ok=True)
            custom_metadata = {
                "title": title,
                "tags": [t.strip() for t in metadata.get("Genres", "").split(",")
                         if t.strip()] if metadata.get("Genres") else [],
                "description": metadata.get("Description", ""),
                "source": metadata.get("Source", "Miruro"),
                "anime_id": metadata.get("ID", "Unknown"),
                "thumbnail": metadata.get("Thumbnail"),
                "total_episodes": metadata.get("Total Videos", 0),
                "url": url,
            }
            with open(zine_dir / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(custom_metadata, f, indent=4)
        except Exception as e:
            console.print(f"[warning]Failed to save .zine/metadata.json: {e}[/warning]")

        ext_str = "flac" if is_music else "mp4"
        verified_ids = verify_videos(folder, videos, ext_str, tracker, scraper.url)

    ext_str = "flac" if is_music else "mp4"

    # ── Header log ────────────────────────────────────────────────────
    startup_clear()
    print_banner()
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    console.print(f"[menu]Category[/menu]     : [info]{tui_rel_path}[/info]")
    console.print("")

    if not is_single_episode:
        render_completion_tree(title, folder, metadata, verified_ids, cover_exists)
    else:
        from rich.tree import Tree
        def _align(label: str, value: Any) -> str:
            return f"{label:<18} : {value}"
        tree = Tree(f"[title]◆ {title} (Single Episode)[/title]")
        tree.add(_align("❖ Location", f"[sexy_pink]{folder}[/sexy_pink]"))
        tree.add(_align("Source", f"[info]{metadata.get('Source', 'Miruro')}[/info]"))
        console.print(tree)
        console.print("")

    if not videos:
        console.print(f"[warning]No videos found for {url}[/warning]")
        return

    try:
        from butler.part_cleaner import clean_part_files
        clean_part_files(folder, videos, tracker, scraper.url)
    except Exception:
        pass

    success_count = 0
    skipped_count = 0   # existing files — not a failure
    
    # ── Smart domain ranker: probe all mirrors once in parallel ─────────
    # All confirmed Miruro mirrors
    ALL_MIRURO_DOMAINS = [
        "www.miruro.to",
        "www.miruro.ru",
        "www.miruro.tv",
        "www.miruro.bz",
    ]
    
    import threading, time as _t
    _domain_rank = []   # filled once below, sorted fastest→slowest
    _rank_lock = threading.Lock()

    def _ping_domain(domain):
        """Returns (latency_ms, domain) or (inf, domain) if dead."""
        try:
            import requests as _req
            t0 = _t.monotonic()
            r = _req.get(f"https://{domain}/", timeout=5, allow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code < 500:
                return (_t.monotonic() - t0) * 1000, domain
        except Exception:
            pass
        return float("inf"), domain

    def _rank_domains():
        results = [None] * len(ALL_MIRURO_DOMAINS)
        def _worker(i, d):
            results[i] = _ping_domain(d)
        threads = [threading.Thread(target=_worker, args=(i, d), daemon=True)
                   for i, d in enumerate(ALL_MIRURO_DOMAINS)]
        for t in threads: t.start()
        for t in threads: t.join(timeout=6)
        ranked = sorted([r for r in results if r], key=lambda x: x[0])
        with _rank_lock:
            _domain_rank.clear()
            _domain_rank.extend([d for _, d in ranked if _ < float("inf")])
            # Dead ones go last as last-resort
            _domain_rank.extend([d for _, d in ranked if _ == float("inf")])
        logger.info(f"[Miruro] Domain rank: {_domain_rank}")

    # Fire the rank probe in background — it runs while the TUI is loading
    _rank_thread = threading.Thread(target=_rank_domains, daemon=True)
    _rank_thread.start()

    # Track which domain actually worked during downloading (runtime override)
    working_domain = [None]
    # Pre-fetch cache: resolve next episode in background while current downloads
    prefetch_cache = {}   # {vid_id: stream_info or None}
    prefetch_lock = threading.Lock()

    def _prefetch_stream(episode, domain):
        eid = episode.get("id")
        try:
            result = scraper.resolve_episode_stream(episode, force_domain=domain)
            with prefetch_lock:
                prefetch_cache[eid] = result
        except Exception:
            with prefetch_lock:
                prefetch_cache[eid] = None

    def _get_miruro_domains(vid_url_str):
        from urllib.parse import urlparse as _up
        orig = _up(vid_url_str).netloc
        
        # Wait up to 1s for the background rank probe to finish
        _rank_thread.join(timeout=1)
        
        with _rank_lock:
            base = list(_domain_rank) if _domain_rank else list(ALL_MIRURO_DOMAINS)
        
        # If we confirmed a working domain during this session, always use it first
        if working_domain[0]:
            if working_domain[0] in base:
                base.remove(working_domain[0])
            base.insert(0, working_domain[0])
        
        # Ensure the URL's original domain is somewhere in the list
        if orig not in base:
            base.insert(0, orig)
        
        return base

    for idx, video in enumerate(videos, 1):
        vid_id    = video.get("id")
        vid_title = video.get("title")
        vid_url   = video.get("url")

        resolved_file_path, is_in_verified = tracker.resolve_download_path(
            folder, str(vid_id), vid_title, ext_str, url=vid_url)
        display_name = resolved_file_path.name

        if is_in_verified:
            sub_dir = folder / "Subtitles"
            has_subs = sub_dir.exists() and any(sub_dir.glob(f"{resolved_file_path.stem}*"))
            if not has_subs and is_single_episode:
                console.print(f"  [info]Video exists, fetching missing subtitles...[/info]")
            else:
                tracker.mark_downloaded(scraper.url, str(vid_id))
                console.print(f"  [unselected]File exists: {display_name}[/unselected]")
                skipped_count += 1
                continue

        # ── Per-episode progress state ────────────────────────────────
        progress_data = {
            "phase": "resolving",   # resolving → downloading → baking → done
            "total_bytes": 0,
            "downloaded_bytes": 0,
            "done": False,
            "success": False,
            "status": "Resolving stream...",
            "current_title": vid_title,
            "retry": 0,
            "speed": 0.0,
        }

        from rich.tree import Tree
        from rich.live import Live
        from rich.progress import Progress, TextColumn, TaskProgressColumn, DownloadColumn
        from core.ui import MinimalPulseBar, MbpsColumn, set_active_live

        # Exact progress bar once we know total bytes
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
                import time
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
                success = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text  = "Complete" if success else f"Failed ({progress_data.get('status', 'Error')})"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
            return tree

        import core.ui as ui

        def _sigint_handler(sig, frame):
            try:
                live.stop()
            except Exception:
                pass
            from core.ui import clean_exit
            clean_exit(forceful=True)

        old_sigint = signal.signal(signal.SIGINT, _sigint_handler)
        ui._REVOLT_LISTENER_ACTIVE = True

        global _LIVE_INSTANCE
        with Live(render_video_tree(), console=console, refresh_per_second=12,
                  transient=True) as live:
            _LIVE_INSTANCE = live
            from core.ui import MinimalPulseBar, set_active_live
            set_active_live(live)            
            live_active = [True]
            import threading
            def refresh_loop():
                import time
                while live_active[0]:
                    try:
                        live.update(render_video_tree())
                    except Exception:
                        pass
                    time.sleep(0.1)
            threading.Thread(target=refresh_loop, daemon=True).start()

            def stats_callback(stats):
                """
                Called by the HLS downloader and yt-dlp subprocess parser.
                We update phase here so the renderer shows the right widget.
                """
                progress_data.update(stats)
                # Once we have a locked total, switch to 'downloading' phase
                if progress_data.get("total_bytes", 0) > 0:
                    if progress_data.get("phase") not in ("baking", "done"):
                        progress_data["phase"] = "downloading"
                try:
                    live.update(render_video_tree())
                except Exception:
                    pass

            # miruro.bz is the only mirror confirmed to load headlessly.
            # Keep .to as fallback.
            miruro_domains = _get_miruro_domains(vid_url)

            domain_success = False
            for target_domain in miruro_domains:
                if domain_success:
                    break

                # ── Check prefetch cache first, fall back to live resolve ──
                raw_stream_url = None
                referer = None
                stream_info = None
                progress_data["phase"] = "resolving"
                progress_data["status"] = f"Trying {target_domain}..."
                live.update(render_video_tree())

                # Use cached probe stream for ep1 (avoids double Playwright launch)
                cached = None
                if idx == 1 and hasattr(scraper, '_cached_probe_stream') and scraper._cached_probe_stream:
                    cached = scraper._cached_probe_stream
                    scraper._cached_probe_stream = None  # consume once
                
                # Use prefetch result if available
                with prefetch_lock:
                    if vid_id in prefetch_cache:
                        cached = prefetch_cache.pop(vid_id)

                if cached and cached.get("m3u8_url"):
                    stream_info = cached
                    raw_stream_url = cached["m3u8_url"]
                    referer = cached.get("referer")
                elif hasattr(scraper, "resolve_episode_stream"):
                    try:
                        stream_info = scraper.resolve_episode_stream(video, force_domain=target_domain)
                        if stream_info and stream_info.get("m3u8_url"):
                            raw_stream_url = stream_info["m3u8_url"]
                            referer = stream_info.get("referer")
                    except Exception:
                        pass

                if hasattr(scraper, "resolve_episode_stream") and not raw_stream_url:
                    progress_data["status"] = f"Failed on {target_domain}"
                    continue
                else:
                    if referer:
                        scraper.engine.headers["Referer"] = referer
                        scraper.engine.headers["Origin"]  = referer.rstrip("/")

                    # ── Pick quality for this episode ────────────────────────────
                    effective_stream_url = raw_stream_url
                    if chosen_quality_url and raw_stream_url:
                        try:
                            ep_qualities = _fetch_hls_qualities(raw_stream_url, scraper.engine.headers)
                            if ep_qualities:
                                chosen_res = re.search(r'(\d{3,4})x(\d{3,4})', chosen_quality_url)
                                chosen_h   = int(chosen_res.group(2)) if chosen_res else 0
                                if chosen_h:
                                    best = next((q for q in ep_qualities
                                                 if f"{chosen_h}p" == q["label"]), None)
                                    if best:
                                        effective_stream_url = best["url"]
                        except Exception:
                            pass

                    # ── Download subtitles NOW while the CDN token is still fresh ──
                    # The token in s1.watami.win URLs is time-limited — if we wait until
                    # after the video finishes downloading (minutes later) it will 403.
                    _subs = stream_info.get("subtitles", []) if stream_info else []
                    logger.info(f"[Miruro] Detected subtitles: {_subs}")
                    if _subs:
                        _download_subtitles(_subs, resolved_file_path, scraper.engine.headers)

                    # ── Wrap stats_callback to inject baking phase ───────────────
                    def baking_callback():
                        """Called by _download_custom_hls when ffmpeg starts."""
                        progress_data["phase"] = "baking"
                        try:
                            live.update(render_video_tree())
                        except Exception:
                            pass

                    progress_data["phase"] = "downloading"
                    progress_data["status"] = ""
                    live.update(render_video_tree())
                
                    if is_in_verified:
                        progress_data["success"] = True
                        progress_data["done"] = True
                        tracker.mark_downloaded(scraper.url, str(vid_id))
                        domain_success = True
                        continue

                    for attempt in range(1, 4):
                        if attempt > 1:
                            progress_data["retry"] = attempt - 1
                            time.sleep(2)
                        try:
                            success = scraper.engine.download_video(
                                vid_url, folder, stats_callback,
                                raw_stream_url=effective_stream_url,
                                is_audio=is_music,
                                custom_thumbnail=None,
                                fixed_title=vid_title,
                                fixed_artist=None,
                                format_override="best[ext=mp4]/best",
                                baking_callback=baking_callback,
                            )
                            if success:
                                tracker.mark_downloaded(scraper.url, str(vid_id))
                                progress_data["success"] = True
                                progress_data["done"]    = True
                                success_count += 1
                                domain_success = True
                                # Remember this domain so next episode uses it first
                                working_domain[0] = target_domain
                                # Pre-fetch next episode stream in background
                                next_videos = [v for v in videos if v.get("id") != vid_id]
                                if next_videos:
                                    next_ep = next_videos[0]
                                    nid = next_ep.get("id")
                                    with prefetch_lock:
                                        already = nid in prefetch_cache
                                    if not already:
                                        threading.Thread(
                                            target=_prefetch_stream,
                                            args=(next_ep, target_domain),
                                            daemon=True
                                        ).start()
                                break
                            else:
                                # Engine failed completely — don't retry same dead domain
                                break
                        except Exception as e:
                            progress_data["status"] = str(e)
                            from core.video_engine import handle_internet_loss
                            if not handle_internet_loss():
                                break
                                
            if not domain_success:
                # [WEB CROSS-SCRAPER FALLBACK]
                from scrapers.anikoto.cross_scraper import fallback_cross_scraper
                import re
                
                ep_match = re.search(r'ep(?:isode)?\s*-?\s*(\d+)', vid_title, re.IGNORECASE)
                if not ep_match:
                    ep_match = re.search(r'ep-(\d+)', vid_url)
                ep_num = int(ep_match.group(1)) if ep_match else idx
                
                console.print(f"\n[warning]❖ Core Reroute Engine Engaged[/warning]")
                console.print(f"[sexy_pink]╰─ Automatically shifting source to Anikoto...[/sexy_pink]\n")
                
                web_success = fallback_cross_scraper(
                    failed_title=metadata.get("Channel/Series", vid_title),
                    failed_episode=ep_num,
                    folder=folder,
                    stats_callback=stats_callback,
                    progress_data=progress_data
                )
                
                if web_success:
                    tracker.mark_downloaded(scraper.url, str(vid_id))
                    progress_data["success"] = True
                    success_count += 1
                else:
                    progress_data["status"] = "All alternative domains & Web Fallback failed"
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
        console.print(f"  [{res_color}]●[/{res_color}] [unselected]{display_name}[/unselected]")
        time.sleep(CHAPTER_DELAY)

        # ── Revolt check ─────────────────────────────────────────────
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT == 0:
                console.print("[warning]● Revolt shutdown triggered. Exiting cleanly...[/warning]\n")
                import sys; sys.exit(0)
            else:
                ui._REVOLT_LIMIT -= 1

    # ── Summary ───────────────────────────────────────────────────────
    total = len(videos)
    attempted = total - skipped_count
    if success_count > 0 or (skipped_count == total):
        # All done or all already existed
        console.print(f"\n[success]✦[/success] Finalized: "
                      f"{success_count} new, {skipped_count} existing / {total} total\n")
    else:
        console.print(f"\n[error]✘[/error] Failed: {success_count}/{attempted} downloaded\n")

    if not is_batch:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
