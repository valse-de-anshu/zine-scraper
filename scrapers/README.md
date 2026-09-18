# 🏛️ Scrapers Architecture — The Holy Grail of Zine Scraper

> **The Definitive Blueprint & Reference Manual for Zine's Categorized Media Archiving Engines.**

---

## 1. Architectural Taxonomy Overview

Zine Scraper organizes its 48+ scrapers and extraction engines into a strict, self-contained, three-tier classification taxonomy. This eliminates clutter, provides immediate clarity on site capabilities and domain targets, guarantees absolute site-level isolation, and prevents dependency spaghetti.

```text
scrapers/
├── 1_SFW/
│   ├── ANIME/              # Episodic anime streaming (Sub & Dub)
│   │   ├── anikai/
│   │   ├── anikoto/
│   │   ├── anineko/
│   │   ├── anitaku/
│   │   ├── hianime/
│   │   └── miruro/
│   ├── MANGA/              # Open community manga archives & APIs
│   │   └── mangadex/
│   ├── MANHWA/             # Dedicated Korean Manhwa & Chinese Manhua scanlations
│   │   ├── asurascans/
│   │   ├── projectsuki/
│   │   └── manhuaplus/
│   ├── HYBRID_COMICS/      # Multi-origin comic aggregators (Manga + Manhwa + Manhua)
│   │   ├── kunmanga/
│   │   ├── topmanhua/
│   │   ├── weebcentral/
│   │   ├── fanfox/
│   │   └── mangak/
│   ├── NOVELS/             # Web serials, light novels, and translation epics
│   │   ├── chikari/
│   │   ├── novelarchive/
│   │   ├── novelbuddy/
│   │   ├── novelfire/
│   │   └── novelphoenix/
│   ├── KNOWLEDGE_STUDY/    # Public domain digital libraries & open archives
│   │   ├── archive/
│   │   └── gutenberg/
│   ├── MUSIC/              # High-fidelity audio, classical works & streaming tracks
│   │   ├── idagio/
│   │   ├── soundcloud/
│   │   └── yt_music/
│   └── SOCIAL_MEDIA/       # Creator portfolios, image boards, reels & feeds
│       ├── facebook/
│       ├── instagram/
│       ├── pinterest/
│       └── youtube/
├── 2_NSFW_ADULT/
│   ├── ADULT_ANIME/        # Dedicated adult anime (Hentai) streaming portals
│   │   ├── hanime/
│   │   ├── hanime_red/
│   │   ├── hentaicity/
│   │   ├── hentaihaven/
│   │   ├── hentaihaven_co/
│   │   ├── hentaimama/
│   │   ├── hstream/
│   │   ├── ohentai/
│   │   └── oppai_stream/
│   ├── ADULT_PORN/         # Mainstream adult video streaming & creator channels
│   │   └── pornhub/
│   ├── Doujinshi/          # Numeric ID doujinshi galleries & fan-comic archives
│   │   ├── asmhentai/
│   │   └── nhentai/
│   └── ADULT_Webtoons/     # 18+ Uncensored Korean manhwa & adult webtoon readers
│       ├── hentai18/
│       ├── hentai20/
│       ├── manga18fx/
│       ├── manhwaus/
│       ├── omegascans/
│       └── oppai_stream_toon/
└── 3_SYSTEM/               # Core headless bridges, stream decryptors & downloaders
    ├── hls_extractor.py
    ├── playwright_extractor.py
    └── ytdlp/
```

---

## 2. Master Site Directory & Encyclopedic Catalog

