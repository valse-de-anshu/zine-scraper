import time
import json
import html
from pathlib import Path
from typing import Optional, Tuple, List, Any
from core.ui import (
    console, startup_clear, print_banner, Selector, MultiSelector,
    active_status, set_active_live, apply_chapter_limit, filter_subchapters
)
from core.cache import save_url_to_file
from core.paths import ZineFolder, get_container_root

from .location import get_save_path
from .verification import verify_chapters
from .progress import render_completion_tree
from .scraper import LANGUAGE_NAMES

_LIVE_INSTANCE = None
CHAPTER_DELAY = 0.5

def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any, batch_path: Optional[Path] = None, is_batch: bool = False):
    url = url.strip().rstrip("/")
    
    startup_clear()
    print_banner()

    with active_status("[info]Metadata...[/info]", spinner="dots"):
        try:
            title, chapters = scraper.get_title_and_chapters()
            
            _is_chapter = False
            if not chapters:
                if hasattr(scraper, "is_chapter_link"):
                    _is_chapter = scraper.is_chapter_link()
                else:
                    _is_chapter = "chapter" in url.lower()
                    
            if not chapters and _is_chapter:
                import re
                m = re.search(r"/chapter/([0-9a-fA-F\-]{36})", url)
                ch_id = m.group(1) if m else "1"
                chapters = [("1", url)]

        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    # Immediately register authentic manga title into history tracker
    if title:
        tracker.set_title(scraper.url, title)

    default_root = get_container_root(url, scraper, is_batch, batch_path)
    target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
    if not target_path:
        return
        
    if "Quick grab" in target_path.parts:
        idx = target_path.parts.index("Quick grab")
        base_folder = Path(*target_path.parts[:idx+1])
    else:
        base_folder = ZineFolder(target_path) / title
    location_manager.create_directory(base_folder)
    save_url_to_file(url, title)

    # ── Interactive Multi-Language Selection ─────────────────────────────────
    import sys
    available_langs = getattr(scraper, "available_languages", []) or []
    
    chosen_langs = []
    if not scraper.is_chapter_link():
        if len(available_langs) > 1 and not is_batch and sys.stdin.isatty():
            startup_clear()
            print_banner()
            if is_batch:
                console.print("[menu]Menu[/menu]         : [site]Batch Mode[/site]")
            console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
            cat_display = f"{target_path.parts[-2]} ⬩➤ {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
            console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
            console.print(f"[menu]Folder[/menu]       : [sexy_pink]{target_path.resolve()}[/sexy_pink]")
            console.print(f"[menu]Manga[/menu]        : [title]{title}[/title]")
            console.print("")

            other_langs = [l for l in available_langs if l != "en"]
            other_langs.sort(key=lambda l: LANGUAGE_NAMES.get(l, l.upper()))
            ordered_langs = (["en"] if "en" in available_langs else []) + other_langs

            lang_options = []
            for l in ordered_langs:
                lang_display = LANGUAGE_NAMES.get(l, l.upper())
                lang_options.append({
                    "name": lang_display,
                    "desc": f"Language [{l}]",
                    "right_text": f"[{l}]",
                    "lang": l,
                    "size_bytes": 0,
                })
            lang_options.append({
                "name": "Back",
                "desc": "Cancel selection",
                "right_text": "",
                "lang": "BACK",
                "size_bytes": 0,
                "is_action": True
            })

            selected_items = MultiSelector(lang_options, "Select Languages to Download").select()
            if not selected_items or any(item.get("lang") == "BACK" for item in selected_items):
                return
            chosen_langs = [item["lang"] for item in selected_items if item.get("lang") and item["lang"] != "BACK"]
            if not chosen_langs:
                chosen_langs = ["en" if "en" in available_langs else available_langs[0]]
        elif available_langs:
            chosen_langs = ["en" if "en" in available_langs else available_langs[0]]
        else:
            chosen_langs = ["en"]
    else:
        chosen_langs = [getattr(scraper, "chosen_language", "en") or "en"]

    # Hide terminal cursor throughout the entire downloading workflow
    console.show_cursor(False)
    try:
        for lang_idx, chosen_lang in enumerate(chosen_langs, 1):
            scraper.chosen_language = chosen_lang
            lang_display_name = LANGUAGE_NAMES.get(chosen_lang, chosen_lang.upper())
            lang_display = f"{lang_display_name} [{chosen_lang}]"

            if len(chosen_langs) > 1:
                if "Quick grab" in target_path.parts:
                    folder = base_folder / f"{title} [{chosen_lang}]"
                else:
                    folder = base_folder.parent / f"{title} [{chosen_lang}]"
            else:
                folder = base_folder
            location_manager.create_directory(folder)

            if not scraper.is_chapter_link():
                with active_status(f"[info]Loading chapters ({lang_display_name})...[/info]", spinner="dots"):
                    chapters = scraper.get_chapters_for_language(chosen_lang)

            if not chapters:
                console.print(f"[warning]No downloadable chapters found for {lang_display_name}.[/warning]")
                continue

            chapters = filter_subchapters(url, title, chapters, is_batch=is_batch, scraper=scraper)

            # Create .zine metadata folder if not in Quick grab mode
            is_quick_grab = "Quick grab" in folder.parts or "Quick grab" in str(folder)
            if not is_quick_grab:
                zine_folder = folder / ".zine"
                location_manager.create_directory(zine_folder)
                meta_path = zine_folder / "meta.json"
                
                meta_data = {
                    "title": f"{title} [{chosen_lang}]" if len(chosen_langs) > 1 else title,
                    "url": getattr(scraper, "url", url),
                    "category": next((part for part in target_path.parts if part.lower() in ["ongoing", "completed", "complete"]), target_path.parts[-2] if len(target_path.parts) > 1 else target_path.name),
                    "source": getattr(scraper, "domain", "mangadex.org"),
                    "language": chosen_lang
                }
                if getattr(scraper, "author", None):
                    meta_data["author"] = scraper.author
                if getattr(scraper, "artist", None):
                    meta_data["artist"] = scraper.artist
                if getattr(scraper, "description", None):
                    meta_data["description"] = scraper.description
                if getattr(scraper, "status", None):
                    meta_data["status"] = scraper.status
                if getattr(scraper, "tags", None):
                    meta_data["tags"] = scraper.tags
                if getattr(scraper, "genres", None):
                    meta_data["genres"] = scraper.genres

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
            if "Quick grab" in target_path.parts:
                cover_status_ui = None
            else:
                if not cover_exists:
                    try:
                        scraper.download_cover(folder)
                        cover_exists = any(folder.glob("cover.*"))
                    except Exception:
                        pass
                cover_status_ui = cover_exists

            track_url = f"{scraper.url}#{chosen_lang}" if len(chosen_langs) > 1 else scraper.url
            verified_nums, to_process = verify_chapters(folder, chapters, tracker, track_url)
            to_process = apply_chapter_limit(to_process, scraper)

            startup_clear()
            print_banner()
            if is_batch:
                console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
            console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
            cat_display = f"{target_path.parts[-2]} ⬩➤ {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
            console.print(f"[menu]Category[/menu]     : [info]{cat_display}[/info]")
            console.print(f"[menu]Folder[/menu]       : [sexy_pink]{folder.resolve()}[/sexy_pink]")
            console.print("")
            
            render_completion_tree(title, folder, default_root.name, len(chapters), verified_nums, cover_status_ui, language=lang_display)
            
            completed_history = []

            # Bulletproof TUI Reconstruction Callback
            from butler.whistleblower import set_tui_callback
            def tui_reconstruct():
                from core.ui import startup_clear, print_banner
                startup_clear()
                print_banner()
                if is_batch:
                    console.print("[menu]Menu[/menu]         : [site]Batch Mode[/site]")
                console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
                cat_disp = f"{target_path.parts[-2]} ⬩➤ {target_path.parts[-1]}" if len(target_path.parts) > 1 else target_path.name
                console.print(f"[menu]Category[/menu]     : [info]{cat_disp}[/info]")
                console.print(f"[menu]Folder[/menu]       : [sexy_pink]{folder.resolve()}[/sexy_pink]")
                console.print("")
                render_completion_tree(title, folder, default_root.name, len(chapters), verified_nums, cover_status_ui, language=lang_display)
                for hist in completed_history:
                    console.print(hist)
                    
                username = __import__('getpass').getuser()
                console.print(f"  [error]✘ Connection lost! I've got your back, {username}...[/error]")
                console.print(f"  [success]● Connection restored, starting the engine please wait...[/success]")
                
                import core.ui as ui_module
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
            
            if not to_process:
                console.print(f"[success]All chapters for {lang_display_name} are already downloaded.[/success]\n")
                continue

            console.print(" ")
            console.print(" ")
            success_count = 0

            from rich.tree import Tree
            from rich.live import Live
            from rich.progress import Progress, TextColumn, TaskProgressColumn
            from core.ui import MinimalPulseBar

            for ch_num, link in to_process:
                chapter_folder = folder / f"Chapter{ch_num}"
                location_manager.create_directory(chapter_folder)

                page_data = {
                    "total":      0,
                    "downloaded": 0,
                    "retry":      0,
                    "missing":    0,
                    "done":       False,
                    "success":    False,
                    "status":     "loading",
                }

                progress_bar = Progress(
                    TextColumn("[progress.description]{task.description}"),
                    MinimalPulseBar(bar_width=40),
                    TaskProgressColumn(),
                    TextColumn("{task.completed}/{task.total} pages"),
                    transient=False,
                )
                task_id = progress_bar.add_task("Downloading", total=None)

                def render_chapter_tree() -> Tree:
                    tree = Tree(f"[info]●[/info] [menu]Progress[/menu]", guide_style="unselected")
                    tree.add(f"{'Current':<14}: ch{ch_num}")
                    tree.add(f"{'Total Pages':<14}: [sexy_pink]{page_data['total'] or '?'}[/sexy_pink]")
                    tree.add(f"{'Downloaded':<14}: [success]{page_data['downloaded']}[/success]")
                    tree.add(f"{'Retry':<14}: [warning]{page_data['retry']}[/warning]")
                    tree.add(f"{'Missing':<14}: [error]{page_data['missing']}[/error]")
                    res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")
                    if not page_data["done"]:
                        if page_data.get("status") == "baking":
                            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                            frame = frames[int(time.time() * 10) % len(frames)]
                            res_branch.add(f"[success]{frame}[/success] [sexy_pink]almost done with baking...[/sexy_pink]")
                        elif page_data.get("status") == "loading" or page_data["total"] == 0:
                            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                            frame = frames[int(time.time() * 10) % len(frames)]
                            res_branch.add(f"[info]{frame}[/info] [info]Loading chapter stream...[/info]")
                        else:
                            total = page_data["total"] if page_data["total"] > 0 else None
                            progress_bar.update(task_id, total=total, completed=page_data["downloaded"])
                            res_branch.add(progress_bar)
                    else:
                        success = page_data.get("success", False)
                        res_color = "success" if success else "error"
                        res_text = "Complete" if success else f"Failed ({page_data.get('status', 'Error')})"
                        res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
                    return tree

                for attempt in range(1, 4):
                    page_data["retry"] = attempt - 1
                    if attempt > 1:
                        time.sleep(2)

                    _chapter_error = [None]

                    global _LIVE_INSTANCE
                    with Live(get_renderable=render_chapter_tree, console=console, refresh_per_second=12, transient=True) as live:
                        _LIVE_INSTANCE = live
                        set_active_live(live)

                        def stats_callback(stats: dict):
                            page_data.update(stats)

                        try:
                            result = scraper.process_chapter(
                                link, ZineFolder(chapter_folder), ch_num,
                                live=live, stats_callback=stats_callback
                            )
                            if isinstance(result, dict):
                                page_data.update(result)
                                if result.get("success"):
                                    tracker.mark_downloaded(track_url, ch_num, title=title)
                                    page_data["done"] = True
                                    page_data["success"] = True
                                    success_count += 1
                            elif result:
                                tracker.mark_downloaded(track_url, ch_num, title=title)
                                page_data["done"] = True
                                page_data["success"] = True
                                success_count += 1
                        except Exception as e:
                            _chapter_error[0] = e
                            page_data["status"] = str(e)

                    _LIVE_INSTANCE = None
                    set_active_live(None)

                    if page_data.get("success"):
                        break

                    if _chapter_error[0] is not None:
                        from core.video_engine import handle_internet_loss
                        if not handle_internet_loss():
                            break
                    else:
                        break

                res_color = "success" if page_data.get("success") else "error"
                console.print(f"  [{res_color}]●[/{res_color}] [unselected]Chapter {ch_num}[/unselected]")
                completed_history.append(f"  [{res_color}]●[/{res_color}] [unselected]Chapter {ch_num}[/unselected]")
                from core.ui import check_revolt
                if check_revolt():
                    return
                time.sleep(CHAPTER_DELAY)

            if success_count > 0:
                console.print(f"\n[success]✦[/success] Done: {success_count}/{len(to_process)} chapters saved for {lang_display_name}\n")
            else:
                console.print(f"\n[error]✘[/error] Failed: No chapters saved for {lang_display_name}\n")

    finally:
        console.show_cursor(True)
        if not is_batch:
            console.input("\n[info]Download finished. Press Enter to return...[/info]") if sys.stdin.isatty() else None
