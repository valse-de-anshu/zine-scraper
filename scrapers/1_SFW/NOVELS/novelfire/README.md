# NovelFire Scraper (`scrapers/light_novel/novelfire/`)

Fully isolated, self-contained scraper for **NovelFire** (`novelfire.net`, `novelfire.docs`).

---

## 📖 Overview
NovelFire is a high-volume web novel and light novel reader. This scraper parses NovelFire series catalogs, handles multi-page chapter pagination, and cleans extracted chapter text for offline reading.

---

## ✨ Features
- **Multi-Page Chapter Pagination**: Automatically navigates through paginated chapter lists across long-running serials.
- **HTML Content Sanitization**: Cleans and strips non-story elements, ads, and navigation buttons.
- **Binary Magic-Byte Cover Sniffing**: Inspects binary headers to accurately detect cover image formats.
- **Batch Range Selection**: Supports downloading whole novels, ranges (e.g. `1-50`), or individual chapters.

---

## 📁 Architecture & File Layout
```
scrapers/light_novel/novelfire/
├── __init__.py        # Exports NovelfireScraper, NovelfireEngine, run_workflow
├── engine.py          # HTTP requests, cover downloads, magic-byte format detection
├── scraper.py         # Catalog parser, chapter pagination, text extractor
├── location.py        # Storage directory resolution and collision prevention
├── progress.py        # Tokyo Night Storm completion status tree
├── verification.py    # Chapter text verification on disk
├── tui.py             # Chapter range and batch download selector
├── workflow.py        # Download orchestration, Live progress bars, set_active_live hooks
└── README.md          # Scraper documentation
```