### 📺 1_SFW / ANIME
Dedicated to Japanese animation with high-speed HLS multi-server stream extraction, subtitle track capture, and AniList/MyAnimeList metadata syncing.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`hianime`** | `hianime.to`<br>`hianime.sx`, `hianime.mn`, `hianime.nz`, `hianime.ad`, `hianime.re`, `hianime.pm` | Multi-server HLS streams, multi-language Sub & Dub audio feeds. | Spiritual successor to Zoro.to; vast global catalog, highest server uptime, clean adaptive UI. |
| **`anikoto`** | `anikoto.cz`<br>`anikototv.to`, `anikoto.me`, `anikoto.net`, `anikototv.se`, `anikoto.online` | Low-latency subbed & dubbed streams with auto domain rotations. | Rapid domain rotation and dependable mirror failover when primary aggregators face congestion. |
| **`anineko`** | `anineko.to` | Minimalist, ad-light subbed episode streams with direct extraction. | Ultra-lightweight layout with fast, distraction-free playback and zero intrusive ad wrappers. |
| **`anitaku`** | `anitaku.online`<br>`anitaku.to`, `anitaku.me` | Multi-resolution episode downloads from early 2000s to modern releases. | Formerly Gogoanime; legendary deep legacy anime archive spanning decades of vintage series. |
| **`miruro`** | `miruro.to`<br>`miruro.ru`, `miruro.tv`, `miruro.bz` | Fast API stream extraction, automated AniList GraphQL metadata sync. | Modern minimalist UI that proxies high-speed CDN video feeds with zero layout clutter. |
| **`anikai`** | `anikai.to` | High-definition anime episode streams with responsive player feeds. | Fast-loading newer platform with dependable subtitle synchronization and high bitrate encodes. |

---

### 📖 1_SFW / MANGA
Community-driven open manga archiving via direct REST API integration.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`mangadex`** | `mangadex.org`<br>`api.mangadex.org` | Official REST API v5, MangaDex@Home CDN, multi-language chapter select, decimal parsing. | The internet's gold standard open manga archive; completely ad-free, high-resolution original scanlations. |

---

### 🇰🇷 1_SFW / MANHWA
Dedicated platforms specializing in Korean action/regression manhwa and Chinese martial arts/cultivation manhua.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`asurascans`** | `asurascans.com`<br>`asuracomic.net`, `asuratoon.com` | High-resolution vertical webtoon strips, decimal chapter numbering. | Premier active scanlation team for top-tier Korean action, fantasy, and regression webtoons. |
| **`projectsuki`** | `projectsuki.com` | Clean, ad-free webtoon reader with fast chapter packaging. | Community-funded, completely ad-free reader focused on distraction-free reading. |
| **`manhuaplus`** | `manhuaplus.org` | Continuous vertical strips for Chinese cultivation manhua. | The leading home for xianxia, cultivation, and martial arts series with daily translation updates. |

---

### 📑 1_SFW / HYBRID_COMICS
Large-scale comic aggregators indexing Manga, Manhwa, and Manhua under a single roof.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`weebcentral`** | `weebcentral.com` | Ultra-fast CDN image delivery, comprehensive series indexing. | Modern aesthetic reader with zero invasive redirects and reliable image delivery. |
| **`kunmanga`** | `kunmanga.com`<br>`kunmanga.co.uk` | Broad shonen, shojo, and fantasy coverage with auto-retry. | Rapid chapter updates and stable image mirrors across trending ongoing series. |
| **`topmanhua`** | `topmanhua.fan` | Vertical webtoon strips, romance, shoujo, and action manhwa. | Fast English translations of trending Korean and Chinese romance/drama webtoons. |
| **`fanfox`** | `fanfox.net`<br>`m.fanfox.net` | Massive legacy comic directory, completed classic titles. | Formerly MangaFox; historic pioneer of online manga reading with an irreplaceable archive. |
| **`mangak`** | `mangak.io` | Classic serials, one-shots, and broad cross-genre indexing. | Formerly MangaKakalot; massive archive spanning decades of Japanese serialization. |

---

