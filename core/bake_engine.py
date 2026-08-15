"""
core/bake_engine.py
-------------------
Metadata & Cover Art Baking Engine for Zine Scraper Suite.

Command: bake / metadata
Allows users to view, edit, and bake metadata tags (Title, Artist, Album, Year, Genre, Track Number)
and embed high-res Cover Art into audio files (.flac, .mp3, .m4a, .wav, .ogg, .opus) via FFmpeg / Mutagen.

DESIGN: All editing happens INLINE inside the Rich table.
Uses single-session cbreak TTY event processing (identical to settings_tui.py).
Zero escape sequence leaks (^[[D, ^[[C, ^[), zero stdin blocking locks.
"""

import sys
import os
import re
import time
import tty
import termios
import select
import logging
import subprocess
import shutil
import urllib.parse
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from core.ui import (
    console, startup_clear, print_banner, Selector,
    active_status, set_active_live, get_theme_input_ansi,
    raw_prompt_input, _read_tty_chunk, _parse_input_chunk,
)
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live

logger = logging.getLogger(__name__)

try:
    import mutagen
    from mutagen import File as MutagenFile
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

# ── Field Definitions ───────────────────────────────────────────────────────

FIELDS = [
    ("title",   "Title"),
    ("artist",  "Artist"),
    ("album",   "Album"),
    ("year",    "Year / Date"),
    ("genre",   "Genre"),
    ("track",   "Track Number"),
    ("cover",   "Cover Art"),
]

FIELD_KEYS = [f[0] for f in FIELDS]


def clean_path_input(raw_input: str) -> Optional[Path]:
    """Cleans up user path input (stripping file:// URIs, URL decoding %20, quotes, unescaping spaces, expanding tilde, auto-fixing missing leading slash)."""
    if not raw_input:
        return None
    s = raw_input.strip().strip("'\"")
    if s.startswith("file://"):
        s = s[7:]
    s = urllib.parse.unquote(s)
    s = s.replace("\\ ", " ")
    s = s.strip("'\"")
    if not s:
        return None

    # Smart fix for missing leading slash (e.g. 'home/valse-de-anshu/...')
    if s.startswith("home/") or s.startswith("Users/"):
        s = "/" + s

    if s.startswith("~"):
        s = os.path.expanduser(s)
    try:
        p = Path(s).resolve()
        if not p.exists():
            if not s.startswith("/"):
                p_slash = Path("/" + s).resolve()
                if p_slash.exists():
                    return p_slash
            p_home = Path.home() / s.lstrip("/")
            if p_home.exists():
                return p_home
        return p
    except Exception:
        return None


# ── Table Builder ────────────────────────────────────────────────────────────

def _build_table(tags: Dict, cursor: int, editing_field: Optional[str], edit_buf: str) -> Table:
    """
    Build the interactive metadata table.
    - cursor: which row is currently selected/highlighted (0-indexed over FIELDS)
    - editing_field: if not None, that field's value cell shows the live input buffer
    - edit_buf: current typed text while editing
    """
    table = Table(border_style="menu", width=88, show_header=True, header_style="title")
    table.add_column("#", style="unselected", width=3, justify="right")
    table.add_column("Tag Field", width=18)
    table.add_column("Value", width=61)

    for i, (field_key, field_label) in enumerate(FIELDS):
        is_cursor = (i == cursor)
        is_editing = editing_field == field_key

        row_num = Text(str(i + 1), style="unselected")

        if is_cursor:
            label_style = "sexy_pink"
            prefix = "▶ "
        else:
            label_style = "menu"
            prefix = "  "

        label_text = Text(prefix + field_label, style=label_style)

        if is_editing:
            val_text = Text()
            val_text.append(edit_buf, style="success")
            val_text.append("█", style="blink bright_white")
        else:
            raw_val = tags.get(field_key, "")
            if field_key == "cover" and "_new_cover_path" in tags and tags["_new_cover_path"]:
                raw_val = f"✔ {Path(tags['_new_cover_path']).name}"
            if is_cursor:
                val_text = Text(raw_val or "—", style="title")
            else:
                val_text = Text(raw_val or "—", style="success" if raw_val else "unselected")

        table.add_row(row_num, label_text, val_text)

    return table


