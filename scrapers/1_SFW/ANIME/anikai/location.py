from pathlib import Path
from typing import Optional, Any


def get_save_path(
    url: str, scraper: Any, is_batch: bool,
    batch_path: Optional[Path], default_root: Path, store_layer: Any
) -> Optional[Path]:
    """
    For batch/headless runs return the pre-computed batch_path.
    For interactive Vacuum downloads, launch the Anime Import Wizard.
    Quick-grab falls straight through without prompting.
    """
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

        zine_root = default_root.parent.parent   # …/Zine
        return zine_root / "Anime" / path
    else:
        # Quick-grab: no prompt needed
        return default_root
