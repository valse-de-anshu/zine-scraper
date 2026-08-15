# NovelBuddy Scraper (`scrapers/light_novel/novelbuddy/`)

Fully isolated, self-contained scraper for **NovelBuddy** (`novelbuddy.me`, `novelbuddy.com`).

---

## 📖 Overview
NovelBuddy is a prominent Next.js web novel platform hosting thousands of translated Asian web serials. This scraper integrates with NovelBuddy's API and HTML reader to fetch clean text, rich metadata, and chapter indices.

---

## ✨ Features
- **Next.js API Extraction**: Utilizes `api.novelbuddy.me/titles/{id}/chapters` for fast chapter discovery.
- **Rich Metadata Extraction**: Parses clean synopsis (stripping HTML), Author, Rating, Status, Origin Type, Tags, Genres, and Alt Titles.
- **Ad & Watermark Sanitization**: Strips ad injection blocks and sponsor scripts from chapter text.
- **Binary Magic-Byte Cover Sniffing**: Inspects binary headers to accurately detect JPEG, PNG, and WebP cover formats.
- **Word Count & Paragraph Formatting**: Formats chapter text into clean `.txt` files with word counts.

---

## 📁 Architecture & File Layout
```
scrapers/light_novel/novelbuddy/
├── __init__.py        # Exports NovelbuddyScraper, NovelbuddyEngine, run_workflow
├── engine.py          # HTTP requests, cover downloads, magic-byte format detection
├── scraper.py         # API client, Next.js metadata extraction, chapter parsing
├── location.py        # Storage directory resolution and collision prevention
├── progress.py        # Tokyo Night Storm completion status tree
├── verification.py    # Chapter text verification on disk
├── tui.py             # Chapter range and batch download selector
├── workflow.py        # Download orchestration, Live progress bars, set_active_live hooks
└── README.md          # Scraper documentation
```
