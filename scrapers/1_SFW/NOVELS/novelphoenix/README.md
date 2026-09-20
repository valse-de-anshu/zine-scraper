# NovelPhoenix Scraper (`scrapers/light_novel/novelphoenix/`)

Fully isolated, self-contained scraper for **NovelPhoenix** (`novelphoenix.com`).

---

## 📖 Overview
NovelPhoenix is an aggregator for translated Asian web novels and light novels. This scraper handles paginated chapter indexes, metadata extraction, and clean text downloads.

---

## ✨ Features
- **Paginated Chapter Indexing**: Extracts full chapter lists across multiple pagination pages.
- **Text Filtering & Ad Stripping**: Sanitizes reading panes to isolate pure story paragraphs.
- **Binary Magic-Byte Cover Sniffing**: Inspects binary headers to accurately detect cover image formats.
- **Full Range & Batch Modes**: Supports downloading complete series or custom chapter ranges.

---

## 📁 Architecture & File Layout
```
scrapers/light_novel/novelphoenix/
├── __init__.py        # Exports NovelphoenixScraper, NovelphoenixEngine, run_workflow
├── engine.py          # HTTP requests, cover downloads, magic-byte format detection
├── scraper.py         # Catalog parser, chapter pagination, text extractor
├── location.py        # Storage directory resolution and collision prevention
├── progress.py        # Tokyo Night Storm completion status tree
├── verification.py    # Chapter text verification on disk
├── tui.py             # Chapter range and batch download selector
├── workflow.py        # Download orchestration, Live progress bars, set_active_live hooks
└── README.md          # Scraper documentation
```
