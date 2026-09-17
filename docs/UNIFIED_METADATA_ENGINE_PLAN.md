# Unified Metadata Engine Architecture & All-Scraper Audit Plan

## 1. Executive Context

The user has approved the **Unified Metadata Engine** as the primary focus to solve the metadata gap in **Hwaran (`com.ballade.hwaran`)**.

### Guiding Directives
1. **Focus on Metadata First:** Fix metadata generation and alignment before implementing server/daemon features.
2. **Preserve Quick Grab Unchanged:** Quick Grab is intentionally lightweight and ad-hoc. It remains untouched as requested.
3. **Planning Phase Only:** Provide an exhaustive audit across all 49 scraper sites and define the architecture before modifying production code.

---

## 2. Exhaustive Audit: Current Metadata State Across All 49 Scrapers

A programmatic audit of all 49 scraper modules reveals the current state:

* **Total Scrapers Audited:** 49
* **Writes `type` (or `box_purpose`):** **0 / 49 (0%)** $\rightarrow$ *Major cause of Hwaran misclassifying media*
* **Writes `.zine/meta.json`:** **22 / 49 (45%)** (Only Toon and Novel scrapers write manifests)
* **Writes NO Manifests:** **27 / 49 (55%)** (Anime, Video, Music, Books write nothing)
* **Extracts Rating:** 4 / 49
* **Extracts Status:** 9 / 49
* **Extracts Release Year:** 2 / 49

### 2.1 Category Breakdown Table

| Category | Sites | Current Metadata Extracted | Current `.zine/meta.json` State | Missing in Manifest for Hwaran |
| :--- | :--- | :--- | :--- | :--- |
| **1. Anime (SFW)** | `hianime`, `anitaku`, `miruro`, `anikoto`, `anineko`, `anikai` | Title, Cover, Synopsis, Genres, Studio, Air Year, Status, Rating, Episodes | **NONE (0/6 write JSON)** | Everything: `type="Series"`, `tags`, `rating`, `year`, `author`, `cover.jpg` |
| **2. Manga & Manhwa (SFW)** | `mangadex`, `asurascans`, `topmanhua`, `weebcentral`, `projectsuki`, `manhuaplus`, `mangak`, `kunmanga`, `fanfox`, `manhwaus`, `omegascans` | Title, Cover, Synopsis, Author, Artist, Genres | **Writes partial `meta.json`** | Missing `type="Manga"`, `status`, `rating`, `year`, `cover.jpg` |
| **3. Light Novels (SFW)** | `chikari`, `novelbuddy`, `novelfire`, `novelphoenix`, `novelarchive` | Title, Cover, Synopsis, Author, Genres, Status, Rating | **Writes rich `meta.json`** | Needs `type="Novel"`, `alt_title` standardization, tag arrays |
| **4. Music & Audio (SFW)** | `youtube/yt_music`, `soundcloud`, `idagio`, `archive` (audio) | Track titles, Artists, Album name, 1200px Artwork, Duration, Track numbering | **NONE (0/4 write JSON)** | Everything: `type="Song"`, `author`, `year`, `tags`, `cover.jpg` |
| **5. Books & Archives (SFW)** | `gutenberg`, `archive` (texts) | Title, Author, Language, Subjects (Tags), Cover URL | **NONE (0/2 write JSON)** | Everything: `type="Book"`, `language`, `tags`, `cover.jpg` |
| **6. Video & Social (SFW)** | `youtube`, `instagram`, `facebook`, `pinterest`, `ytdlp` | Channel name, Handle, Subscriber count, View count, Video list, Durations | **NONE (0/5 write JSON)** | Everything: `type="Channel"`, `views`, `likes`, `videos` ranking list |
| **7. Adult Video (NSFW)** | `pornhub`, `hstream`, `hentai18`, `ohentai`, `hentaimama`, `oppai_stream`, `hanime`, `hanime_red`, `hentaihaven`, `hentaihaven_co`, `hentaicity` | Title, Studio/Model, Tags, Quality streams, Duration | **NONE (0/11 write JSON)** | Everything: `type="Series"` or `type="Channel"`, `tags`, `cover.jpg` |
| **8. Adult Comics (NSFW)** | `nhentai`, `asmhentai`, `hentai20`, `manga18fx`, `oppai_stream_toon` | Title, Cover, Tags, Parodies, Artists | **Writes partial `meta.json`** | Missing `type="Manga"`, `cover.jpg` |

---

## 3. The Unified `core/metadata_engine.py` Architecture

