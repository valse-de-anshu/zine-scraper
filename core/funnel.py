"""
core/funnel.py
--------------
Funnel Layer: Captures raw inputs, resolves commands, and dynamically handshakes 
with site-specific scraper TUIs. Routes all operations through path config and storage layers.
"""

import os
import sys
import time
import importlib
import select
from pathlib import Path
from typing import List, Tuple, Any, Optional
import logging

from core.ui import console, startup_clear, print_banner, clean_exit, Selector, get_theme_input_ansi, read_tty_key
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from rich.console import Group
from rich.text import Text
from rich.markup import escape
from core.paths import PathAuthority
from core.storage import StorageLayer
from core.config import ConfigLayer
from core.history import HistoryLayer
from core.cache import CacheLayer

# Initialize Centralized Foundation Services
paths = PathAuthority()
storage = StorageLayer()
config = ConfigLayer(paths, storage)
history = HistoryLayer(paths, storage)
cache = CacheLayer(paths, storage)

# Centralized dynamic path settings via module-level __getattr__
URLS_FILE = paths.get_urls_file()

from core.domain_manager import DomainManager
domain_manager = DomainManager(Path(__file__).parent.parent / "scrapers")


def __getattr__(name: str) -> Any:
    if name == "BASE_SAVE_PATH":
        return Path(config.get("download_base") or paths.get_downloads_root())
    if name == "VIDEO_SAVE_ROOT":
        return Path(config.get("download_base") or paths.get_downloads_root()) / "video"
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

def load_urls() -> List[str]:
    urls = []
    if URLS_FILE.exists():
        try:
            content = storage.read_file(URLS_FILE)
            for line in content.splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("="): urls.append(line)
        except Exception:
            pass
    return urls

from core.site_map import get_site_folder

def get_scraper_instance(url: str):
    try:
        site_folder = get_site_folder(url)
        if not site_folder: return None

        module = importlib.import_module(f"scrapers.{site_folder}.scraper")
        base_classes = ["BaseScraper", "AssetBaseScraper", "VideoBaseScraper", "MusicBaseScraper"]
        scraper_class = next((getattr(module, n) for n in dir(module) 
                            if n.endswith("Scraper") and n not in base_classes), None)
        return scraper_class(url) if scraper_class else None
    except Exception as e:
        console.print(f"[error]Failed to load scraper: {escape(str(e))}[/error]")
    return None

from core.settings_tui import launch_settings_tui
from wizard.setup import run_first_launch_setup

def clear_lines(num_lines: int):
    for _ in range(num_lines):
        sys.stdout.write("\033[1A\033[2K")
    sys.stdout.flush()

def handle_batch(hist_layer, store_layer):
    urls = load_urls()
    if not urls:
        console.print("[warning]No URLs found in Batch URL.txt![/warning]")
        time.sleep(1.5)
        return
    
    startup_clear()
    print_banner()
    console.print(f"[menu]Menu:[/menu] [site]Batch Mode[/site]")
    console.print(f"[info]Batch: {len(urls)} URLs loaded.[/info]")
    
    if not sys.stdin.isatty():
        cat_mode = "ALL"
    else:
        cat_mode = Selector([("Apply Global", "ALL"), ("Ask Individual", "PER"), ("Back", "BACK")], "Cat Mode").select()
    if cat_mode == "BACK":
        return

    global_path = None
    if cat_mode == "ALL":
        from core.ui import get_batch_save_path
        global_path = get_batch_save_path(store_layer)
        if not global_path:
            return

    successful_urls = []
    for raw_url in urls:
        url = raw_url
        batch_quick_grab = False
        if url.endswith("--0"):
            url = url[:-3].strip()
            batch_quick_grab = True
            
        if route_url(url, hist_layer, store_layer, batch_path=global_path, is_batch=True, batch_quick_grab=batch_quick_grab):
            successful_urls.append(raw_url)
            
    if successful_urls:
        try:
            current_urls = load_urls()
            remaining = [u for u in current_urls if u not in successful_urls]
            content = "\n".join(remaining) + ("\n" if remaining else "")
            store_layer.write_file(URLS_FILE, content)
            console.print(f"\n[success]Cleaned up {len(successful_urls)} completed URLs from Batch URL.txt[/success]")
        except Exception:
            pass
            
    console.input("\n[info]Batch finished. Press Enter to return to menu...[/info]")

