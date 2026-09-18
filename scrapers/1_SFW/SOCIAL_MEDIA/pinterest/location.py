import sys
import time
from pathlib import Path
from typing import Optional, Any
from core.ui import Selector, get_theme_input_ansi, console

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

    if not is_batch and sys.stdin.isatty():
        from core.ui import startup_clear, print_banner
        startup_clear()
        print_banner()
        
        display_url = url
        profile_name = "Unknown"
        import re
        m = re.search(r"pinterest\.[a-z\.]+/([^/?#]+)", url)
        if m:
            profile_name = m.group(1)
            if profile_name == "pin":
                profile_name = "Single Pin"
            elif profile_name == "board" or profile_name == "boards":
                profile_name = "Board"
                
        console.print(f"[menu]Site[/menu]         : [title]Pinterest[/title]")
        console.print(f"[menu]Profile[/menu]      : [title]{profile_name}[/title]")
        console.print(f"[menu]URL[/menu]          : [unselected]{display_url}[/unselected]")
        console.print(f"[menu]Save Path[/menu]    : [info]{default_root}[/info]\n")
        
        loc_choice = Selector([
            ("Use Default Location", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK"),
        ], "Save Location").select()
    else:
        loc_choice = "DEFAULT"

    if loc_choice == "BACK":
        return None
    if loc_choice == "DEFAULT":
        return default_root

    # CUSTOM branch
    while True:
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
            return None

        is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
        if not is_valid:
            console.print(f"\n[error]Invalid directory.[/error]")
            console.print(f"[warning]Reason:\n{err_msg}[/warning]")
            time.sleep(2)
            for _ in range(4):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue
        
        # Pinterest custom paths behave like toon paths (no subfolder creation by core)
        return Path(custom_path_str)
