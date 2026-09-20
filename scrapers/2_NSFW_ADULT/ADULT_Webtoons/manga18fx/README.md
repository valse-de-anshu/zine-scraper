# Manga18fx Scraper

Site scraper implementation for **Manga18fx** (`https://manga18fx.com/`).

## Architecture & Isolation

This scraper strictly follows the **Zine Scraper Suite Site-Level Isolation** architecture. It is fully self-contained and exposes zero cross-dependencies to other scrapers:

```text
scrapers/manga18fx/
├── __init__.py      # Module exports (Manga18fxScraper, run_workflow, get_save_path, handle_tui)
├── engine.py        # HTTP session, thread pool image downloader, continuous vertical canvas stitching & 2000px chunk slicing in 💩/
├── scraper.py       # Manga18fxScraper (series & chapter URL parsing, self-contained cover extraction, metadata)
├── tui.py           # Site TUI entrypoint (handle_tui)
├── workflow.py      # Orchestrator with Tokyo Night Storm styling, Live progress bar, braille baking spinner, Whistleblower recovery
├── location.py      # Interactive directory routing (SFW / NSFW, OnGoing / Completed, Quick grab vs Vacuum)
├── verification.py  # Local filesystem image verification & tracker sync
└── progress.py      # Pre-flight completion tree renderer
```

## Features

- **Mixed Content Handling**: Distinguishes SFW and NSFW series via metadata tags, offering interactive routing to `<library_root>/Toon/SFW/...` or `<library_root>/Toon/NSFW/...`.
- **Long-Strip Slicing**: Automatically stiches vertical manhwa/webtoon strips and slices them into standard 2000px height chunks.
- **💩/ Temp Directory Buffer**: All intermediate chunk downloads and PIL baking occur inside the centralized temp directory (`PathAuthority().get_temp_root()`), leaving no intermediate garbage in the user's permanent library.
- **Single Chapter & Series Support**: Supports full series URLs (`/manga/<slug>`) as well as individual chapter links (`/manga/<slug>/chapter-<n>`).
