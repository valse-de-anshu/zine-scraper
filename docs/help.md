# Zine Scraper Suite — Comprehensive User & CLI Guide

Welcome to the **Zine Scraper Suite** help console! Zine is a high-performance, modular desktop scraper suite designed for archiving manga, webtoons, anime, videos, music, books, and images.

---

## 🚀 Available Commands

You can type any of the following commands directly at the main prompt:

- **`server`** or **`/server`**
  Launch the high-performance Go companion relay daemon for Hwaran (Android) and remote ingestion. Features zero-configuration LAN UDP discovery on ports 53319 and 53318, real-time unbuffered progress streaming, direct ZIP extraction, and ephemeral relay mode.

- **`bake`** or **`/bake`**
  Launch the Audio Metadata & Cover Art Baking Engine. Edit tags, inject hi-res covers, and embed standard metadata into audio files via FFmpeg / Mutagen.

- **`vacuum`** or **`/vacuum`**
  Process all queued URLs listed inside your `vacuum.txt` or custom queue file headlessly with per-line flag support.

- **`exit`** or **`quit`** or **`q`**
  Gracefully exit the Zine Scraper Suite and instantly flush all active AI models from system memory.

- **`help`** or **`/help`**
  Display this comprehensive user guide and keyboard shortcut reference.

- **`lyrs`** or **`/lyrs`** or **`lyrics`**
  Search, fetch, and download synchronized `.lrc` lyrics for any song via a 6-tier waterfall (LRCLIB, NetEase, Megalobiz).

- **`sc-lyrics`** or **`/sc-lyrics`** or **`sclyrs`**
  Batch scanner for your music library. Automatically finds missing `.lrc` lyrics files and fetches synced lyrics across all tracks.

- **`settings`** or **`/settings`**
  Open the interactive Settings Configurator to adjust Library Root Path, Music Quick-Grab Path, Chapter Download Delay, Connection Check Delay, AI Subtitles (Whisper), Breeze TTS 2, Qwen TTS logic, and Visual Color Themes.

- **`site`** or **`/site`** or **`sites`**
  Open the interactive Supported Site Database TUI to view all 48+ supported platforms, domain aliases, categories, and direct extraction capability.

- **`slice`** or **`/slice`** or **`slicer`**
  Launch the Manhua & Webtoon Image Slicer Tool. Automatically splits long vertical image strips into perfectly proportioned 2000px height pages (numbered `001.jpg`, `002.jpg`), leaving normal ratio images untouched.

- **`subs`** or **`/subs`** or **`subtitles`**
  Launch the built-in AI Subtitle Generator. Uses `faster-whisper` and `deep-translator` to run fully offline on your GPU (or CPU) to generate and translate `.srt` subtitles (e.g. from JP to EN) for any downloaded video.

- **`tts`** or **`/tts`** or **`audiobook`**
  Launch the Universal Audiobook TTS Hub. Interactively select between Breeze-TTS-2 (GGUF / Vulkan C++ with Voice Design, Cloning & Vocal Events) or Qwen3-TTS (ComfyUI Workflow Server). Converts any `.txt` novel into an audiobook with synced `.srt` subtitles and auto-resume tracking.

- **`doctor`** or **`/doctor`**
  Run complete system diagnostic health check across Python, FFmpeg, Aria2, Deno, Playwright, GPU acceleration, and storage permissions.

- **`clean`** or **`/clean`**
  Instantly purge temporary chunks, fragmented video downloads, and buffer files in `💩/`.

- **`version`** or **`/version`**
  Display complete version, kernel runtime telemetry, and dependency status.

---

## ⌨️ TUI Navigation & Shortcuts