def _build_hint_row(editing_field: Optional[str], cursor: int) -> Text:
    """Return the bottom hint line appropriate for current state."""
    t = Text()
    if editing_field is None:
        t.append("  ↑↓", style="bold white")
        t.append(" Navigate  ", style="unselected")
        t.append("Enter", style="bold white")
        t.append(" Edit Field  ", style="unselected")
        t.append("B", style="bold white")
        t.append(" Bake Metadata  ", style="unselected")
        t.append("Esc / Q", style="bold white")
        t.append(" Exit", style="unselected")
    else:
        field_label = FIELDS[cursor][1]
        if editing_field == "cover":
            t.append(f"  Paste cover image path for {field_label}  ", style="info")
        else:
            t.append(f"  Editing {field_label}  ", style="info")
        t.append("Enter", style="bold white")
        t.append(" Confirm  ", style="unselected")
        t.append("Esc", style="bold white")
        t.append(" Cancel", style="unselected")
    return t


# ── Metadata I/O ─────────────────────────────────────────────────────────────

def read_audio_tags(file_path: Path) -> Dict[str, str]:
    """Reads existing audio metadata tags from a file using mutagen."""
    tags = {
        "title": file_path.stem,
        "artist": "Unknown",
        "album": "",
        "year": "",
        "genre": "",
        "track": "",
        "cover": "None",
    }
    if not file_path.exists():
        return tags
    if MUTAGEN_OK:
        try:
            audio = MutagenFile(str(file_path), easy=True)
            if audio is not None:
                for k in ["title", "artist", "album", "date", "genre", "tracknumber"]:
                    val = audio.get(k)
                    if val and isinstance(val, list) and len(val) > 0:
                        key_name = "year" if k == "date" else "track" if k == "tracknumber" else k
                        tags[key_name] = str(val[0])
            raw_audio = MutagenFile(str(file_path), easy=False)
            if raw_audio is not None:
                if hasattr(raw_audio, "pictures") and raw_audio.pictures:
                    tags["cover"] = "Embedded (FLAC/Vorbis)"
                elif any(k.startswith("APIC") for k in raw_audio.keys()):
                    tags["cover"] = "Embedded (ID3 APIC)"
                elif any(k.startswith("covr") for k in raw_audio.keys()):
                    tags["cover"] = "Embedded (MP4 covr)"
        except Exception as e:
            logger.debug(f"Mutagen tag read error: {e}")
    return tags