### 📚 1_SFW / NOVELS
Translated Asian web novels, Korean light novels, and western web serials with ad-filtering and chapter text normalization.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`chikari`** | `chikari.moe` | High-speed REST API chapter indexing (1,400+ chapters in seconds). | Modern SvelteKit architecture delivering lightning-fast index queries and clean novel formatting. |
| **`novelphoenix`**| `novelphoenix.com` | Cultivation epics, fantasy novels, clean chapter pagination. | Extensive translation catalog for Chinese cultivation and Korean fantasy series. |
| **`novelfire`** | `novelfire.net`<br>`novelfire.docs` | Sanitized chapter extraction, ad-filtered text exports. | Deep catalog coverage for ongoing fantasy epics with reliable chapter RSS feeds. |
| **`novelbuddy`** | `novelbuddy.me`<br>`novelbuddy.com` | Next.js API discovery, synopsis, ratings, and clean text. | Polished modern web novel reader with rich community metadata and verified user ratings. |
| **`novelarchive`**| `novelarchive.cc` | Lightweight REST API web novel repository. | Dependable backup archive for completed web novels when primary aggregators face downtime. |

---

### 🏛 1_SFW / KNOWLEDGE_STUDY
Preservation of human culture, public domain literature, historical audio, and open records.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`gutenberg`** | `gutenberg.org` | 70,000+ free e-books in plain text and EPUB formats. | The world's oldest digital library (founded 1971); universal access to classic literature. |
| **`archive`** | `archive.org` | Scanned rare manuscripts, public texts, and cultural preservation. | The internet's largest non-profit digital library preserving billions of cultural artifacts. |

---

### 🎵 1_SFW / MUSIC
High-bitrate audio, lossless classical recordings, and synchronized lyrics capture.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`soundcloud`** | `soundcloud.com` | High-bitrate audio, track metadata, automated lyrics sync. | The defining global hub for independent artists, remixers, DJs, and unsigned musicians. |
| **`idagio`** | `idagio.com` | Lossless classical recordings with conductor/orchestra tagging. | The premier dedicated classical music service with specialized opus/movement metadata. |
| **`yt_music`** | `music.youtube.com` | Lossless FLAC/AAC audio, ID3/Vorbis tagging, embedded cover art, `.lrc` lyrics. | Google's global music streaming network; official studio tracks + live concert bootlegs. |

---

### 🌐 1_SFW / SOCIAL_MEDIA
Creator visual assets, multi-image posts, profiles, and video reels.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`youtube`** | `youtube.com`<br>`youtu.be` | Videos, playlists, channels, shorts, auto-subs & ASR captions. | The internet's video standard; multi-quality resolution feeds up to 4K/8K. |
| **`instagram`** | `instagram.com` | Full-res photos, multi-image carousels, reels, highlights. | Visual creator portfolios, photography showcase, and vertical short video reels. |
| **`facebook`** | `facebook.com`<br>`fb.watch` | Full-resolution profile pictures, photo albums, video reels. | Core social network media extraction with automated session cookie support. |
| **`pinterest`** | `pinterest.com`<br>`pin.it` | Ultra-high-resolution boards, aesthetic pins, concept art. | Global visual discovery engine; perfect for aesthetic mood boards and art reference packs. |

---

### 🔞 2_NSFW_ADULT / ADULT_ANIME
Adult anime (Hentai) streaming portals with Playwright headless bypass and custom HLS segment decryption.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`hanime`** | `hanime1.me`<br>`hanime.tv` | Full HD 1080p uncensored video streams, playlist feeds. | The undisputed flagship adult anime portal with complete franchise indexing and 1080p feeds. |
| **`hanime_red`** | `hanime.red` | Franchise collections, tagged releases, subtitle extraction. | Dependable mirror portal with categorized franchise tags and clean video manifests. |
| **`hentaihaven`** | `hentaihaven.xxx`<br>`hentaihaven.red`, `hentaihaven.online`, `hentaihaven.club` | Multi-mirror stream extraction, series indexing. | Historic adult anime streaming brand with widespread mirror distribution. |
| **`hentaihaven_co`** | `hentaihaven.co` | Headless Playwright extraction via nhplayer cloud streams. | Specialized portal routing video streams through Cloudflare Turnstile protected players. |
| **`hentaimama`** | `hentaimama.io` | Translated adult anime releases, episode archiving. | Renowned for fan-translated releases and obscure OVAs not found on mainstream sites. |
| **`hstream`** | `hstream.moe` | HD adult anime video streams, clean direct streams. | Clean, ad-light interface with optimized direct HLS streaming performance. |
| **`ohentai`** | `ohentai.org` | Vintage OVA and classic adult anime archives. | The best archive for vintage 80s/90s adult anime OVAs and classic series. |
| **`hentaicity`** | `hentaicity.com` | High-definition adult anime episodes, series tracking. | Granular tag matrix, multi-episode series tracking, and direct stream feeds. |
| **`oppai_stream`** | `oppai.stream` | Fast direct HLS adult video streaming. | Specialized streaming portal with high-speed video fragment delivery. |

