"""
Site-specific TUI layer.
This file delegates presentation logic to the core generic TUI handler.
"""

import sys
from .workflow import run_workflow

def handle_tui(url, tracker, location_manager, scraper, batch_path=None, is_batch=False):
    run_workflow(url, tracker, location_manager, scraper, batch_path=batch_path, is_batch=is_batch)
