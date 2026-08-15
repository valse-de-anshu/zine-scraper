import time
from pathlib import Path
from typing import Optional, List, Any
from core.ui import console, startup_clear, print_banner, MultiSelector, active_status
from core.cache import save_url_to_file
from core.paths import resolve_folder_collision

from .location import get_save_path
from .verification import verify_assets
from .progress import render_completion_tree

_LIVE_INSTANCE = None
CHAPTER_DELAY = 1.0

def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any, batch_path: Optional[Path] = None, is_batch: bool = False):
    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            pre_metadata, pre_assets = scraper.get_metadata_and_assets()
            title = pre_metadata.get("Title", "Unknown")
        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    from core.paths import get_container_root
    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager, metadata=pre_metadata)
    if not target_path:
        return
        
    save_url_to_file(url, title)
    is_vacuum = getattr(scraper, "get_link_type", lambda: "")() in ["author", "collection", "playlist"] or getattr(scraper, "is_playlist", False)
    if is_vacuum:
        platform_id = getattr(scraper, "book_id", "gutenberg") or "gutenberg"
        folder = resolve_folder_collision(target_path, title, platform_id)
        location_manager.create_directory(folder)
        cover_url = pre_metadata.pop("Cover URL", None)
        if cover_url:
            import requests
            try:
                r = requests.get(cover_url, stream=True, timeout=10)
                if r.status_code == 200:
                    with open(folder / "cover.jpg", "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
            except Exception:
                pass
    else:
        folder = target_path
        location_manager.create_directory(folder)
    
    verified_ids = verify_assets(folder, pre_assets, tracker, scraper.url)
    
    startup_clear()
    print_banner()
    if is_batch:
        console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    cat_display = f"{target_path.parts[-2]} / {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
    console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
    console.print(f"[menu]Folder[/menu]       : [sexy_pink]{target_path.resolve()}[/sexy_pink]")
    console.print("")
    
    render_completion_tree(title, folder, pre_metadata, verified_ids)
    
    if not pre_assets:
        console.print(f"[warning]No assets found for {url}[/warning]")
        return
        
    import sys
    if not is_batch and sys.stdin.isatty():
        options = list(pre_assets)
        options.append({
            "name": "Back",
            "url": "BACK",
            "title": "Back",
            "id": "BACK",
            "size_bytes": 0,
            "right_text": "",
            "is_action": True
        })
        selected_assets = MultiSelector(options, "Select Files to Download").select()
        if not selected_assets:
            console.print("[warning]No files selected.[/warning]")
            return
            
        if any(a.get("id") == "BACK" for a in selected_assets):
            return
            
        selected_assets = [a for a in selected_assets if a.get("id") != "BACK"]
    else:
        selected_assets = pre_assets
        if getattr(scraper, '_batch_quick_grab', False):
            selected_assets = selected_assets[:1]
        
    console.print("")
    for asset in selected_assets:
        asset_id = asset.get("id")
        filename = asset.get("filename", asset_id)
        link = asset.get("url")
        
        chapter_path = folder / filename
        is_in_history = tracker.is_downloaded(scraper.url, asset_id)
        file_exists = chapter_path.exists()
        
        if is_in_history and not file_exists:
            tracker.unmark_downloaded(scraper.url, asset_id)
            is_in_history = False
            
        if file_exists:
            if not is_in_history:
                tracker.mark_downloaded(scraper.url, asset_id)
            console.print(f"  [unselected]File exists: {filename}[/unselected]")
            continue
            
        progress_data = {
            "total_bytes": asset.get("size_bytes", 0),
            "downloaded_bytes": 0,
            "done": False,
            "success": False
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
        total_b = progress_data["total_bytes"] if progress_data["total_bytes"] > 0 else None
        task_id = progress_bar.add_task("Downloading", total=total_b)
        
        def render_asset_tree() -> Tree:
            tree = Tree(f"[menu]⬢ {filename}[/menu]")
            res_branch = tree.add("[menu]⬡ Result[/menu]")
            if not progress_data["done"]:
                import time
                blink_state = int(time.time() * 3) % 2
                ball_style = "warning" if blink_state == 0 else "unselected"
                res_branch.add(f"[{ball_style}]●[/{ball_style}] Downloading...")
            else:
                success = progress_data.get("success", False)
                res_color = "success" if success else "error"
                res_text = "Complete" if success else "Failed"
                res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
            return tree
            
        global _LIVE_INSTANCE
        with Live(render_asset_tree(), console=console, refresh_per_second=12, transient=True) as live:
            _LIVE_INSTANCE = live
            from core.ui import MinimalPulseBar, set_active_live
            set_active_live(live)
            
            def stats_callback(stats):
                progress_data.update(stats)
                try:
                    live.update(render_asset_tree())
                    
                except Exception:
                    pass
            
            live_active = [True]
            import threading
            def refresh_loop():
                import time
                while live_active[0]:
                    try:
                        live.update(render_asset_tree())
                    except Exception:
                        pass
                    time.sleep(0.1)
            threading.Thread(target=refresh_loop, daemon=True).start()
                    
            try:
                while True:
                    success = scraper.download_file(link, chapter_path, stats_callback=stats_callback)
                    if success:
                        tracker.mark_downloaded(scraper.url, asset_id)
                        progress_data["success"] = True
                        break
                    else:
                        from core.video_engine import handle_internet_loss

                        if not handle_internet_loss():
                            break
                            
                progress_data["done"] = True
                try:
                    live.update(render_asset_tree())
                except Exception:
                    pass
            finally:
                live_active[0] = False
                
        _LIVE_INSTANCE = None
        set_active_live(None)
        
        res_color = "success" if progress_data.get("success") else "error"
        console.print(f"  [{res_color}]●[/{res_color}] [unselected]{filename}[/unselected]")
        time.sleep(CHAPTER_DELAY)
        
    console.print(f"\n[success]✦[/success] Done\n")
    time.sleep(CHAPTER_DELAY)
    
    if not is_batch:
        console.input("\n[info]Download finished. Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None