def bake_metadata_and_cover(
    audio_path: Path,
    title: str,
    artist: str,
    album: str = "",
    year: str = "",
    genre: str = "",
    track: str = "",
    cover_path: Optional[Path] = None
) -> bool:
    """Uses FFmpeg to bake tags and optional cover art into the audio file in-place."""
    if not audio_path.exists():
        return False
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    ext = audio_path.suffix.lower()
    tmp_path = audio_path.with_suffix(f".bake_tmp{ext}")

    cmd = [ffmpeg_bin, "-y", "-i", str(audio_path)]
    if cover_path and cover_path.exists():
        cmd.extend(["-i", str(cover_path)])
        cmd.extend(["-map", "0:a", "-map", "1:0"])
        cmd.extend(["-disposition:v:0", "attached_pic"])
        cmd.extend(["-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"])
    else:
        cmd.extend(["-map", "0"])
    cmd.extend(["-c", "copy"])
    if title:   cmd.extend(["-metadata", f"title={title}"])
    if artist:  cmd.extend(["-metadata", f"artist={artist}"])
    if album:   cmd.extend(["-metadata", f"album={album}"])
    if year:    cmd.extend(["-metadata", f"date={year}", "-metadata", f"year={year}"])
    if genre:   cmd.extend(["-metadata", f"genre={genre}"])
    if track:   cmd.extend(["-metadata", f"track={track}"])
    if ext == ".mp3":
        cmd.extend(["-id3v2_version", "3"])
    cmd.append(str(tmp_path))

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
            audio_path.unlink()
            tmp_path.rename(audio_path)
            return True
        logger.error(f"FFmpeg bake failed: {res.stderr[-300:]}")
        if tmp_path.exists():
            tmp_path.unlink()
        return False
    except Exception as e:
        logger.error(f"Failed to execute FFmpeg bake: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        return False


def _scan_recent_audio_files() -> List[Path]:
    """Scans ~/Downloads/Zine for recently downloaded audio files."""
    downloads_root = Path.home() / "Downloads" / "Zine"
    if not downloads_root.exists():
        return []
    audio_extensions = {".flac", ".mp3", ".m4a", ".wav", ".ogg", ".opus"}
    found = []
    for root, _, files in os.walk(downloads_root):
        if ".zine" in root or ".git" in root:
            continue
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in audio_extensions:
                found.append(p)
    found.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    return found[:20]


# ── Main TUI ─────────────────────────────────────────────────────────────────

def run_bake_tui():
    """
    Interactive Metadata Baking TUI.
    Uses single-session cbreak TTY event processing (identical to settings_tui.py).
    All editing happens INLINE inside the Rich Live table.
    Use ↑↓ to navigate rows, Enter to edit the selected field,
    ESC to cancel an edit, B to bake, Q / ESC outside edit to exit.
    """
    if not sys.stdin.isatty():
        console.print("[warning]Non-interactive environment. Returning...[/warning]")
        return

    target_file = None
    err_hint = ""

    # ── File Path Entry / Selector Loop ──────────────────────────────────────
    while not target_file:
        startup_clear()
        print_banner()

        hint_text = err_hint or "Enter or paste target audio file path (or press Enter to select from recent downloads)"

        user_input = raw_prompt_input(
            prompt_title="AUDIO METADATA & COVER ART BAKING ENGINE",
            hint=hint_text
        )

        if user_input is None or user_input.strip().lower() in ("exit", "quit", "q"):
            return

        if not user_input.strip():
            # User pressed Enter on empty prompt → show audio file selector!
            recent_files = _scan_recent_audio_files()
            if not recent_files:
                err_hint = "No audio files found in ~/Downloads/Zine. Please paste a file path:"
                continue
            selector_opts = [(f"{p.name}  [dim]({p.parent.name})[/dim]", str(p)) for p in recent_files]
            picked = Selector(selector_opts, prompt_title="SELECT AUDIO FILE TO EDIT & BAKE").select()
            if not picked or picked in ("ESC", "CTRL_C"):
                return
            target_file = Path(picked)
            break

        p = clean_path_input(user_input)
        if p and p.exists() and p.is_file():
            target_file = p
        else:
            err_hint = f"✘ File not found: '{user_input.strip()}'. Check path or paste again (or ESC to cancel)"

    tags = read_audio_tags(target_file)

    # Clean screen before starting Live table display
    startup_clear()
    print_banner()

    cursor = 0                   # which row is highlighted
    editing_field: Optional[str] = None   # None = navigation, str = editing that field
    edit_buf = ""                # live typed buffer
    cursor_pos = 0
    status_msg = Text("")

    # ── Single-Session Raw TTY Live Editing Event Loop ───────────────────────
    if os.name != "nt":
        import tty, termios
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            termios.tcflush(fd, termios.TCIFLUSH)
            tty.setcbreak(fd)
        except Exception as e:
            logger.debug(f"TTY initialization failed: {e}")
            console.print(f"[menu]Editing metadata for: {target_file.name}[/menu]")
            return

        try:
            with Live(console=console, refresh_per_second=30, auto_refresh=True, screen=False) as live:
                set_active_live(live)

                def render():
                    from rich.console import Group
                    table = _build_table(tags, cursor, editing_field, edit_buf)
                    hint = _build_hint_row(editing_field, cursor)
                    header = Text()
                    header.append("Target File:   ", style="menu")
                    header.append(f"{target_file.name}\n", style="site")
                    header.append("File Path:     ", style="menu")
                    header.append(f"{target_file.parent}", style="unselected")
                    header.append("  (Updated in-place)", style="info")
                    return Group(header, Text(""), table, Text(""), hint, status_msg)

                live.update(render(), refresh=True)

                while True:
                    chunk = _read_tty_chunk(fd, 0.05)
                    if not chunk:
                        continue

                    action, payload = _parse_input_chunk(chunk)

                    if editing_field is None:
                        # ── Row Navigation Mode ─────────────────────────────
                        if action == "UP":
                            cursor = (cursor - 1) % len(FIELDS)
                            live.update(render(), refresh=True)
                        elif action == "DOWN":
                            cursor = (cursor + 1) % len(FIELDS)
                            live.update(render(), refresh=True)
                        elif action == "ENTER":
                            editing_field = FIELDS[cursor][0]
                            if editing_field == "cover":
                                edit_buf = tags.get("_new_cover_path", "") or ""
                            else:
                                edit_buf = tags.get(editing_field, "")
                            cursor_pos = len(edit_buf)
                            live.update(render(), refresh=True)
                        elif action == "TEXT" and payload and payload.upper() == "B":
                            live.stop()
                            console.print("")
                            with active_status("[info]Baking metadata & cover art into audio file...[/info]", spinner="dots"):
                                cover_img_str = tags.get("_new_cover_path")
                                success = bake_metadata_and_cover(
                                    audio_path=target_file,
                                    title=tags.get("title", ""),
                                    artist=tags.get("artist", ""),
                                    album=tags.get("album", ""),
                                    year=tags.get("year", ""),
                                    genre=tags.get("genre", ""),
                                    track=tags.get("track", ""),
                                    cover_path=Path(cover_img_str) if cover_img_str else None
                                )
                            if success:
                                console.print(f"\n[success]✔ Metadata baked into '{target_file.name}'![/success]")
                                console.print(f"[info]ℹ Note: The song stays in its original location: '{target_file.parent}'[/info]\n")
                            else:
                                console.print(f"\n[error]✘ Failed to bake '{target_file.name}'[/error]\n")
                            if sys.stdin.isatty():
                                try:
                                    sys.stdout.write("\033[38;2;125;207;255m  Press Enter to return...\033[0m ")
                                    sys.stdout.flush()
                                    input()
                                except (EOFError, KeyboardInterrupt):
                                    pass
                            return
                        elif action == "ESC" or (action == "TEXT" and payload and payload.upper() == "Q"):
                            return

                    else:
                        # ── Field Editing Mode ──────────────────────────────
                        if action == "ESC":
                            editing_field = None
                            edit_buf = ""
                            status_msg = Text("")
                            live.update(render(), refresh=True)
                        elif action in ("ENTER", "PASTE_AND_ENTER"):
                            if editing_field == "cover":
                                if edit_buf.strip():
                                    cp = clean_path_input(edit_buf)
                                    if cp and cp.exists() and cp.is_file():
                                        tags["_new_cover_path"] = str(cp)
                                        tags["cover"] = f"✔ {cp.name}"
                                        status_msg = Text(f"  Cover set: {cp.name}", style="success")
                                    else:
                                        status_msg = Text(f"  ✘ Cover file not found: {edit_buf.strip()}", style="error")
                            else:
                                if edit_buf.strip():
                                    tags[editing_field] = edit_buf.strip()
                                    status_msg = Text(f"  ✔ {FIELDS[cursor][1]} updated", style="success")
                                else:
                                    status_msg = Text("")
                            editing_field = None
                            edit_buf = ""
                            live.update(render(), refresh=True)
                        elif action == "BACKSPACE":
                            if cursor_pos > 0:
                                edit_buf = edit_buf[:cursor_pos - 1] + edit_buf[cursor_pos:]
                                cursor_pos -= 1
                                live.update(render(), refresh=True)
                        elif action == "DELETE":
                            if cursor_pos < len(edit_buf):
                                edit_buf = edit_buf[:cursor_pos] + edit_buf[cursor_pos + 1:]
                                live.update(render(), refresh=True)
                        elif action == "LEFT":
                            if cursor_pos > 0:
                                cursor_pos -= 1
                                live.update(render(), refresh=True)
                        elif action == "RIGHT":
                            if cursor_pos < len(edit_buf):
                                cursor_pos += 1
                                live.update(render(), refresh=True)
                        elif action == "HOME":
                            cursor_pos = 0
                            live.update(render(), refresh=True)
                        elif action == "END":
                            cursor_pos = len(edit_buf)
                            live.update(render(), refresh=True)
                        elif action in ("TEXT", "PASTE") and payload:
                            edit_buf = edit_buf[:cursor_pos] + payload + edit_buf[cursor_pos:]
                            cursor_pos += len(payload)
                            live.update(render(), refresh=True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            set_active_live(None)
    else:
        # Fallback for Windows
        console.print(f"[menu]Editing metadata for: {target_file.name}[/menu]")
