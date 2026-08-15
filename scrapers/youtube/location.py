import sys
from pathlib import Path
from typing import Optional, Any
from core.ui import Selector, get_theme_input_ansi, console

def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any) -> Optional[Path]:
    if batch_path is not None:
        return Path(batch_path)

    is_single = getattr(scraper, "get_link_type", lambda: "")() == "single" or getattr(scraper, "is_playlist", False) is False
    if is_single:
        from core.config import ConfigLayer
        from core.paths import PathAuthority
        cfg = ConfigLayer(PathAuthority(), store_layer)
        if cfg.get("music_quick_grab_path"):
            return default_root

    if not is_batch and sys.stdin.isatty():
        loc_choice = Selector([
            ("Use Default Location", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK")
        ], "Save Location").select()
    else:
        loc_choice = "DEFAULT"

    if loc_choice == "BACK":
        return None

    if loc_choice == "DEFAULT":
        return default_root

    if loc_choice == "toggle":
        return "toggle"

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
            import time
            time.sleep(2)
            for _ in range(6):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue

        try:
            custom_base = Path(custom_path_str)
            is_single = getattr(scraper, "get_link_type", lambda: "")() == "single" or getattr(scraper, "is_playlist", False) is False
            custom_yt_root = custom_base if is_single else (custom_base / "youtube")
            store_layer.create_directory(custom_yt_root)
            for _ in range(2):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            return custom_yt_root
        except Exception as e:
            console.print(f"\n[error]Error creating directory: {e}[/error]")
            import time
            time.sleep(2)
            for _ in range(4):
                sys.stdout.write("\033[1A\033[2K")
            sys.stdout.flush()
            continue
