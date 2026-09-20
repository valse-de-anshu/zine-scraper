<div align="center">

<img src="assets/banner.png" alt="Zine Scraper Banner" width="100%">

<img src="assets/zine%20banner.png" alt="Zine Scraper Logo Banner" width="100%">

# Zine Scraper Suite

**A high-performance media archiving suite built to save the content you love permanently onto your local storage.**

<p align="center">
  🎵 <b>Music:</b> Lossless FLAC audio with high-res cover art, full artist metadata, and synced scrolling <code>.lrc</code> lyrics.<br>
  📖 <b>Manga, Manhua, Novels & Comics:</b> Complete franchise archiving with clean chapters and zero clutter.<br>
  🎬 <b>Adult Anime & Videos (18+):</b> Multi-season series, playlists, and 1080p/4K streams without ads or popups.<br>
  📚 <b>Books & AI Voice:</b> Web serials, public domain classics, and GPU-accelerated neural audiobook synthesis.
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-red?style=for-the-badge" alt="CC BY-NC-SA 4.0 License"></a>
  <a href="https://discord.gg/suJD5xtFj"><img src="https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord Community"></a>
  <a href="https://github.com/valse-de-anshu/zine-scraper/releases"><img src="https://img.shields.io/badge/Release-v1.2.0-orange?style=for-the-badge" alt="v1.2.0"></a>
</p>

</div>

---

<div align="center">

## 🖼️ Live Previews & Interactive Showcase

### ⚡ Live Interactive Workflows

| 🎮 Interactive TUI & Quality Selector | 🚀 Automated Headless & Batch Pipeline |
| :---: | :---: |
| <img src="preview/interactive%20tui.gif" width="480" alt="Interactive TUI & Chapter Selector"> | <img src="preview/auto%20downlode.gif" width="480" alt="Automated Download Pipeline"> |

<br>

### 🎨 80+ Themes Dynamic Showcase

<img src="preview/theme%20preview.gif" width="85%" alt="80+ Dark Themes Dynamic Preview">

<br>

### 🖥️ Interface & Progress Views

| 🏠 Home Interactive Dashboard | 🧭 Universal 48-Site Selector |
| :---: | :---: |
| <img src="preview/home.png" width="480" alt="Home TUI Menu"> | <img src="preview/site%20tui.png" width="480" alt="Universal Site TUI"> |
| **📊 Real-time Dual Progress Engine** | **⚙️ Live Theme Settings** |
| <img src="preview/progress%20bar.png" width="480" alt="Dual Progress Gauge"> | <img src="preview/theme%20setting.png" width="480" alt="Theme Settings"> |
| **✨ Minimal Home Mode** | **⚡ Minimal Progress Mode** |
| <img src="preview/minimal%20home.png" width="480" alt="Minimal Home Mode"> | <img src="preview/minimal%20progress%20bar.png" width="480" alt="Minimal Progress Bar"> |

</div>

---

## 🚀 Quick Start

*(If you already have Python and Git installed, you can skip directly to Step 2).*

### 1. Prerequisites
You only need **Git** and **Python 3.10+** installed. The automated installer configures all remaining system tools (`ffmpeg`, `aria2`, `atomicparsley`, `deno`) and python virtual environments automatically.

* **🐧 Linux (Debian / Ubuntu / Arch / Fedora / openSUSE):**
  ```bash
  # Debian/Ubuntu: sudo apt update && sudo apt install -y git python3 python3-pip python3-venv curl
  # Arch/Manjaro:  sudo pacman -Sy --noconfirm git python python-pip curl
  # Fedora/RHEL:   sudo dnf install -y git python3 python3-pip curl
  # openSUSE:      sudo zypper install -y git python3 python3-pip python3-venv curl
  ```
* **🍏 macOS:**
  ```bash
  brew install git python
  ```
