# Zine Scraper Suite — Comprehensive User & CLI Guide

Welcome to the **Zine Scraper Suite** help console! Zine is a high-performance, modular desktop scraper suite designed for archiving manga, webtoons, anime, videos, music, books, and images.

---

## 🚀 Available Commands

You can type any of the following commands directly at the main prompt:

- **`settings`** or **`/settings`**
  Open the interactive Settings Configurator to adjust Library Root Path, Music Quick-Grab Path, Chapter Download Delay, Connection Check Delay, AI Subtitles (Whisper), Qwen TTS logic, and Visual Color Themes.

- **`site`** or **`/site`** or **`sites`**
  Open the interactive Supported Site Database TUI to view all 34+ supported platforms, domain aliases, categories, and direct extraction capability.

- **`slice`** or **`/slice`** or **`slicer`**
  Launch the Manhua & Webtoon Image Slicer Tool. Automatically splits long vertical image strips into perfectly proportioned 2000px height pages (numbered `001.jpg`, `002.jpg`), leaving normal ratio images untouched.

- **`batch`** or **`/batch`**
  Process all queued URLs listed inside your `Batch URL.txt` file automatically.

- **`help`** or **`/help`**
  Display this comprehensive user guide and keyboard shortcut reference.

- **`subs`** or **`/subs`**
  Launch the built-in AI Subtitle Generator. Uses `faster-whisper` and `deep-translator` to run fully offline on your GPU (or CPU) to generate and translate `.srt` subtitles (e.g. from JP to EN) for any downloaded video.

- **`tts`** or **`/tts`** or **`qween`**
  Launch the Qwen-TTS Audiobook Generator. Converts any downloaded `.txt` novel chapter into a high-quality, expressive audiobook with built-in character acting, custom voice cloning, and perfectly synced `.srt` subtitles. Includes auto-resume chunk tracking.

- **`exit`** or **`quit`** or **`q`**
  Gracefully exit the Zine Scraper Suite and instantly flush all active AI models from system memory.

---

## ⌨️ TUI Navigation & Shortcuts

| Key | Action |
|---|---|
| **`↑` / `↓`** | Navigate between menu items and selection lists |
| **`Tab`** | Toggle edit mode or switch field focus |
| **`Enter`** | Select option, save edit, or launch selected action |
| **`Esc`** | Exit current modal / return to main menu |
| **`Backspace`** | Delete character in text edit fields |
| **`Ctrl + C`** | Cancel active task, cleanly exit, and flush AI models from VRAM |
| **`Ctrl + R`** | (TTS Only) Bail out of audiobook generation early, merge current chunks, and free memory |

---

## 📁 Library & Configuration Rules

- **Library Root Path**: Default parent directory for all downloaded media (`~/Downloads/Zine`). All content is saved into structured subdirectories:
  - `toon/` : Manga, Manhua, Manhwa, Comics
  - `video/` : Anime, Movies, Web Videos
  - `music/` : Songs, Albums, Audio Tracks
  - `book/` : Light Novels, E-books, PDFs
  - `image/` : Wallpapers, Galleries, Artwork
- **Duplicate Protection**: Downloaded files are automatically checked against `Logs/Download History.json` to prevent re-downloading existing media.
- **Error Tracking**: Fatal crashes are natively logged to `Logs/💩/crash_trace.txt`.
- **Site Isolation**: Each scraper platform runs as a self-contained module under `scrapers/<site>/`.

---

Press **ESC** to exit help and return to the main menu.