def route_url(url: str, hist_layer: HistoryLayer, store_layer: StorageLayer, batch_path: Optional[Path] = None, is_batch: bool = False, batch_quick_grab: bool = False) -> bool:
    if not is_batch:
        startup_clear()
        print_banner()
        try:
            from core.history_links import URLHistoryManager
            URLHistoryManager().append(url)
        except Exception:
            pass
        
    try:
        scraper = get_scraper_instance(url)
    except Exception as e:
        logger.error(f"Error resolving scraper for URL: {url} -> {e}")
        scraper = None

    safe_url = escape(str(url))

    if not scraper:
        logging.error(f"Unsupported URL: {url}")
        console.print(f"[warning]Unsupported URL or command: {safe_url}[/warning]")
        if not is_batch:
            if sys.stdin.isatty():
                try:
                    sys.stdout.write("\033[38;2;125;207;255m  Press Enter to return...\033[0m ")
                    sys.stdout.flush()
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
        else:
            time.sleep(1.5)
        return False

    site_folder = get_site_folder(url)
    if not site_folder:
        console.print(f"[warning]Unsupported site folder for URL: {safe_url}[/warning]")
        if not is_batch:
            if sys.stdin.isatty():
                try:
                    sys.stdout.write("\033[38;2;125;207;255m  Press Enter to return...\033[0m ")
                    sys.stdout.flush()
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
        else:
            time.sleep(1.5)
        return False



    try:
        logging.info(f"Passing control to TUI for site: {site_folder} with scraper: {scraper.__class__.__name__}")
        tui_module = importlib.import_module(f"scrapers.{site_folder}.tui")
        
        notification_fired = False
        def fire_notification():
            nonlocal notification_fired
            if not notification_fired:
                try:
                    from butler.notify import send_os_notification
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.replace("www.", "")
                    send_os_notification(f"Zine Scraper: {domain}", "Successfully finished scraping job!", is_success=True)
                except Exception as e:
                    logging.error(f"Notification failed: {e}")
                notification_fired = True

        original_input = console.input
        original_print = console.print
        
        def patched_input(prompt="", **kwargs):
            if "[info]" in str(prompt) or "finished" in str(prompt).lower() or "return" in str(prompt).lower():
                fire_notification()
                if is_batch:
                    return ""
            return original_input(prompt, **kwargs)

        def patched_print(*args, **kwargs):
            text = " ".join(str(a) for a in args)
            if "finished" in text.lower() and "return" in text.lower():
                fire_notification()
            return original_print(*args, **kwargs)

        console.input = patched_input
        console.print = patched_print
        try:
            scraper._batch_quick_grab = batch_quick_grab
            tui_module.handle_tui(url, hist_layer, store_layer, scraper, batch_path=batch_path, is_batch=is_batch)
            fire_notification() # In case it's batch mode and didn't call input
        finally:
            console.input = original_input
            console.print = original_print
            
        logging.info(f"Finished TUI execution for: {url}")
        return True
    except Exception as e:
        logging.error(f"Failed to load/execute TUI for {site_folder}: {e}", exc_info=True)
        
        try:
            from butler.notify import send_os_notification
            send_os_notification("Zine Scraper Error", f"Scraping failed: {e}", is_success=False)
        except Exception:
            pass
            
        console.print(f"[error]Failed to load TUI for {escape(str(site_folder))}: {escape(str(e))}[/error]")
        if not is_batch:
            console.print("\n[info]Press any key to return...[/info]", end="")
            get_key_with_esc()
        else:
            time.sleep(1.5)
        return False

