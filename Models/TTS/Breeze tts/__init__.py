"""
Breeze TTS 2 Engine for Zine Scraper Suite
------------------------------------------
Bilingual instruction-following Text-to-Speech in C++ / GGUF with Vulkan GPU acceleration.
Supports Voice Design, Voice Cloning, Voice Direction, Voice Conversion, and Saved Voices.
Includes specialized Harness TTS for JSON-driven chapter recaps and structured voiceover workflows.
"""

from .breeze_engine import run_breeze_tui, process_book_breeze, BreezeTTS, render_recap_script, render_recap_chapters
from .harness_engine import run_harness_tui, run_harness_cli, render_harness_json, parse_harness_json

__all__ = [
    "run_breeze_tui",
    "process_book_breeze",
    "BreezeTTS",
    "render_recap_script",
    "render_recap_chapters",
    "run_harness_tui",
    "run_harness_cli",
    "render_harness_json",
    "parse_harness_json",
]
