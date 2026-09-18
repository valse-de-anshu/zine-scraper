"""
scrapers/light_novel/novelarchive/location.py
---------------------------------------------
Save-path resolver for NovelArchive novels.
"""

import sys
from pathlib import Path
from typing import Optional, Any


def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path],
                  default_root: Path, store_layer: Any) -> Optional[Path]:
    if is_batch and batch_path:
        return Path(batch_path)
        
    if not is_batch and sys.stdin.isatty():
        from core.ui import Selector, console, startup_clear, print_banner, get_theme_input_ansi
        import time

        state = 0
        status_choice = "OnGoing"
        tag_choice = "SFW"
        
        library_root = default_root.parent
        current_menu = "Quick grab" if "Quick grab" in default_root.parts else library_root.name
        
        if "Quick grab" in default_root.parts:
            return default_root

        if getattr(scraper, "title", None):
            novel_name = scraper.title
        else:
            url_parts = [p for p in url.strip('/').split('/') if p]
            novel_name = url_parts[-1] if url_parts else "unknown"

        def draw_header():
            startup_clear()
            print_banner()
            console.print(f"[menu]{'Menu':<12}:[/menu] [site]{current_menu}[/site]", overflow="ellipsis", no_wrap=True)
            console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]", overflow="ellipsis", no_wrap=True)
            console.print(f"[menu]{'Novel':<12}:[/menu] [title]{novel_name}[/title]", overflow="ellipsis", no_wrap=True)
            console.print("")

        while True:
            if state == 0:
                draw_header()
                ans = Selector(
                    [("OnGoing", "OnGoing"), ("Complete", "Complete"), ("Hiatus", "Hiatus"), ("Cancelled", "Cancelled"), ("Back", "BACK")], 
                    "Novel Status"
                ).select()
                
                if ans == "BACK":
                    return None
                status_choice = ans
                state = 1
                
            elif state == 1:
                draw_header()
                console.print(f"[menu]Status      :[/menu] [site]{status_choice}[/site]")
                ans = Selector(
                    [("SFW (Safe for Work)", "SFW"), ("NSFW (Not Safe for Work)", "NSFW"), ("Back", "BACK")], 
                    "Content Tag"
                ).select()
                
                if ans == "BACK":
                    state = 0
                    continue
                tag_choice = ans
                state = 2
                
            elif state == 2:
                draw_header()
                console.print(f"[menu]Status      :[/menu] [site]{status_choice}[/site]")
                console.print(f"[menu]Content Tag :[/menu] [site]{tag_choice}[/site]")
                choice = Selector([
                    ("Default Location", "DEFAULT"),
                    ("Select Custom Location", "CUSTOM"),
                    ("Back", "BACK")
                ], "Save Location").select()
                
                if choice == "BACK":
                    state = 1
                    continue
                
                if choice == "DEFAULT":
                    draw_header()
                    console.print(f"[menu]Status      :[/menu] [site]{status_choice}[/site]")
                    console.print(f"[menu]Content Tag :[/menu] [site]{tag_choice}[/site]")
                    console.print(f"[menu]Location    :[/menu] [site]Default[/site]\n")
                    final_path = default_root / tag_choice / status_choice
                    return final_path
                    
                if choice == "CUSTOM":
                    state = 3
                    
            elif state == 3:
                console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
                sys.stdout.write(get_theme_input_ansi())
                sys.stdout.flush()
                custom_path_str = input().strip()
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                if not custom_path_str:
                    state = 2
                    continue
                
                custom_path = Path(custom_path_str).expanduser().resolve()
                is_valid, err_msg = store_layer.validate_directory(custom_path)
                if not is_valid:
                    console.print(f"\n[error]Invalid directory.[/error]")
                    console.print(f"[warning]Reason:\n{err_msg}[/warning]")
                    time.sleep(2)
                    continue
                
                try:
                    custom_ln_root = custom_path / "Light Novel"
                    store_layer.create_directory(custom_ln_root)
                    final_path = store_layer.create_directory(custom_ln_root / tag_choice / status_choice / default_root.name)
                    draw_header()
                    console.print(f"[menu]Status      :[/menu] [site]{status_choice}[/site]")
                    console.print(f"[menu]Content Tag :[/menu] [site]{tag_choice}[/site]")
                    console.print(f"[menu]Location    :[/menu] [site]{final_path}[/site]\n")
                    return final_path
                except Exception as e:
                    console.print(f"\n[error]Error creating directory: {e}[/error]")
                    time.sleep(2)
                    continue

    # Fallback
    return default_root / "SFW" / "OnGoing"
