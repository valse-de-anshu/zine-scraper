# YouTube Music Scraper (`scrapers/youtube/yt_music/`)

Fully isolated, self-contained scraper for **YouTube Music** (`music.youtube.com`).

---

## 🎵 Features
- **High-Fidelity FLAC Audio**: Extracts best available source audio and encodes directly into lossless `.flac`.
- **Rich Vorbis Metadata Tagging**: Embeds track `TITLE`, clean `ARTIST` (stripping `- Topic`), `ALBUM`, `DATE`, `TRACKNUMBER`.
- **Album Cover Art**: Fetches max-resolution album covers and embeds them into FLAC `METADATA_BLOCK_PICTURE` alongside saving `cover.jpg`/`cover.png` in the directory.
- **Synced Lyrics (.lrc)**: Fetches time-synced `.lrc` lyrics in the background using the 6-layer lyrics engine.
- **Single Tracks & Batch Playlists/Albums**:
  - Single Song: `https://music.youtube.com/watch?v=...`
  - Playlists & Albums: `https://music.youtube.com/playlist?list=...` or `/browse/VL...`
  - Range selection (e.g. `1-10`), multi-selection, or complete album download.

---

## 📁 Folder Structure
```
scrapers/youtube/yt_music/
├── __init__.py
├── engine.py
├── scraper.py
├── location.py
├── progress.py
├── verification.py
├── tui.py
├── workflow.py
└── README.md
```
