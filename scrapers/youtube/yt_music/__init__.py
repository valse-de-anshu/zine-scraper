"""
scrapers/youtube/yt_music
-------------------------
YouTube Music isolated scraper subpackage.
Supports single song extraction, playlist/album batch scraping,
and high-fidelity FLAC audio downloads with embedded metadata and synced lyrics.
"""

from .scraper import YoutubeMusicScraper
from .engine import YoutubeMusicEngine
from .workflow import run_workflow

__all__ = ["YoutubeMusicScraper", "YoutubeMusicEngine", "run_workflow"]
