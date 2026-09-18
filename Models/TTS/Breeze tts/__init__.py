"""
Breeze TTS 2 Engine for Zine Scraper Suite
------------------------------------------
Bilingual instruction-following Text-to-Speech in C++ / GGUF with Vulkan GPU acceleration.
Supports Voice Design, Voice Cloning, Voice Direction, Voice Conversion, and Saved Voices.
"""

from .breeze_engine import run_breeze_tui, process_book_breeze, BreezeTTS

__all__ = ["run_breeze_tui", "process_book_breeze", "BreezeTTS"]