* **🪟 Windows 10 / 11:**
  * Install Git: `winget install Git.Git` or via [git-scm.com](https://git-scm.com/)
  * Install Python 3.10+: `winget install Python.Python.3.11` *(Ensure you check **"Add Python to PATH"**)*

---

### 2. Automated 1-Click Install

```bash
# Clone the repository
git clone https://github.com/valse-de-anshu/zine-scraper.git
cd "zine-scraper"

# Run the installer
# Linux / macOS:
cd "run me" && chmod +x install.sh run.sh && ./install.sh

# Windows:
# Double-click "run me\install.bat" (or run in CMD: cd "run me" && install.bat)
```

---

### 3. Launching Zine

Launch Zine using either the global **`zine`** command (linked automatically during installation) or directly via **`python3 orchestrator.py`**:

#### ⚡ Direct Headless CLI Execution (Fast & Scriptable)
Pass URLs and flags directly from your terminal. Zine displays the official ASCII banner, parses inputs, resolves metadata, and downloads immediately without blocking prompts:

```bash
# Quick single chapter/episode grab (--0)
zine "https://hanime.red/watch/episode-1" --0

# Full series vacuum archiving (--a or --A)
zine "https://hentaihaven.xxx/watch/sei-brunehilde-gakuen.../" --a

# Sequential chapter continuation (--5)
zine "https://asurascans.com/comics/series-title" --5

# Extract & save series metadata and cover art only (--meta)
zine "https://chikari.moe/novels/endless-extraction-in-a-game-like-world" --meta

# Vacuum queue processing (defaults to vacuum.txt)
zine --vacuum

# Custom queue file processing with optional flags
zine "my_reading_list.txt" --meta
zine --vacuum "my_reading_list.txt"

# Or directly with Python:
python3 orchestrator.py "https://example.com/media/title" --0
python3 orchestrator.py "my_reading_list.txt" --meta
```

#### 🖥️ Interactive TUI Mode
Launch into the full-screen interactive interface with live keyboard navigation, settings configurator, and site catalog:

```bash
# Launch interactive menu:
zine

# Or directly with Python:
python3 orchestrator.py
```
*(Windows users can also use `zine` in Command Prompt / PowerShell, or double-click `run me\run.bat`).*

---

### 🔑 4. API Keys & Personal Credentials (`secrets.json`)

Zine Scraper includes a built-in, secure credentials manager so personal API keys and client secrets are **never committed or leaked to Git**:

* **Auto-Scaffolded on Launch**: On first startup, Zine automatically generates a gitignored `secrets.json` file in the project root:
  ```json
  {
      "mangadex": {
          "client_id": "personal-client-your-uuid",
          "client_secret": "your-client-secret"
      }
  }
  ```
* **Git Safe**: `secrets.json`, `core/secrets.json`, and `.env` are permanently excluded in `.gitignore`. You can safely push, pull, or share your repository without exposing credentials.
* **Environment Variables**: You can also optionally provide keys as system environment variables (e.g. `MANGADEX_CLIENT_ID` and `MANGADEX_CLIENT_SECRET`).
* **Complete Guide**: See [`docs/ManaDex.md`](docs/ManaDex.md) for a comprehensive step-by-step walkthrough on generating API keys, language selection, and library management.

---

## 💬 Available Commands

Type any of these commands directly into the main `Paste URL:` prompt:

| Command | Category | Description |
|---|---|---|
| **`vacuum`** / **`batch`** | **Automation** | Headless Queue Runner (processes all links in `vacuum.txt` or a custom text file) |
| **`bake`** / **`metadata`** | **Audio** | Audio Metadata & Cover Art Baking Engine (FFmpeg / Mutagen) |
| **`lyrs`** | **Audio** | Synced `.lrc` Lyrics Search & Downloader (6-tier waterfall: LRCLIB, NetEase, Megalobiz) |
| **`sc-lyrics`** | **Audio** | Batch music folder scanner and automated `.lrc` lyrics synchronization |
| **`tts`** | **AI Speech** | Universal Audiobook TTS Hub (select between Breeze-TTS-2 or Qwen3-TTS) |
| **`subs`** | **AI Tools** | AI Subtitle Generator (`faster-whisper` local GPU transcription & translation) |
| **`slice`** | **Tools** | Webtoon & Manhua Image Slicer (splits long vertical strips into standard pages) |
| **`doctor`** | **System** | System Diagnostic Health Check (Python, FFmpeg, Aria2, Deno, Playwright, paths) |
| **`clean`** | **System** | Purges temporary fragments, chunks, and cache buffers in `💩/` |
| **`version`** | **System** | Display detailed version, runtime telemetry, and dependency status |
| **`settings`** | **System** | Interactive Settings Configurator (download paths, audio format, 80+ themes) |
| **`site`** | **System** | Interactive Supported Sites Database & Catalog viewer |
| **`help`** | **System** | In-app documentation and quick guide browser |
| **`exit` / `q`** | **System** | Clean exit from Zine Scraper Suite |

> [!IMPORTANT]
> **💡 Pro-Tip on Social Media Scrapers (Instagram, Facebook & Pinterest):**
> When scraping Instagram, Facebook, or Pinterest (profiles, reels, highlights, albums, and boards), the scraper initially takes a few moments to negotiate sessions, solve anti-bot challenges / captchas, parse infinite-scroll post streams, and hydrate DOM assets in the headless browser engine.
> **Please give the scraper a little time to work through this initial anti-bot negotiation phase!** Once solved and indexed, Zine rapidly downloads all requested media at maximum multithreaded connection speed.

> [!TIP]
> **💡 Pro-Tip on TUI Performance & Smooth Riding:**
> Sometimes after a very long session or heavy continuous usage (large batch downloads, multi-chapter TTS synthesis), the terminal interface may become slightly sluggish. Simply exit (`exit` or `q`) and reopen Zine (`zine` or `python3 orchestrator.py`) for a fresh, buttery-smooth ride!

---

### ⌨️ Keybindings & Hotkeys Reference

| Key | Context | Action |
|---|---|---|
| **`Ctrl + R`** | **Any Active Download** | **Global Revolt Mode** — Gracefully halt downloads after current file (`0`) or `N` more files. Exits cleanly with an OS notification. |
| **`Ctrl + T`** | **Any Active Download** | **Global Truncate Mode** — Stop active download early after current item and return cleanly to the main menu without terminating Zine. |
| **`Ctrl + C`** | **Global** | **Force Clean Exit** — Immediately cancels active operations, restores terminal cursor & raw mode, and unloads AI models from VRAM. |
| **`↑` / `↓`** | **Menus & Prompt** | Navigate menu items, selector options, and cycle through previous URL command history. |
| **`←` / `→`** | **Input & Menus** | Move cursor left/right within input prompts and switch between horizontal menu buttons. |
| **`Home` / `End`** | **Input Prompt** | Instantly jump the cursor to the beginning or end of the pasted URL or command. |
| **`Tab`** | **Input Prompt** | Auto-complete inline command suggestions and previous URL history matches. |
| **`Space`** | **Multi-Selectors** | Toggle item selection on/off in multi-select prompts (e.g. MangaDex multi-language selection, Archive.org asset lists). |
| **`Enter`** | **Global** | Confirm selection, submit URL, or save setting value. |
| **`Esc`** | **Modals & Revolt** | Cancel current modal dialog, dismiss Revolt prompt, or return to the main menu. |

---

### 🏷️ Smart URL Flags & Chapter Continuation

You can append smart flags directly to URLs at the main prompt or inside `vacuum.txt`:

* **`--0` (Quick Grab Mode)**:
  * Forces the download directly into the `Quick grab/` directory, bypassing series indexing and vacuum directory creation.
  * *Example:* `https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664/chapter/211 --0`
* **`--A` / `--a` / `--all` (Vacuum All Mode)**:
  * Forces full vacuum download of all episodes, chapters, and materials for the series into the `Vacuum/` destination folder, bypassing single-item quick grab and interactive selection.
  * Automatically scrapes complete metadata, cover art, and creates the proper series folder structure.
  * *Examples:*
    * `https://hentaihaven.xxx/watch/shoujo-ramune/episode-1/ --a`
    * `https://ohentai.org/detail.php?vid=NjcyNg== --A`
    * `https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664/chapter/211 --a`
* **`--<N>` (Sequential Continuation Limit)**:
  * Continues from where you last left off in `Download History.json` and downloads exactly **`N`** chapters in systematic order (e.g. `--2`, `--4`, `--5`, `--10`).
  * Seamlessly processes decimal chapters (e.g. `Chapter 2.5`) in proper sequence without annoying confirmation prompts.
  * *Example:* `https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664 --5` *(downloads the next 5 unread chapters sequentially).*
* **`--meta` / `--metadata` (Metadata Extraction Mode)**:
  * Headlessly scrapes and extracts all series metadata (Title, Type, Box Purpose, Author/Artist, Studio, Status, Rating, Views, Likes, Tags, Genres, Canonical URL, and Full Synopsis) along with the high-resolution Cover Art into `.zine/metadata.json` without downloading chapters or videos.
  * Compatible with Hwaran (Android) and universal media players.
  * *Examples:*
    * `zine "https://chikari.moe/novels/endless-extraction-in-a-game-like-world" --meta`
    * `zine "https://www.pornhub.com/model/berrybabe69/videos" --meta`
* **`--vacuum` / `--batch` or Direct File Input (Headless Queue Mode)**:
  * Pass any custom text file path directly from the terminal or main prompt with optional flags:
    ```bash
    zine "my_reading_list.txt" --meta
    zine "my_reading_list.txt" --0
    zine --vacuum "my_reading_list.txt"
    # or inside the interactive prompt:
    vacuum "/path/to/my_queue.txt"
    ```
  * Automatically retrieves all URLs, processes them sequentially (honoring per-line inline `--0`, `--a`, `--N`, and `--meta` flags), and automatically checkpoints completed URLs from the queue file for safe resume.
  * If no custom file is specified, it automatically processes `vacuum.txt` located in your project root (auto-generated if missing).

---

### ⚡ Industry-Grade Developer CLI & Diagnostics

Zine Scraper is built for professional developers, terminal power-users, and scriptable headless automation with sub-second responsiveness (< 0.1s):

#### 📖 Master Help Manual (`zine --help` or `zine -h`)
Displays a comprehensive, color-coded manual covering CLI syntax, download control flags, built-in power tools, and copy-paste examples:
```bash
zine --help
# or:
python3 orchestrator.py -h
```

#### 🩺 System Diagnostic Health Check (`zine doctor`)
Performs a live validation of all external binaries, runtime engines, write permissions, and credential files:
```bash
zine doctor
```
```text
╭─────────────────────────────┬──────────────────┬─────────────────────────────╮
│ Diagnostic Check            │ Status           │ Remedy / Notes              │
├─────────────────────────────┼──────────────────┼─────────────────────────────┤
│ Python Version (>= 3.10)    │ ✔ PASS           │ Detected Python 3.14.7      │
│ FFmpeg Audio/Video Engine   │ ✔ PASS           │ /usr/bin/ffmpeg             │
│ Aria2 Multi-Connection Tool │ ✔ PASS           │ /usr/bin/aria2c             │
│ AtomicParsley (M4A/MP4 tags)│ ✔ PASS           │ /usr/bin/atomicparsley      │
│ Deno Runtime (JS Decryption)│ ✔ PASS           │ ~/.deno/bin/deno            │
│ Downloads Storage Access    │ ✔ PASS           │ ~/Downloads/Zine            │
│ Session Logs Storage Access │ ✔ PASS           │ ~/Logs/💩                   │
│ Credentials (secrets.json)  │ ✔ FOUND          │ Auto-scaffolds on API usage │
╰─────────────────────────────┴──────────────────┴─────────────────────────────╯
✦ All critical subsystem diagnostics completed.
```

#### ℹ️ Runtime & Dependency Telemetry (`zine --version` or `zine -v`)
Displays exact version info, Python interpreter path, kernel architecture, binary locations, and active storage roots:
```bash
zine --version
```

#### 🌐 Non-Interactive Supported Sites Directory (`zine sites`)
Prints a clean terminal catalog of all 48 supported platforms, engines, and domains grouped by category without launching the interactive TUI:
```bash
zine sites
```

#### 🧹 Instant Cache Purge (`zine clean`)
Purges all orphaned video segments, fragments (`.part`, `.ytdl`, `.ts`), and slice buffers in `💩/`:
```bash
zine clean
```

#### ⚡ Zero-Friction Return & Error Retention
* **Zero Extra Keystrokes on Success**: When a download completes successfully, Zine automatically returns to the menu without demanding redundant Enter keypresses.
* **Full Error Retention**: If a download fails or an upstream platform errors, Zine **never** clears the screen automatically. The failure card, reason, and error logs stay visible until you explicitly dismiss them.

---

### 📂 Clean Directory Hierarchy (`Vacuum/` & `Quick grab/`)

All downloaded media is cleanly partitioned to eliminate loose root file pollution and redundant nested subfolders:

* **Vacuum Series Archiving (`~/Downloads/Zine/Vacuum/<Site>/<Media Title>/`)**:
  ```text
  # Video Series:
  ~/Downloads/Zine/Vacuum/HentaiHaven/Sei Brunehilde Gakuen Shoujo Kishidan/
  ├── cover.jpg                   # Full-resolution cover artwork
  ├── .zine/metadata.json         # Standardized series & video metadata
  ├── Episode 1.mp4               # Merged high-definition video + audio
  └── subtitle/                   # Cleanly isolated subtitles
      └── Episode 1.en.srt

  # Music Albums:
  ~/Downloads/Zine/Vacuum/YouTube Music/LOVELI LORI/Not So Lovely/
  ├── cover.jpg                   # Full-resolution album artwork
  ├── .zine/metadata.json         # Complete album & track metadata
  └── music/                      # Lossless audio tracks (FLAC default)
      ├── hate u love u.flac
      ├── who else.flac
      └── lyrics/                 # Synced .lrc companion lyrics
          └── hate u love u.lrc

  # Comics / Webtoons:
  ~/Downloads/Zine/Vacuum/Hentai20/Heart-Pounding S-Matching/
  ├── cover.png                   # Full-resolution cover artwork
  ├── .zine/metadata.json         # Standardized series metadata
  ├── Chapter 01/                 # Clean page archives
  └── Chapter 02/

  # Web Novels:
  ~/Downloads/Zine/Vacuum/Chikari/Endless Extraction in a Game-Like World/
  ├── cover.webp                  # Cover artwork
  ├── .zine/metadata.json         # Standardized novel metadata
  └── novel chapter/              # Formatted text chapters
      ├── chapter_0001.txt
      └── chapter_0002.txt
  ```
* **Quick Grab Path (`~/Downloads/Zine/Quick grab/`)**:
  Single one-off downloads are routed directly into `Quick grab/` without generating series scaffolding.
* **Intermediate Cache (`/zine scraper/💩/`)**:
  Temporary video chunks (`.part`, `.ytdl`, `.ts`) and image slices reside in the gitignored temp buffer during assembly and are automatically purged upon completion.

---

### 📋 Industrial Logging & Structured Download Journal (`Logs/`)

Zine features an enterprise-grade dual-tier logging and debugging pipeline split into execution traces (`Logs/💩/`) and structured download journals (`Logs/Downlode 💩/`):

```text
Logs/
├── Downlode 💩/
│   ├── session_YYYY-MM-DD_HH-MM-SS.json   # Unique structured journal per session
│   ├── latest_session.json                # Live mirror of active/most recent session
│   ├── Download History.json              # Master enriched history (site, mode, options, metadata, destination)
│   └── Batch History.json                 # Master batch progress & URL tracking
├── 💩/
│   ├── session_YYYY-MM-DD_HH-MM-SS.log    # Detailed console & network execution traces
│   ├── latest_session.log                 # Pointer to the most recent run trace
│   ├── error_YYYY-MM-DD_HH-MM-SS.log      # Forensic error dumps on failure
│   └── latest_error.log                   # Instant pointer to the last error
└── URL History.txt                        # Master test URL bank
```

#### 📓 1. Structured Download Journal (`Logs/Downlode 💩/`)
* **Fresh JSON Session Per Run**: Every execution generates a fresh session record capturing interactive choices, CLI parameters, item breakdown, and summaries.
* **Interactive & CLI Choice Recording**: Records exact choices (format: `FLAC (Lossless)`, quality: `1080p`, mode: `Vacuum`, continuation counts: `--5`).
* **Rich Metadata & Item Telemetry**: Records media details (Artist, Album, Channel, Author, Total Items, Cover status, Destination path) and individual item states (`downloaded`, `already_exists`, `failed`).

#### 🛠️ 2. Execution Traces & Fault-Tolerant Error Logger (`Logs/💩/`)
* **Silent & Clean Terminal Output**: Unformatted raw Python tracebacks never clutter the UI.
* **1-Second Root-Cause Diagnosis**: If an upstream platform fails, Zine renders an elegant failure card and writes the full contextual traceback with request headers directly to `Logs/💩/latest_error.log`:
  ```text
  ╭─ 🔴 Download Incomplete / Failed ──────────────────────────────────────────╮
  │                                                                            │
  │  Error   : Upstream CDN domain expired or returned HTTP 403                │
  │  Details : Logs/💩/latest_error.log                                        │
  │                                                                            │
  ╰────────────────────────────────────────────────────────────────────────────╯
  ```
* **Instant Inspection Command**:
  ```bash
  cat Logs/💩/latest_error.log
  ```

---

## 🌐 Supported Platforms (48 Scrapers)

Zine natively supports 48 platforms across 12 structured categories (80+ supported domains), with automatic platform detection, multi-mirror failover, and strict site-level isolation (browse interactively via `site` in-app):

### 📺 1. Anime, Torrents & Direct Indexers
> [!NOTE]
> **Web streaming anime scrapers have been retired in favor of high-fidelity Torrents & DDL indexers.**
> Unofficial free streaming sites suffer from relentless takedowns, anti-bot Cloudflare challenges, and aggressive CDN throttling. Zine maintains an encyclopedic database of premier anime indexers (Nyaa, SeaDex, TsukiHime, AnimeTosho) accessible via the in-app `site` command. Direct downloading is not handled by Zine for torrents; users are advised to use an external desktop client such as [qBittorrent](https://www.qbittorrent.org/). Adult anime (Hentai) streaming remains fully supported via native scrapers in Section 8 below.

### 📖 2. Manga (`1_SFW/MANGA`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **MangaDex** | `mangadex.org`<br>`api.mangadex.org` | Official REST API v5, MangaDex@Home, multi-language, decimal parsing ([Guide](docs/ManaDex.md)) |

### 🇰🇷 3. Manhwa (`1_SFW/MANHWA`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Asura Scans** | `asurascans.com`<br>`asuracomic.net`, `asuratoon.com` | Manhwa/Webtoons, decimal chapter resolution |
| **Project Suki** | `projectsuki.com` | Clean ad-free comic scans and chapter batches |
| **Manhuaplus** | `manhuaplus.org` | Chinese manhua, cultivation & martial arts releases |

### 📑 4. Hybrid Comics (`1_SFW/HYBRID_COMICS`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Weeb Central** | `weebcentral.com` | High-speed CDN reader scans, series archiving |
| **Kunmanga** | `kunmanga.com`<br>`kunmanga.co.uk` | Fast chapter image extraction & auto-retry |
| **Topmanhua** | `topmanhua.fan` | High-res manhua/webtoon strip reader, full metadata extraction |
| **Fanfox** | `fanfox.net`<br>`m.fanfox.net` | Global manga directory and complete classic series |
| **MangaK** | `mangak.io` | Historic manga archive, high-res chapter reader |

### 📚 5. Light Novels & Web Serials (`1_SFW/NOVELS`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Chikari** | `chikari.moe` | SvelteKit REST API extraction, ultra-fast 1,400+ chapters indexing |
| **NovelPhoenix** | `novelphoenix.com` | Translated Asian web novels, cultivation epics, clean pagination |
| **NovelFire** | `novelfire.net`<br>`novelfire.docs` | Sanitized chapter extraction, ad-filtered text exports |
| **NovelBuddy** | `novelbuddy.me`<br>`novelbuddy.com` | Next.js API chapter discovery, rich synopsis & cover grabs |
| **NovelArchive** | `novelarchive.cc` | Lightweight REST API web novel repository |

### 🏛 6. Books & Public Archives (`1_SFW/KNOWLEDGE_STUDY`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Project Gutenberg** | `gutenberg.org` | 70,000+ public domain e-books, classic literature, philosophy |
| **Internet Archive** | `archive.org` | Scanned texts, rare manuscripts, permanent open access archives |

### 🎵 7. Music & Audio (`1_SFW/MUSIC`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **SoundCloud** | `soundcloud.com` | High-bitrate audio, track metadata, automated lyrics synchronization |
| **Idagio** | `idagio.com` | Classical music streams, conductor/orchestra/opus metadata tagging |
| **YouTube Music** | `music.youtube.com` | Lossless FLAC, Vorbis tagging, embedded cover art, auto synced `.lrc` lyrics |

### 🌐 8. Video & Social Platforms (`1_SFW/SOCIAL_MEDIA`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **YouTube** | `youtube.com`<br>`youtu.be` | Videos, playlists, channels, shorts, auto-subs & rolling ASR sync |
| **Instagram** | `instagram.com` | High-resolution photos, multi-image carousels, reels, stories |
| **Facebook** | `facebook.com`<br>`fb.watch` | Public photo albums, full-resolution profile media, video reels |
| **Pinterest** | `pinterest.com`<br>`pin.it` | Ultra-high-resolution boards, aesthetic pins, concept art |

### 🔞 9. Adult Anime (`2_NSFW_ADULT/ADULT_ANIME`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Hanime** | `hanime1.me`<br>`hanime.tv` | Full HD 1080p uncensored video streams, playlist feeds |
| **Hanime Red** | `hanime.red` | Franchise collections, tagged releases, subtitle extraction |
| **Hentai Haven** | `hentaihaven.xxx`<br>`hentaihaven.red`, `hentaihaven.online`, `hentaihaven.club` | Multi-mirror stream extraction |
| **HentaiHaven Co** | `hentaihaven.co` | Headless browser bridge extraction via nhplayer |
| **Hentaimama** | `hentaimama.io` | Translated adult anime releases, episode archiving |
| **HStream** | `hstream.moe` | HD adult anime streaming, clean direct streams |
| **OHentai** | `ohentai.org` | Vintage OVA and classic adult anime archives |
| **HentaiCity** | `hentaicity.com` | Comprehensive video repository, multi-episode series tracking |
| **Oppai Stream** | `oppai.stream` | Fast direct HLS adult video streaming |

### 🔞 10. Adult Video (`2_NSFW_ADULT/ADULT_PORN`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **Pornhub** | `pornhub.com`<br>`phncdn.com` | Multi-resolution video downloads (up to 1080p/4K), playlists |

### 🔞 11. Doujinshi (`2_NSFW_ADULT/Doujinshi`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **NHentai** | `nhentai.net` | Fast 6-digit ID lookups, complete tag indexing, tankōbon archives |
| **AsmHentai** | `asmhentai.com` | Curated doujinshi and adult comics with extensive tag matrix |

### 🔞 12. Adult Webtoons (`2_NSFW_ADULT/ADULT_Webtoons`)
| Scraper | Primary & Alternate Domains | Capabilities |
|---|---|---|
| **ManhwaUS** | `manhwaus.net` | Adult Korean webtoons, romance & drama ongoing manhwa |
| **Omega Scans** | `omegascans.org` | Uncensored adult manhwa & webtoons, English scanlations |
| **Hentai20** | `hentai20.io` | Western adult comics, webtoons, and doujinshi releases |
| **Manga18fx** | `manga18fx.com` | Mixed SFW & NSFW manhwa/webtoons, vertical strip slicing |
| **Hentai18** | `hentai18.net` | Uncensored adult manhwa & webtoons, multi-server feeds |
| **Oppai Stream Toon** | `read.oppai.stream` | Dedicated webtoon and comic vertical strip reader |

---

## 🛠️ Feature Toolkit Deep Dive

### 1. Audio Suite & Metadata Baking (`bake`, `lyrs`, `sc-lyrics`)
* **Default Lossless FLAC (`.flac`)**: All music downloads default to pristine Lossless FLAC with dynamic format switching (FLAC, MP3, OPUS, M4A, WAV, AAC) configurable in `settings`.
* **Metadata & Cover Art Baker (`bake` / `metadata`)**: Inspects, edits, and injects ID3/Vorbis tags (**Title**, **Artist**, **Album**, **Year**, **Genre**, **Track Number**) and attaches uncompressed **Cover Art** into `.flac`, `.mp3`, `.m4a`, `.wav`, `.ogg`, and `.opus` files with zero quality degradation.
* **Synced Lyrics Engine (`lyrs`)**: Multi-tier waterfall search (LRCLIB $\rightarrow$ NetEase $\rightarrow$ Megalobiz $\rightarrow$ YouTube ASR auto-captions) with timestamp preview and instant `.lrc` companion export.
* **Folder Lyrics Scanner (`sc-lyrics`)**: Recursively scans existing music folders, detects tracks missing lyrics, and downloads synchronized `.lrc` files automatically.

### 2. AI Speech & Subtitle Generator (`subs`)
* Powered by **`faster-whisper`** (CTranslate2), executing up to **4x faster than standard OpenAI Whisper** with efficient GPU VRAM utilization.
* Transcribes spoken dialogue and translates foreign audio into synchronized `.srt` and `.vtt` subtitles directly on your local GPU/CPU with zero telemetry.
* Models reside in the unified `Models/STT/` directory (`Models/STT/faster-whisper-large-v3-turbo`). Quick download:
  ```bash
  python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/STT/faster-whisper-large-v3-turbo')"
  ```
  *(See [**AI Models Hub Guide**](Models/README%20to%20downlode%20ai%20model.md) for small, medium, and large model options).*

### 3. Neural Speech & Audiobook Synthesis (`breeze`, `tts`)
* **Breeze-TTS-2 Hub (`breeze`)**: C++ / GGUF neural speech engine running on Vulkan GPU acceleration. Features **Voice Design** (text prompt defines voice), **Voice Cloning** (5-15s reference audio), **Voice Direction** (tone/pace steering), **Saved Voice Profiles** (`.breeze` fast 280ms TTFA cache), **Voice Conversion** (`breeze-convert`), and **Vocal Event Tags** `(sigh)`, `(laugh)`, `(whispering)`, `(clears throat)` with dynamic 2.5x CFG auto-boost.
* **Qwen-TTS Audiobook Synthesizer (`tts` / `qwen`)**: Converts `.txt` web serials, light novels, and e-books into studio-grade `.wav` audiobooks with synchronized `.srt` subtitles via ComfyUI integration.
* **Semantic Context Splitting & Subtitles**: Detects chapter headers, character dialogue, poetry, system alerts, and emotional beats to dynamically adapt vocal intonation and generate frame-accurate `.srt` subtitles.
* **Auto-Resume Caching**: Caches intermediate synthesized chunks in temp buffers to prevent loss on interruptions.
* **Unified AI Models Hub (`Models/`)**: Organized into `Models/STT/` (Whisper models) and `Models/TTS/` (Breeze GGUF weights & C++ binaries). See [**AI Models Hub Guide**](Models/README%20to%20downlode%20ai%20model.md).

### 4. Webtoon & Manhua Image Slicer (`slice`)
* Automatically detects tall continuous vertical image strips common in Korean Manhwa and Chinese Manhua.
* Intelligently slices them into uniform 2000px height pages (numbered `001.jpg`, `002.jpg`), leaving normal ratio pages untouched.

### 5. Automated Vacuum Queue Pipeline (`vacuum`)
* Drop any combination of URLs (manga, anime, songs, channels, playlists, e-books) into `vacuum.txt`.
* Run `vacuum` (or launch in headless mode with `--vacuum`). Zine iterates through the queue sequentially with automatic error recovery and zero manual intervention.
* **Atomic State Checkpointing**: Automatically updates `vacuum.txt` by removing finished items, while writing detailed JSON history records to `Logs/Downlode 💩/Batch History.json` and session logs so you can safely resume interrupted batches.

### 6. Global Revolt (`Ctrl + R`) & Truncate (`Ctrl + T`)
* **Ctrl + R (Revolt Mode)**: Gracefully halts downloads after current item (`0`) or `N` more items, shuts down cleanly, and triggers an OS notification.
* **Ctrl + T (Truncate Mode)**: Immediately finishes the active file/chapter and returns straight back to the main interactive menu without closing Zine.

### 7. MangaDex Multi-Language Archiving
* Full integration with official MangaDex REST API v5 and MangaDex@Home CDN infrastructure.
* **Interactive Multi-Language Selector**: Use **`Space`** in the `MultiSelector` prompt to choose multiple language translations at once.
* **Isolated Folder Architecture**: Automatically routes distinct translations into separated directories (e.g. `MangaDex/Title [en]`, `MangaDex/Title [ja]`) with per-language history tracking.

### 8. Butler Whistleblower & Network Auto-Recovery
* Continuous background network connection monitor running alongside the download engine.
* Automatically pauses active queues upon internet dropouts and seamlessly resumes downloading as soon as connectivity returns, preventing corrupted chunks or broken files.

---

## 🗂️ Architecture & Engineering

### Directory Layout
```text
zine-scraper/
├── orchestrator.py          ← Main entry point — launches CLI and TUI
├── core/
│   ├── funnel.py            ← Universal CLI/queue ingestion funnel & path routing
│   ├── metadata_engine.py   ← Standardized JSON metadata serialization & schema engine
│   ├── logger.py            ← Dual-tier session & contextual error logging engine
│   ├── site_map.py          ← Centralized site-to-category domain mapper
│   ├── domain_manager.py    ← Dynamic site_config.json discovery loader
│   ├── ui.py                ← Rich TUI primitives, banners, failure cards & cbreak TTY loop
│   ├── bake_engine.py       ← Audio Metadata & Cover Art Baking Engine
│   ├── lyrics_engine.py     ← Multi-tier Synced Lyrics Search & Batch Sync
│   ├── subtitle_engine.py   ← Faster-Whisper GPU Subtitle Generator
│   ├── settings_tui.py      ← Interactive Settings Configurator TUI
│   ├── site_tui.py          ← Supported Sites Database TUI & Catalog
│   ├── image_slicer.py      ← Manhua & Webtoon Image Strip Slicer Tool
│   ├── config.py            ← Persistent settings & configuration layer
│   ├── paths.py             ← Filesystem authority & path routing (Vacuum vs Quick Grab)
│   ├── storage.py           ← Atomic disk I/O layer
│   └── history.py           ← Download registry & duplicate protection
├── scrapers/                ← Categorized site scraper packages (strict site isolation)
│   ├── 1_SFW/
│   │   ├── MANGA/           ← mangadex
│   │   ├── MANHWA/          ← asurascans, projectsuki, manhuaplus
│   │   ├── HYBRID_COMICS/   ← kunmanga, topmanhua, weebcentral, fanfox, mangak
│   │   ├── NOVELS/          ← chikari, novelarchive, novelbuddy, novelfire, novelphoenix
│   │   ├── KNOWLEDGE_STUDY/ ← archive, gutenberg
│   │   ├── MUSIC/           ← idagio, soundcloud, yt_music
│   │   └── SOCIAL_MEDIA/    ← facebook, instagram, pinterest, youtube
│   ├── 2_NSFW_ADULT/
│   │   ├── ADULT_ANIME/     ← hanime, hanime_red, hentaicity, hentaihaven, hentaihaven_co, hentaimama, hstream, ohentai, oppai_stream
│   │   ├── ADULT_PORN/      ← pornhub
│   │   ├── Doujinshi/       ← asmhentai, nhentai
│   │   └── ADULT_Webtoons/  ← manhwaus, omegascans, hentai20, manga18fx, hentai18, oppai_stream_toon
│   └── 3_SYSTEM/            ← hls_extractor.py, playwright_extractor.py, ytdlp/
├── Logs/                    ← Operational logging, download registry & debug forensics
│   ├── 💩/                  ← Timestamped session traces & latest_error.log dumps
│   ├── Downlode 💩/         ← Structured JSON download journals & session logs
│   ├── Batch History.json   ← Checkpointed history of completed batch jobs
│   ├── Download History.json← Permanent media index preventing duplicate grabs
│   └── URL History.txt      ← In-app command history and URL suggestions
├── Models/                  ← Unified storage hub for offline AI models & engines
│   ├── STT/                 ← Speech-to-Text models (faster-whisper)
│   └── TTS/                 ← Text-to-Speech models & engines (Breeze-TTS-2 / Qwen)
│       ├── Breeze tts/      ← Breeze-TTS-2 C++/GGUF Neural Speech Synthesizer
│       └── Qween tts/       ← Qwen-TTS Audiobook Synthesizer Engine
├── preview/                 ← TUI screenshots & showcase gallery
├── theme/                   ← 80+ custom Tokyo Night & Dark color palettes
└── run me/                  ← Cross-platform automated installers & launchers
```

### Key Engineering Principles
* **Dual-Tier Forensic Logging**: Every run records clean telemetry to `Logs/💩/latest_session.log`. When upstream CDNs or servers fail, full stack traces and request contexts are captured to `Logs/💩/latest_error.log` while the terminal displays a concise status card.
* **Scriptable Headless CLI**: Direct URL invocation bypasses interactive selector prompts when flags (`--0`, `--a`, `--<N>`, `--vacuum`) are passed, enabling seamless automation via terminal or scripts.
* **Isolated Media Packaging**: Downloads are strictly organized in `~/Downloads/Zine/Vacuum/<Category>/<Site>/<Media Title>/` with cover art, metadata, and subtitle folders without polluting root directories.
* **Single-Session cbreak Event Processing**: Replaced per-keystroke `tty.setraw()` invocations with a single persistent `tty.setcbreak()` session, eliminating stdin blocking locks and 30Hz loop latency.
* **Zero ANSI Sequence Leaks**: Multi-byte escape sequences (`\x1b[A`, `\x1b[B`, `\x1b[C`, `\x1b[D`) are cleanly buffered so arrow keys, `Backspace`, `Home`, and `End` never print control artifacts into the terminal.
* **Universal Rich Markup Sanitization**: All pasted inputs and exception messages are passed through `rich.markup.escape()` to prevent syntax crashes from square brackets or URL tags.
* **Intermediate Temp Buffer (`💩/`)**: All video fragments, image chunks, and tag buffers remain safely inside the centralized temp directory until validation is verified.
* **Site-Level Isolation**: Scrapers never share cross-dependencies, keeping each extraction platform fully self-contained.

---

<p align="center">
  Licensed under <a href="LICENSE">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)</a>.<br>
  Strictly for personal, non-commercial archival use. Commercial resale or unauthorized rebranding is strictly prohibited.
</p>