---

### 🔞 2_NSFW_ADULT / ADULT_PORN
Mainstream adult video archiving.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`pornhub`** | `pornhub.com`<br>`phncdn.com` | Multi-resolution video downloads (up to 1080p/4K), creator model channel vacuuming. | The world's largest adult video streaming network with extensive creator catalogs. |

---

### 🔞 2_NSFW_ADULT / Doujinshi
Gallery and fan-comic archives indexed by numeric IDs and comprehensive character/author tags.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`nhentai`** | `nhentai.net` | Fast 6-digit ID lookups, complete tag indexing, tankōbon galleries. | The universal gold standard for doujinshi archiving, numeric ID lookups, and dual raw/translated releases. |
| **`asmhentai`** | `asmhentai.com` | Curated doujinshi and adult comics with extensive tag matrix. | Well-curated doujinshi reader with clean pagination and strong western translation coverage. |

---

### 🔞 2_NSFW_ADULT / ADULT_Webtoons
Uncensored adult Korean manhwa, western adult comics, and continuous vertical scroll webtoons.

| Scraper | Primary & Alternate Domains | What It Provides | What It Is Most Famous For |
|---|---|---|---|
| **`manhwaus`** | `manhwaus.net` | Adult Korean webtoons, ongoing romance & drama manhwa. | Fast-updating reader for localized adult Korean webtoons with high-resolution vertical strips. |
| **`omegascans`** | `omegascans.org` | Uncensored adult manhwa & webtoons, English scanlations. | Premium scanlation group famous for high-fidelity English translations of adult manhwa. |
| **`hentai20`** | `hentai20.io` | Western adult comics, webtoons, and doujinshi releases. | Community-driven reader for western adult comics and webtoons with clean chapter pagination. |
| **`manga18fx`** | `manga18fx.com` | Mixed SFW & NSFW manhwa/webtoons, vertical strip slicing. | Hybrid platform hosting adult and all-ages webtoons with continuous image feeds. |
| **`hentai18`** | `hentai18.net` | Uncensored adult manhwa & webtoons, multi-server feeds. | Rapid chapter releases for translated Asian adult comics with complete gallery archives. |
| **`oppai_stream_toon`** | `read.oppai.stream` | Dedicated webtoon and comic vertical strip reader. | Webtoon reading arm of Oppai Stream; clean vertical strips for adult webtoons. |

---

## 3. System Extractors (`3_SYSTEM/`)

Helper scripts located in `scrapers/3_SYSTEM/` act as isolated workers invoked via `core.paths.get_system_script()`:

### 1. `hls_extractor.py`
A resilient, anti-bot HTTP Live Streaming (HLS) downloader that fetches `.m3u8` playlists and losslessly assembles `.ts` video segments into a single file:
- **TLS Fingerprint Spoofing**: Employs `curl_cffi` to mimic a Chrome 124 browser, cleanly bypassing Cloudflare and DDoS-Guard barriers.
- **Bandwidth Auto-Selection**: Parses `#EXT-X-STREAM-INF` master playlists and automatically selects the stream with the highest bitrate (1080p guaranteed).
- **AES-128 Decryption**: Fetches encryption keys from `#EXT-X-KEY`, extracts the Initialization Vector (IV), and decrypts `.ts` chunks on the fly via `pycryptodome`.
- **PNG Header Stripping**: Neutralizes anti-scraping CDN obfuscation that disguises video chunks behind fake PNG headers (`\x89PNG ... IEND`).
- **Concurrent Chunk Piping**: Utilizes `aria2c` for high-throughput concurrent segment downloads, falling back to `ThreadPoolExecutor`.
- **Lossless FFmpeg Concatenation**: Pipes decrypted segments directly into `ffmpeg` via standard input (`pipe:0`) using `-c copy` with zero transcode loss.

### 2. `playwright_extractor.py`
An automated headless Chromium bridge designed to defeat Cloudflare Turnstile, JavaScript challenges, and obfuscated players:
- **Dynamic VENV Injection**: Automatically crawls the filesystem, locates the project virtual environment, and bootstraps dependencies into `sys.path`.
- **Stealth Automation**: Launches Chromium via `playwright_stealth`, stripping `navigator.webdriver` markers.
- **Network Telemetry Sniffing**: Hooks into browser `page.on("response")` events, capturing raw `.m3u8` manifests, direct `.mp4` URLs, and `.vtt`/`.srt` subtitle streams.
- **JWPlayer Telemetry Interception**: Intercepts `jwpltx.com` telemetry pings with `mu=` parameters to uncover direct video endpoints.
- **Simulated DOM Interaction**: Bypasses lazy-loading mechanisms by triggering synthetic clicks on `.jw-icon-display` and `.vjs-big-play-button`.
- **Structured JSON Output**: Emits captured stream URLs and metadata as clean JSON prefixed by `JSON_RESULT:`.

### 3. `ytdlp/`
Encapsulated CLI extraction engine for universal video platforms, handling rate-limiting and format selection.

---

## 4. Standard 8-File Scraper Architecture

Every site scraper follows a uniform, strictly isolated 8-file structure:

```text
scrapers/<category>/<site>/
├── __init__.py          # Package initialization
├── engine.py            # Site extraction logic, API querying & decryption
├── scraper.py           # Metadata parsing, link routing (quick vs vacuum)
├── tui.py               # Interactive selector & pre-flight Rich terminal UI
├── workflow.py          # Multi-threaded download pipeline & retry management
├── location.py          # Save path resolution (Quick grab vs Vacuum vs Batch)
├── verification.py      # Two-tier integrity check (history.json + disk check)
└── progress.py          # Visual progress trees & completion summaries
```

### Architectural Contract
1. **Zero Cross-Scraper Dependencies**: A scraper inside `scrapers/1_SFW/ANIME/miruro` must never import directly from another site scraper. All shared functionality must reside in `core/` or `scrapers/3_SYSTEM/`.
2. **Relative Intra-Package Imports**: Inside any scraper folder, use relative imports (`from .engine import ...`, `from .verification import ...`) to preserve absolute relocation independence.
3. **No Site Extraction in `core/`**: Core services (`core/paths.py`, `core/ui.py`, `core/storage.py`) provide infrastructure only. Site-specific HTML parsing, regexes, and headers belong strictly in `engine.py` and `scraper.py`.
4. **Intermediate Files in `💩/`**: All temporary chunks, raw manifests, and buffer files must be written to `PathAuthority().get_temp_root()` (`/zine scraper/💩/`) and cleaned up immediately on completion or exit.
5. **Batch & Headless Rule**: When `is_batch=True` or `not sys.stdin.isatty()`, interactive TUI prompts are completely suppressed. The link's URL structure decides whether to execute a single-item quick grab or full series vacuum. Command line flags (`--0`, `--1,2,3`, `--A / --a`) take immediate precedence.
6. **Graceful Limiter (`Ctrl + R`)**: All download loops in `workflow.py` must register the global Revolt mode hook (`set_active_live`) to allow emergency stop and item limiting without corrupting terminal state.
