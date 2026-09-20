"""
scrapers/hanime/location.py
-----------------------------
Save-location resolver for Hanime.
Mirrors youtube/location.py — handles default and custom path selection.

Key rule: Never create a new folder for an existing creator.
  resolve_folder_collision() in core/paths.py enforces this via simple title matching.
"""

import sys
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
    """
    Resolves the save root for a Hanime scrape session.
    Returns None if user goes Back, or the confirmed Path.
    """
    if batch_path is not None:
        return Path(batch_path)

    loc_choice = Selector(
        [
            ("Use Default Location", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK"),
        ],
        "Save Location",
    ).select()

    if loc_choice == "BACK":
        return None
    if loc_choice == "toggle":
        return "toggle"
    if loc_choice == "DEFAULT":
        return default_root

    # CUSTOM branch
    import time
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
            for _ in range(6):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue

        try:
            custom_base = Path(custom_path_str)
            is_vacuum = getattr(scraper, "get_link_type", lambda: "")() in ["model", "franchise", "playlist"]
            custom_ph_root = (custom_base / "hanime") if is_vacuum else custom_base
            store_layer.create_directory(custom_ph_root)
            for _ in range(2):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            return custom_ph_root
        except Exception as e:
            console.print(f"\n[error]Error creating directory: {e}[/error]")
            time.sleep(2)
            for _ in range(4):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue
