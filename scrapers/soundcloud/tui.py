"""
Site-specific TUI layer.
This file delegates presentation logic to the site workflow handler.
"""

import sys
import time
from .workflow import run_workflow
from core.ui import console, print_banner, startup_clear
from rich.panel import Panel
from rich.align import Align
from rich.text import Text

def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    if getattr(scraper, "is_banned_playlist", False):
        if not is_batch:
            startup_clear()
            print_banner()
            
            message = Text()
            message.append("\n  SoundCloud Playlists are Restricted  \n\n", style="bold #f7768e")
            message.append("The extraction flow for SoundCloud playlists has become a convoluted mess.\n", style="#7dcfff")
            message.append("Due to severe limitations, playlist downloading is no longer supported.\n\n", style="#565f89")
            message.append("Please feed the scraper single tracks instead.\n", style="bold #9ece6a")
            
            panel = Panel(
                Align.center(message),
                border_style="#f7768e",
                padding=(1, 2)
            )
            console.print("")
            console.print(panel)
            console.input("\n[info]Press Enter to return to the URL field...[/info]") if __import__("sys").stdin.isatty() else None
        else:
            console.print("[error]Skipping SoundCloud playlist in batch mode (Unsupported).[/error]")
            time.sleep(1.5)
        return

    custom_thumb_path = None
    if not is_batch and sys.stdin.isatty():
        from core.ui import Selector, get_theme_input_ansi, clear_lines
        from pathlib import Path
        
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]SoundCloud[/site]")
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]\n")
        
        while True:
            choice = Selector([
                ("Default Cover (Use SoundCloud artwork)", "default"),
                ("Custom Cover (Provide your own image)", "custom"),
                ("Back", "BACK")
            ], "Cover Art Preference").select()
            
            if choice == "BACK":
                return
            elif choice == "default":
                break
            elif choice == "custom":
                console.print("\n[menu]Enter Image File Path (Empty to cancel): [/menu]", end="")
                sys.stdout.write(get_theme_input_ansi())
                sys.stdout.flush()
                custom_path_str = input().strip()
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                
                if not custom_path_str:
                    clear_lines(3)
                    continue
                
                p = Path(custom_path_str)
                if not p.exists() or not p.is_file():
                    console.print(f"\n[error]Image file not found: {p}[/error]")
                    time.sleep(1.5)
                    clear_lines(6)
                    continue
                    
                custom_thumb_path = p
                break

    run_workflow(url, tracker, location_manager, scraper, batch_path=batch_path, is_batch=is_batch, custom_thumb_path=custom_thumb_path)
