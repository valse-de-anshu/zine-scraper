# Topmanhua Scraper Architecture

The `topmanhua` scraper is an isolated, self-contained scraper module within the Zine Scraper Suite for extracting manhwa and comics from `topmanhua.fan`.

## Structure

```
scrapers/topmanhua/
├── __init__.py        # Public module exports
├── engine.py          # HTTP transport, thread pool, image downloading, vertical strip slicing
├── scraper.py         # TopmanhuaScraper class with comprehensive metadata & chapter discovery
├── location.py        # SFW/NSFW & Ongoing/Completed directory routing
├── verification.py    # Local disk chapter verification & history tracker synchronization
├── progress.py        # Tokyo Night Storm completion tree UI
├── workflow.py        # Orchestration, Live progress UI, Whistleblower recovery
├── tui.py             # Entrypoint interface for the funnel layer
└── README.md          # Architecture and design documentation
```

## Features

- **Strict Isolation**: Zero satellite or parasite files, zero cross-scraper dependencies.
- **Comprehensive Metadata**: Extracts full titles, clean descriptions, authors, artists, genres, status, release year, and star ratings into `.zine/meta.json`.
- **Vertical Strip Slicing**: Stitches variable-width strip fragments and slices continuous strips into uniform 2000px high chunks in centralized `💩/` buffer before moving to destination.
- **Robust CDN Headers**: Automatically passes `Referer: https://topmanhua.fan/` for `2xstorage.com` CDN authorization.
