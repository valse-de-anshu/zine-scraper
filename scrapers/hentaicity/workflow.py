"""
scrapers/hentaicity/workflow.py
---------------------------------
Download loop for HentaiCity.

Handles two content types:
  video   → Blinking-circle TUI + yt-dlp/aria2c download
  gallery → Concurrent image download with blinking-circle TUI
"""

import re
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.ui import (
    console, align_header, set_active_live,
    CustomDownloadColumn, MbpsColumn, CustomTimeRemainingColumn,
)
from core.history import HistoryLayer
from rich.live import Live
from rich.tree import Tree
from rich.layout import Layout
from rich.panel import Panel

_LIVE_INSTANCE = None
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
    from scrapers.hentaicity.engine import HentaicityEngine

    engine: HentaicityEngine = scraper.engine
    content_type = metadata.get("Content Type", "video")
    series_title = metadata.get("Channel/Series", "Unknown")

    ext = "mp4" if content_type == "video" else "jpg"

    # ── Paths ─────────────────────────────────────────────────────────────
    if is_vacuum:
        clean = re.sub(r'[<>:"/\\|?*]', "", series_title).strip() or "Series"
        creator_root = target_root / clean
        creator_root.mkdir(parents=True, exist_ok=True)
        sub_folder = creator_root
    else:
        target_root.mkdir(parents=True, exist_ok=True)
        sub_folder = target_root

    # ── Metadata tree ─────────────────────────────────────────────────────
    root_tree = Tree(f"[site]◆[/site] [title]{series_title}[/title]", guide_style="unselected")
    root_tree.add(align_header("Location", f"[unselected]{sub_folder}[/unselected]"))
    root_tree.add(align_header("Source",   "[site]HentaiCity[/site]"))
    root_tree.add(align_header("Total",    f"[info]{len(videos)} {'videos' if content_type == 'video' else 'images'}[/info]"))
    console.print(root_tree)
    console.print(" ")

    # ── Verification ─────────────────────────────────────────────────────
    from scrapers.hentaicity.verification import verify_videos
    tracker.sync_local_history(sub_folder, videos, ext, url)

    # ── Save metadata (vacuum only) ───────────────────────────────────────
    if is_vacuum:
        try:
            engine.save_metadata(
                root_dir=creator_root,
                info=info,
                source="HentaiCity",
                model_name=series_title,
                avatar_url=metadata.get("Avatar URL", ""),
                videos=videos,
                skip_cover=(content_type == "gallery"),
                custom_metadata=metadata,
            )
        except Exception as e:
            logger.warning(f"HentaiCity: metadata save failed: {e}")

    # ── TUI reconstructor ─────────────────────────────────────────────────
    from butler.whistleblower import set_tui_callback
    completed_history: list = []

    def tui_reconstruct():
        from core.ui import startup_clear, print_banner
        import core.ui as ui_module
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]Hentai[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]")
        console.print(f"[menu]{'Series':<12}:[/menu] [title]{series_title}[/title]")
        console.print(root_tree)
        console.print(" ")
        for h in completed_history:
            console.print(h)
        username = __import__("getpass").getuser()
        console.print(f"  [error]✘ Connection lost! I've got your back, {username}... pausing.[/error]")
        console.print(f"  [success]● Connection restored, resuming...[/success]")

    set_tui_callback(tui_reconstruct)

    # ══════════════════════════════════════════════════════════════════════
    #  GALLERY mode
    # ══════════════════════════════════════════════════════════════════════
    if content_type == "gallery":
        _run_gallery_workflow(
            engine=engine,
            videos=videos,
            sub_folder=sub_folder,
            series_title=series_title,
            completed_history=completed_history,
            tracker=tracker,
            url=url,
        )
        return

    # ══════════════════════════════════════════════════════════════════════
    #  VIDEO mode
    # ══════════════════════════════════════════════════════════════════════
    for idx, video in enumerate(videos, 1):
        vid_url   = video.get("url", "")
        vid_title = video.get("title", f"Video {idx}")
        vid_id    = video.get("id", str(idx))
        pre_stream = video.get("stream_url", "")

        if not vid_url:
            continue

        # Resolve output path
        vid_sub_folder = sub_folder
        if is_vacuum and getattr(scraper, "franchise_structure", "flat") == "nested":
            clean_title = re.sub(r'[<>:"/\\|?*]', "", vid_title).strip() or vid_id
            vid_sub_folder = creator_root / clean_title
            vid_sub_folder.mkdir(parents=True, exist_ok=True)

        resolved_path, is_done = tracker.resolve_download_path(
            vid_sub_folder, vid_id, vid_title, ext
        )
        display_name = resolved_path.name

        if is_done:
            tracker.mark_downloaded(url, vid_id)
            hist = f"  [unselected]●[/unselected] [unselected]File exists: {display_name}[/unselected]"
            console.print(hist)
            completed_history.append(hist)
            continue

        # ── Progress state ────────────────────────────────────────────────
        progress_data = {
            "total_bytes":      0,
            "downloaded_bytes": 0,
            "done":    False,
            "success": False,
            "status":  "Extracting stream...",
            "baking":  False,
            "speed":   0,
            "eta":     None,
            "retry":   0,
        }

        def render_video_tree() -> Tree:
            tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
            tree.add(align_header("Current", vid_title))
            if is_vacuum:
                tree.add(align_header("Folder", f"[site]{vid_sub_folder.name}[/site]"))
            tree.add(align_header("Retry", f"[warning]{progress_data['retry']}[/warning]"))
            res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

            if not progress_data["done"]:
                total      = progress_data["total_bytes"]
                downloaded = min(progress_data["downloaded_bytes"], total) if total > 0 else progress_data["downloaded_bytes"]

                is_100 = (total > 0 and downloaded >= total)
                is_90  = (total > 0 and downloaded >= total * 0.9)

                if progress_data.get("baking") or is_100:
                    blink = int(time.time() * 6) % 3
                    style = ["success", "white", "unselected"][blink]
                    res_branch.add(f"[{style}]●[/{style}] Almost done with baking...")
                elif is_90:
                    blink = int(time.time() * 6) % 3
                    style = ["success", "white", "unselected"][blink]
                    res_branch.add(f"[{style}]●[/{style}] Downloading (Almost done)...")
                else:
                    blink = int(time.time() * 3) % 2
                    style = "warning" if blink == 0 else "unselected"
                    status = progress_data["status"] if progress_data["status"] != "Downloading" else "Downloading..."
                    res_branch.add(f"[{style}]●[/{style}] {status}")
            else:
                ok    = progress_data.get("success", False)
                color = "success" if ok else "error"
                text  = "Complete" if ok else "Failed"
                res_branch.add(f"[{color}]● {text}[/{color}]")

            return tree

        # ── yt-dlp hook ───────────────────────────────────────────────────
        completed_files: dict = {}

        def yt_dlp_hook(d):
            status = d.get("status", "")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                speed = d.get("speed") or 0
                eta = d.get("eta")
                if total:
                    progress_data["total_bytes"] = total
                progress_data["downloaded_bytes"] = downloaded
                progress_data["speed"] = speed
                progress_data["eta"] = eta
                progress_data["status"] = "Downloading"
                fn = d.get("filename", "")
                if fn:
                    completed_files[fn] = False
            elif status == "finished":
                fn = d.get("filename", "")
                if fn:
                    completed_files[fn] = True
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or progress_data["total_bytes"]
                if total:
                    progress_data["total_bytes"] = total
                    progress_data["downloaded_bytes"] = total
                progress_data["baking"] = True
                progress_data["status"] = "Almost done with baking..."

        # ── Live TUI ──────────────────────────────────────────────────────
        global _LIVE_INSTANCE
        _stop = [False]

        with Live(render_video_tree(), refresh_per_second=8, console=console, transient=True) as live:
            _LIVE_INSTANCE = live
            set_active_live(live)

            import threading

            def _refresh():
                while not _stop[0]:
                    try:
                        live.update(render_video_tree())
                    except Exception:
                        pass
                    time.sleep(0.13)

            t = threading.Thread(target=_refresh, daemon=True)
            t.start()

            try:
                success = engine.download_hentaicity_video(
                    page_url=vid_url,
                    output_dir=vid_sub_folder,
                    progress_hook=yt_dlp_hook,
                    fixed_title=vid_title,
                    fixed_artist="HentaiCity",
                    pre_extracted_stream=pre_stream,
                )
            except Exception as e:
                logger.error(f"HentaiCity workflow: download error: {e}")
                success = False
            finally:
                _stop[0] = True
                t.join(timeout=1)

            progress_data["done"] = True
            progress_data["success"] = success
            progress_data["baking"] = False
            live.update(render_video_tree())

        set_active_live(None)
        _LIVE_INSTANCE = None

        if success:
            tracker.mark_downloaded(url, vid_id)
            hist = f"  [success]●[/success] {display_name}"
        else:
            hist = f"  [error]●[/error] {display_name}"

        console.print(hist)
        completed_history.append(hist)

    console.print(" ")
    console.print("[success]✦ Done[/success]")
    console.print(" ")


