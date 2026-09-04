# MangaDex Scraper

```text
scrapers/mangadex/
├── __init__.py
├── engine.py        # MangaDex REST API client, MangaDex@Home retrieval, rate-limit guards
├── scraper.py       # MangaDexScraper class, metadata extraction, chapter pagination
├── location.py      # Library routing (Quick grab vs Vacuum: Toon/SFW/OnGoing)
├── verification.py  # Local filesystem verification & duplicate tracking
├── progress.py      # Rich completion tree renderables
├── tui.py           # Site TUI entrypoint
├── workflow.py      # Multi-threaded download orchestrator & Live UI tree
└── README.md
```

## Architecture and Design

- **Official REST API v5 Integration**: Directly interfaces with `https://api.mangadex.org` to index manga metadata, authors, artists, covers, tags, and paginated chapter feeds (`/feed`).
- **MangaDex@Home Distributed Delivery**: Resolves high-speed image CDN nodes via `/at-home/server/{chapter_id}`.
- **Strict Compliance with MangaDex Guidelines**:
  - Enforces a rate limit of $\le$ 5 requests per second with automatic exponential backoff on HTTP 429.
  - Strictly does NOT send authorization headers to image download domains (`*.mangadex.network` or `uploads.mangadex.org`).
- **Centralized Temp Directory (`💩/`)**: All intermediate page downloads and image slicing are contained within the `💩/` buffer before being committed to the final library.
- **Webtoon & Manhua Slicing**: Slices continuous tall vertical strips into standard 2000px height pages (`001.jpg`, `002.jpg`, ...) while leaving normal aspect-ratio pages untouched.
