"""
scrapers/light_novel/novelphoenix/workflow.py
---------------------------------------------
NovelPhoenix download workflow.
"""

import time
import json
from pathlib import Path
from typing import Optional, Any

from core.ui import console, startup_clear, print_banner, active_status, set_active_live
from core.cache import save_url_to_file
from core.paths import ZineFolder

from .location import get_save_path
from .verification import verify_chapters
from .progress import render_completion_tree

_LIVE_INSTANCE = None
CHAPTER_DELAY = 0.3


def run_workflow(url: str, tracker: Any, location_manager: Any, scraper: Any,
                 batch_path: Optional[Path] = None, is_batch: bool = False):
    url = url.strip().rstrip("/")
    
    is_chapter = getattr(scraper, "is_chapter_link", lambda: False)()
    if is_chapter:
        scraper._single_chapter_only = True

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
                    _is_chapter = any(x in url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/"])
                    
            if not chapters and _is_chapter:
                import re
                m = re.search(r"chapter-([\d]+(?:[\.-][\d]+)?)", url.lower())
                if m:
                    num = m.group(1).replace("-", ".")
                else:
                    parts = [p for p in url.strip('/').split('/') if p]
                    num = parts[-1] if parts else "1"
                    num = re.sub(r"[^\d.]", "", num)
                    if not num: num = "1"
                
                chapters = [(num, url)]

        except Exception as e:
            console.print(f"[error]Failed to fetch metadata: {e}[/error]")
            if not is_batch:
                console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
            else:
                time.sleep(1.5)
            return

    from core.ui import filter_subchapters
    chapters = filter_subchapters(url, title, chapters, is_batch=is_batch)

    if getattr(scraper, "_single_chapter_only", False):
        url_normalized = url.rstrip("/")
        filtered = [ch for ch in chapters if ch[1].rstrip("/") == url_normalized]
        if not filtered:
            import re
            m = re.search(r"chapter-([\d\.]+)", url_normalized)
            if m:
                ch_target = m.group(1)
                filtered = [ch for ch in chapters if ch[0] == ch_target]
        if filtered:
            chapters = filtered

        from core.paths import get_container_root
        default_root = get_container_root(url, scraper, is_batch, batch_path)
        target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
        if not target_path:
            return
        if "Quick grab" in target_path.parts:
            idx = target_path.parts.index("Quick grab")
            folder = Path(*target_path.parts[:idx+1])
        else:
            folder = ZineFolder(target_path)
        location_manager.create_directory(folder)
        save_url_to_file(url, title)
        is_quick_grab = True
    else:
        from core.paths import get_container_root
        default_root = get_container_root(url, scraper, is_batch, batch_path)
        target_path = get_save_path(url, scraper, is_batch, batch_path, default_root, location_manager)
        if not target_path:
            return

        is_quick_grab = "Quick grab" in str(target_path)

        if "Quick grab" in target_path.parts:
            idx = target_path.parts.index("Quick grab")
            folder = Path(*target_path.parts[:idx+1])
        else:
            folder = ZineFolder(target_path) / title
            
        location_manager.create_directory(folder)
        save_url_to_file(url, title)

    # ── .zine metadata ───────────────────────────────────────────────────────
    if not is_quick_grab:
        zine_folder = folder / ".zine"
        location_manager.create_directory(zine_folder)
        meta_path = zine_folder / "meta.json"

        meta_data = {
            "title":    title,
            "url":      scraper.series_url,
            "source":   scraper.domain,
            "status":   getattr(scraper, "status", "Unknown"),
        }
        if getattr(scraper, "author", None):
            meta_data["author"] = scraper.author
        if getattr(scraper, "description", None):
            meta_data["description"] = scraper.description
        if getattr(scraper, "genres", None):
            meta_data["genres"] = scraper.genres
        if getattr(scraper, "tags", None):
            meta_data["tags"] = scraper.tags
        if getattr(scraper, "rating", None):
            meta_data["rating"] = scraper.rating
        if getattr(scraper, "type", None):
            meta_data["type"] = scraper.type
        if getattr(scraper, "alt_titles", None):
            meta_data["alt_titles"] = scraper.alt_titles
        if chapters:
            meta_data["total_chapters"] = len(chapters)

        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                updated = False
                for k, v in meta_data.items():
                    if k not in existing or existing[k] != v:
                        existing[k] = v
                        updated = True
                if updated:
                    with open(meta_path, "w", encoding="utf-8") as f:
                        json.dump(existing, f, indent=4, ensure_ascii=False)
            except Exception:
                pass
        else:
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

    # ── Cover ────────────────────────────────────────────────────────────────
    cover_exists = any((folder / f"cover{ext}").exists() for ext in [".jpg", ".png", ".webp", ".jpeg", ".avif"])
    if not is_quick_grab and not cover_exists:
        cover_url = getattr(scraper, "cover_url", "")
        if cover_url:
            with active_status("[info]Cover...[/info]", spinner="dots"):
                cover_exists = scraper.download_cover(cover_url, folder)

    cover_status_ui = None if is_quick_grab else cover_exists

    # ── Verify existing chapters ─────────────────────────────────────────────
    verified_nums, to_process = verify_chapters(folder, chapters, tracker, scraper.series_url)

    # ── Initial TUI header ───────────────────────────────────────────────────
    startup_clear()
    print_banner()
    if is_batch:
        console.print(f"[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    cat_display = (
        f"{target_path.parts[-2]} ⬩➤ {target_path.parts[-1]}"
        if len(target_path.parts) >= 2 else str(target_path)
    )
    console.print(f"[menu]Category[/menu]     : [site]{cat_display}[/site]")
    console.print(f"[menu]Novel[/menu]        : [title]{title}[/title]")
    console.print("")

    render_completion_tree(title, folder, scraper.domain, len(chapters),
                           verified_nums, cover_status_ui)

    if not to_process:
        console.print("\n[success]All chapters are already downloaded and verified.[/success]")
        if not is_batch:
            console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
        else:
            time.sleep(1.0)
        return

    # ── Download Loop ────────────────────────────────────────────────────────
    total = len(chapters)
    processed = len(verified_nums)

    for ch_num, ch_url in to_process:
        res = scraper.process_chapter(ch_url, folder, ch_num)
        if res.get("success"):
            tracker.mark_downloaded(scraper.series_url, ch_num)
            verified_nums.append(ch_num)
            processed += 1
            words_info = f"({res.get('words', 0)} words)" if res.get("words") else ""
            console.print(
                f"[site]{scraper.domain}[/site] ── [title]Chapter {ch_num}[/title] ── "
                f"[success]Done[/success] {words_info} ── [unselected]({processed}/{total})[/unselected]"
            )
        else:
            console.print(
                f"[site]{scraper.domain}[/site] ── [title]Chapter {ch_num}[/title] ── "
                f"[error]Failed[/error] ── [unselected]({processed}/{total})[/unselected]"
            )

        time.sleep(CHAPTER_DELAY)

    console.print(f"\n[success]Download complete: {title}[/success]")
    if not is_batch:
        console.input("\n[info]Press Enter to return...[/info]") if __import__("sys").stdin.isatty() else None
    else:
        time.sleep(1.5)