# ══════════════════════════════════════════════════════════════════════════
#  Gallery download helper
# ══════════════════════════════════════════════════════════════════════════

def _run_gallery_workflow(engine, videos, sub_folder, series_title, completed_history, tracker, url):
    """
    Downloads gallery images like the manga scrapers:
      - Each image saved as 001.jpg, 002.jpg, ... (zero-padded, no stitching)
      - 8 concurrent threads
      - Blinking-circle TUI showing X / total
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    image_urls = [v["url"] for v in videos]
    total = len(image_urls)

    sub_folder.mkdir(parents=True, exist_ok=True)

    progress_data = {
        "downloaded": 0,
        "failed":     0,
        "total":      total,
        "done":       False,
        "success":    False,
    }
    lock = threading.Lock()

    def render_gallery_tree() -> Tree:
        tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
        res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")

        done_n  = progress_data["downloaded"]
        fail_n  = progress_data["failed"]

        if not progress_data["done"]:
            blink = int(time.time() * 3) % 2
            style = "warning" if blink == 0 else "unselected"
            res_branch.add(f"[{style}]●[/{style}] Downloading... {done_n}/{total}")
        else:
            ok    = progress_data.get("success", False)
            color = "success" if ok else "warning"
            fail_txt = f"  ({fail_n} failed)" if fail_n else ""
            text  = f"Complete — {done_n}/{total} images{fail_txt}"
            res_branch.add(f"[{color}]● {text}[/{color}]")

        return tree

    def _download_one(idx: int, img_url: str) -> bool:
        # Determine extension from URL (strip query params)
        ext = img_url.rsplit(".", 1)[-1].split("?")[0].lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = "jpg"
        # Zero-pad based on total count width
        width = len(str(total))
        filename = f"{idx:0{width}d}.{ext}"
        path = sub_folder / filename

        if path.exists() and path.stat().st_size > 0:
            with lock:
                progress_data["downloaded"] += 1
            return True

        # Delegate to engine so proxy can intercept it!
        success = engine.download_hentaicity_image(img_url, path)
        if success:
            with lock:
                progress_data["downloaded"] += 1
            return True
        else:
            with lock:
                progress_data["failed"] += 1
            return False

    _stop = [False]

    with Live(render_gallery_tree(), refresh_per_second=8, console=console, transient=True) as live:
        set_active_live(live)

        def _refresh():
            while not _stop[0]:
                try:
                    live.update(render_gallery_tree())
                except Exception:
                    pass
                time.sleep(0.13)

        t = threading.Thread(target=_refresh, daemon=True)
        t.start()

        try:
            with ThreadPoolExecutor(max_workers=16) as pool:
                futures = {
                    pool.submit(_download_one, idx, img_url): idx
                    for idx, img_url in enumerate(image_urls, 1)
                }
                for future in as_completed(futures):
                    future.result()  # surface exceptions if any
        except Exception as e:
            logger.error(f"HentaiCity gallery pool error: {e}")
        finally:
            _stop[0] = True
            t.join(timeout=1)

        success = progress_data["failed"] == 0
        progress_data["done"]    = True
        progress_data["success"] = success
        live.update(render_gallery_tree())

    set_active_live(None)

    dl_count = progress_data["downloaded"]
    fail_n   = progress_data["failed"]

    if success:
        hist = f"  [success]●[/success] {series_title} — {dl_count}/{total} images"
    else:
        hist = f"  [warning]●[/warning] {series_title} — {dl_count}/{total} images ({fail_n} failed)"

    console.print(hist)
    completed_history.append(hist)
    console.print(" ")
    console.print("[success]✦ Done[/success]")
    console.print(" ")

