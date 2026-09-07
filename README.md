<div align="center">

<pre>
███████╗██╗███╗   ██╗███████╗
╚══███╔╝██║████╗  ██║██╔════╝
  ███╔╝ ██║██╔██╗ ██║█████╗  
 ███╔╝  ██║██║╚██╗██║██╔══╝  
███████╗██║██║ ╚████║███████╗
╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝
</pre>

# Zine Scraper Suite

**A high-performance CLI tool build to save the media you love permanently onto your hard drive.**

<p align="center">
  🎵 <b>Music:</b> Full-quality audio with proper artist metadata, album art, and scrolling lyrics.<br>
  📖 <b>Manga, Manhua, Novels & Comics:</b> Complete series archiving with neatly organized chapters.<br>
  🎬 <b>Anime & Videos(18+) :</b> Multi-season series, playlists, and 1080p/4K streams without ads or popups.<br>
  📚 <b>Books & Images:</b> Web serials, public domain classics, and AI-powered audiobooks.
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-red?style=for-the-badge" alt="CC BY-NC-SA 4.0 License"></a>
  <a href="https://discord.gg/suJD5xtFj"><img src="https://img.shields.io/badge/Discord-Join%20Community-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord Community"></a>
  <a href="https://github.com/valse-de-anshu/zine-scraper/releases"><img src="https://img.shields.io/badge/Release-v1.0.0-orange?style=for-the-badge" alt="v1.0.0"></a>
</p>

</div>

---

<div align="center">

## 🖼️ Preview & Showcase

| Interactive Command Prompt | Chapter & Episode Selector |
| :---: | :---: |
| <img src="preview/01-home-tui-quick-guide.png" width="440" alt="Command Prompt"> | <img src="preview/03-interactive-tui-quick-grab.png" width="440" alt="Chapter Selector"> |
| **Live Multi-Threaded Download Pipeline** | **Download Summary & Finished Media** |
| <img src="preview/04-download-log-tui-01.png" width="440" alt="Download Pipeline"> | <img src="preview/06-download-complete-tui.png" width="440" alt="Download Complete"> |

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

* **Linux / macOS:**
  ```bash
  cd "zine-scraper"
  ./"run me"/run.sh
  # (Or manually: source venv/bin/activate && python3 orchestrator.py)
  ```
* **Windows:**
  ```cmd
  cd "zine-scraper"
  "run me\run.bat"
  ```

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
| **`bake`** | **Audio** | Audio Metadata & Cover Art Baking Engine (FFmpeg / Mutagen) |
| **`lyrs`** | **Audio** | Synced `.lrc` Lyrics Search & Downloader (6-tier waterfall: LRCLIB, NetEase, Megalobiz) |
| **`sc-lyrics`** | **Audio** | Batch music folder scanner and automated `.lrc` lyrics synchronization |
| **`subs`** | **AI Tools** | AI Subtitle Generator (`faster-whisper` local GPU transcription & translation) |
| **`tts`** | **AI Tools** | Qwen-TTS Audiobook Synthesizer (voice design & character acting from `.txt`) |
| **`slice`** | **Tools** | Webtoon & Manhua Image Slicer (splits long vertical strips into standard pages) |
| **`batch`** | **System** | Batch Downloader (auto-processes all queued links in `Batch URL.txt`) |
| **`settings`** | **System** | Interactive Settings Configurator (download paths, 80+ themes, network delays) |
| **`site`** | **System** | Interactive Supported Sites Database & Catalog viewer |
| **`help`** | **System** | In-app documentation and quick guide browser |
| **`exit` / `q`** | **System** | Clean exit from Zine Scraper Suite |

---

### ⌨️ Keybindings & Hotkeys Reference

| Key | Context | Action |
|---|---|---|
| **`Ctrl + R`** | **Any Active Download** | **Global Revolt Mode** — Interactively halt downloads after current file (`0`) or `N` more files. Exits cleanly and dispatches an OS completion notification. |
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

You can append smart flags directly to URLs at the main prompt or inside `Batch URL.txt`:

* **`--0` (Quick Grab Mode)**:
  * Forces the download directly into the `Quick grab/` directory, bypassing series indexing and vacuum directory creation.
  * *Example:* `https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664/chapter/211 --0`
* **`--<N>` (Sequential Continuation Limit)**:
  * Continues from where you last left off in `Download History.json` and downloads exactly **`N`** chapters in systematic order (e.g. `--2`, `--4`, `--5`, `--10`).
  * Seamlessly processes decimal chapters (e.g. `Chapter 2.5`) in proper sequence without annoying confirmation prompts.
  * *Example:* `https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664 --5` *(downloads the next 5 unread chapters sequentially).*
* **Flag Combinations in Batch Mode**:
  * Flags can be mixed freely inside `Batch URL.txt` per-line:
    ```text
    https://asurascans.com/comics/the-return-of-the-crazy-demon-08677664 --5
    https://omegascans.org/series/my-lewd-college-friends/chapter-58 --0
    https://mangadex.org/title/a1c7c817-4e59-43b7-9365-09675a149a6f --3
    ```

---

## 🌐 Supported Platforms

Zine natively supports 48+ platforms across 8 dedicated categories (80+ supported domains), with automatic platform detection, multi-mirror failover, and strict site-level isolation (browse interactively via `site` in-app):

### 📺 1. Anime (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **HiAnime** | `hianime.to` | `hianime.sx`, `hianime.mn`, `hianime.nz`, `hianime.ad` | Multi-server HLS streams, Sub & Dub multi-audio |
| **Anikoto** | `anikoto.cz` | `anikototv.to`, `anikoto.me`, `anikoto.net` | Low-latency streaming, auto domain rotation |
| **Anineko** | `anineko.to` | — | Minimalist, ad-light subbed episode streams |
| **Anitaku** | `anitaku.online` | `anitaku.to`, `anitaku.me` | Legacy anime archive, multi-quality resolutions |
| **Miruro** | `miruro.to` | `miruro.ru`, `miruro.tv`, `miruro.bz` | Fast API stream extraction, AniList GraphQL sync |

### 📖 2. Manga & Manhwa (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **MangaDex** | `mangadex.org` | `api.mangadex.org` | Official REST API v5, MangaDex@Home, multi-language, decimal parsing ([Guide](docs/ManaDex.md)) |
| **Asura Scans** | `asurascans.com` | `asuracomic.net`, `asuratoon.com` | Manhwa/Webtoons, decimal chapter resolution |
| **Weeb Central** | `weebcentral.com` | — | High-speed CDN reader scans, series archiving |
| **Project Suki** | `projectsuki.com` | — | Clean ad-free comic scans and chapter batches |
| **Manhuaplus** | `manhuaplus.org` | — | Chinese manhua, cultivation & martial arts releases |
| **MangaK** | `mangak.io` | — | Historic manga archive, high-res chapter reader |
| **Kunmanga** | `kunmanga.com` | `kunmanga.co.uk` | Fast chapter image extraction & auto-retry |
| **Fanfox** | `fanfox.net` | `m.fanfox.net` | Global manga directory and complete classic series |

### 📚 3. Light Novels & Web Serials (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **Chikari** | `chikari.moe` | — | SvelteKit REST API extraction, ultra-fast 1,400+ chapters indexing |
| **NovelPhoenix** | `novelphoenix.com` | — | Translated Asian web novels, cultivation epics, clean pagination |
| **NovelFire** | `novelfire.net` | `novelfire.docs` | Sanitized chapter extraction, ad-filtered text exports |
| **NovelBuddy** | `novelbuddy.me` | `novelbuddy.com` | Next.js API chapter discovery, rich synopsis & cover grabs |
| **NovelArchive** | `novelarchive.cc` | — | Lightweight REST API web novel repository |

