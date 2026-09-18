import sys
from pathlib import Path
from typing import Optional, Any

def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any) -> Optional[Path]:
    from core.ui import get_toon_save_path
    return get_toon_save_path(url, scraper, is_batch, batch_path, default_root, store_layer)
