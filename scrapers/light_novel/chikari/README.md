# Chikari Scraper (`scrapers/light_novel/chikari/`)

Fully isolated, self-contained scraper for **Chikari** (`chikari.moe`).

---

## 📖 Overview
Chikari is a modern SvelteKit-powered web novel, light novel, and comic platform. This scraper interacts directly with Chikari's internal REST endpoints to rapidly extract series metadata, chapters, formatted text, and comic pages without executing heavy client-side JavaScript.

---

## ✨ Features
- **High-Speed Chapter Extraction**: Leverages `/api/novels/<slug>/chapters/<num>/read` for instantaneous text retrieval.
- **Dual Novel & Comic Support**: Automatically detects novel chapters vs comic image galleries (`/series/<slug>`).
- **Binary Magic-Byte Cover Sniffing**: Inspects binary headers (`JPEG`, `PNG`, `WebP`, `GIF`, `AVIF`) to save covers and comic pages with correct file extensions.
- **Offset Pagination**: Traverses long chapter listings (1,400+ chapters) seamlessly using paginated API limits.
- **Full Metadata Extraction**: Title, synopsis, author, artist, tags, genres, status, and view counts.

---

## 📁 Architecture & File Layout
```
scrapers/light_novel/chikari/
├── __init__.py        # Exports ChikariScraper, ChikariEngine, run_workflow
├── engine.py          # HTTP requests, image downloading, magic-byte format detection
├── scraper.py         # SvelteKit REST API client and metadata parser
├── location.py        # Storage directory resolution and collision prevention
├── progress.py        # Tokyo Night Storm completion status tree
├── verification.py    # Chapter text and image verification on disk
├── tui.py             # Chapter range and batch download selector
├── workflow.py        # Download orchestration, Live progress bars, set_active_live hooks
└── README.md          # Scraper documentation
```
