# Hwaran & Zine Scraper Integration Roadmap

## Objective

To execute the systematic, atomic-level alignment of **Zine Scraper** with **Hwaran**, guaranteeing 100% metadata population, automated UI card hydration, and seamless wireless synchronization.

---

## Phase Breakdown & Milestones

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       INTEGRATION EXECUTION ROADMAP                         │
├─────────────────────┬─────────────────────┬─────────────────────────────────┤
│ PHASE 1: MANIFEST   │ PHASE 2: HYDRATION  │ PHASE 3: COMPANION BRIDGE       │
│ Foundations & Core  │ Scrapers & Domains  │ Wireless Wi-Fi Daemon & Sync    │
├─────────────────────┼─────────────────────┼─────────────────────────────────┤
│ • MetadataEngine    │ • Toon Scrapers     │ • FastAPI / Daemon Mode         │
│ • Universal Schema  │ • Novel Scrapers    │ • mDNS Discovery                │
│ • Zero-Loss QG      │ • Anime / Series    │ • Wireless Package Ingest       │
│ • Cover Standard    │ • Music & Channels  │ • Progress Checkpoint Sync      │
└─────────────────────┴─────────────────────┴─────────────────────────────────┘
```

---

## Phase 1: Ingestion & Manifest Foundations

### Objective
Create the universal metadata generation service in `core/` and eliminate all metadata suppression across workflows.

### Action Items
1. **Implement `core/metadata_engine.py`:**
   * Define `ZineMetadataPayload` dataclass matching Hwaran's `EntryMetadata`.
   * Standardize JSON keys: `title`, `alt_title`, `author`, `artist`, `description`, `type`, `status`, `rating`, `tags` (as array), `publisher`, `serialization`, `year`, `language`, `total_chapters`, `cover`, `url`, `views`, `likes`, `comments`, `videos`.
   * Implement atomic file writing to `.zine/metadata.json`.
2. **Remove Quick Grab Metadata Suppression:**
   * Update `scrapers/*/workflow.py` to remove `if not is_quick_grab:` guards.
   * Ensure single-chapter and ad-hoc downloads generate a valid `.zine/metadata.json` and `cover.jpg` inside the output folder.
3. **Enforce Dedicated Cover Standard:**
   * Ensure all cover images are saved as `cover.jpg` (or preserve format with `.jpg`/`.webp`/`.png`) and correctly referenced in `metadata.json`.

---

## Phase 2: Domain-Wide Scraper Hydration

### Objective
Upgrade all scrapers across the 5 media domains to supply rich, typed metadata manifests.

### Domain 1: Manga, Manhwa & Manhua (`contentType = 0`)
* **Target Scrapers:** `mangadex`, `asurascans`, `topmanhua`, `manhuaplus`, `manhwaus`, `kunmanga`, `fanfox`, `weebcentral`, `projectsuki`, `mangak`, `manga18fx`, `nhentai`, `asmhentai`, `hentai20`.
* **Output Standard:**
  * `"type": "Manga"` (or `"Manhwa"`, `"Manhua"`).
  * Ascending numeric chapter ordering (`Chapter 1`, `Chapter 2`, etc.).
  * Populates `ToonDescriptionView` with author, artist, status, score, publication year, genres, and synopsis.

### Domain 2: Novels & WebBooks (`contentType = 4`)
* **Target Scrapers:** `chikari`, `novelbuddy`, `novelfire`, `novelphoenix`, `novelarchive`.
* **Output Standard:**
  * `"type": "Novel"`.
  * Chapter `.txt` files with clean paragraph breaks and word counts.
  * Populates WebBook reader and novel checkpoint UI with full synopsis, authors, and serialization source.

### Domain 3: Anime & Structured Video Series (`contentType = 2`)
* **Target Scrapers:** `hianime`, `anitaku`, `miruro`, `anikoto`, `anineko`, `hanime`, `hentai18`, `hentaimama`.
* **Output Standard:**
  * `"type": "Series"`.
  * Franchise structure (`related_series` mapping seasons, movies, and specials).
  * Populates `SeriesDescriptionView` and `SeriesRelatedView` with studio, air year, episode counts, and franchise tabs.

### Domain 4: Creator Channels & Video Hubs (`contentType = 2`)
* **Target Scrapers:** `youtube`, `pornhub`.
* **Output Standard:**
  * `"type": "Channel"`.
  * Populates `ChannelDescriptionView` with channel banner, views, likes, comments, author handle, and tri-tab video lists (`most_viewed`, `top_rated`, `latest`).

### Domain 5: Music & Soundtracks (`contentType = 3`)
* **Target Scrapers:** `youtube/yt_music`, `soundcloud`, `idagio`, `archive/audio`.
* **Output Standard:**
  * `"type": "Song"` or `"Album"`.
  * Embedded ID3/Vorbis tags via Mutagen.
  * Synchronized `.lrc` lyrics alongside audio tracks for real-time karaoke canvas shader playback.

---

## Phase 3: Zine Companion Daemon & Wireless Ingestion

### Objective
Create a zero-friction, local-network bridge connecting Zine Scraper on PC with Hwaran on Android.

### Action Items
1. **`zine --daemon` Command:**
   * Build a lightweight FastAPI / Uvicorn server in `core/daemon.py`.
   * Broadcast presence via mDNS Zeroconf (`_zine._tcp.local.`).
2. **REST & WebSocket API:**
   * `POST /api/scrape`: Queue download requests from Hwaran.
   * `WS /ws/progress`: Stream live terminal progress trees to Hwaran's UI.
   * `GET /api/library/packages`: List completed downloads ready for wireless import.
   * `GET /api/sync/pull/{id}`: Stream media packages directly into Hwaran via Android SAF.
3. **Bidirectional Progress Checkpoints:**
   * Export Hwaran's `HistoryEventEntity` and reading bookmarks to sync new chapters automatically.

---

## Verification & Compatibility Matrix

Before declaring any phase complete:
1. **Hwaran Unit Test Verification:**
   * Verify generated `.zine/metadata.json` files pass Hwaran's `ZineMetadataImportRulesTest.kt` with zero parsing warnings.
2. **Room Database Ingestion:**
   * Inspect SQLite Room schema v16 tables (`manga`, `chapter`) to confirm all fields (`title`, `description`, `coverPath`, `contentType`, `boxPurpose`, `genre`, `lastModified`) are correctly populated.
3. **UI Description View Hydration:**
   * Launch `ToonDescriptionView`, `BookDescriptionView`, `SeriesDescriptionView`, and `ChannelDescriptionView` to ensure hero cards, chips, badges, and rankings render with zero missing placeholders.