### 🎵 4. Music & Audio (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **YouTube Music** | `music.youtube.com` | `youtube.com` | Lossless FLAC, Vorbis tagging, embedded cover art, auto synced `.lrc` lyrics |
| **SoundCloud** | `soundcloud.com` | — | High-bitrate audio, track metadata, automated lyrics synchronization |
| **Idagio** | `idagio.com` | — | Classical music streams, conductor/orchestra/opus metadata tagging |
| **Internet Archive Music** | `archive.org/details/audio` | `archive.org` | Lossless live concerts (250,000+ shows), historical audio recordings |

### 🏛 5. Books & Public Archives (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **Project Gutenberg** | `gutenberg.org` | — | 70,000+ public domain e-books, classic literature, philosophy |
| **Internet Archive** | `archive.org` | — | Scanned texts, rare manuscripts, permanent open access archives |

### 🌐 6. Video & Social Platforms (SFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **YouTube** | `youtube.com` | `youtu.be` | Videos, playlists, channels, shorts, auto-subs & rolling ASR sync |
| **Instagram** | `instagram.com` | — | High-resolution photos, multi-image carousels, reels, stories |
| **Facebook** | `facebook.com` | `fb.watch` | Public photo albums, full-resolution profile media, video reels |
| **Pinterest** | `pinterest.com` | `pin.it` | Ultra-high-resolution boards, aesthetic pins, concept art |

### 🔞 7. Adult Video (NSFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **Pornhub** | `pornhub.com` | `phncdn.com` | Multi-resolution video downloads (up to 1080p/4K), playlists |
| **HStream** | `hstream.moe` | — | HD adult anime streaming, clean direct streams |
| **Hentai18** | `hentai18.net` | — | Uncensored HD releases, multi-server feeds |
| **OHentai** | `ohentai.org` | — | Vintage OVA and classic adult anime archives |
| **Hentaimama** | `hentaimama.io` | — | Translated adult anime releases, episode archiving |
| **Oppai Stream** | `oppai.stream` | `read.oppai.stream` | Unified adult video streaming and webtoon reader |
| **hanime.red** | `hanime.red` | — | Franchise collections, tagged releases, creator catalogs |
| **Hentai Haven** | `hentaihaven.xxx` | `hentaihaven.red`, `hentaihaven.co` | Multi-mirror stream extraction |

### 🔞 8. Adult Comics & Doujinshi (NSFW)
| Platform | Primary Domain | Alternate Domains | Capabilities |
|---|---|---|---|
| **NHentai** | `nhentai.net` | — | Fast 6-digit ID lookups, complete tag indexing, tankōbon archives |
| **Omega Scans** | `omegascans.org` | — | Uncensored adult manhwa & webtoons, English scanlations |
| **Hentai8** | `hentai8.net` | — | Fast-loading translated Japanese doujinshi galleries |
| **AsmHentai** | `asmhentai.com` | — | Curated doujinshi and adult comics with extensive tag matrix |
| **Hentaicity** | `hentaicity.com` | — | Granular tag intersection search and chapter downloads |
| **Hentai20** | `hentai20.io` | — | Western adult comics, webtoons, and doujinshi releases |
| **ManhwaUS** | `manhwaus.net` | — | Adult Korean webtoons, romance & drama ongoing manhwa |
| **Manga18fx** | `manga18fx.com` | — | Mixed SFW & NSFW manhwa/webtoons, vertical strip slicing |

---

## 🛠️ Feature Toolkit Deep Dive

### 1. Audio Suite & Metadata Baking (`bake`, `lyrs`, `sc-lyrics`)
* **Metadata & Cover Art Baker (`bake`)**: Inspects, edits, and injects ID3/Vorbis tags (**Title**, **Artist**, **Album**, **Year**, **Genre**, **Track Number**) and attaches uncompressed **Cover Art** into `.flac`, `.mp3`, `.m4a`, `.wav`, `.ogg`, and `.opus` files with zero quality degradation.
* **Synced Lyrics Engine (`lyrs`)**: Multi-tier waterfall search (LRCLIB $\rightarrow$ NetEase $\rightarrow$ Megalobiz $\rightarrow$ YouTube ASR auto-captions) with timestamp preview and instant `.lrc` companion export.
* **Folder Lyrics Scanner (`sc-lyrics`)**: Recursively scans existing music folders, detects tracks missing lyrics, and downloads synchronized `.lrc` files automatically.

