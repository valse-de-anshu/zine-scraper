"""
core/site_tui.py
----------------
Site Database TUI — Interactive multi-panel browser and explorer
for all platforms and domains in the Zine Scraper catalog.

Panels side-by-side inside one unified expanded frame:
  LEFT   (Platforms) — ↑↓ when focused
  MIDDLE (Domains)   — ↑↓ when focused
  RIGHT  (Specs)     — read-only metadata, updates with selected site

Navigation:
  Tab / ← / → : Switch focus between Platforms and Domains
  1-8         : Jump directly to Category
  Enter       : Launch selected domain in default Web Browser
  Esc / q     : Return to Main Menu
"""

import os
import sys
import select
import textwrap
import webbrowser

from rich         import box
from rich.console import Group
from rich.live    import Live
from rich.panel   import Panel
from rich.table   import Table
from rich.text    import Text

from core.ui import console, startup_clear, print_banner

# ─────────────────────────────────────────────────────────────────────────────
# Master Catalog Data (SFW 1-6, NSFW 7-8) - Aligned with scrapper_site_catalog.md
# ─────────────────────────────────────────────────────────────────────────────
SITE_CATEGORIES = [
    {
        "id": "1",
        "icon": "📺",
        "label": "Anime",
        "tag": "SFW",
        "sites": [
            {
                "name": "HiAnime",
                "primary": "hianime.to",
                "alts": ["hianime.sx", "hianime.mn", "hianime.nz", "hianime.ad", "hianime.re", "hianime.pm"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Anime streaming (Sub / Dub)",
                "tags": "SFW · Anime · Streaming · Sub · Dub · HLS",
                "desc": "Spiritual successor of Zoro.to. Serves millions of daily users with fast HLS streams, multiple server mirrors, and a clean adaptive UI. The premier choice for both subbed and dubbed anime."
            },
            {
                "name": "Anikoto",
                "primary": "anikoto.cz",
                "alts": ["anikototv.to", "anikoto.me", "anikoto.net", "anikototv.se", "anikoto.online"],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Anime streaming (Sub / Dub)",
                "tags": "SFW · Anime · Streaming · Multi-Domain · Fast",
                "desc": "A fast-growing anime streaming platform with frequent domain rotations. Recommended as a dependable, low-latency backup whenever primary aggregators experience congestion."
            },
            {
                "name": "Anineko",
                "primary": "anineko.to",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Anime streaming (Sub)",
                "tags": "SFW · Anime · Streaming · Minimal · Sub",
                "desc": "Minimalist, ad-light streaming site with a tight community and consistently high uptime. Streamlined layout focused purely on fast episode playback."
            },
            {
                "name": "Anitaku",
                "primary": "anitaku.online",
                "alts": ["anitaku.to", "anitaku.me"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Anime legacy archive (Sub / Dub)",
                "tags": "SFW · Anime · Legacy Archive · Sub · Dub",
                "desc": "Formerly the legendary Gogoanime. One of the oldest and most extensive anime databases on the internet with a deep catalogue stretching back to the early 2000s."
            },
            {
                "name": "Miruro",
                "primary": "miruro.to",
                "alts": ["miruro.ru", "miruro.tv", "miruro.bz"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Anime streaming (Sub / Dub)",
                "tags": "SFW · Anime · Streaming · Minimal · Modern",
                "desc": "Obsessively minimal design with zero clutter. Pulls high-speed video streams via third-party APIs, delivering superior uptime versus standard self-hosted platforms."
            },
        ]
    },
    {
        "id": "2",
        "icon": "📖",
        "label": "Manga",
        "tag": "SFW",
        "sites": [
            {
                "name": "Asura Scans",
                "primary": "asurascans.com",
                "alts": ["asuracomic.net", "asuratoon.com"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Korean Manhwa / Webtoons",
                "tags": "SFW · Manhwa · Webtoon · Action · Korean",
                "desc": "One of the most prominent active scanlation groups in the world. Specialises in top-tier Korean action, fantasy, and regression webtoons with swift chapter release schedules."
            },
            {
                "name": "Weeb Central",
                "primary": "weebcentral.com",
                "alts": [],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Manga / Manhwa / Comics",
                "tags": "SFW · Manga · Manhwa · Aggregator · Fast",
                "desc": "Modern, ultra-fast manga aggregator built with a clean aesthetic interface. Provides high-resolution reader scans and comprehensive series tracking without invasive ads."
            },
            {
                "name": "Project Suki",
                "primary": "projectsuki.com",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Manga / Webtoons",
                "tags": "SFW · Manga · Ad-Free · Community",
                "desc": "Ad-free, community-supported manga reader. Operates entirely through user donations with zero commercial monetisation, ensuring a distraction-free reading experience."
            },
            {
                "name": "Manhuaplus",
                "primary": "manhuaplus.org",
                "alts": [],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Chinese Manhua / Webtoons",
                "tags": "SFW · Manhua · Chinese · Cultivation · Xianxia",
                "desc": "Dedicated platform for Chinese Manhua. Dominates the cultivation, xianxia, martial arts, and reincarnation comic niches with frequent daily updates."
            },
            {
                "name": "MangaK",
                "primary": "mangak.io",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Manga archive",
                "tags": "SFW · Manga · Legacy Archive · Aggregator",
                "desc": "Formerly MangaKakalot. One of the internet's oldest and most massive manga repositories, containing decades of serialised Japanese manga and one-shots."
            },
            {
                "name": "Kunmanga",
                "primary": "kunmanga.com",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Manga / Comics",
                "tags": "SFW · Manga · Comics · Fast",
                "desc": "Streamlined manga reader with broad coverage across shonen, shojo, and fantasy series with low latency chapter image loading."
            },
            {
                "name": "Fanfox",
                "primary": "fanfox.net",
                "alts": ["m.fanfox.net"],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Manga global directory",
                "tags": "SFW · Manga · Legacy Directory · Global",
                "desc": "Formerly MangaFox. A historic pioneer of online manga reading. Holds an immense legacy catalogue, especially strong for completed classic series."
            },
        ]
    },
    {
        "id": "3",
        "icon": "📚",
        "label": "Novels",
        "tag": "SFW",
        "sites": [
            {
                "name": "Chikari",
                "primary": "chikari.moe",
                "alts": [],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Light novels / web serials / manga",
                "tags": "SFW · Light Novel · Web Novel · SvelteKit · API",
                "desc": "Modern SvelteKit platform delivering light novels, web serials, and manhwa. Features high-speed REST API chapter retrieval capable of indexing 1,400+ chapters in seconds."
            },
            {
                "name": "NovelPhoenix",
                "primary": "novelphoenix.com",
                "alts": [],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Asian web novels / light novels",
                "tags": "SFW · Light Novel · Web Novel · Xianxia · Korean",
                "desc": "Extensive archive for translated Asian web novels, cultivation epics, and fantasy series with clean chapter pagination and ad-filtered chapter text extraction."
            },
            {
                "name": "NovelFire",
                "primary": "novelfire.net",
                "alts": ["novelfire.docs"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Light novels / web serials",
                "tags": "SFW · Light Novel · Web Novel · Fantasy · Action",
                "desc": "Feature-rich web serial reader boasting thousands of translated light novels and fantasy epics with deep catalogue coverage and reliable chapter feeds."
            },
            {
                "name": "NovelBuddy",
                "primary": "novelbuddy.me",
                "alts":["novelbuddy.com"],
                "rating": "8/10",
                "popularity": "High",
                "status": "Active",
                "content": "Light novels / web serials",
                "tags": "SFW · Light Novel · Web Novel · Next.js · Modern",
                "desc": "Polished Next.js web novel platform hosting thousands of popular translated series with high uptime, rich metadata, and verified user ratings."
            },
            {
                "name": "NovelArchive",
                "primary": "novelarchive.cc",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Web serials / light novels",
                "tags": "SFW · Light Novel · Archive · REST API",
                "desc": "Clean API-driven light novel repository. Serves as a dependable backup reader for completed web serials and light novels when primary aggregators go offline."
            },
            {
                "name": "LightNovelWorld",
                "primary": "lightnovelworld.org",
                "alts": [],
                "rating": "8/10",
                "popularity": "High",
                "status": "Shutting down",
                "content": "Web serials (Legacy / Deprecated)",
                "tags": "SFW · Light Novel · Legacy · Shutting Down",
                "desc": "Leading historical reader for translated Japanese, Korean, and Chinese web serials. The site is currently shutting down; alternative platforms above are recommended."
            },
        ]
    },
    {
        "id": "4",
        "icon": "🎵",
        "label": "Music",
        "tag": "SFW",
        "sites": [
            {
                "name": "SoundCloud",
                "primary": "soundcloud.com",
                "alts": [],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Music / audio / podcasts",
                "tags": "SFW · Music · Audio · Indie · Podcast · Remixes",
                "desc": "The defining open platform for independent music. Hosts hundreds of millions of tracks from unsigned musicians, DJs, beatmakers, podcasters, and premier record labels."
            },
            {
                "name": "Idagio",
                "primary": "idagio.com",
                "alts": [],
                "rating": "8/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Classical music recordings",
                "tags": "SFW · Music · Classical · Lossless · Metadata",
                "desc": "The world's leading streaming service tailored exclusively to classical music. Features specialist search by composer, orchestra, conductor, soloist, and opus with lossless audio quality."
            },
            {
                "name": "YouTube Music",
                "primary": "music.youtube.com",
                "alts": ["youtube.com"],
                "rating": "9/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Music streaming & video audio",
                "tags": "SFW · Music · Video · Global · High-Res",
                "desc": "Google's global music streaming network. Integrates official studio releases with rare live recordings, concert bootlegs, and user covers across every genre."
            },
            {
                "name": "Internet Archive Music",
                "primary": "archive.org/details/audio",
                "alts": ["archive.org"],
                "rating": "9/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Live concerts / audio recordings / 78s",
                "tags": "SFW · Archive · Audio · Live Music · Historical",
                "desc": "Massive repository of historical audio recordings, public domain music, old-time radio broadcasts, and the Live Music Archive containing 250,000+ lossless live concert recordings."
            },
        ]
    },
    {
        "id": "5",
        "icon": "🏛",
        "label": "Books",
        "tag": "SFW",
        "sites": [
            {
                "name": "Project Gutenberg",
                "primary": "gutenberg.org",
                "alts": [],
                "rating": "10/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Public domain ebooks & classics",
                "tags": "SFW · Books · Ebooks · Public Domain · Classics",
                "desc": "The oldest digital library in human history, founded in 1971 by Michael S. Hart. Offers over 70,000 completely free eBooks of timeless world literature, philosophy, and history."
            },
            {
                "name": "Internet Archive",
                "primary": "archive.org",
                "alts": [],
                "rating": "9/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Books / scans / manuscripts / archives",
                "tags": "SFW · Archive · Books · Preservation · Non-Profit",
                "desc": "The world's largest non-profit digital library. Preserves 835+ billion web pages, 44 million books and texts, 15 million audio recordings, and 10 million films for universal permanent access."
            },
        ]
    },
    {
        "id": "6",
        "icon": "🌐",
        "label": "Social",
        "tag": "SFW",
        "sites": [
            {
                "name": "YouTube",
                "primary": "youtube.com",
                "alts": ["youtu.be"],
                "rating": "9/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Video / shorts / podcasts / streams",
                "tags": "SFW · Video · Social · Mainstream · Global",
                "desc": "The internet's preeminent video platform. Serves over 2.5 billion monthly active users with video tutorials, podcasts, documentaries, music videos, and live broadcasts."
            },
            {
                "name": "Instagram",
                "primary": "instagram.com",
                "alts": [],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Photos / reels / stories",
                "tags": "SFW · Social · Photos · Reels · Video",
                "desc": "Meta's flagship platform for photo, carousel, reel, and story sharing. The global center for visual creator content, photography, and digital art portfolios."
            },
            {
                "name": "Facebook",
                "primary": "facebook.com",
                "alts": ["fb.watch"],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Profile media / photos / video reels",
                "tags": "SFW · Social · Profiles · Photos · Reels · Live",
                "desc": "Meta's core social network. Zine provides dedicated modules for extracting full-resolution profile pictures, photo albums, and public video reels."
            },
            {
                "name": "Pinterest",
                "primary": "pinterest.com",
                "alts": ["pin.it"],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Visual discovery / inspiration boards",
                "tags": "SFW · Images · Video · Inspiration · Visual",
                "desc": "Global visual discovery and bookmarking engine. Ideal for harvesting ultra-high-resolution aesthetic photography, art references, concept designs, and infographics."
            },
        ]
    },
    {
        "id": "7",
        "icon": "🔞",
        "label": "18+ Vid",
        "tag": "NSFW",
        "sites": [
            {
                "name": "Pornhub",
                "primary": "pornhub.com",
                "alts": ["phncdn.com"],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Adult video streaming",
                "tags": "NSFW · Adult · Video · Mainstream",
                "desc": "The world's largest adult video streaming network, delivering high-definition video content across virtually every adult category with multi-quality resolution feeds."
            },
            {
                "name": "HStream",
                "primary": "hstream.moe",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult anime video streaming",
                "tags": "NSFW · Adult · Anime · Streaming · HD",
                "desc": "Clean, optimized streaming platform tailored exclusively to adult anime and hentai series. Delivers reliable video playback with minimal intrusive ads."
            },
            {
                "name": "Hentai18",
                "primary": "hentai18.net",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Uncensored HD adult anime",
                "tags": "NSFW · Adult · Anime · HD · Uncensored",
                "desc": "Fast-loading adult streaming platform focused on uncensored HD hentai releases with a steady stream of newly translated series."
            },
            {
                "name": "OHentai",
                "primary": "ohentai.org",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult anime archive",
                "tags": "NSFW · Adult · Anime · Archive · Classic",
                "desc": "Classic adult anime streaming network with a rich archive spanning older vintage OVAs through contemporary releases."
            },
            {
                "name": "Hentaimama",
                "primary": "hentaimama.io",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Translated adult anime",
                "tags": "NSFW · Adult · Anime · Translated · HD",
                "desc": "Specialises in fan-translated adult anime releases that are difficult to locate on larger mainstream streaming portals."
            },
            {
                "name": "Oppai Stream",
                "primary": "oppai.stream",
                "alts": ["read.oppai.stream"],
                "rating": "6/10",
                "popularity": "Low",
                "status": "Active",
                "content": "Adult anime & webtoons",
                "tags": "NSFW · Adult · Video · Toons · Unified",
                "desc": "Unified adult hub featuring both high-definition video streaming and a dedicated webtoon/comic reader platform."
            },
            {
                "name": "hanime.red",
                "primary": "hanime.red",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult anime streaming",
                "tags": "NSFW · Adult · Anime · Video · HD",
                "desc": "Alternative adult anime portal featuring organized franchise collections, tagged search filters, and creator profiles."
            },
            {
                "name": "Hentai Haven",
                "primary": "hentaihaven.xxx",
                "alts": ["hentaihaven.red", "hentaihaven.online", "hentaihaven.club", "hentaihaven.co"],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult anime streaming",
                "tags": "NSFW · Adult · Anime · Video · Mirrors",
                "desc": "Mirror network for the historic adult anime streaming brand with broad coverage of trending releases."
            },
        ]
    },
    {
        "id": "8",
        "icon": "🔞",
        "label": "18+ Toon",
        "tag": "NSFW",
        "sites": [
            {
                "name": "NHentai",
                "primary": "nhentai.net",
                "alts": [],
                "rating": "8/10",
                "popularity": "Very High",
                "status": "Active",
                "content": "Doujinshi / adult manga / images",
                "tags": "NSFW · Doujinshi · Archive · Translated · Raw",
                "desc": "The most recognised global archive for doujinshi. The universal gold standard for numeric ID lookups, complete tag indexing, and dual raw/translated archives."
            },
            {
                "name": "Omega Scans",
                "primary": "omegascans.org",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult manhwa / manga",
                "tags": "NSFW · Manga · Manhwa · Uncensored · Premium",
                "desc": "Premium-tier adult scanlation group renowned for high-fidelity English translations and ongoing uncensored Korean adult manhwa."
            },
            {
                "name": "Hentai8",
                "primary": "hentai8.net",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult manga / doujinshi",
                "tags": "NSFW · Manga · Doujinshi · Images",
                "desc": "Simple, fast-loading adult manga gallery reader with broad coverage across translated Japanese doujinshi releases."
            },
            {
                "name": "AsmHentai",
                "primary": "asmhentai.com",
                "alts": [],
                "rating": "6/10",
                "popularity": "Low",
                "status": "Active",
                "content": "Doujinshi / adult manga",
                "tags": "NSFW · Doujinshi · Manga · Western · Clean",
                "desc": "Well-curated doujinshi and adult comic platform with an extensive tag catalogue, particularly strong for western translated works."
            },
            {
                "name": "Hentaicity",
                "primary": "hentaicity.com",
                "alts": [],
                "rating": "6/10",
                "popularity": "Low",
                "status": "Active",
                "content": "Doujinshi / adult comics",
                "tags": "NSFW · Doujinshi · Tags · Discovery",
                "desc": "Engineered around a granular tagging matrix, making it exceptionally effective for discovering doujinshi through narrow tag intersections."
            },
            {
                "name": "Hentai20",
                "primary": "hentai20.io",
                "alts": [],
                "rating": "6/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult comics / manga",
                "tags": "NSFW · Manga · Western · Comics · Community",
                "desc": "Community-driven reader for western adult comics, webtoons, and doujinshi with an active upload repository and clean pagination."
            },
            {
                "name": "ManhwaUS",
                "primary": "manhwaus.net",
                "alts": [],
                "rating": "7/10",
                "popularity": "Medium",
                "status": "Active",
                "content": "Adult manhwa / webtoons",
                "tags": "NSFW · Manhwa · Webtoon · Romance · Drama",
                "desc": "Fast-updating reader for localized adult Korean webtoons spanning romance, drama, and modern workplace themes."
            },
        ]
    },
]

# ── Dimensions ───────────────────────────────────────────────────────────────
PANEL_W = 144   # Frame width
COL_S   = 24    # Platforms column
COL_D   = 36    # Domains column
COL_I   = 70    # Details & Specs column
FIXED_H = 17    # Number of content rows

FOCUS_S = "sites"
FOCUS_D = "domains"


class SiteDatabaseTUI:

    def __init__(self):
        self.cat_idx  = 0
        self.site_idx = 0
        self.dom_idx  = 0
        self.focus    = FOCUS_S

    # ── accessors ─────────────────────────────────────────────────────────────

    def _cat(self):
        return SITE_CATEGORIES[self.cat_idx]

    def _site(self):
        return self._cat()["sites"][self.site_idx]

    def _doms(self):
        s = self._site()
        return [s["primary"]] + s["alts"]

    # ── low-level raw TTY key reader ──────────────────────────────────────────

    def _get_key(self):
        if os.name == "nt":
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H": return "UP"
                if ch2 == b"P": return "DOWN"
                if ch2 == b"K": return "LEFT"
                if ch2 == b"M": return "RIGHT"
            if ch in (b"\r", b"\n"): return "ENTER"
            if ch == b"\x1b":       return "ESC"
            if ch == b"\x09":       return "TAB"
            if ch in (b"q", b"Q"):  return "ESC"
            try:
                c = ch.decode()
                if c in "12345678": return c
            except Exception: pass
            return ""
        else:
            import tty, termios
            fd  = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                mode    = termios.tcgetattr(fd)
                mode[3] = mode[3] | termios.ISIG
                mode[1] = mode[1] | termios.OPOST
                termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                select.select([fd], [], [])
                raw = os.read(fd, 1)
                if not raw: return ""
                ch = raw.decode("utf-8", errors="ignore")
                if ch in ("q", "Q"):
                    return "ESC"
                if ch == "\x1b":
                    r, _, _ = select.select([fd], [], [], 0.08)
                    if r:
                        ch2 = os.read(fd, 1).decode("utf-8", errors="ignore")
                        if ch2 in ("[", "O"):
                            r2, _, _ = select.select([fd], [], [], 0.08)
                            if r2:
                                ch3 = os.read(fd, 1).decode("utf-8", errors="ignore")
                                if ch3 == "A": return "UP"
                                if ch3 == "B": return "DOWN"
                                if ch3 == "C": return "RIGHT"
                                if ch3 == "D": return "LEFT"
                    return "ESC"
                if ch in ("\r", "\n"): return "ENTER"
                if ch == "\x03":       return "CTRL_C"
                if ch == "\x09":       return "TAB"
                if ch in "12345678":   return ch
                return ""
            except Exception:
                return ""
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # ── category bar ─────────────────────────────────────────────────────────

    def _cat_bar(self) -> Text:
        t = Text(no_wrap=True)
        for i, cat in enumerate(SITE_CATEGORIES):
            nsfw   = cat["tag"] == "NSFW"
            active = (i == self.cat_idx)
            if active:
                style = "bold error" if nsfw else "bold sexy_pink"
            else:
                style = "error" if nsfw else "unselected"
            t.append(f"[{cat['id']}] {cat['icon']} {cat['label']}   ", style=style)
        return t

    # ── composite render ──────────────────────────────────────────────────────

    def render(self):
        focused_s = self.focus == FOCUS_S
        focused_d = self.focus == FOCUS_D

        sites = self._cat()["sites"]
        doms  = self._doms()
        site  = self._site()

        # Build list of Lines for Left Column (Platforms)
        col_s_lines = []
        for i, s in enumerate(sites):
            active = (i == self.site_idx)
            t = Text(no_wrap=True)
            name_display = s["name"][:COL_S - 3]
            if active and focused_s:
                t.append("▶ ", style="sexy_pink")
                t.append(name_display, style="bold sexy_pink")
            elif active:
                t.append("  ", style="")
                t.append(name_display, style="bold white")
            else:
                t.append("  ", style="")
                t.append(name_display, style="unselected")
            col_s_lines.append(t)

        # Build list of Lines for Middle Column (Domains)
        col_d_lines = []
        for j, dom in enumerate(doms):
            active = (j == self.dom_idx)
            t = Text(no_wrap=True)
            dom_display = dom[:COL_D - 11]
            if active and focused_d:
                t.append("▶ ", style="sexy_pink")
                t.append(dom_display, style="bold sexy_pink")
                if j == 0:
                    t.append("  primary", style="info")
            elif active:
                t.append("  ", style="")
                t.append(dom_display, style="bold white")
                if j == 0:
                    t.append("  primary", style="unselected")
            else:
                t.append("  ", style="")
                t.append(dom_display, style="unselected")
                if j == 0:
                    t.append("  (p)", style="unselected")
            col_d_lines.append(t)

        # Build list of Lines for Right Column (Details & Specs)
        col_i_lines = []
        
        # Site Name + Status
        title_line = Text(no_wrap=True)
        title_line.append(site["name"], style="bold menu")
        status_val = site.get("status", "Active")
        status_style = "warning" if "shut" in status_val.lower() else "success"
        title_line.append(f"  [{status_val}]", style=status_style)
        col_i_lines.append(title_line)

        # Rating & Popularity
        meta_line = Text(no_wrap=True)
        meta_line.append("Rating: ", style="unselected")
        meta_line.append(site.get("rating", "8/10"), style="bold success")
        meta_line.append("  │  Popularity: ", style="unselected")
        meta_line.append(site.get("popularity", "High"), style="bold info")
        col_i_lines.append(meta_line)

        # Tags Line
        tags_line = Text(no_wrap=True)
        tags_line.append("Tags: ", style="unselected")
        tags_line.append(site.get("tags", "")[:COL_I - 8], style="site")
        col_i_lines.append(tags_line)

        # Type Line
        content_line = Text(no_wrap=True)
        content_line.append("Type: ", style="unselected")
        content_line.append(site.get("content", "")[:COL_I - 8], style="white")
        col_i_lines.append(content_line)
        col_i_lines.append(Text(""))

        # Wrapped Description
        desc_text = site.get("desc", "")
        for w_line in textwrap.wrap(desc_text, COL_I - 4):
            col_i_lines.append(Text(f"  {w_line}", style="white", no_wrap=True))

        # Main Table with crisp vertical splitting lines and clean headers
        table = Table(
            show_header=True,
            show_edge=False,
            box=box.MINIMAL,
            border_style="unselected",
            padding=(0, 2),
            expand=False
        )

        hdr_s = Text(no_wrap=True)
        hdr_s.append("Platforms", style="bold menu" if focused_s else "unselected")
        if focused_s:
            hdr_s.append("  ↑↓", style="unselected")

        hdr_d = Text(no_wrap=True)
        hdr_d.append("Domains", style="bold menu" if focused_d else "unselected")
        if focused_d:
            hdr_d.append("  [Enter=open]", style="info")

        hdr_i = Text("Details & Specs", style="unselected", no_wrap=True)

        table.add_column(hdr_s, width=COL_S, no_wrap=True)
        table.add_column(hdr_d, width=COL_D, no_wrap=True)
        table.add_column(hdr_i, width=COL_I, no_wrap=True)

        # Add all rows with guaranteed vertical dividing lines
        for r in range(FIXED_H):
            s_cell = col_s_lines[r] if r < len(col_s_lines) else Text("")
            d_cell = col_d_lines[r] if r < len(col_d_lines) else Text("")
            i_cell = col_i_lines[r] if r < len(col_i_lines) else Text("")
            table.add_row(s_cell, d_cell, i_cell)

        footer = Text(justify="center", no_wrap=True)
        footer.append("↑↓", style="bold white");        footer.append(" Navigate  ", style="unselected")
        footer.append("Tab / ← →", style="bold white"); footer.append(" Switch Panel  ", style="unselected")
        footer.append("1-8", style="bold white");       footer.append(" Category  ", style="unselected")
        footer.append("Enter", style="bold white");     footer.append(" Open in Browser  ", style="unselected")
        footer.append("Esc / q", style="bold white");   footer.append(" Return", style="unselected")

        return Panel(
            Group(
                Text("◆ ZINE SCRAPER CATALOG & SITES DATABASE", style="bold menu", no_wrap=True),
                Text(""),
                Text("  * Note: Piracy and aggregator sites periodically update domains or rotate mirrors.", style="dim italic", no_wrap=True),
                Text("    You can easily add or customize domain mirrors in: core/site_tui.py", style="dim italic", no_wrap=True),
                Text(""),
                self._cat_bar(),
                Text(""),
                table,
            ),
            subtitle=footer,
            subtitle_align="center",
            border_style="unselected",
            padding=(1, 2),
            expand=False,
            width=PANEL_W,
        )

    # ── run loop ──────────────────────────────────────────────────────────────

    def run(self):
        startup_clear()
        print_banner()
        console.show_cursor(False)

        with Live(self.render(), console=console, screen=False,
                  auto_refresh=False) as live:
            while True:
                try:
                    live.update(self.render(), refresh=True)
                    key = self._get_key()
                except KeyboardInterrupt:
                    break
                except Exception:
                    continue

                try:
                    sites = self._cat()["sites"]
                    doms  = self._doms()

                    if key == "UP":
                        if self.focus == FOCUS_S:
                            if self.site_idx > 0:
                                self.site_idx -= 1
                                self.dom_idx   = 0
                        else:
                            if self.dom_idx > 0:
                                self.dom_idx -= 1

                    elif key == "DOWN":
                        if self.focus == FOCUS_S:
                            if self.site_idx < len(sites) - 1:
                                self.site_idx += 1
                                self.dom_idx   = 0
                        else:
                            if self.dom_idx < len(doms) - 1:
                                self.dom_idx += 1

                    elif key in ("TAB", "LEFT", "RIGHT"):
                        self.focus = FOCUS_D if self.focus == FOCUS_S else FOCUS_S

                    elif key and key in "12345678":
                        idx = int(key) - 1
                        if 0 <= idx < len(SITE_CATEGORIES):
                            self.cat_idx  = idx
                            self.site_idx = 0
                            self.dom_idx  = 0
                            self.focus    = FOCUS_S

                    elif key == "ENTER":
                        try:
                            selected_domain = self._doms()[self.dom_idx]
                            target_url = f"https://{selected_domain}" if not selected_domain.startswith("http") else selected_domain
                            webbrowser.open(target_url)
                        except Exception:
                            pass

                    elif key in ("ESC", "CTRL_C"):
                        break

                except Exception:
                    continue

        console.show_cursor(True)
