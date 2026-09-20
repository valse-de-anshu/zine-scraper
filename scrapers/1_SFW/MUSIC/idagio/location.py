from pathlib import Path
from typing import Optional, Any

def get_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any) -> Optional[Path]:
    """Resolve and return the save path for Idagio downloads."""
    if batch_path is not None:
        return Path(batch_path)
    
    is_single = getattr(scraper, "get_link_type", lambda: "")() == "single" or getattr(scraper, "is_playlist", False) is False
    if is_single:
        from core.config import ConfigLayer
        from core.paths import PathAuthority
        cfg = ConfigLayer(PathAuthority(), store_layer)
        if cfg.get("music_quick_grab_path"):
            return default_root

    return default_root