### 2. AI Speech & Subtitle Generator (`subs`)
* Powered by **`faster-whisper`** (CTranslate2), executing up to **4x faster than standard OpenAI Whisper** with efficient GPU VRAM utilization.
* Transcribes spoken dialogue and translates foreign audio into synchronized `.srt` and `.vtt` subtitles directly on your local GPU/CPU with zero telemetry.
* Quick download for the recommended flagship model:
  ```bash
  python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/faster-whisper-large-v3-turbo')"
  ```
  *(See [**AI Models Guide**](Models/README%20to%20downlode%20ai%20model.md) for small, medium, and large model options).*

### 3. Qwen-TTS Audiobook Synthesizer (`tts`)
* Transforms downloaded `.txt` web serials, light novels, and e-books into studio-grade `.wav` audiobooks with synchronized `.srt` subtitles.
* **Semantic Context Splitting**: Detects chapter headers, character dialogue, poetry, and narrative action to modulate vocal inflection.
* **Auto-Resume Caching**: Caches intermediate synthesized chunks in temp buffers to prevent loss on interruptions.
* **ComfyUI Integration**: Seamlessly interfaces with local or remote GPU servers running Qwen-TTS custom nodes.

### 4. Webtoon & Manhua Image Slicer (`slice`)
* Automatically detects tall continuous vertical image strips common in Korean Manhwa and Chinese Manhua.
* Intelligently slices them into uniform 2000px height pages (numbered `001.jpg`, `002.jpg`), leaving normal ratio pages untouched.

### 5. Automated Batch Pipeline (`batch`)
* Drop any combination of URLs (manga, anime, songs, channels, playlists, e-books) into `Batch URL.txt`.
* Run `batch` (or launch in headless mode). Zine iterates through the queue sequentially with automatic error recovery and zero manual intervention.
* **Dual History Logging & State Checkpointing**: Atomically updates `Batch URL.txt` by checking off finished items, while writing dual-target JSON history records to `Logs/Batch History.json` and `Logs/💩/batch_history.json` so you can safely resume interrupted batches.

### 6. Global Revolt Mode (`Ctrl + R`)
* Universal graceful download limiter and emergency stop integrated across all 47 scrapers.
* Press **`Ctrl + R`** during active downloads to trigger the inline Revolt prompt:
  * Enter **`0`** to finish the active file/chapter and immediately shut down.
  * Enter **`N`** (e.g. `2`, `5`) to download $N$ more items sequentially before exiting.
  * Press **`Esc`** or submit an empty input to cancel Revolt mode.
* **Native Desktop Notification**: Automatically triggers a cross-platform OS notification (`Zine Scraper — Revolt`) upon completion with series title context.
* Restores terminal cursor visibility (`\033[?25h`) and raw mode settings without lingering listener threads.

### 7. MangaDex Multi-Language Archiving
* Full integration with official MangaDex REST API v5 and MangaDex@Home CDN infrastructure.
* **Interactive Multi-Language Selector**: Use **`Space`** in the `MultiSelector` prompt to choose multiple language translations at once.
* **Isolated Folder Architecture**: Automatically routes distinct translations into separated directories (e.g. `MangaDex/Title [en]`, `MangaDex/Title [ja]`) with per-language history tracking.
* **Smooth 12Hz Braille Spinners**: Rotating braille animations (`⠋`, `⠙`, `⠹`, `⠸`...) during stream loading and metadata baking.

### 8. Butler Whistleblower & Network Auto-Recovery
* Continuous background network connection monitor running alongside the download engine.
* Automatically pauses active queues upon internet dropouts and seamlessly resumes downloading as soon as connectivity returns, preventing corrupted chunks or broken files.

---

## 🗂️ Architecture & Engineering

