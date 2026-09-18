import sys
import time
from pathlib import Path
from typing import Optional, Any
from core.ui import console, Selector, get_theme_input_ansi
from core.ui import clear_lines

def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any) -> Optional[Path]:
    if batch_path is not None:
        return batch_path
        
    category = default_root.parent.name
    
    if category == "Vacuum":
        from core.import_tui import CategoryImportTUI
        from core.anime_categories import CATEGORIES
        
        tui = CategoryImportTUI(CATEGORIES, title="ZINE SCRAPER · Anime Import Wizard")
        path = tui.run()
        if not path:
            return None
            
        zine_root = default_root.parent.parent
        return zine_root / "Anime" / path
    else:
        # Quick grab goes straight to the folder without prompting.
        return default_root
