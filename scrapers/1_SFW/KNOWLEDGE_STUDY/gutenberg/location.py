import sys
import time
from pathlib import Path
from typing import Optional
from core.ui import console, Selector, get_theme_input_ansi
from core.ui import clear_lines

def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any, metadata: dict = None) -> Optional[Path]:
    if batch_path is not None:
        return batch_path
        
    category = default_root.parent.name
    site_folder = default_root.name
    
    if not is_batch and sys.stdin.isatty():
        from core.ui import startup_clear, print_banner
        startup_clear()
        print_banner()
        console.print(f"[menu]URL[/menu]          : [info]{url}[/info]")
        console.print(f"[menu]Category[/menu]     : [info]{category} / {site_folder}[/info]")
        console.print(f"[menu]Folder[/menu]       : [unselected]{default_root}[/unselected]\n")
        
        if metadata:
            title = metadata.get("Title", "Unknown")
            author = metadata.get("Author", "Unknown")
            lang = metadata.get("Language", "Unknown")
            ebook_id = metadata.get("Ebook ID", "Unknown")
            subjects = metadata.get("Subjects", "Unknown")
            
            console.print(f"[site]◆ {title}[/site]")
            console.print(f"[tree.line]├──[/tree.line] [site]❖[/site] [menu]Location[/menu]         : [info]{default_root}[/info]")
            console.print(f"[tree.line]├──[/tree.line] [menu]Source[/menu]             : [unselected]gutenberg.org[/unselected]")
            console.print(f"[tree.line]├──[/tree.line] [menu]Author[/menu]             : [unselected]{author}[/unselected]")
            console.print(f"[tree.line]├──[/tree.line] [menu]Language[/menu]           : [unselected]{lang}[/unselected]")
            console.print(f"[tree.line]├──[/tree.line] [menu]Ebook ID[/menu]           : [unselected]{ebook_id}[/unselected]")
            
            # Truncate subjects if too long
            if len(subjects) > 60:
                subjects = subjects[:57] + "..."
                
            console.print(f"[tree.line]├──[/tree.line] [menu]Subjects[/menu]           : [unselected]{subjects}[/unselected]")
            console.print(f"[tree.line]└──[/tree.line] [menu]Cover[/menu]              : [unselected]● Extracted[/unselected]\n")

    while True:
        loc_choice = Selector([
            (f"Use Default Location ({category}/{site_folder})", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK")
        ], "Save Location").select()
        if loc_choice == "BACK":
            return None
        if loc_choice == "DEFAULT":
            return default_root
        elif loc_choice == "CUSTOM":
            console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
            sys.stdout.write(get_theme_input_ansi())
            sys.stdout.flush()
            custom_path_str = input().strip()
            sys.stdout.write("\033[0m")
            sys.stdout.flush()
            if not custom_path_str:
                clear_lines(2)
                continue
            is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
            if not is_valid:
                console.print(f"\n[error]Invalid directory.[/error]")
                console.print(f"[warning]Reason:\n{err_msg}[/warning]")
                time.sleep(2)
                clear_lines(6)
                continue
            clear_lines(2)
            return Path(custom_path_str)
