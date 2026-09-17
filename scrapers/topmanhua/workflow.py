import json
import time
from pathlib import Path
from typing import Optional, Any
from rich.tree import Tree
from rich.live import Live
from rich.progress import Progress, TextColumn, TaskProgressColumn

from core.ui import (
    console, startup_clear, print_banner, active_status,
    MinimalPulseBar, set_active_live, filter_subchapters, apply_chapter_limit
)
from core.cache import save_url_to_file
from core.paths import ZineFolder, get_container_root
from butler.whistleblower import set_tui_callback

from .location import get_save_path
from .verification import verify_chapters
from .progress import render_completion_tree

_LIVE_INSTANCE = None
CHAPTER_DELAY = 0.5

def run_workflow(
    url: str,
    tracker: Any,
    location_manager: Any,
    scraper: Any,
    batch_path: Optional[Path] = None,
    is_batch: bool = False
):
    url = url.strip().rstrip("/")

    startup_clear()
    print_banner()

    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            title, chapters = scraper.get_title_and_chapters()
            scraper.title = title
            if hasattr(tracker, "set_title") and title:
                tracker.set_title(scraper.url, title)

            if not chapters and getattr(scraper, "is_chapter_link", lambda: False)():
                import re
                m_ch = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", url.lower())
                ch_num = m_ch.group(1).replace("-", ".") if m_ch else "1"
                chapters = [(ch_num, url)]
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                if __import__("sys").stdin.isatty():
                    console.input("\n[info]Press Enter to return...[/info]")
            else:
                time.sleep(1.5)
            return

    chapters = filter_subchapters(url, title, chapters, is_batch=is_batch)

    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_path:
        return

    if "Quick grab" in target_path.parts:
        idx = target_path.parts.index("Quick grab")
        folder = Path(*target_path.parts[:idx + 1])
    else:
        folder = ZineFolder(target_path) / title

    location_manager.create_directory(folder)
    save_url_to_file(url, title)

    # Save .zine metadata if not in Quick grab mode
    is_quick_grab = "Quick grab" in folder.parts or "Quick grab" in str(folder)
    if not is_quick_grab:
        zine_folder = folder / ".zine"
        location_manager.create_directory(zine_folder)
        meta_path = zine_folder / "meta.json"
        meta_data = {
            "title": title,
            "url": url,
            "category": next(
                (part for part in target_path.parts if part.lower() in ["ongoing", "completed", "complete"]),
                target_path.parts[-2] if len(target_path.parts) > 1 else target_path.name
            ),
            "source": getattr(scraper, "domain", "topmanhua.fan")
        }
        if getattr(scraper, "author", None):
            meta_data["author"] = scraper.author
        if getattr(scraper, "artist", None):
            meta_data["artist"] = scraper.artist
        if getattr(scraper, "description", None):
            meta_data["description"] = scraper.description
        if getattr(scraper, "genres", None):
            meta_data["genres"] = scraper.genres
        if getattr(scraper, "status", None):
            meta_data["status"] = scraper.status
        if getattr(scraper, "rating", None):
            meta_data["rating"] = scraper.rating
        if getattr(scraper, "release", None):
            meta_data["release"] = scraper.release

        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                updated = False
                for k, v in meta_data.items():
                    if k not in existing_data or existing_data[k] != v:
                        existing_data[k] = v
                        updated = True
                if updated:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(existing_data, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
        else:
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

    cover_exists = any(folder.glob("cover.*"))
    if is_quick_grab:
        cover_status_ui = None
    else:
        if not cover_exists:
            try:
                scraper.download_cover(folder)
                cover_exists = any(folder.glob("cover.*"))
            except Exception:
                pass
        cover_status_ui = cover_exists

    verified_nums, to_process = verify_chapters(folder, chapters, tracker, scraper.url)
    to_process = apply_chapter_limit(to_process, scraper)

    startup_clear()
    print_banner()
    if is_batch:
        console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    cat_display = f"{target_path.parts[-2]} ⬩➤ {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
    console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
    console.print(f"[menu]Folder[/menu]       : [sexy_pink]{target_path.resolve()}[/sexy_pink]")
    console.print("")

    render_completion_tree(
        title=title,
        folder=folder,
        source="Topmanhua",
        total_chapters=len(chapters),
        verified_nums=verified_nums,
        cover_exists=cover_status_ui
    )

    if not to_process:
        console.print("\n[success]All chapters are already downloaded and verified![/success]")
        if not is_batch:
            if __import__("sys").stdin.isatty():
                console.input("\n[info]Press Enter to return to main menu...[/info]")
        else:
            time.sleep(1.0)
        return

    # Whistleblower state
    wb_tracker = {
        "active_chapter": "",
        "downloaded_files": 0,
        "downloaded_bytes": 0,
        "failed_files": 0,
        "start_time": time.time(),
        "total_chapters": len(to_process),
        "completed_chapters": 0,
        "last_network_loss_time": 0,
        "network_loss_total_duration": 0
    }

    def whistleblower_callback():
        elapsed = time.time() - wb_tracker["start_time"]
        return {
            "site": "topmanhua",
            "url": url,
            "title": title,
            "category": cat_display,
            "folder": str(folder),
            "total_items": wb_tracker["total_chapters"],
            "downloaded_items": wb_tracker["completed_chapters"],
            "current_item": wb_tracker["active_chapter"],
            "item_unit": "chapters",
            "downloaded_files": wb_tracker["downloaded_files"],
            "downloaded_bytes": wb_tracker["downloaded_bytes"],
            "failed_files": wb_tracker["failed_files"],
            "elapsed_time": elapsed,
            "network_loss_duration": wb_tracker["network_loss_total_duration"]
        }

    set_tui_callback(whistleblower_callback)

    # Progress displays
    overall_progress = Progress(
        TextColumn("{task.description}"),
        MinimalPulseBar(bar_width=30),
        TaskProgressColumn(),
        console=console
    )

    overall_task = overall_progress.add_task("[accent]Overall Progress[/accent]", total=len(to_process))
    step_task = overall_progress.add_task("[progress]Downloading[/progress]", total=100, visible=False)

    def stats_callback(data):
        if data.get("type") == "file_done":
            wb_tracker["downloaded_files"] += 1
            wb_tracker["downloaded_bytes"] += data.get("size", 0)
        elif data.get("type") == "file_error":
            wb_tracker["failed_files"] += 1

    braille_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def make_renderable(active_num, step_text):
        tree = Tree(f"[title]◆ {title}[/title]")
        for num, _ in to_process:
            if num in verified_nums:
                tree.add(f"[success]● Chapter {num}[/success]")
            elif num == active_num:
                sub = tree.add(f"[accent]● Chapter {num}[/accent]")
                sub.add(f"[dim]{step_text}[/dim]")
            else:
                tree.add(f"[unselected]○ Chapter {num}[/unselected]")
        return tree

    global _LIVE_INSTANCE
    with Live(overall_progress, console=console, refresh_per_second=10) as live:
        _LIVE_INSTANCE = live
        set_active_live(live)

        for chapter_num, ch_url in to_process:
            wb_tracker["active_chapter"] = f"Chapter {chapter_num}"
            live.update(make_renderable(chapter_num, "Downloading images..."))

            res = None
            for retry_attempt in range(5):
                try:
                    res = scraper.process_chapter(
                        ch_url=ch_url,
                        folder=folder,
                        ch_num=chapter_num,
                        live=live,
                        overall_progress=overall_progress,
                        overall_task=overall_task,
                        step_task=step_task,
                        stats_callback=stats_callback
                    )
                    break
                except Exception as e:
                    err_msg = str(e).lower()
                    if any(w in err_msg for w in ["connection", "network", "timeout", "disconnected"]):
                        loss_start = time.time()
                        live.update(make_renderable(chapter_num, f"[warning]Network interrupted. Reconnecting (attempt {retry_attempt+1}/5)...[/warning]"))
                        time.sleep(3.0 * (retry_attempt + 1))
                        wb_tracker["network_loss_total_duration"] += (time.time() - loss_start)
                    else:
                        time.sleep(1.0)

            if res and res.get("success"):
                verified_nums.append(chapter_num)
                wb_tracker["completed_chapters"] += 1
                if hasattr(tracker, "mark_downloaded"):
                    tracker.mark_downloaded(scraper.url, chapter_num)
                overall_progress.advance(overall_task, 1)
                live.update(make_renderable(chapter_num, "Done"))
            else:
                live.update(make_renderable(chapter_num, "[error]Failed[/error]"))

            time.sleep(CHAPTER_DELAY)

    _LIVE_INSTANCE = None
    set_active_live(None)
    set_tui_callback(None)

    console.print("\n[success]❖ Download & Slicing Process Complete ❖[/success]")
    if not is_batch:
        if __import__("sys").stdin.isatty():
            console.input("\n[info]Press Enter to return to main menu...[/info]")
    else:
        time.sleep(1.0)
