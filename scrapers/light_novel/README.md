# Light Novel Scrapers

```text
light_novel
├── README.md
├── __init__.py
├── chikari
│   ├── __init__.py
│   ├── engine.py
│   ├── location.py
│   ├── progress.py
│   ├── scraper.py
│   ├── tui.py
│   ├── verification.py
│   └── workflow.py
├── lightnovelworld
│   ├── __init__.py
│   ├── engine.py
│   ├── location.py
│   ├── progress.py
│   ├── scraper.py
│   ├── tui.py
│   ├── verification.py
│   └── workflow.py
├── novelarchive
│   ├── engine.py
│   ├── location.py
│   ├── progress.py
│   ├── scraper.py
│   ├── tui.py
│   ├── verification.py
│   └── workflow.py
├── novelbuddy
│   ├── __init__.py
│   ├── engine.py
│   ├── location.py
│   ├── progress.py
│   ├── scraper.py
│   ├── tui.py
│   ├── verification.py
│   └── workflow.py
├── novelfire
│   ├── __init__.py
│   ├── engine.py
│   ├── location.py
│   ├── progress.py
│   ├── scraper.py
│   ├── tui.py
│   ├── verification.py
│   └── workflow.py
└── novelphoenix
    ├── __init__.py
    ├── engine.py
    ├── location.py
    ├── progress.py
    ├── scraper.py
    ├── tui.py
    ├── verification.py
    └── workflow.py
```

## Detailed Platform Implementations

The `light_novel` directory acts as an umbrella package for text-based light novel and web serial scraper implementations:
- **Chikari** (`chikari.moe`): SvelteKit frontend + REST API backend for high-speed chapter extraction.
- **NovelPhoenix** (`novelphoenix.com`): Asian web novel and cultivation aggregator with pagination handling.
- **NovelFire** (`novelfire.net`): High-catalogue light novel platform with DOM sanitization.
- **NovelBuddy** (`novelbuddy.me`): Next.js platform with API-driven chapter indexing.
- **NovelArchive** (`novelarchive.cc`): Direct REST API reader for web serials.
- **LightNovelWorld** (`lightnovelworld.org`): Legacy scraper (site shutting down).

Because light novels are text-based, chapters are formatted as clean `.txt` files containing chapter titles, paragraph breaks, and calculated word counts inside `<Title>/novel chapter/` with rich `.zine/meta.json` metadata.
