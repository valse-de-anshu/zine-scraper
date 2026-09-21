"""
core/settings_tui.py
--------------------
Standalone Settings TUI module for Zine Scraper Suite.
Renders all settings options cleanly inside a single Rich Panel box.
Features an interactive edit panel with ESC cancel, native backspace, and zero raw key bleed.
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Tuple, Any, Optional

from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from core.ui import console, startup_clear, print_banner, Selector, BoxSelector, set_active_live
from core.paths import PathAuthority
from core.storage import StorageLayer
from core.config import ConfigLayer
from wizard.setup import ThemeSelector, detect_terminal

paths = PathAuthority()
storage = StorageLayer()
config = ConfigLayer(paths, storage)


def _is_default_music_path(path_val: str) -> bool:
    if not path_val or path_val in ["Default", "Quick Grab"]:
        return True
    path_str = str(path_val).replace("\\", "/")
    if path_str.endswith("/Default") or "/Default/" in path_str:
        return True
    return False


def _short_path(path_val: str, max_len: int = 38) -> str:
    if not path_val or path_val in ["Default", "Quick Grab"]:
        return "Quick Grab"
    val_str = str(path_val)
    if len(val_str) > max_len:
        if "/" in val_str or "\\" in val_str:
            parts = [p for p in val_str.replace("\\", "/").split("/") if p]
            if len(parts) >= 2:
                return f"…/{parts[-2]}/{parts[-1]}"
            elif len(parts) == 1:
                return f"…/{parts[0]}"
        else:
            return val_str[:16] + "…" + val_str[-16:]
    return val_str


class SettingsSelector(Selector):
    """Aesthetic multi-section and flat Panel renderer for Zine Settings."""

    def __init__(self, options: Any, default_key: Optional[str] = None, title: str = "◆ ZINE SETTINGS CONFIGURATOR ◆"):
        super().__init__(options=[], title=title)
        self.raw_options = options
        self.flat_items: List[Tuple[str, Any, Optional[str], bool]] = []
        self.is_sectioned = False
        self.box_title = title

        # Check if passed categorized sections or flat list
        if options and isinstance(options[0], tuple) and len(options[0]) == 2 and isinstance(options[0][1], list):
            self.is_sectioned = True
            for sec_title, items in options:
                self.flat_items.append((sec_title, None, None, True))  # header
                for label, val_str, key in items:
                    self.flat_items.append((label, val_str, key, False))
        else:
            self.is_sectioned = False
            for label_and_val, key in options:
                label, val_str = label_and_val
                self.flat_items.append((label, val_str, key, False))

        # Determine initial selection index
        self.index = 1 if self.is_sectioned else 0
        if default_key:
            for i, item in enumerate(self.flat_items):
                if not item[3] and item[2] == default_key:
                    self.index = i
                    break

    def _render(self) -> Panel:
        table = Table(box=None, show_header=False, padding=(0, 1), expand=True)
        table.add_column("label", width=32, no_wrap=True)
        table.add_column("sep", width=2, justify="center")
        table.add_column("val", width=38, no_wrap=True)

        for i, (label_or_sec, val_str, key, is_header) in enumerate(self.flat_items):
            if is_header:
                if i > 0:
                    table.add_row(Text(""), Text(""), Text(""))
                table.add_row(Text(f"◆ {label_or_sec}", style="bold sexy_pink"), Text(""), Text(""))
            else:
                is_active = (i == self.index)
                if is_active:
                    l_text = Text(f"  ▶ {label_or_sec}", style="bold sexy_pink")
                    sep = Text(":", style="bold sexy_pink")
                    v_text = Text(str(val_str), style="bold white")
                else:
                    l_text = Text(f"    {label_or_sec}", style="unselected")
                    sep = Text(":", style="unselected")
                    v_text = Text(str(val_str), style="unselected")
                table.add_row(l_text, sep, v_text)

        footer = Text(justify="center")
        footer.append("↑↓", style="bold white");    footer.append(" Navigate  ", style="unselected")
        footer.append("Enter", style="bold white"); footer.append(" Select  ", style="unselected")
        footer.append("Esc", style="bold white");   footer.append(" Exit to Menu", style="unselected")

        return Panel(
            table,
            title=f"[bold white]{self.box_title}[/bold white]",
            subtitle=footer,
            subtitle_align="center",
            border_style="sexy_pink",
            padding=(1, 2),
            width=80,
        )

    def select(self) -> Optional[str]:
        if "unittest" in sys.modules or not sys.stdin.isatty():
            for item in self.flat_items:
                if not item[3]:
                    return item[2]
            return "ESC"

        console.show_cursor(False)
        if os.name != "nt" and sys.stdin.isatty():
            import tty, termios
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                termios.tcflush(fd, termios.TCIFLUSH)
                tty.setcbreak(fd)
                with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                    set_active_live(live)
                    live.update(self._render(), refresh=True)
                    while True:
                        chunk = _read_tty_chunk(fd, timeout=0.05)
                        if not chunk:
                            continue

                        action = _parse_selector_chunk(chunk)
                        if action == "ESC":
                            return "ESC"

                        elif action == "UP":
                            new_i = self.index
                            for _ in range(len(self.flat_items)):
                                new_i = (new_i - 1) % len(self.flat_items)
                                if not self.flat_items[new_i][3]:
                                    self.index = new_i
                                    break
                            live.update(self._render(), refresh=True)

                        elif action == "DOWN":
                            new_i = self.index
                            for _ in range(len(self.flat_items)):
                                new_i = (new_i + 1) % len(self.flat_items)
                                if not self.flat_items[new_i][3]:
                                    self.index = new_i
                                    break
                            live.update(self._render(), refresh=True)

                        elif action == "ENTER":
                            return self.flat_items[self.index][2]

                        elif action == "HOME":
                            for idx, item in enumerate(self.flat_items):
                                if not item[3]:
                                    self.index = idx
                                    break
                            live.update(self._render(), refresh=True)

                        elif action == "END":
                            for idx in range(len(self.flat_items) - 1, -1, -1):
                                if not self.flat_items[idx][3]:
                                    self.index = idx
                                    break
                            live.update(self._render(), refresh=True)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                set_active_live(None)
                console.show_cursor(True)
        else:
            import msvcrt, time
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                set_active_live(live)
                live.update(self._render(), refresh=True)
                while True:
                    if not msvcrt.kbhit():
                        time.sleep(0.03)
                        continue
                    ch = msvcrt.getch()
                    if ch in (b"\x1b", b"\x03", b"q", b"Q"):
                        return "ESC"
                    elif ch in (b"\r", b"\n", b" "):
                        return self.flat_items[self.index][2]
                    elif ch in (b"\x00", b"\xe0"):
                        if msvcrt.kbhit():
                            ch2 = msvcrt.getch()
                            if ch2 in (b"H", b"K"):  # Up / Left
                                new_i = self.index
                                for _ in range(len(self.flat_items)):
                                    new_i = (new_i - 1) % len(self.flat_items)
                                    if not self.flat_items[new_i][3]:
                                        self.index = new_i
                                        break
                                live.update(self._render(), refresh=True)
                            elif ch2 in (b"P", b"M"):  # Down / Right
                                new_i = self.index
                                for _ in range(len(self.flat_items)):
                                    new_i = (new_i + 1) % len(self.flat_items)
                                    if not self.flat_items[new_i][3]:
                                        self.index = new_i
                                        break
                                live.update(self._render(), refresh=True)
                            elif ch2 == b"G":  # Home
                                for idx, item in enumerate(self.flat_items):
                                    if not item[3]:
                                        self.index = idx
                                        break
                                live.update(self._render(), refresh=True)
                            elif ch2 == b"O":  # End
                                for idx in range(len(self.flat_items) - 1, -1, -1):
                                    if not self.flat_items[idx][3]:
                                        self.index = idx
                                        break
                                live.update(self._render(), refresh=True)


def _parse_selector_chunk(chunk_bytes: bytes) -> str:
    if not chunk_bytes:
        return "NONE"

    if b"\x03" in chunk_bytes or chunk_bytes in (b"\x1b", b"q", b"Q"):
        return "ESC"

    if chunk_bytes in (b"\r", b"\n", b" "):
        return "ENTER"

    raw_str = chunk_bytes.decode("utf-8", errors="ignore")

    up_patterns = ["\x1b[A", "\x1bOA", "[A", "OA", "k", "K", "\x1b[D", "\x1bOD"]
    if any(raw_str == p or raw_str.startswith(p) for p in up_patterns):
        return "UP"

    down_patterns = ["\x1b[B", "\x1bOB", "[B", "OB", "j", "J", "\x1b[C", "\x1bOC"]
    if any(raw_str == p or raw_str.startswith(p) for p in down_patterns):
        return "DOWN"

    home_patterns = ["\x1b[H", "\x1bOH", "[H", "OH", "\x1b[1~", "[1~", "\x01"]
    if any(raw_str == p or raw_str.startswith(p) for p in home_patterns):
        return "HOME"

    end_patterns = ["\x1b[F", "\x1bOF", "[F", "OF", "\x1b[4~", "[4~", "\x05"]
    if any(raw_str == p or raw_str.startswith(p) for p in end_patterns):
        return "END"

    if "\r" in raw_str or "\n" in raw_str:
        return "ENTER"

    if raw_str.startswith("\x1b") and len(raw_str) == 1:
        return "ESC"

    return "NONE"


def _read_tty_chunk(fd: int, timeout: float = 0.05) -> bytes:
    import select
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return b""
    try:
        chunk = os.read(fd, 4096)
        if chunk == b"\x1b":
            r2, _, _ = select.select([fd], [], [], 0.03)
            if r2:
                chunk += os.read(fd, 4096)
        return chunk
    except Exception:
        return b""


def _parse_input_chunk(chunk_bytes: bytes) -> Tuple[str, Optional[str]]:
    import re
    if not chunk_bytes:
        return ("NONE", None)

    if b"\x03" in chunk_bytes:
        return ("ESC", None)

    if chunk_bytes == b"\x1b":
        return ("ESC", None)

    raw_str = chunk_bytes.decode("utf-8", errors="ignore")

    # Clean bracketed paste markers (\x1b[200~ and \x1b[201~)
    clean_str = re.sub(r"\x1b\[20[01]~", "", raw_str)

    if not clean_str:
        return ("NONE", None)

    if clean_str == "\x1b":
        return ("ESC", None)

    if "\r" in clean_str or "\n" in clean_str:
        part = clean_str.split("\r")[0].split("\n")[0]
        part = re.sub(r"\x1b\[[0-9;]*[a-zA-Z~]", "", part)
        part = re.sub(r"\[[ADCBSHOF]", "", part)
        printable = "".join(c for c in part if c.isprintable())
        if printable:
            return ("PASTE_AND_ENTER", printable)
        return ("ENTER", None)

    left_patterns = ["\x1b[D", "\x1bOD", "\x1b[1;2D", "\x1b[1;5D", "\x1b[1;3D", "[D", "OD"]
    if any(clean_str == p or clean_str.startswith(p) for p in left_patterns):
        return ("LEFT", None)

    right_patterns = ["\x1b[C", "\x1bOC", "\x1b[1;2C", "\x1b[1;5C", "\x1b[1;3C", "[C", "OC"]
    if any(clean_str == p or clean_str.startswith(p) for p in right_patterns):
        return ("RIGHT", None)

    up_down_patterns = ["\x1b[A", "\x1bOA", "[A", "OA", "\x1b[B", "\x1bOB", "[B", "OB"]
    if any(clean_str == p or clean_str.startswith(p) for p in up_down_patterns):
        return ("NONE", None)

    home_patterns = ["\x1b[H", "\x1bOH", "[H", "OH", "\x1b[1~", "[1~"]
    if any(clean_str == p or clean_str.startswith(p) for p in home_patterns):
        return ("HOME", None)

    end_patterns = ["\x1b[F", "\x1bOF", "[F", "OF", "\x1b[4~", "[4~"]
    if any(clean_str == p or clean_str.startswith(p) for p in end_patterns):
        return ("END", None)

    delete_patterns = ["\x1b[3~", "[3~", "\x1b[3;5~"]
    if any(clean_str == p or clean_str.startswith(p) for p in delete_patterns):
        return ("DELETE", None)

    if clean_str in ("\x7f", "\x08"):
        return ("BACKSPACE", None)
    if clean_str == "\x01":
        return ("HOME", None)
    if clean_str == "\x05":
        return ("END", None)
    if clean_str == "\x15":
        return ("CLEAR_LINE", None)
    if clean_str == "\x17":
        return ("DELETE_WORD", None)

    clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z~]", "", clean_str)
    clean_text = re.sub(r"\[[ADCBSHOF]", "", clean_text)

    printable = "".join(c for c in clean_text if c.isprintable())
    if printable:
        return ("TEXT", printable)

    return ("NONE", None)


def prompt_field_value(field_title: str, current_val: str, hint: str = "") -> Optional[str]:
    """
    Renders an isolated interactive prompt panel for editing a setting value.
    - Pre-fills current value into buffer.
    - Supports full paste streams without character loss, bracketed paste decoding.
    - Supports left/right cursor navigation, home, end, backspace, delete.
    - ESC or Ctrl+C cancels and returns None (zero rubbish saved!).
    - ENTER saves and returns trimmed string.
    """
    buffer = str(current_val)
    cursor_pos = len(buffer)

    def _build_prompt_panel() -> Panel:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("content", width=74)

        table.add_row(Text(f"Editing: {field_title}", style="bold sexy_pink"))
        table.add_row(Text("─" * 74, style="unselected"))

        before = buffer[:cursor_pos]
        after = buffer[cursor_pos:]

        edit_text = Text()
        edit_text.append("❯ ", style="bold sexy_pink")
        edit_text.append(before, style="bold white")
        if cursor_pos >= len(buffer):
            edit_text.append("█", style="bold sexy_pink")
        else:
            edit_text.append(after[0], style="bold reverse")
            edit_text.append(after[1:], style="bold white")

        table.add_row(edit_text)
        if hint:
            table.add_row(Text(hint, style="unselected"))

        footer = Text(justify="center")
        footer.append("Enter", style="bold white");     footer.append(" Save   ", style="unselected")
        footer.append("Esc", style="bold white");       footer.append(" Cancel / Go Back   ", style="unselected")
        footer.append("Backspace", style="bold white"); footer.append(" Delete", style="unselected")

        return Panel(
            table,
            title=f"[bold white]◆ EDIT {field_title.upper()} ◆[/bold white]",
            subtitle=footer,
            subtitle_align="center",
            border_style="sexy_pink",
            padding=(1, 2),
            width=80,
        )

    startup_clear()
    print_banner()

    if os.name != "nt" and sys.stdin.isatty():
        import tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            termios.tcflush(fd, termios.TCIFLUSH)
            tty.setcbreak(fd)
            with Live(_build_prompt_panel(), console=console, auto_refresh=False, transient=True) as live:
                set_active_live(live)
                live.update(_build_prompt_panel(), refresh=True)
                while True:
                    chunk = _read_tty_chunk(fd, 0.05)
                    if not chunk:
                        continue

                    action, payload = _parse_input_chunk(chunk)

                    if action == "ESC":
                        return None

                    elif action in ("ENTER", "PASTE_AND_ENTER"):
                        if payload:
                            buffer = buffer[:cursor_pos] + payload + buffer[cursor_pos:]
                        return buffer.strip()

                    elif action == "BACKSPACE":
                        if cursor_pos > 0:
                            buffer = buffer[:cursor_pos - 1] + buffer[cursor_pos:]
                            cursor_pos -= 1
                            live.update(_build_prompt_panel(), refresh=True)

                    elif action == "DELETE":
                        if cursor_pos < len(buffer):
                            buffer = buffer[:cursor_pos] + buffer[cursor_pos + 1:]
                            live.update(_build_prompt_panel(), refresh=True)

                    elif action == "LEFT":
                        if cursor_pos > 0:
                            cursor_pos -= 1
                            live.update(_build_prompt_panel(), refresh=True)

                    elif action == "RIGHT":
                        if cursor_pos < len(buffer):
                            cursor_pos += 1
                            live.update(_build_prompt_panel(), refresh=True)

                    elif action == "HOME":
                        cursor_pos = 0
                        live.update(_build_prompt_panel(), refresh=True)

                    elif action == "END":
                        cursor_pos = len(buffer)
                        live.update(_build_prompt_panel(), refresh=True)

                    elif action == "CLEAR_LINE":
                        buffer = buffer[cursor_pos:]
                        cursor_pos = 0
                        live.update(_build_prompt_panel(), refresh=True)

                    elif action == "DELETE_WORD":
                        before = buffer[:cursor_pos].rstrip()
                        idx = max(before.rfind("/"), before.rfind(" "), before.rfind("\\"))
                        idx = 0 if idx == -1 else idx
                        buffer = buffer[:idx] + buffer[cursor_pos:]
                        cursor_pos = idx
                        live.update(_build_prompt_panel(), refresh=True)

                    elif action == "TEXT" and payload:
                        buffer = buffer[:cursor_pos] + payload + buffer[cursor_pos:]
                        cursor_pos += len(payload)
                        live.update(_build_prompt_panel(), refresh=True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            set_active_live(None)

    elif os.name == "nt" and sys.stdin.isatty():
        import msvcrt, time
        with Live(_build_prompt_panel(), console=console, auto_refresh=False, transient=True) as live:
            set_active_live(live)
            try:
                live.update(_build_prompt_panel(), refresh=True)
                while True:
                    if not msvcrt.kbhit():
                        time.sleep(0.03)
                        continue

                    ch = msvcrt.getch()
                    if ch in (b"\x1b", b"\x03"):
                        return None

                    elif ch in (b"\r", b"\n"):
                        return buffer.strip()

                    elif ch in (b"\x08", b"\x7f"):
                        if cursor_pos > 0:
                            buffer = buffer[:cursor_pos - 1] + buffer[cursor_pos:]
                            cursor_pos -= 1
                            live.update(_build_prompt_panel(), refresh=True)

                    elif ch in (b"\x00", b"\xe0"):
                        if msvcrt.kbhit():
                            ch2 = msvcrt.getch()
                            if ch2 == b"K":
                                if cursor_pos > 0:
                                    cursor_pos -= 1
                                    live.update(_build_prompt_panel(), refresh=True)
                            elif ch2 == b"M":
                                if cursor_pos < len(buffer):
                                    cursor_pos += 1
                                    live.update(_build_prompt_panel(), refresh=True)
                            elif ch2 == b"G":
                                cursor_pos = 0
                                live.update(_build_prompt_panel(), refresh=True)
                            elif ch2 == b"O":
                                cursor_pos = len(buffer)
                                live.update(_build_prompt_panel(), refresh=True)
                            elif ch2 == b"S":
                                if cursor_pos < len(buffer):
                                    buffer = buffer[:cursor_pos] + buffer[cursor_pos + 1:]
                                    live.update(_build_prompt_panel(), refresh=True)

                    else:
                        chars = [ch]
                        while msvcrt.kbhit():
                            chars.append(msvcrt.getch())
                        raw_bytes = b"".join(chars)
                        decoded = raw_bytes.decode("utf-8", errors="ignore")
                        if "\r" in decoded or "\n" in decoded:
                            part = decoded.split("\r")[0].split("\n")[0]
                            printable = "".join(c for c in part if c.isprintable())
                            if printable:
                                buffer = buffer[:cursor_pos] + printable + buffer[cursor_pos:]
                            return buffer.strip()
                        printable = "".join(c for c in decoded if c.isprintable())
                        if printable:
                            buffer = buffer[:cursor_pos] + printable + buffer[cursor_pos:]
                            cursor_pos += len(printable)
                            live.update(_build_prompt_panel(), refresh=True)
            finally:
                set_active_live(None)

    else:
        try:
            val = input(f"Editing {field_title} (Current: {current_val}): ")
            return val.strip() if val.strip() else current_val
        except (EOFError, KeyboardInterrupt):
            return None


def whisper_settings_tui():
    while True:
        startup_clear()
        print_banner()
        curr_sub_mode = config.get("ai_subtitles_mode", "Both")
        curr_sub_engine = config.get("ai_subtitles_engine", "Auto")
        curr_sub_model = config.get("ai_subtitles_model", "Models/STT/faster-whisper-large-v3-turbo")
        curr_sub_vram = config.get("ai_subtitles_vram", "6GB (INT8)")
        curr_target_lang = config.get("ai_target_lang", "English")

        options = [
            (("AI Subtitle Generation", curr_sub_mode), "ai_subtitles_mode"),
            (("STT Engine",             curr_sub_engine), "ai_subtitles_engine"),
            (("Translation Language",   curr_target_lang), "ai_target_lang"),
            (("AI Model Path",          _short_path(curr_sub_model)), "ai_subtitles_model"),
            (("AI GPU Mode",            curr_sub_vram), "ai_subtitles_vram"),
        ]
        choice = SettingsSelector(options).select()
        if not choice or choice in ("ESC", "CTRL_C"):
            break
        elif choice == "ai_subtitles_engine":
            engine_opts = [
                ("Auto-Detect (Based on selected model path)      ", "Auto"),
                ("Confucius4-R2T2 (Qwen3-ASR — High Fidelity)     ", "Confucius4-R2T2"),
                ("Faster-Whisper (Standard Whisper Architecture)  ", "Faster-Whisper")
            ]
            new_engine = BoxSelector(engine_opts, "Select STT Engine").select()
            if new_engine and new_engine != "ESC":
                config.set("ai_subtitles_engine", new_engine)
                if new_engine == "Confucius4-R2T2" and "faster-whisper" in curr_sub_model.lower():
                    config.set("ai_subtitles_model", "Models/STT/Confucius4")
                elif new_engine == "Faster-Whisper" and "confucius" in curr_sub_model.lower():
                    config.set("ai_subtitles_model", "Models/STT/faster-whisper-large-v3-turbo")
        elif choice == "ai_subtitles_mode":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("AI Subtitle Output Options", style="bold sexy_pink"))
            table.add_row(Text("Choose which subtitles to generate when using the manual AI subtitle tool.", style="unselected"))
            panel = Panel(table, title="[bold white]◆ AI SUBTITLES CONFIGURATION ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80)
            console.print()
            mode_opts = [
                ("Only give me translated subtitles (e.g. English)      ", "Target"), 
                ("Only give me the original spoken language subtitles   ", "Original"), 
                ("Give me both (Original language + Translated language)", "Both"), 
                ("Turn off AI Subtitles entirely                        ", "None")
            ]
            new_mode = BoxSelector(mode_opts, "Select Generation Mode").select()
            if new_mode and new_mode != "ESC":
                config.set("ai_subtitles_mode", new_mode)
                
        elif choice == "ai_target_lang":
            langs = [
                ("Translate to English   ", "English"),
                ("Translate to Spanish   ", "Spanish"),
                ("Translate to French    ", "French"),
                ("Translate to German    ", "German"),
                ("Translate to Italian   ", "Italian"),
                ("Translate to Portuguese", "Portuguese"),
                ("Translate to Russian   ", "Russian"),
                ("Translate to Korean    ", "Korean"),
                ("Translate to Chinese   ", "Chinese"),
                ("Translate to Japanese  ", "Japanese")
            ]
            new_lang = BoxSelector(langs, "Select Language").select()
            if new_lang and new_lang != "ESC":
                config.set("ai_target_lang", new_lang)
                
        elif choice == "ai_subtitles_model":
            new_m_path = prompt_field_value("AI Model Path", str(curr_sub_model), "(Path to downloaded HF Model)")
            if new_m_path is not None and new_m_path.strip() != "":
                from core.paths import sanitize_user_path
                config.set("ai_subtitles_model", sanitize_user_path(new_m_path))

        elif choice == "ai_subtitles_vram":
            vram_opts = [("6GB (INT8 - Fastest/Safest)", "6GB (INT8)"), ("8GB+ (FP16 - High Quality)", "FP16"), ("CPU-Only (Very Slow)", "CPU-Only")]
            new_vram = BoxSelector(vram_opts, "Select Hardware Target").select()
            if new_vram and new_vram != "ESC":
                config.set("ai_subtitles_vram", new_vram)


def qwen_tts_settings_tui():
    while True:
        startup_clear()
        print_banner()
        curr_tts_mode          = config.get("tts_mode", "Custom Voice")
        curr_tts_speaker       = config.get("tts_custom_speaker", "Ryan")
        curr_tts_comfy_url     = config.get("tts_comfyui_url", "http://127.0.0.1:8188")

        default_instruct = "Dynamic and expressive narrator. Seamlessly switch between professional normal narration, deep emotional acting, and sultry/horny character voices based on the text. Emphasize feelings and intonations naturally."
        curr_tts_instruct         = config.get("tts_voice_instruct", default_instruct)
        curr_tts_instruct_display = _short_path(curr_tts_instruct) if curr_tts_instruct else "None"

        curr_tts_ref_audio        = config.get("tts_clone_ref_audio", "")
        curr_tts_ref_audio_display= _short_path(curr_tts_ref_audio) if curr_tts_ref_audio else "None"

        curr_tts_transcript       = config.get("tts_clone_ref_transcript", "")
        curr_tts_transcript_display = (
            _short_path(curr_tts_transcript) if (curr_tts_transcript and ('/' in curr_tts_transcript or '\\' in curr_tts_transcript))
            else (curr_tts_transcript[:38] + "…" if len(curr_tts_transcript) > 38 else curr_tts_transcript)
        ) if curr_tts_transcript else "None"

        curr_tts_model_choice  = config.get("tts_model_choice", "1.7B")
        curr_tts_precision     = config.get("tts_precision", "bf16")
        curr_tts_temp          = config.get("tts_temperature", 0.9)
        curr_tts_top_p         = config.get("tts_top_p", 0.8)
        curr_tts_top_k         = config.get("tts_top_k", 20)
        curr_tts_rep_pen       = config.get("tts_repetition_penalty", 1.05)
        curr_tts_max_tokens    = config.get("tts_max_new_tokens", 2048)

        curr_tts_xvec          = config.get("tts_x_vector_only", True)
        curr_tts_xvec_display  = "x-vector (Timbre Only - Smooth)" if curr_tts_xvec else "ICL (Full Text Alignment)"

        is_clone  = "Voice Cloning"  in curr_tts_mode
        is_design = "Voice Design"   in curr_tts_mode
        is_custom = not is_clone and not is_design  # Custom Voice

        # ── Build mode-aware options list ────────────────────────────────
        options = [
            (("Qwen TTS Server URL", curr_tts_comfy_url),  "tts_comfyui_url"),
            (("Qwen TTS Mode",       curr_tts_mode),        "tts_mode"),
        ]

        if is_custom:
            options.append((("Qwen TTS Speaker",         curr_tts_speaker),         "tts_custom_speaker"))
            options.append((("Voice Style Prompt",       curr_tts_instruct_display), "tts_voice_instruct"))
        elif is_design:
            options.append((("Voice Style Prompt",       curr_tts_instruct_display), "tts_voice_instruct"))
        else:  # Voice Cloning
            options.append((("Clone Audio Path",         curr_tts_ref_audio_display),    "tts_clone_ref_audio"))
            options.append((("Clone Feature Method",     curr_tts_xvec_display),         "tts_x_vector_only"))
            options.append((("Clone Transcript",         curr_tts_transcript_display),    "tts_clone_ref_transcript"))

        options += [
            (("Model Choice",        curr_tts_model_choice), "tts_model_choice"),
            (("Precision",           curr_tts_precision),    "tts_precision"),
            (("Temperature",         str(curr_tts_temp)),    "tts_temperature"),
            (("Top P",               str(curr_tts_top_p)),   "tts_top_p"),
            (("Top K",               str(curr_tts_top_k)),   "tts_top_k"),
            (("Repetition Penalty",  str(curr_tts_rep_pen)), "tts_repetition_penalty"),
            (("Max New Tokens",      str(curr_tts_max_tokens)), "tts_max_new_tokens"),
        ]

        choice = SettingsSelector(options).select()
        if not choice or choice in ("ESC", "CTRL_C"):
            break
            
        elif choice == "tts_comfyui_url":
            new_val = prompt_field_value("Qwen TTS Server URL", curr_tts_comfy_url, "(e.g., http://127.0.0.1:8188 or network IP)")
            if new_val is not None:
                config.set("tts_comfyui_url", new_val.strip())

        elif choice == "tts_mode":
            mode_opts = [
                ("Custom Voice (Preset Speakers)",          "Custom Voice"),
                ("Voice Cloning (Requires Ref Audio)",      "Voice Cloning"),
                ("Voice Design (Text-to-Voice Generation)", "Voice Design")
            ]
            new_mode = BoxSelector(mode_opts, "Select Qwen TTS Generation Mode").select()
            if new_mode and new_mode != "ESC":
                config.set("tts_mode", new_mode)
                # Flush previous model weights from GPU VRAM on mode switch
                try:
                    import urllib.request, json
                    comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
                    req = urllib.request.Request(f"{comfy_url}/free", data=json.dumps({"unload_models":True,"free_memory":True}).encode(), method='POST')
                    urllib.request.urlopen(req, timeout=1.0)
                except Exception:
                    pass

        elif choice == "tts_custom_speaker":
            speaker_opts = [
                ("Aiden (Male)",    "Aiden"),   ("Dylan (Male)",    "Dylan"),
                ("Eric (Male)",     "Eric"),    ("Ono_anna (Female)","Ono_anna"),
                ("Ryan (Male)",     "Ryan"),    ("Serena (Female)",  "Serena"),
                ("Sohee (Female)",  "Sohee"),   ("Uncle_fu (Male)",  "Uncle_fu"),
                ("Vivian (Female)", "Vivian")
            ]
            new_speaker = BoxSelector(speaker_opts, "Select TTS Preset Speaker").select()
            if new_speaker and new_speaker != "ESC":
                config.set("tts_custom_speaker", new_speaker)

        elif choice == "tts_voice_instruct":
            hint = (
                "Voice Design: describe the voice (e.g. 'old man, gravelly, slow')\n"
                "Custom Voice: optional acting style. Type text OR pass absolute path to a .txt file."
            )
            new_val = prompt_field_value("Voice Style Prompt", curr_tts_instruct, hint)
            if new_val is not None:
                from core.paths import sanitize_user_path
                config.set("tts_voice_instruct", sanitize_user_path(new_val) if ('/' in new_val or '\\' in new_val) else new_val.strip())

        elif choice == "tts_clone_ref_audio":
            new_val = prompt_field_value(
                "Clone Audio Path",
                curr_tts_ref_audio,
                "(Absolute path to reference WAV/MP3. This audio's voice will be cloned.)"
            )
            if new_val is not None:
                from core.paths import sanitize_user_path
                config.set("tts_clone_ref_audio", sanitize_user_path(new_val))

        elif choice == "tts_x_vector_only":
            opts = [
                ("x-vector (Timbre Only - Clean, Smooth & Fast - Recommended)", True),
                ("ICL (Full Transcript Alignment - Needs 100% Exact Transcript)", False)
            ]
            new_val = BoxSelector(opts, "Select Voice Clone Feature Extraction Method").select()
            if new_val is not None and new_val != "ESC":
                config.set("tts_x_vector_only", bool(new_val))

        elif choice == "tts_clone_ref_transcript":
            hint = (
                "What was SPOKEN in the reference audio clip — word for word.\n"
                "Type it inline here, OR pass an absolute path to a .txt file."
            )
            new_val = prompt_field_value("Clone Transcript", curr_tts_transcript, hint)
            if new_val is not None:
                from core.paths import sanitize_user_path
                val = sanitize_user_path(new_val) if ('/' in new_val or '\\' in new_val) else new_val.strip()
                config.set("tts_clone_ref_transcript", val)
                
        elif choice == "tts_model_choice":
            opts = [("1.7B (High Quality, More VRAM)", "1.7B"), ("0.6B (Fast, Low VRAM)", "0.6B")]
            new_val = BoxSelector(opts, "Select Qwen TTS Model").select()
            if new_val and new_val != "ESC":
                config.set("tts_model_choice", new_val)
                
        elif choice == "tts_precision":
            opts = [("bf16 (Recommended for RTX 3000/4000)", "bf16"), ("fp16 (Good fallback)", "fp16"), ("fp32 (High Memory / Old GPUs)", "fp32")]
            new_val = BoxSelector(opts, "Select Math Precision").select()
            if new_val and new_val != "ESC":
                config.set("tts_precision", new_val)

        elif choice == "tts_temperature":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Creativity & Emotion (Temperature)", style="bold sexy_pink"))
            table.add_row(Text("Higher = More expressive, dynamic, and dramatic.\nLower = More flat, predictable, and robotic.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ TEMPERATURE ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            new_val = prompt_field_value("Temperature", str(curr_tts_temp), "(e.g. 1.0 for expressive, 0.5 for flat)")
            if new_val is not None and new_val != "":
                try: config.set("tts_temperature", float(new_val))
                except: pass

        elif choice == "tts_top_p":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Vocabulary Focus (Top P)", style="bold sexy_pink"))
            table.add_row(Text("Limits how wild the AI's pronunciation choices get. 0.8 is the sweet spot to prevent weird random noises.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ TOP P ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            new_val = prompt_field_value("Top P", str(curr_tts_top_p), "(e.g. 0.8)")
            if new_val is not None and new_val != "":
                try: config.set("tts_top_p", float(new_val))
                except: pass

        elif choice == "tts_top_k":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Strictness (Top K)", style="bold sexy_pink"))
            table.add_row(Text("Similar to Top P, but more rigid. 20 stops the AI from hallucinating words entirely.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ TOP K ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            new_val = prompt_field_value("Top K", str(curr_tts_top_k), "(e.g. 20)")
            if new_val is not None and new_val != "":
                try: config.set("tts_top_k", int(new_val))
                except: pass

        elif choice == "tts_repetition_penalty":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Stutter Control (Repetition Penalty)", style="bold sexy_pink"))
            table.add_row(Text("Forces the AI to stop looping the same word over and over. Keep around 1.05 to 1.15.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ REPETITION PENALTY ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            new_val = prompt_field_value("Repetition Penalty", str(curr_tts_rep_pen), "(e.g. 1.05)")
            if new_val is not None and new_val != "":
                try: config.set("tts_repetition_penalty", float(new_val))
                except: pass

        elif choice == "tts_max_new_tokens":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Audio Generation Limit (Max Tokens)", style="bold sexy_pink"))
            table.add_row(Text("How much audio to generate before stopping. High values (2048) ensure long sentences aren't cut off.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ MAX TOKENS ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            new_val = prompt_field_value("Max New Tokens", str(curr_tts_max_tokens), "(e.g. 2048)")
            if new_val is not None and new_val != "":
                try: config.set("tts_max_new_tokens", int(new_val))
                except: pass


def breeze_tts_settings_tui():
    """Settings configurator for Breeze-TTS-2 (C++ / GGUF engine)."""
    while True:
        startup_clear()
        print_banner()

        curr_backend = config.get("breeze_backend", "Direct CLI (breeze-cli)")
        curr_mode = config.get("breeze_mode", "Voice Design")
        curr_model = config.get("breeze_model_path", "Models/TTS/breeze-tts-2-q8_0.gguf")
        curr_bin_dir = config.get("breeze_bin_dir", "Models/TTS/Breeze-TTS-2.cpp/build")
        curr_server_url = config.get("breeze_server_url", "http://127.0.0.1:8080")

        default_instruct = "A captivating, seductive woman with an irresistibly sultry, velvety, breathy voice. Her delivery is deeply expressive, intimate, and cinematic, with slow mesmerizing cadence, alluring nuance, and spine-tingling emotional presence."
        curr_instruct = config.get("breeze_voice_instruct", "")
        if not curr_instruct or "A warm, thoughtful narrator" in curr_instruct:
            curr_instruct = default_instruct
        curr_instruct_display = _short_path(curr_instruct) if curr_instruct else "None"

        curr_saved_voice = config.get("breeze_saved_voice", "") or "None"

        curr_ref_audio = config.get("breeze_clone_ref_audio", "")
        curr_ref_audio_display = _short_path(curr_ref_audio) if curr_ref_audio else "None"

        curr_ref_transcript = config.get("breeze_clone_ref_transcript", "")
        curr_ref_transcript_display = (
            _short_path(curr_ref_transcript) if (curr_ref_transcript and ('/' in curr_ref_transcript or '\\' in curr_ref_transcript))
            else (curr_ref_transcript[:38] + "…" if len(curr_ref_transcript) > 38 else curr_ref_transcript)
        ) if curr_ref_transcript else "None"

        curr_cfg = float(config.get("breeze_cfg_scale", 1.0))
        curr_auto_vocal = "Enabled (2.5x Boost)" if config.get("breeze_auto_vocal_cfg", True) else "Disabled"
        curr_hardware = config.get("breeze_hardware", "Vulkan (GPU)")
        curr_seed = config.get("breeze_seed", 42)
        curr_temp = config.get("breeze_temperature", 0.9)
        curr_top_k = config.get("breeze_top_k", 50)
        curr_top_p = config.get("breeze_top_p", 1.0)
        curr_rep_pen = config.get("breeze_rep_penalty", 1.1)
        curr_split_chars = config.get("breeze_split_chars", 600)
        curr_llm_adapt = "Enabled (Ollama Directing)" if config.get("breeze_llm_adaptation", True) else "Disabled (Direct Text)"
        curr_llm_model = config.get("breeze_llm_model", "") or "Auto (emma:latest / luna:latest)"

        is_saved = curr_mode == "Saved Voice"
        is_clone = curr_mode in ("Voice Cloning", "Voice Direction")

        options = [
            (("Execution Backend",     curr_backend),        "breeze_backend"),
            (("Breeze TTS Mode",       curr_mode),           "breeze_mode"),
            (("LLM Script Adaptation", curr_llm_adapt),      "breeze_llm_adaptation"),
            (("LLM Directing Model",   curr_llm_model),      "breeze_llm_model"),
        ]

        if "Server" in curr_backend:
            options.append((("Breeze Server URL",   curr_server_url), "breeze_server_url"))
        else:
            options.append((("Model GGUF Path",     _short_path(curr_model)), "breeze_model_path"))
            options.append((("Binaries Directory",  _short_path(curr_bin_dir)), "breeze_bin_dir"))

        if is_saved:
            options.append((("Saved Voice Profile", curr_saved_voice), "breeze_saved_voice"))
            options.append((("Delivery Instruction", curr_instruct_display), "breeze_voice_instruct"))
        elif is_clone:
            options.append((("Clone Audio (.wav)",  curr_ref_audio_display), "breeze_clone_ref_audio"))
            options.append((("Clone Transcript",    curr_ref_transcript_display), "breeze_clone_ref_transcript"))
            if curr_mode == "Voice Direction":
                options.append((("Direction Prompt", curr_instruct_display), "breeze_voice_instruct"))
        else:
            # Voice Design
            options.append((("Voice Design Prompt", curr_instruct_display), "breeze_voice_instruct"))

        options += [
            (("Base CFG Scale",        str(curr_cfg)),       "breeze_cfg_scale"),
            (("Vocal Event Auto-Boost",curr_auto_vocal),     "breeze_auto_vocal_cfg"),
            (("Hardware Acceleration", curr_hardware),       "breeze_hardware"),
            (("RNG Seed",              str(curr_seed)),      "breeze_seed"),
            (("Temperature",           str(curr_temp)),      "breeze_temperature"),
            (("Top K",                 str(curr_top_k)),     "breeze_top_k"),
            (("Top P",                 str(curr_top_p)),     "breeze_top_p"),
            (("Repetition Penalty",    str(curr_rep_pen)),   "breeze_rep_penalty"),
            (("Split Character Cap",   str(curr_split_chars)), "breeze_split_chars"),
        ]

        choice = SettingsSelector(options).select()
        if not choice or choice in ("ESC", "CTRL_C"):
            break

        elif choice == "breeze_backend":
            opts = [
                ("Direct CLI (breeze-cli — Vulkan GPU / No Server Required)", "Direct CLI (breeze-cli)"),
                ("HTTP Server (breeze-server — Streaming API on port 8080)", "HTTP Server (breeze-server)")
            ]
            new_val = BoxSelector(opts, "Select Breeze TTS Execution Backend").select()
            if new_val and new_val != "ESC":
                config.set("breeze_backend", new_val)

        elif choice == "breeze_mode":
            mode_opts = [
                ("Voice Design (Text description shapes narrator)", "Voice Design"),
                ("Saved Voice (Instant cached .breeze profile)", "Saved Voice"),
                ("Voice Cloning (Reference .wav + transcript)", "Voice Cloning"),
                ("Voice Direction (Reference audio + emotional direction)", "Voice Direction")
            ]
            new_mode = BoxSelector(mode_opts, "Select Breeze Generation Mode").select()
            if new_mode and new_mode != "ESC":
                config.set("breeze_mode", new_mode)

        elif choice == "breeze_model_path":
            new_val = prompt_field_value("Model GGUF Path", curr_model, "(Absolute path to breeze-tts-2-*.gguf)")
            if new_val is not None and new_val.strip():
                from core.paths import sanitize_user_path
                config.set("breeze_model_path", sanitize_user_path(new_val))

        elif choice == "breeze_bin_dir":
            new_val = prompt_field_value("Binaries Directory", curr_bin_dir, "(Path to build/ containing breeze-cli)")
            if new_val is not None and new_val.strip():
                from core.paths import sanitize_user_path
                config.set("breeze_bin_dir", sanitize_user_path(new_val))

        elif choice == "breeze_server_url":
            new_val = prompt_field_value("Breeze Server URL", curr_server_url, "(e.g. http://127.0.0.1:8080)")
            if new_val is not None and new_val.strip():
                config.set("breeze_server_url", new_val.strip())

        elif choice == "breeze_voice_instruct":
            hint = (
                "Describe the voice personality or acting direction.\n"
                "Type text OR pass an absolute path to a .txt file."
            )
            new_val = prompt_field_value("Voice Style Prompt", curr_instruct, hint)
            if new_val is not None:
                from core.paths import sanitize_user_path
                config.set("breeze_voice_instruct", sanitize_user_path(new_val) if ('/' in new_val or '\\' in new_val) else new_val.strip())

        elif choice == "breeze_saved_voice":
            from core.paths import PathAuthority
            pa = PathAuthority()
            tts_dir = pa.get_breeze_tts_dir() / "zine tts"
            v_files = sorted(tts_dir.glob("*.breeze")) if tts_dir.exists() else []
            if not v_files:
                alt_dir = Path(__file__).parent.parent / "Models" / "TTS" / "Breeze tts" / "zine tts"
                v_files = sorted(alt_dir.glob("*.breeze")) if alt_dir.exists() else []
            if not v_files:
                alt_dir2 = Path(__file__).parent.parent / "zine tts"
                v_files = sorted(alt_dir2.glob("*.breeze")) if alt_dir2.exists() else []
            if not v_files:
                console.print("\n[warning]● No .breeze voice profiles found in zine tts.[/warning]")
                console.print("[unselected]Bake a reference audio into a voice profile first via 'breeze' menu.[/unselected]")
                time.sleep(2)
            else:
                opts = [(vf.stem, vf.stem) for vf in v_files]
                new_v = BoxSelector(opts, "Select Saved .breeze Voice Profile").select()
                if new_v and new_v != "ESC":
                    config.set("breeze_saved_voice", new_v)

        elif choice == "breeze_clone_ref_audio":
            new_val = prompt_field_value("Clone Audio Path", curr_ref_audio, "(Path to reference .wav)")
            if new_val is not None:
                from core.paths import sanitize_user_path
                config.set("breeze_clone_ref_audio", sanitize_user_path(new_val))

        elif choice == "breeze_clone_ref_transcript":
            new_val = prompt_field_value("Clone Transcript", curr_ref_transcript, "(Exact words spoken in reference audio)")
            if new_val is not None:
                from core.paths import sanitize_user_path
                val = sanitize_user_path(new_val) if ('/' in new_val or '\\' in new_val) else new_val.strip()
                config.set("breeze_clone_ref_transcript", val)

        elif choice == "breeze_cfg_scale":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Classifier-Free Guidance (CFG Scale)", style="bold sexy_pink"))
            table.add_row(Text("1.0 = Default natural narration.\n2.0 - 2.8 = Strong guidance for acting / dramatic delivery.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ CFG SCALE ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            new_val = prompt_field_value("CFG Scale", str(curr_cfg), "(e.g. 1.0 or 1.5)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_cfg_scale", float(new_val))
                except: pass

        elif choice == "breeze_auto_vocal_cfg":
            opts = [
                ("Enabled (Boosts to 2.5 when (sigh), (laugh), etc. detected - Recommended)", True),
                ("Disabled (Keeps base CFG Scale constant)", False)
            ]
            new_val = BoxSelector(opts, "Auto-Boost CFG on Vocal Event Tags").select()
            if new_val is not None and new_val != "ESC":
                config.set("breeze_auto_vocal_cfg", bool(new_val))

        elif choice == "breeze_hardware":
            opts = [
                ("Vulkan (GPU Acceleration — Blazing Fast)", "Vulkan (GPU)"),
                ("CPU (Force CPU Backend)", "CPU")
            ]
            new_val = BoxSelector(opts, "Select Hardware Acceleration Backend").select()
            if new_val and new_val != "ESC":
                config.set("breeze_hardware", new_val)

        elif choice == "breeze_seed":
            new_val = prompt_field_value("RNG Seed", str(curr_seed), "(Integer seed)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_seed", int(new_val))
                except: pass

        elif choice == "breeze_temperature":
            new_val = prompt_field_value("Temperature", str(curr_temp), "(0.9 = Natural variation)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_temperature", float(new_val))
                except: pass

        elif choice == "breeze_top_k":
            new_val = prompt_field_value("Top K", str(curr_top_k), "(50 = Default)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_top_k", int(new_val))
                except: pass

        elif choice == "breeze_top_p":
            new_val = prompt_field_value("Top P", str(curr_top_p), "(1.0 = Default)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_top_p", float(new_val))
                except: pass

        elif choice == "breeze_rep_penalty":
            new_val = prompt_field_value("Repetition Penalty", str(curr_rep_pen), "(1.1 = Default)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_rep_penalty", float(new_val))
                except: pass

        elif choice == "breeze_split_chars":
            new_val = prompt_field_value("Split Character Cap", str(curr_split_chars), "(Default 600)")
            if new_val is not None and new_val != "":
                try: config.set("breeze_split_chars", int(new_val))
                except: pass

        elif choice == "breeze_llm_adaptation":
            opts = [
                ("Enabled (Dramatic Screenplay Adaptation & Voice Directing via Ollama)", True),
                ("Disabled (Feed raw novel text directly into Breeze-TTS)", False)
            ]
            new_val = BoxSelector(opts, "Configure LLM Screenplay Adaptation").select()
            if new_val is not None:
                config.set("breeze_llm_adaptation", bool(new_val))

        elif choice == "breeze_llm_model":
            opts = [("Auto (Detect best: emma:latest / luna:latest)", "")]
            try:
                import urllib.request, json
                req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "ZineTTS"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    for m in data.get("models", []):
                        m_name = m.get("name", "")
                        if m_name:
                            opts.append((f"Ollama: {m_name}", m_name))
            except Exception:
                pass
            new_model = BoxSelector(opts, "Select LLM Screenplay Director Model").select()
            if new_model is not None:
                config.set("breeze_llm_model", new_model)


def launch_settings_tui():
    """Interactive settings menu to configure Zine preferences cleanly in a single panel box."""
    last_key = None
    while True:
        startup_clear()
        print_banner()

        # Resolve the effective library root — always a valid, writable path
        _stored = config.get("download_base") or ""
        if _stored:
            _resolved_stored = Path(_stored).expanduser().resolve()
            if _resolved_stored.exists() or _resolved_stored.parent.exists():
                curr_download = str(_resolved_stored)
            else:
                # Stored path no longer exists — fall back gracefully
                curr_download = str(Path.home() / "Downloads" / "Zine")
        else:
            curr_download = str(Path.home() / "Downloads" / "Zine")
        curr_music_raw = config.get("music_quick_grab_path") or ""
        curr_music_display = "Quick Grab" if _is_default_music_path(curr_music_raw) else str(curr_music_raw)
        curr_delay = config.get("chapter_delay", 1.0)
        curr_theme = config.get("theme", "tokyo-night-storm")
        curr_tips = "Show" if config.get("show_tips", True) else "Hide"
        curr_check = config.get("internet_check_interval", 10)
        curr_novel_fmt = config.get("novel_format", "TXT")
        curr_cover_art = "Yes" if config.get("download_cover", True) else "No"
        curr_vid_qual = config.get("default_video_quality", "1080p")
        curr_audio_fmt = config.get("default_audio_format", "MP3")
        curr_dup_act = config.get("duplicate_behavior", "Skip Existing")
        curr_sub_mode = config.get("ai_subtitles_mode", "Both")
        curr_sub_model = config.get("ai_subtitles_model", "~/Models/faster-whisper-large-v3-turbo")
        curr_sub_vram = config.get("ai_subtitles_vram", "6GB (INT8)")

        curr_target_lang = config.get("ai_target_lang", "English")

        curr_tts_mode = config.get("tts_mode", "Custom Voice")
        curr_tts_speaker = config.get("tts_custom_speaker", "Ryan")
        curr_tts_comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
        
        default_instruct = "Dynamic and expressive narrator. Seamlessly switch between professional normal narration, deep emotional acting, and sultry/horny character voices based on the text. Emphasize feelings and intonations naturally."
        curr_tts_instruct = config.get("tts_voice_instruct", default_instruct)
        
        curr_tts_instruct_display = _short_path(curr_tts_instruct) if curr_tts_instruct else "None"
        curr_tts_ref_audio = config.get("tts_clone_ref_audio", "")
        curr_tts_ref_audio_display = _short_path(curr_tts_ref_audio) if curr_tts_ref_audio else "None"
        
        sections = [
            ("📁 Storage & Directories", [
                ("Library Root Path",        _short_path(curr_download), "download_base"),
                ("Music Quick-Grab Path",    _short_path(curr_music_display), "music_quick_grab_path"),
            ]),
            ("⚡ Engine & Network", [
                ("Chapter Download Delay",   f"{curr_delay}s", "chapter_delay"),
                ("Connection Check Delay",   f"{curr_check}s", "internet_check_interval"),
                ("Duplicate File Action",    curr_dup_act, "duplicate_behavior"),
            ]),
            ("🎨 Media Preferences", [
                ("Novel Output Format",      curr_novel_fmt, "novel_format"),
                ("Download Cover Art",       curr_cover_art, "download_cover"),
                ("Video Quality Preset",     curr_vid_qual, "default_video_quality"),
                ("Audio Download Format",    curr_audio_fmt, "default_audio_format"),
            ]),
            ("🧠 AI & Audiobooks", [
                ("Whisper AI Subtitles",     "▶ Configure Options", "submenu_whisper"),
                ("Breeze TTS 2 (Audiobooks)","▶ Configure Options", "submenu_breeze"),
                ("Qwen Audiobooks TTS",      "▶ Configure Options", "submenu_qwen"),
            ]),
            ("🖥️ Interface & System", [
                ("Color Theme",              curr_theme, "theme"),
                ("Quick Guide",              curr_tips, "show_tips"),
            ]),
        ]

        choice = SettingsSelector(sections, default_key=last_key).select()

        if choice in ("ESC", None, "CTRL_C"):
            break

        last_key = choice

        if choice == "novel_format":
            fmt_opts = [
                ("Plain Text (.txt)                   ", "TXT"),
                ("EPUB E-Book (.epub)                 ", "EPUB"),
                ("PDF Document (.pdf)                 ", "PDF"),
                ("All Formats (TXT + EPUB + PDF)      ", "All"),
            ]
            new_fmt = BoxSelector(fmt_opts, "Select Novel Format").select()
            if new_fmt and new_fmt != "ESC":
                config.set("novel_format", new_fmt)

        elif choice == "download_cover":
            cov_opts = [
                ("Yes (Download and save cover art)", True),
                ("No  (Skip cover art downloads)  ", False),
            ]
            new_cov = BoxSelector(cov_opts, "Download Cover Art").select()
            if new_cov is not None and new_cov != "ESC":
                config.set("download_cover", new_cov)

        elif choice == "default_video_quality":
            qual_opts = [
                ("Best Available Quality", "Best"),
                ("1080p (Full HD)       ", "1080p"),
                ("720p (HD)             ", "720p"),
                ("480p (Standard)       ", "480p"),
            ]
            new_qual = BoxSelector(qual_opts, "Select Video Quality").select()
            if new_qual and new_qual != "ESC":
                config.set("default_video_quality", new_qual)

        elif choice == "default_audio_format":
            aud_opts = [
                ("FLAC (Lossless Audio / Default) ", "FLAC"),
                ("MP3 (320kbps Standard)         ", "MP3"),
                ("OPUS (High Efficiency)          ", "OPUS"),
                ("M4A (AAC / Apple Audio)         ", "M4A"),
                ("WAV (Uncompressed PCM)          ", "WAV"),
            ]
            new_aud = BoxSelector(aud_opts, "Select Audio Format").select()
            if new_aud and new_aud != "ESC":
                config.set("default_audio_format", new_aud)


        elif choice == "duplicate_behavior":
            dup_opts = [
                ("Skip Existing (Prevent re-downloading) ", "Skip Existing"),
                ("Overwrite (Re-download fresh copies)   ", "Overwrite"),
            ]
            new_dup = BoxSelector(dup_opts, "Duplicate File Action").select()
            if new_dup and new_dup != "ESC":
                config.set("duplicate_behavior", new_dup)

        elif choice == "submenu_whisper":
            whisper_settings_tui()

        elif choice == "submenu_breeze":
            breeze_tts_settings_tui()
            
        elif choice == "submenu_qwen":
            qwen_tts_settings_tui()

        elif choice == "download_base":
            new_path = prompt_field_value("Library Root Path", curr_download, "(Press ESC to cancel without saving)")

            if new_path is not None and new_path.strip() != "":
                from core.paths import sanitize_user_path
                raw = sanitize_user_path(new_path)
                # Guard: reject suspiciously short paths (< 3 chars = likely garbled input)
                if len(raw) < 3:
                    console.print(f"\n[error]● Path too short to be valid: '{raw}' — not saved.[/error]")
                    time.sleep(1.5)
                    continue
                resolved = Path(raw).expanduser().resolve()
                if resolved.name.lower() == "zine":
                    resolved = resolved.parent / "Zine"
                else:
                    resolved = resolved / "Zine"
                # Validate parent is accessible before trying to create
                parent = resolved.parent
                if not parent.exists():
                    console.print(f"\n[error]● Parent directory does not exist: {parent}[/error]")
                    console.print(f"[warning]  Tip: Enter a path whose parent folder already exists.[/warning]")
                    time.sleep(2.0)
                    continue
                import os as _os
                if not _os.access(parent, _os.W_OK):
                    console.print(f"\n[error]● Permission denied — cannot write to: {parent}[/error]")
                    time.sleep(2.0)
                    continue
                try:
                    storage.create_directory(resolved)
                    config.set("download_base", str(resolved))
                    console.print(f"\n[success]● Library Root Path updated to: {resolved}[/success]")
                    time.sleep(1.2)
                except Exception as e:
                    console.print(f"\n[error]● Failed to create directory: {e}[/error]")
                    time.sleep(1.5)

        elif choice == "music_quick_grab_path":
            new_m_path = prompt_field_value("Music Quick-Grab Path", curr_music_display, "(Enter empty string or 'Default' to reset)")

            if new_m_path is not None:
                if not new_m_path or _is_default_music_path(new_m_path):
                    config.set("music_quick_grab_path", "")
                    console.print("\n[success]● Music Quick-Grab Path reset to Default[/success]")
                    time.sleep(1.2)
                else:
                    try:
                        from core.paths import sanitize_user_path
                        resolved_m = Path(sanitize_user_path(new_m_path)).expanduser().resolve()
                        storage.create_directory(resolved_m)
                        config.set("music_quick_grab_path", str(resolved_m))
                        console.print(f"\n[success]● Music Quick-Grab Path updated to: {resolved_m}[/success]")
                        time.sleep(1.2)
                    except Exception as e:
                        console.print(f"\n[error]● Failed to create directory: {e}[/error]")
                        time.sleep(1.5)

        elif choice == "chapter_delay":
            new_delay = prompt_field_value("Chapter Download Delay", str(curr_delay), "(Enter delay in seconds, e.g. 1.5)")

            if new_delay is not None and new_delay != "":
                try:
                    val = float(new_delay)
                    if val < 0:
                        raise ValueError("Delay cannot be negative")
                    config.set("chapter_delay", val)
                    console.print(f"\n[success]● Chapter Delay updated to: {val}s[/success]")
                    time.sleep(1.2)
                except ValueError as e:
                    console.print(f"\n[error]● Invalid delay value: {e}[/error]")
                    time.sleep(1.5)

        elif choice == "internet_check_interval":
            new_check = prompt_field_value("Connection Check Delay", str(curr_check), "(Enter check interval in seconds, e.g. 10)")

            if new_check is not None and new_check != "":
                try:
                    val = int(new_check)
                    if val <= 0:
                        raise ValueError("Must be positive")
                    config.set("internet_check_interval", val)
                    console.print(f"\n[success]● Connection Check Delay updated to: {val}s[/success]")
                    time.sleep(1.2)
                except Exception as e:
                    console.print(f"\n[error]● Invalid check interval: {e}[/error]")
                    time.sleep(1.5)

        elif choice == "show_tips":
            config.set("show_tips", not config.get("show_tips", True))

        elif choice == "theme":
            import platform
            os_name = platform.system()
            os_release = platform.release()
            if os_name == "Linux":
                try:
                    os_display = f"Linux ({platform.freedesktop_os_release().get('NAME', 'Generic Linux')})"
                except Exception:
                    os_display = "Linux"
            elif os_name == "Darwin":
                os_display = f"macOS ({os_release})"
            else:
                os_display = f"Windows {os_release}"
            term_display = detect_terminal()
            raw_lib = config.get("download_base") or str(paths.get_downloads_root())
            try:
                home = Path.home().resolve()
                res_l = Path(raw_lib).resolve()
                library_display = "~" if res_l == home else f"~/{res_l.relative_to(home)}"
            except Exception:
                library_display = str(raw_lib)

            theme_options = [
                ("Tokyo Night", "tokyo-night-storm"),
                ("Catppuccin", "catppuccin"),
                ("GitHub Dark", "github-dark"),
                ("Dracula", "dracula"),
                ("Nord", "nord"),
                ("One Dark", "one-dark"),
                ("Everforest", "everforest"),
                ("Gruvbox Dark", "gruvbox-dark"),
                ("Rose Pine", "rose-pine"),
                ("Night Owl", "night-owl"),
                ("Ayu Dark", "ayu-dark"),
                ("Monokai Pro", "monokai-pro"),
                ("Solarized Dark", "solarized-dark"),
                ("Horizon", "horizon"),
                ("Oxocarbon", "oxocarbon"),
                ("Nordic Frost", "nordic-frost"),
                ("Jungle Dim", "jungle-dim"),
                ("Muted Lavender", "muted-lavender"),
                ("Dim Charcoal", "dim-charcoal"),
                ("Calm Ocean", "calm-ocean"),
                ("Earthy Moss", "earthy-moss"),
                ("Soft Sepia", "soft-sepia"),
                ("Dusk Rose", "dusk-rose"),
                ("Slate Storm", "slate-storm"),
                ("Night Sky", "night-sky"),
            ]
            new_t = ThemeSelector(theme_options, "Select Color Theme", os_display, term_display, library_display).select()
            config.set("theme", new_t)
