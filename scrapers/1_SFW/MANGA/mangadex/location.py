"""
scrapers/mangadex/location.py
-----------------------------
Save-location resolver for MangaDex.
Owns folder routing and prompts for Manga / Toon library classification.
"""
import sys
import time
from pathlib import Path
from typing import Optional, Any
from core.ui import Selector, console, startup_clear, print_banner, get_theme_input_ansi

def get_save_path(
    url: str,
    scraper: Any,
    is_batch: bool,
    batch_path: Optional[Path],
    default_root: Path,
    store_layer: Any,
) -> Optional[Path]:
    if batch_path is not None:
        return Path(batch_path)

    library_root = default_root.parent
    site_folder = default_root.name
    current_menu = library_root.name

    if current_menu == "Quick grab":
        return default_root

    toon_name = getattr(scraper, "title", None) or "Manga"

    if is_batch or not sys.stdin.isatty():
        target_dir = library_root / "Toon" / "SFW" / "OnGoing" / site_folder
        store_layer.create_directory(target_dir)
        return target_dir

    def draw_header():
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{current_menu}[/site]", overflow="ellipsis", no_wrap=True)
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]", overflow="ellipsis", no_wrap=True)
        console.print(f"[menu]{'Manga':<12}:[/menu] [title]{toon_name}[/title]", overflow="ellipsis", no_wrap=True)
        console.print("")

    state = 0
    type_choice = None
    status_choice = None

    while True:
        if state == 0:
            draw_header()
            choice = Selector([("SFW", "SFW"), ("NSFW", "NSFW"), ("Back", "BACK")], "Type").select()
            if choice == "BACK":
                return None
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            type_choice = choice
            state = 1
        elif state == 1:
            draw_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
            choice = Selector([("Ongoing", "OnGoing"), ("Complete", "Completed"), ("Back", "BACK")], "Status").select()
            if choice == "BACK":
                state = 0
                continue
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            status_choice = choice
            state = 2
        elif state == 2:
            draw_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
            console.print(f"[menu]{'Status':<12}:[/menu] [site]{status_choice}[/site]")
            choice = Selector([
                ("Use Default Location", "DEFAULT"),
                ("Select Custom Location", "CUSTOM"),
                ("Back", "BACK")
            ], "Save Location").select()
            if choice == "BACK":
                state = 1
                continue
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            elif choice == "DEFAULT":
                draw_header()
                console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
                console.print(f"[menu]{'Status':<12}:[/menu] [site]{status_choice}[/site]")
                console.print(f"[menu]{'Location':<12}:[/menu] [site]Default[/site]\n")
                target_dir = library_root / "Toon" / type_choice / status_choice / site_folder
                try:
                    store_layer.create_directory(target_dir)
                    return target_dir
                except Exception as e:
                    console.print(f"\n[error]Error creating directory: {e}[/error]")
                    time.sleep(2)
                    return None
            elif choice == "CUSTOM":
                state = 3
        elif state == 3:
            console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
            sys.stdout.write(get_theme_input_ansi())
            sys.stdout.flush()
            custom_path_str = input().strip()
            sys.stdout.write("\033[0m")
            sys.stdout.flush()

            if not custom_path_str:
                for _ in range(2):
                    sys.stdout.write("\033[1A\033[2K")
                sys.stdout.flush()
                state = 2
                continue

            is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
            if is_valid:
                target_dir = Path(custom_path_str).resolve()
                draw_header()
                console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
                console.print(f"[menu]{'Status':<12}:[/menu] [site]{status_choice}[/site]")
                console.print(f"[menu]{'Location':<12}:[/menu] [site]{target_dir}[/site]\n")
                return target_dir
            else:
                console.print(f"\n[error]{err_msg}[/error]")
                time.sleep(2)
                for _ in range(3):
                    sys.stdout.write("\033[1A\033[2K")
                sys.stdout.flush()
                continue