def _get_tui_key() -> str:
    if os.name == "nt":
        try:
            import msvcrt
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H": return "UP"
                if ch2 == b"P": return "DOWN"
                if ch2 == b"K": return "LEFT"
                if ch2 == b"M": return "RIGHT"
                if ch2 == b"G": return "HOME"
                if ch2 == b"O": return "END"
                return ""
            if ch in (b"\r", b"\n"): return "ENTER"
            if ch == b"\x1b":       return "ESC"
            if ch == b"\x09":       return "TAB"
            if ch in (b"\x7f", b"\x08"): return "BACKSPACE"
            if ch == b"\x03":       return "CTRL_C"
            try:
                c = ch.decode("utf-8", errors="ignore")
                if c.isprintable(): return c
            except Exception: pass
            return ""
        except Exception:
            return ""
    else:
        import tty, termios, select as _sel
        fd  = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            mode    = termios.tcgetattr(fd)
            mode[3] = mode[3] | termios.ISIG   # keep Ctrl-C alive
            mode[1] = mode[1] | termios.OPOST  # keep newline translation
            termios.tcsetattr(fd, termios.TCSADRAIN, mode)
            _sel.select([fd], [], [])
            raw = os.read(fd, 1)
            if not raw: return ""
            ch = raw.decode("utf-8", errors="ignore")
            if ch == "\x1b":
                r, _, _ = _sel.select([fd], [], [], 0.08)
                if r:
                    ch2 = os.read(fd, 1).decode("utf-8", errors="ignore")
                    if ch2 in ("[", "O"):
                        r2, _, _ = _sel.select([fd], [], [], 0.08)
                        if r2:
                            ch3 = os.read(fd, 1).decode("utf-8", errors="ignore")
                            if ch3 == "A": return "UP"
                            if ch3 == "B": return "DOWN"
                            if ch3 == "C": return "RIGHT"
                            if ch3 == "D": return "LEFT"
                            if ch3 == "H": return "HOME"
                            if ch3 == "F": return "END"
                return "ESC"
            if ch in ("\r", "\n"): return "ENTER"
            if ch == "\x03":       return "CTRL_C"
            if ch == "\x09":       return "TAB"
            if ch in ("\x7f", "\x08"): return "BACKSPACE"
            if ch.isprintable():   return ch
            return ""
        except Exception:
            return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

def get_key_with_esc() -> str:
    if os.name == 'nt':
        try:
            import msvcrt
            ch = msvcrt.getch()
            if ch == b'\x1b':
                return 'ESC'
            if ch in (b'\x00', b'\xe0'):
                ch2 = msvcrt.getch()
                if ch2 == b'H':  # Up
                    return '[A'
                elif ch2 == b'P':  # Down
                    return '[B'
                elif ch2 == b'K':  # Left
                    return '[D'
                elif ch2 == b'M':  # Right
                    return '[C'
                return ""
            if ch in (b'\r', b'\n'):
                return '\r'
            if ch in (b'\x7f', b'\x08'):
                return '\x08'
            if ch == b'\x03':
                return '\x03'
            return ch.decode('utf-8', errors='ignore')
        except Exception:
            return ""
    else:
        try:
            import tty
            import termios
            import select as select_mod
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                # Re-enable ISIG so Ctrl+C immediately generates keyboard interrupt signals
                mode = termios.tcgetattr(fd)
                mode[3] = mode[3] | termios.ISIG
                mode[1] = mode[1] | termios.OPOST
                termios.tcsetattr(fd, termios.TCSANOW, mode)
                r, _, _ = select_mod.select([fd], [], [])
                if not r:
                    return ""
                ch_bytes = os.read(fd, 1)
                ch = ch_bytes.decode('utf-8', errors='ignore')
                if ch == '\x1b':
                    seq = ""
                    r, _, _ = select_mod.select([fd], [], [], 0.001)
                    if r:
                        ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                        seq += ch2
                        if ch2 in ('[', 'O'):
                            while True:
                                r2, _, _ = select_mod.select([fd], [], [], 0)
                                if r2:
                                    ch_next = os.read(fd, 1).decode('utf-8', errors='ignore')
                                    seq += ch_next
                                    if ch_next.isalpha() or ch_next == '~':
                                        break
                                else:
                                    break
                    if not seq:
                        return 'ESC'
                    return seq
                else:
                    paste_str = ch
                    while True:
                        r, _, _ = select_mod.select([fd], [], [], 0)
                        if r:
                            extra = os.read(fd, 1).decode('utf-8', errors='ignore')
                            paste_str += extra
                        else:
                            break
                    return paste_str
            finally:
                termios.tcsetattr(fd, termios.TCSANOW, old_settings)
        except Exception:
            return ""

