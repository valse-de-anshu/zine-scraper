"""
core/civitai_engine.py
-----------------------
Bridge to scrapers/3_SYSTEM/civitai engine.
"""

from pathlib import Path
from typing import Optional
import importlib.util


def run_civitai_tui(input_file: Optional[str] = None, threads: int = 6, max_retries: int = 5) -> bool:
    """Launches the Civitai / Anima model ingestion TUI from scrapers/3_SYSTEM/civitai/tui.py."""
    suite_root = Path(__file__).parent.parent
    tui_path = suite_root / "scrapers" / "3_SYSTEM" / "civitai" / "tui.py"
    spec = importlib.util.spec_from_file_location("civitai_tui", tui_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_civitai_tui(input_file=input_file, threads=threads, max_retries=max_retries)