### Directory Layout
```text
zine-scraper/
├── orchestrator.py          ← Main entry point — launches the suite
├── core/
│   ├── funnel.py            ← Command router & input sanitization
│   ├── ui.py                ← Rich TUI primitives, revolt listener & raw cbreak TTY loop
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
├── scrapers/                ← 47+ isolated site scraper packages (80+ domains)
│   └── <category>/<site>/
│       ├── engine.py        ← Extraction logic & API queries
│       ├── scraper.py       ← Scraper interface definition
│       ├── tui.py           ← Site TUI interactive entrypoint
│       └── workflow.py      ← Multi-threaded download orchestrator
├── Models/                  ← Local storage hub for offline AI models
├── Qween tts/               ← Qwen-TTS Audiobook Synthesizer Engine
├── preview/                 ← TUI screenshots & showcase gallery
├── theme/                   ← 80+ custom Tokyo Night & Dark color palettes
└── run me/                  ← Cross-platform automated installers & launchers
```

### Key Engineering Principles
* **Single-Session cbreak Event Processing**: Replaced per-keystroke `tty.setraw()` invocations with a single persistent `tty.setcbreak()` session, eliminating stdin blocking locks and 30Hz loop latency.
* **Zero ANSI Sequence Leaks**: Multi-byte escape sequences (`\x1b[A`, `\x1b[B`, `\x1b[C`, `\x1b[D`) are cleanly buffered so arrow keys, `Backspace`, `Home`, and `End` never print control artifacts into the terminal.
* **Universal Rich Markup Sanitization**: All pasted inputs and exception messages are passed through `rich.markup.escape()` to prevent syntax crashes from square brackets or URL tags.
* **Intermediate Temp Buffer (`💩/`)**: All video fragments, image chunks, and tag buffers remain safely inside the centralized temp directory until validation is verified.
* **Site-Level Isolation**: Scrapers never share cross-dependencies, keeping each extraction platform fully self-contained.

---

## ✉️ Creator Note & Contribution

> [!NOTE]
> ### 📌 A Message From The Creator (Anshu / Valse)
>
> *"I am a 17-year-old developer, and I dedicated 3 full months of my life to building, refining, and perfecting Zine Scraper Suite. As I am currently preparing for my competitive exams, this project was my first and last passionate project for now. I will start releasing bangers again after I achieve my dream college! Till then enjoy, use Zine, and share your experience with everyone!"*
>
> * **Join our Discord Community**: [https://discord.gg/suJD5xtFj](https://discord.gg/suJD5xtFj)
> * **Email Me Directly**: [valsedeanshu@gmail.com](mailto:valsedeanshu@gmail.com)
> * **Contribute**: Check out [CONTRIBUTING.md](CONTRIBUTING.md) to add features or new scrapers!

---

## ❤️ Credits & Acknowledgments

```text
  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │  CREDITS & ACKNOWLEDGMENTS                                                                                      │
  ├───────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Contributor       │ Role & Primary Contributions                                                                │
  ├───────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Anshu / Valse     │ Creator, Lead Architect & Solo Core Developer                                               │
  │                   │ • Designed & built 100% of all scraping logic, engines, and 34+ site scrapers from scratch. │
  │                   │ • Engineered the core architecture, Rich TUI framework, funnel router, and settings suite.  │
  │                   │ • Dedicated 3 months of solo engineering to create and perfect the Zine Scraper Suite.      │
  ├───────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ Antigravity AI    │ AI Pair Programming Assistant                                                               │
  │ (Google DeepMind) │ • Debugged codebase issues, conducted empirical runtime verification & test suites.         │
  │                   │ • Refactored TUI event processing to zero-leak raw TTY cbreak loops for high responsiveness.|
  │                   │ • Assisted in architecture refactoring for site-level scraper isolation & crashproofing.    |
  └───────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

<p align="center">
  Licensed under <a href="LICENSE">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)</a>.<br>
  Strictly for personal, non-commercial archival use. Commercial resale or unauthorized rebranding is strictly prohibited.
</p>