class MainPrompt:
    def __init__(self, paths, config):
        self.paths = paths
        self.config = config
        self.input_text = ""
        self.suggestion = ""
        self.cursor_pos = 0  # index into input_text
        from core.history_links import URLHistoryManager
        self.history_manager = URLHistoryManager()

    def get_input(self) -> str:
        global _LIVE_INSTANCE
        if 'unittest' in sys.modules or not sys.stdin.isatty():
            return self.fallback_input()
        console.show_cursor(False)
        import core.ui
        old_menu_active = core.ui._MENU_ACTIVE
        core.ui._MENU_ACTIVE = True
        self.history_manager.reload()
        try:
            self.input_text = ""
            self.cursor_pos = 0
            self.suggestion = ""
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                core.ui._LIVE_INSTANCE = live
                while True:
                    live.update(self._render(), refresh=True)
                    key = get_key_with_esc()
                    if not key:
                        return self.fallback_input()
                    
                    if key in ('[A', 'OA'): # Up Arrow
                        self.input_text = self.history_manager.get_up(self.input_text)
                        self.cursor_pos = len(self.input_text)
                        self._update_suggestion()
                    elif key in ('[B', 'OB'): # Down Arrow
                        self.input_text = self.history_manager.get_down(self.input_text)
                        self.cursor_pos = len(self.input_text)
                        self._update_suggestion()
                    elif key in ('[D', 'OD'): # Left Arrow
                        if self.cursor_pos > 0:
                            self.cursor_pos -= 1
                    elif key in ('[C', 'OC'): # Right Arrow
                        if self.cursor_pos < len(self.input_text):
                            self.cursor_pos += 1
                    elif key in ('[H', '[1~', 'OH'): # Home
                        self.cursor_pos = 0
                    elif key in ('[F', '[4~', 'OF'): # End
                        self.cursor_pos = len(self.input_text)
                    elif len(key) > 1 and (key.startswith('[') or key.startswith('O')):
                        continue
                    elif key in ('\r', '\n'):
                        if self.suggestion and self.input_text != self.suggestion:
                            self.input_text = self.suggestion
                            self.cursor_pos = len(self.input_text)
                            self.suggestion = ""
                            continue
                        ret = self.input_text.strip()
                        self.history_manager.append(ret)
                        self.history_manager.index = len(self.history_manager.history)
                        return ret
                    elif key in ('\x7f', '\x08'): # Backspace
                        if self.cursor_pos > 0:
                            self.input_text = self.input_text[:self.cursor_pos - 1] + self.input_text[self.cursor_pos:]
                            self.cursor_pos -= 1
                        self._update_suggestion()
                        self.history_manager.index = len(self.history_manager.history)
                    elif key == '\x03': # Ctrl+C
                        clean_exit(forceful=True)
                    elif len(key) >= 1:
                        # Handle pastes that might contain newlines by stripping them
                        clean_key = "".join(c for c in key if c.isprintable())
                        if clean_key:
                            self.input_text = self.input_text[:self.cursor_pos] + clean_key + self.input_text[self.cursor_pos:]
                            self.cursor_pos += len(clean_key)
                            self._update_suggestion()
                            self.history_manager.index = len(self.history_manager.history)
                        
                        # If the paste had a newline, auto-submit
                        if '\n' in key or '\r' in key:
                            ret = self.input_text.strip()
                            if ret:
                                self.history_manager.append(ret)
                                return ret
        except Exception:
            return self.fallback_input()
        finally:
            core.ui._LIVE_INSTANCE = None
            console.show_cursor(True)
            core.ui._MENU_ACTIVE = old_menu_active

    def fallback_input(self) -> str:
        console.print("[menu]Paste URL:[/menu]")
        from core.ui import theme_input
        return theme_input("[menu]❯ [/menu]")

    def _update_suggestion(self):
        if not self.input_text:
            self.suggestion = ""
            return
        
        val = self.input_text.lower()
        # If input is a URL or a file path, immediately suppress any command suggestions
        if val.startswith("http") or val.startswith("www") or "/" in val or "\\" in val or "." in val:
            self.suggestion = ""
            return
            
        commands = ["settings", "exit", "help", "batch", "batch test", "site", "slice", "subs", "tts", "lyrs", "bake", "sc-lyrics"]
        for cmd in commands:
            if cmd.startswith(val) and len(val) < len(cmd):
                self.suggestion = cmd
                return
        self.suggestion = ""

    def _render(self) -> Table:
        show_tips = self.config.get("show_tips", True, force_reload=True)
        
        table = Table.grid(padding=(0, 0))
        table.add_column("main", width=88)
        
        group_content = []
        from core.ui import get_banner_renderable
        group_content.append(get_banner_renderable())
        group_content.append(Text(""))
        
        prompt_text = Text(no_wrap=True)
        prompt_text.append("Paste URL:\n", style="menu")
        prompt_text.append("❯ ", style="menu")
        
        # Split text at cursor position and render the block cursor
        before_cursor = self.input_text[:self.cursor_pos]
        after_cursor  = self.input_text[self.cursor_pos:]

        prompt_text.append(before_cursor, style="selected")

        at_end = self.cursor_pos >= len(self.input_text)
        if at_end:
            # End-of-text: always show solid block cursor
            prompt_text.append("█", style="selected")
        else:
            # Mid-text: highlight the char under the cursor with reverse video (always visible)
            prompt_text.append(after_cursor[0], style="bold reverse")
            prompt_text.append(after_cursor[1:], style="selected")
            
        # Suggestion remainder only shown when cursor is at end
        suggestion_remainder = ""
        if at_end and self.suggestion and self.suggestion.startswith(self.input_text):
            suggestion_remainder = self.suggestion[len(self.input_text):]
            prompt_text.append(suggestion_remainder, style="unselected")
            
        # We want the input block to always occupy a fixed number of lines to prevent UI jumping.
        W = 88
        display_len = len("❯ ") + len(self.input_text) + len(suggestion_remainder)
        occupied_lines = (display_len + W - 1) // W
        if occupied_lines < 1:
            occupied_lines = 1
            
        empty_lines = 2 - occupied_lines
        if empty_lines < 0:
            empty_lines = 0
            
        prompt_text.append("\n" * empty_lines)
        
        group_content.append(prompt_text)
        
        if show_tips:
            tip_text = Text()
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("exit", style="warning")
            tip_text.append(" to quit.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("settings", style="warning")
            tip_text.append(" to configure.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("help", style="warning")
            tip_text.append(" for guide docs.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("batch", style="warning")
            tip_text.append(" to download all from Batch URL.txt\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("site", style="warning")
            tip_text.append(" to view supported site database.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("subs", style="warning")
            tip_text.append(" to generate AI subtitles.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("tts", style="warning")
            tip_text.append(" to generate Audiobooks.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("lyrs", style="warning")
            tip_text.append(" to search & download synced lyrics (.lrc).\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("bake", style="warning")
            tip_text.append(" to edit & embed audio metadata/cover art.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Type ", style="info")
            tip_text.append("sc-lyrics", style="warning")
            tip_text.append(" to batch auto-sync missing .lrc files.\n", style="info")
            
            tip_text.append("● ", style="success")
            tip_text.append("Paste any supported URL to archive.\n", style="info")
            tip_text.append("To hide, go to settings > Quick Guide > Hide", style="unselected")
            
            tip_panel = Panel(
                tip_text,
                title="[info]Quick Guide[/info]",
                border_style="menu",
                expand=False,
                width=88
            )
            group_content.append(tip_panel)
            
        table.add_row(Group(*group_content))
        return table

def show_help_tui():
    """Renders help.md in the console and waits for ESC key to exit."""
    startup_clear()
    print_banner()
    
    help_path = Path(__file__).parent.parent / "docs" / "help.md"
    if not help_path.exists():
        console.print("[error]● Help documentation file not found![/error]")
        time.sleep(2)
        return
        
    try:
        from rich.markdown import Markdown
        with open(help_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        md_renderable = Markdown(md_content)
        
        help_panel = Panel(
            md_renderable,
            title="[bold menu]❖ Zine Help Center[/bold menu]",
            border_style="menu",
            expand=False,
            width=88
        )
        
        startup_clear()
        print_banner()
        console.print(help_panel)
        console.print("\n[success]Press ESC to return to Zine Scraper[/success]")
        
        while True:
            key = get_key_with_esc()
            if key == 'ESC' or key == '\x1b':
                break
            elif key == '\x03': # Ctrl+C
                clean_exit(forceful=True)
            time.sleep(0.05)
    except Exception as e:
        console.print(f"[error]Error rendering help documentation: {e}[/error]")
        time.sleep(2)

def show_site_tui():
    """Renders the comprehensive, split-panel supported sites database table."""
    try:
        from core.site_tui import SiteDatabaseTUI
        tui = SiteDatabaseTUI()
        tui.run()
    except Exception as e:
        console.print(f"[error]Failed to load Site Database TUI: {e}[/error]")
        import time
        time.sleep(2)

def main():
    if config.is_first_launch():
        config._defer_save = True
        config_file = paths.get_config_file()
        if config_file.exists():
            try:
                os.remove(config_file)
            except Exception:
                pass
        run_first_launch_setup(paths, storage, config)

    # ── Ensure library structure is intact on every launch ───────────────────
    try:
        from core.library import scaffold_library, clean_temp
        lib_root_str = config.get("download_base")
        if lib_root_str:
            from pathlib import Path as _Path
            lib_root = _Path(lib_root_str).resolve()
            paths.set_downloads_root(lib_root)
            scaffold_library(lib_root, storage)   # no-op if dirs already exist
            clean_temp(lib_root, storage)          # auto-clean temp on startup
    except Exception:
        pass  # never block launch due to library scaffold errors

    while True:
        history.reload()
        startup_clear()
        if not sys.stdin.isatty() or 'unittest' in sys.modules:
            print_banner()

        try:
            prompt = MainPrompt(paths, config)
            url = prompt.get_input()
            
            if not url:
                continue
            
            logging.info(f"User Input: '{url}'")
            # Match commands
            url_lower = url.lower()
            if url_lower in ["exit", "quit", "q", "/exit"]:
                logging.info("User requested exit.")
                clean_exit(forceful=False)
            elif url_lower in ["batch", "/batch"]:
                logging.info("User launched batch mode.")
                handle_batch(history, storage)

            elif url_lower in ["settings", "/settings"]:
                launch_settings_tui()
            elif url_lower in ["help", "/help"]:
                show_help_tui()
            elif url_lower in ["site", "/site", "sites"]:
                show_site_tui()
            elif url_lower in ["slice", "/slice", "slicer"]:
                from core.image_slicer import run_image_slicer_tui
                run_image_slicer_tui()
            elif url_lower in ["subs", "/subs", "subtitles"]:
                from core.subtitle_engine import run_subtitle_tui
                run_subtitle_tui()
            elif url_lower in ["tts", "/tts", "audiobook"]:
                qwen_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Qween tts")
                if qwen_path not in sys.path:
                    sys.path.insert(0, qwen_path)
                import book_tts
                book_tts.run_tts_tui()
            elif url_lower in ["lyrs", "/lyrs", "lyrics", "/lyrics"]:
                from core.lyrics_engine import run_lyrics_tui
                run_lyrics_tui()
            elif url_lower in ["bake", "/bake"]:
                from core.bake_engine import run_bake_tui
                run_bake_tui()
            elif url_lower in ["sc-lyrics", "/sc-lyrics", "sc_lyrics", "sclyrs"]:
                from core.lyrics_engine import run_batch_lyrics_tui
                run_batch_lyrics_tui()
            else:
                route_url(url, history, storage)
                
        except KeyboardInterrupt:
            clean_exit(forceful=True)

if __name__ == "__main__":
    main()