| Key | Context | Action |
|---|---|---|
| **`Ctrl + R`** | **Any Active Download** | **Global Revolt Mode**: Interactively halt downloads after current file (`0`) or `N` more files. Exits cleanly and dispatches an OS notification |
| **`Ctrl + T`** | **Any Active Download** | **Global Truncate Mode**: Stop active download early after current item and return cleanly to main menu without terminating Zine |
| **`Ctrl + C`** | **Global** | **Force Clean Exit**: Immediately cancel active task, cleanly exit, restore terminal, and flush AI models from VRAM |
| **`↑` / `↓`** | **Menus & Prompt** | Navigate between menu items, selector options, or cycle command history |
| **`←` / `→`** | **Input & Menus** | Move cursor within input text or switch horizontal selector options |
| **`Home` / `End`** | **Input Prompt** | Instantly jump the cursor to the beginning or end of input text |
| **`Tab`** | **Input Prompt** | Auto-complete inline command suggestions or toggle field edit mode |
| **`Space`** | **Multi-Selectors** | Toggle item selection on/off in multi-select prompts (e.g. MangaDex multi-language) |
| **`Enter`** | **Global** | Select option, save edit, or launch selected action |
| **`Esc`** | **Modals & Revolt** | Exit current modal dialog, dismiss Revolt prompt, or return to main menu |
| **`Backspace`** | **Text Input** | Delete character in text edit fields or revolt input buffer |

---

## 🏷️ Smart URL Flags

You can append flags directly to URLs at the main prompt, in terminal CLI commands, or inside `vacuum.txt`:

- **`--0`** (Quick Grab Mode):
  Forces the download directly into the `Quick grab/` directory, bypassing series indexing.
  *Example:* `https://asurascans.com/comics/my-series/chapter-1 --0`

- **`--A` / `--a` / `--all`** (Vacuum All Mode):
  Forces full vacuum download of all episodes, chapters, and materials for the series into the `Vacuum/` directory, bypassing single-item quick grab and interactive selection prompts. Scrapes all metadata, cover art, and creates the proper series folder structure.
  *Example:* `https://asurascans.com/comics/my-series/chapter-1 --a`

- **`--<N>`** (Sequential Chapter Limit):
  Continues from where you left off in `Download History.json` and downloads exactly `N` chapters in systematic order (e.g. `--2`, `--5`, `--10`). Automatically handles decimal chapters without prompting.
  *Example:* `https://asurascans.com/comics/my-series --5`

- **`--meta` / `--metadata`** (Metadata Extraction Only):
  Extracts and writes `.zine/metadata.json` (Title, Creator, Synopsis, Views, Likes, Genres, Tags) and high-res cover art into `Vacuum/` without downloading media streams or chapter images.
  *Example:* `https://chikari.moe/novels/my-novel-slug --meta`

- **`--server [PORT]`** (Companion Relay Server):
  Starts the companion server on the specified port (default `53318`) for Hwaran (Android) and remote ingestion.
  *Example:* `zine --server`

- **`--resolve-link <URL>`** (Link Architecture Inspector):
  Fast headless inspector validating the URL, identifying scraper engine and category, and displaying scope flags in JSON format.
  *Example:* `zine --resolve-link "https://youtube.com/@channel/videos"`

---

## 📁 Library & Configuration Rules

- **Library Root Path**: Default parent directory for all downloaded media (`~/Downloads/Zine`). All content is saved into structured subdirectories:
  - `toon/` : Manga, Manhua, Manhwa, Comics
  - `video/` : Anime, Movies, Web Videos
  - `music/` : Songs, Albums, Audio Tracks
  - `book/` : Light Novels, E-books, PDFs
- **Duplicate Protection**: Downloaded files are automatically checked against `Logs/Downlode 💩/Download History.json` to prevent re-downloading existing media.
- **Batch History & Resume**: Batch operations maintain atomic check-offs in `vacuum.txt` and dual logs in `Logs/Downlode 💩/Batch History.json` and `Logs/💩/batch_history.json`.
- **Site Isolation**: Each scraper platform runs as a self-contained module under `scrapers/<category>/<site>/`.

---

Press **ESC** to exit help and return to the main menu.
