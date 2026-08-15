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

from core.ui import console, startup_clear, print_banner, Selector, set_active_live
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
    """Clean single-box Panel renderer for Zine Settings Configurator."""

    def _render(self) -> Panel:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("label", width=25)
        table.add_column("sep", width=2, justify="center")
        table.add_column("val", width=42)

        for i, (label_and_val, key) in enumerate(self.options):
            label, val_str = label_and_val
            is_active = (i == self.index)

            l_text = Text(no_wrap=True, overflow="crop")
            v_text = Text(no_wrap=True, overflow="crop")

            if is_active:
                l_text.append(f"▶ {label}", style="bold sexy_pink")
                v_text.append(str(val_str), style="bold white")
                table.add_row(l_text, Text(":", style="bold sexy_pink"), v_text)
            else:
                l_text.append(f"  {label}", style="unselected")
                v_text.append(str(val_str), style="unselected")
                table.add_row(l_text, Text(":", style="unselected"), v_text)

        footer = Text(justify="center")
        footer.append("↑↓", style="bold white");    footer.append(" Navigate  ", style="unselected")
        footer.append("Enter", style="bold white"); footer.append(" Select  ", style="unselected")
        footer.append("Esc", style="bold white");   footer.append(" Exit to Menu", style="unselected")

        return Panel(
            table,
            title="[bold white]◆ ZINE SETTINGS CONFIGURATOR[/bold white]",
            subtitle=footer,
            subtitle_align="center",
            border_style="sexy_pink",
            padding=(1, 2),
            width=80,
        )


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
        curr_sub_model = config.get("ai_subtitles_model", "~/Models/faster-whisper-large-v3-turbo")
        curr_sub_vram = config.get("ai_subtitles_vram", "6GB (INT8)")
        curr_target_lang = config.get("ai_target_lang", "English")

        options = [
            (("AI Subtitle Generation", curr_sub_mode), "ai_subtitles_mode"),
            (("Translation Language",   curr_target_lang), "ai_target_lang"),
            (("AI Model Path",          _short_path(curr_sub_model)), "ai_subtitles_model"),
            (("AI GPU Mode",            curr_sub_vram), "ai_subtitles_vram"),
        ]
        choice = SettingsSelector(options).select()
        if not choice or choice in ("ESC", "CTRL_C"):
            break
        elif choice == "ai_subtitles_mode":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("AI Subtitle Output Options", style="bold sexy_pink"))
            table.add_row(Text("Choose which subtitles to generate when using the manual AI subtitle tool.", style="unselected"))
            panel = Panel(table, title="[bold white]◆ AI SUBTITLES CONFIGURATION ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80)
            console.print()
            console.print(panel)
            mode_opts = [
                ("Only give me translated subtitles (e.g. English)      ", "Target"), 
                ("Only give me the original spoken language subtitles   ", "Original"), 
                ("Give me both (Original language + Translated language)", "Both"), 
                ("Turn off AI Subtitles entirely                        ", "None")
            ]
            new_mode = Selector(mode_opts, "Select Generation Mode", vertical=True).select()
            if new_mode and new_mode != "ESC":
                config.set("ai_subtitles_mode", new_mode)
                
        elif choice == "ai_target_lang":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("AI Translation Language", style="bold sexy_pink"))
            table.add_row(Text("If you chose to generate translated subtitles, pick the language here.", style="unselected"))
            panel = Panel(table, title="[bold white]◆ TRANSLATION LANGUAGE ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80)
            console.print()
            console.print(panel)
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
            new_lang = Selector(langs, "Select Language", vertical=True).select()
            if new_lang and new_lang != "ESC":
                config.set("ai_target_lang", new_lang)
                
        elif choice == "ai_subtitles_model":
            new_m_path = prompt_field_value("AI Model Path", str(curr_sub_model), "(Path to downloaded HF Model)")
            if new_m_path is not None and new_m_path.strip() != "":
                from core.paths import sanitize_user_path
                config.set("ai_subtitles_model", sanitize_user_path(new_m_path))

        elif choice == "ai_subtitles_vram":
            vram_opts = [("6GB (INT8 - Fastest/Safest)", "6GB (INT8)"), ("8GB+ (FP16 - High Quality)", "FP16"), ("CPU-Only (Very Slow)", "CPU-Only")]
            new_vram = Selector(vram_opts, "Select Hardware Target").select()
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
            new_mode = Selector(mode_opts, "Select Qwen TTS Generation Mode").select()
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
            new_speaker = Selector(speaker_opts, "Select TTS Preset Speaker", vertical=True).select()
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
            new_val = Selector(opts, "Select Voice Clone Feature Extraction Method").select()
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
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Qwen Model Size", style="bold sexy_pink"))
            table.add_row(Text("1.7B is much smarter and sounds more human, but uses more GPU VRAM.\n0.6B is lightweight, fast, but slightly more robotic.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ MODEL CHOICE ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            opts = [("1.7B (High Quality, More VRAM)", "1.7B"), ("0.6B (Fast, Low VRAM)", "0.6B")]
            new_val = Selector(opts, "Select Qwen TTS Model").select()
            if new_val and new_val != "ESC":
                config.set("tts_model_choice", new_val)
                
        elif choice == "tts_precision":
            table = Table(box=None, show_header=False, padding=(0, 1))
            table.add_column("info", width=70)
            table.add_row(Text("Math Precision", style="bold sexy_pink"))
            table.add_row(Text("bf16 is the golden standard (fast & safe).\nUse fp32 ONLY if you have an older GPU or experience weird static noises.", style="unselected"))
            console.print()
            console.print(Panel(table, title="[bold white]◆ PRECISION ◆[/bold white]", border_style="sexy_pink", padding=(1, 2), width=80))
            
            opts = [("bf16 (Recommended for RTX 3000/4000)", "bf16"), ("fp16 (Good fallback)", "fp16"), ("fp32 (High Memory / Old GPUs)", "fp32")]
            new_val = Selector(opts, "Select Precision").select()
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

def launch_settings_tui():
    """Interactive settings menu to configure Zine preferences cleanly in a single panel box."""
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
        
        options = [
            (("Library Root Path",      _short_path(curr_download)), "download_base"),
            (("Music Quick-Grab Path",  _short_path(curr_music_display)), "music_quick_grab_path"),
            (("Chapter Download Delay", f"{curr_delay}s"), "chapter_delay"),
            (("Connection Check Delay", f"{curr_check}s"), "internet_check_interval"),
            (("Whisper AI Subtitles",   "▶ Configure Options"), "submenu_whisper"),
            (("Qwen Audiobooks TTS",    "▶ Configure Options"), "submenu_qwen"),
            (("Color Theme",            curr_theme), "theme"),
            (("Quick Guide",            curr_tips), "show_tips"),
        ]

        choice = SettingsSelector(options).select()

        if choice in ("ESC", None, "CTRL_C"):
            break

        elif choice == "submenu_whisper":
            whisper_settings_tui()
            
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