### 3.1 Design Principles
1. **Canonical File Manifest:** Always output `.zine/metadata.json` (Hwaran's primary lookup target), with backwards compatibility for `.zine/meta.json`.
2. **Strict Data Contract:** Defined by a Python `dataclass` matching Hwaran's `ParsedZineMetadata` and `EntryMetadata`.
3. **Preservation of Quick Grab:**
   ```python
   if is_quick_grab:
       # Quick grab remains fast and ad-hoc as designed
       return
   ```
4. **Dedicated Cover Standard:** Whenever a cover is downloaded, guarantee it is written to the media folder as `cover.jpg` (or standard image format) and referenced in `metadata.json`.

### 3.2 The Core Schema

```python
@dataclass
class ZineMetadataPayload:
    title: str
    alt_title: Optional[str] = ""
    author: Optional[str] = ""
    artist: Optional[str] = ""
    description: Optional[str] = ""
    type: str = "Manga"          # "Manga", "Manhua", "Manhwa", "Novel", "Book", "Series", "Channel", "Song"
    status: Optional[str] = ""   # "Ongoing", "Completed", "Hiatus"
    rating: Optional[str] = ""   # "8.8" or "5/5"
    tags: List[str] = field(default_factory=list)
    publisher: Optional[str] = ""
    serialization: Optional[str] = ""
    year: Optional[str] = ""
    language: Optional[str] = "en"
    pages: Optional[str] = ""
    total_chapters: int = 0
    cover: str = "cover.jpg"
    url: Optional[str] = ""
    views: Optional[str] = ""
    likes: Optional[str] = ""
    comments: Optional[str] = ""
    videos: List[Dict[str, Any]] = field(default_factory=list)
```

---

## 4. Scraper-by-Scraper Integration Strategy

### Group A: Manga, Manhwa & Manhua Scrapers
* **Extractors to Standardize:**
  * Map domain tags to `type`:
    * Chinese manhua platforms (`manhuaplus`, `topmanhua`) $\rightarrow$ `"type": "Manhua"`
    * Korean manhwa platforms (`asurascans`, `manhwaus`) $\rightarrow$ `"type": "Manhwa"`
    * Japanese manga platforms (`mangadex`, `fanfox`, `mangak`) $\rightarrow$ `"type": "Manga"`
  * Standardize `genres` / `tags` into a clean `List[str]`.
  * Pass payload to `MetadataEngine.save_metadata(folder, meta_payload)`.

### Group B: Light Novel Scrapers
* **Extractors to Standardize:**
  * Pass `"type": "Novel"`.
  * Set `alt_title` (singular) matching Hwaran.
  * Supply word counts and chapter totals into `total_chapters`.

### Group C: Anime & Video Series Scrapers
* **Extractors to Standardize:**
  * Add `MetadataEngine.save_metadata()` in `workflow.py` of `hianime`, `anitaku`, `miruro`, `anikoto`, etc.
  * Pass `"type": "Series"`.
  * Write `title`, `alt_title` (romaji/japanese), `author` (director/creator), `artist` (studio), `year` (air date), `rating` (MAL score), `tags` (genres), and `total_chapters` (episode count).
  * Download series banner/poster as `cover.jpg`.

### Group D: Video Channels & Creators
* **Extractors to Standardize:**
  * In `scrapers/youtube` and `scrapers/pornhub`:
    * Pass `"type": "Channel"`.
    * Supply `author` (channel name), `alt_title` (handle), `views`, `likes`, and list of `videos` (id, title, duration, view_count, upload_date).
    * Save channel avatar/banner as `cover.jpg`.

### Group E: Music & Audio Scrapers
* **Extractors to Standardize:**
  * In `scrapers/youtube/yt_music`, `soundcloud`, `idagio`:
    * Pass `"type": "Song"` (or `"Album"`).
    * Supply `title` (album name), `author` / `artist`, `year`, `total_chapters` (track count).
    * Save 1200px artwork as `cover.jpg`.
    * Save `.lrc` files directly beside tracks for Hwaran's Canvas shaders.

### Group F: Books & Public Archives
* **Extractors to Standardize:**
  * In `scrapers/gutenberg` and `scrapers/archive`:
    * Pass `"type": "Book"`.
    * Supply `title`, `author`, `language`, `tags` (subjects).
    * Save book cover art as `cover.jpg`.

---

## 5. Verification Plan

1. **Unit Testing against Hwaran Parser:**
   * Create test script passing generated `.zine/metadata.json` files through the exact logic of `ZineMetadataExtractor.kt`.
   * Verify zero parsing failures and 100% field retention.
2. **Room Database Ingestion Check:**
   * Verify all 5 Hwaran description views (`ToonDescriptionView`, `BookDescriptionView`, `NovelReader`, `SeriesDescriptionView`, `ChannelDescriptionView`, `PlaylistDetailScreen`) receive complete metadata without fallback placeholders.
