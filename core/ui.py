import sys
import os
import signal
import threading
import logging
import re
from typing import List, Tuple, Any, Optional
from pathlib import Path

try:
    import readline
except ImportError:
    pass

from rich.console import Console
from rich.theme import Theme
from rich.live import Live
from rich.text import Text
from rich.tree import Tree
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TaskProgressColumn, TimeRemainingColumn, ProgressColumn

class MbpsColumn(ProgressColumn):
    """Renders download speed in Mbps (Megabits per second)."""
    def render(self, task) -> Text:
        speed = task.fields.get('speed') or task.speed
        if speed is None or speed == 0:
            return Text("0.0 Mbps", style="unselected")
        mbps = (speed * 8) / 1_000_000
        return Text(f"{mbps:.1f} Mbps", style="success")

class CustomDownloadColumn(ProgressColumn):
    """Renders downloaded/total file size in MB."""
    def render(self, task) -> Text:
        completed = task.completed
        total = task.total
        if total is None or total == 0:
            return Text(f"{completed / 1_000_000:.1f} MB", style="unselected")
        return Text(f"{completed / 1_000_000:.1f}/{total / 1_000_000:.1f} MB", style="success")

class CustomTimeRemainingColumn(ProgressColumn):
    """Renders remaining download time (ETA) based on custom fields or Rich estimates."""
    def render(self, task) -> Text:
        eta = task.fields.get('eta')
        if eta is None:
            remaining = task.time_remaining
            if remaining is not None:
                eta = remaining
        if eta is None or eta < 0:
            return Text("00:00", style="unselected")
        hours, remainder = divmod(int(eta), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return Text(f"{hours}:{minutes:02d}:{seconds:02d}", style="success")
        return Text(f"{minutes:02d}:{seconds:02d}", style="success")

# Tokyo Night Storm Palette Theme
# ── Advanced Dark Theme Definitions ───────────────────────────────────
from theme.registry import THEMES

# ── Terminal Capability Checks & Fallback ──────────────────────────────
def supports_unicode() -> bool:
    try:
        encoding = sys.stdout.encoding or 'ascii'
        if 'utf' in encoding.lower():
            return True
    except Exception:
        pass
    if os.name == 'nt':
        if 'WT_SESSION' in os.environ:
            return True
        try:
            import ctypes
            if ctypes.windll.kernel32.GetConsoleOutputCP() == 65001:
                return True
        except Exception:
            pass
        return False
    return True

def supports_color() -> bool:
    if "NO_COLOR" in os.environ:
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    if not sys.stdout.isatty():
        return False
    return True

UN_SUPPORT = supports_unicode()

class CustomConsole(Console):
    def print(self, *args, **kwargs):
        if not UN_SUPPORT:
            new_args = []
            mapping = {
                "❯": ">",
                "●": "*",
                "◆": "+",
                "⬢": "*",
                "⬡": "o",
                "✔": "[OK]",
                "■": "#",
                "»": ">>",
                "◇": "o",
                "❖": "*",
            }
            for arg in args:
                if isinstance(arg, str):
                    for k, v in mapping.items():
                        arg = arg.replace(k, v)
                elif hasattr(arg, "plain") and hasattr(arg, "copy"):
                    # If it's a Rich Text object
                    try:
                        arg_copy = arg.copy()
                        for k, v in mapping.items():
                            arg_copy.replace(k, v)
                        arg = arg_copy
                    except Exception:
                        pass
                new_args.append(arg)
            super().print(*new_args, **kwargs)
        else:
            super().print(*args, **kwargs)

# Initialize console with active theme styling
custom_theme = Theme(THEMES["tokyo-night-storm"])
console = CustomConsole(theme=custom_theme, color_system="truecolor" if supports_color() else None)

def apply_theme(theme_name: str):
    import theme
    theme.apply_theme(console, theme_name)

def make_gradient_text(text: str, start_color: Tuple[int, int, int], end_color: Tuple[int, int, int], total_length: Optional[int] = None) -> Text:
    rich_text = Text()
    # Use provided total_length or fall back to actual text length
    display_length = total_length if total_length is not None else len(text)
    
    for i, char in enumerate(text):
        if display_length <= 1:
            factor = 0
        else:
            factor = i / (display_length - 1)
            
        # Clamp factor to 1.0 in case text is longer than total_length (unlikely here)
        factor = min(1.0, factor)
        
        r = int(start_color[0] + (end_color[0] - start_color[0]) * factor)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * factor)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * factor)
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        rich_text.append(char, style=f"bold {hex_color}")
    return rich_text

def get_banner_renderable():
    # If the terminal height is small, return a single-line compact title to avoid overflow scrolling
    if console.size.height < 35:
        banner_text = Text("◆ ZINE SCRAPER ◆", style="bold menu")
        return banner_text

    banner_path = Path(__file__).parent.parent / "assets" / "banner.txt"
    banner = ""
    if banner_path.exists():
        try:
            with open(banner_path, "r", encoding="utf-8") as f:
                banner = f.read()
        except Exception:
            pass
            
    if not banner:
        banner = """███████╗██╗███╗   ██╗███████╗
╚══███╔╝██║████╗  ██║██╔════╝
  ███╔╝ ██║██╔██╗ ██║█████╗
 ███╔╝  ██║██║╚██╗██║██╔══╝
███████╗██║██║ ╚████║███████╗
╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝"""

    lines = banner.strip("\n").split("\n")
    try:
        entry = console._theme_stack._entries[-1]
        menu_style = entry.get("menu")
        sexy_pink_style = entry.get("sexy_pink")
        
        if menu_style and menu_style.color:
            start_color = menu_style.color.get_truecolor()
        else:
            start_color = (122, 162, 247)
            
        if sexy_pink_style and sexy_pink_style.color:
            end_color = sexy_pink_style.color.get_truecolor()
        else:
            end_color = (187, 154, 247)
    except Exception:
        start_color = (122, 162, 247)
        end_color = (187, 154, 247)

    max_len = max((len(line) for line in lines), default=0)
    
    banner_text = Text()
    for i, line in enumerate(lines):
        newline = "\n" if i < len(lines) - 1 else ""
        banner_text.append(make_gradient_text(line, start_color, end_color, total_length=max_len))
        banner_text.append(newline)
    return banner_text

def print_banner():
    console.print(get_banner_renderable())
    console.print("")

def startup_clear():
    # Erase visible screen + scrollback buffer so the terminal
    # cannot scroll up into invisible leftover content.
    import sys, os
    if os.name != 'nt':
        try:
            import termios
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            # Restore canonical mode and echo to recover from raw mode crashes
            attrs[3] = attrs[3] | termios.ICANON | termios.ECHO
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()
    console.clear()

_LIVE_INSTANCE = None

_REVOLT_ACTIVE = False
_REVOLT_LIMIT = 0
_REVOLT_TRIGGERING = False
_MENU_ACTIVE = False
_REVOLT_INPUT_BUFFER = ""

_tty_fd = None
_old_tty_settings = None

_INTERNET_DOWN = False
_internet_loss_lock = threading.Lock()
_connection_restored_event = threading.Event()
_connection_restored_event.set()

def get_key_nonblocking():
    import os
    if os.name == 'nt':
        try:
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    msvcrt.getch()
                    return ""
                return ch.decode('utf-8', errors='ignore')
        except Exception:
            return ""
        return ""
    
    global _tty_fd
    if _tty_fd is None:
        return ""
    import select
    try:
        # Use select to check for keyboard buffer inputs with a 50ms timeout
        r, _, _ = select.select([_tty_fd], [], [], 0.05)
        if r:
            ch = os.read(_tty_fd, 1).decode('utf-8', errors='ignore')
            return ch
        return ""
    except Exception:
        return ""


def read_tty_key(timeout: Optional[float] = None) -> str:
    """Read one terminal key in raw mode and normalize special keys."""
    if os.name == 'nt':
        try:
            import msvcrt, time
            deadline = time.time() + timeout if timeout is not None else None
            while True:
                if deadline is not None and time.time() > deadline:
                    return ""
                if not msvcrt.kbhit():
                    if timeout is None:
                        continue
                    time.sleep(0.01)
                    continue
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    ch2 = msvcrt.getch()
                    if ch2 == b'H': return 'UP'
                    if ch2 == b'P': return 'DOWN'
                    if ch2 == b'K': return 'LEFT'
                    if ch2 == b'M': return 'RIGHT'
                    return ''
                if ch in (b'\r', b'\n'): return 'ENTER'
                if ch in (b'\x7f', b'\x08'): return 'BACKSPACE'
                if ch == b'\t': return 'TAB'
                if ch == b'\x1b': return 'ESC'
                if ch == b'\x03': return 'CTRL_C'
                return ch.decode('utf-8', errors='ignore')
        except Exception:
            return ''

    fd = _tty_fd if _tty_fd is not None else sys.stdin.fileno()
    try:
        import tty, termios, select as _select
        close_after = False
        if _tty_fd is None:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setraw(fd)
            mode = termios.tcgetattr(fd)
            mode[3] = mode[3] | termios.ISIG
            mode[1] = mode[1] | termios.OPOST
            termios.tcsetattr(fd, termios.TCSADRAIN, mode)
            close_after = True
        try:
            if timeout is None:
                ready, _, _ = _select.select([fd], [], [])
            else:
                ready, _, _ = _select.select([fd], [], [], timeout)
            if not ready:
                return ''
            raw = os.read(fd, 1)
            if not raw:
                return ''
            ch = raw.decode('utf-8', errors='ignore')
            if ch == '\x1b':
                seq = ch
                for _ in range(2):
                    r, _, _ = _select.select([fd], [], [], 0.02)
                    if not r:
                        break
                    seq += os.read(fd, 1).decode('utf-8', errors='ignore')
                if seq in ('\x1b[A', '\x1bOA'):
                    return 'UP'
                if seq in ('\x1b[B', '\x1bOB'):
                    return 'DOWN'
                if seq in ('\x1b[C', '\x1bOC'):
                    return 'RIGHT'
                if seq in ('\x1b[D', '\x1bOD'):
                    return 'LEFT'
                if seq == '\x1b[H':
                    return 'HOME'
                if seq == '\x1b[F':
                    return 'END'
                return 'ESC'
            if ch in ('\r', '\n'):
                return 'ENTER'
            if ch in ('\x7f', '\x08'):
                return 'BACKSPACE'
            if ch == '\x03':
                return 'CTRL_C'
            if ch == '\x09':
                return 'TAB'
            return ch
        finally:
            if close_after:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    except Exception:
        return ''


def global_internet_monitor():
    import time
    global _LIVE_INSTANCE, _INTERNET_DOWN
    from butler.whistleblower import is_internet_restored
    while True:
        if _LIVE_INSTANCE is not None and not _INTERNET_DOWN:
            if not is_internet_restored():
                _INTERNET_DOWN = True
        time.sleep(2.0)


_monitor_thread = threading.Thread(target=global_internet_monitor, daemon=True)
_monitor_thread.start()

def global_revolt_listener():
    import time
    import sys
    global _LIVE_INSTANCE, _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_TRIGGERING, _MENU_ACTIVE, _REVOLT_INPUT_BUFFER
    while True:
        if _LIVE_INSTANCE is None or _MENU_ACTIVE:
            time.sleep(0.1)
            continue
            
        key = get_key_nonblocking()
        if not key:
            continue
            
        if not _REVOLT_TRIGGERING:
            if key == '\x12':  # Ctrl+R
                _REVOLT_TRIGGERING = True
                _REVOLT_INPUT_BUFFER = ""
        else:
            # We are in Revolt typing mode (inline inside Rich Live context)
            if key == '\x1b' or key == 'ESC':  # Escape key cancels Revolt prompt
                _REVOLT_TRIGGERING = False
                _REVOLT_INPUT_BUFFER = ""
            elif key in ('\r', '\n'):  # Enter key confirms
                val = _REVOLT_INPUT_BUFFER.strip()
                if val:  # Non-empty input activates Revolt limit
                    try:
                        limit = int(val)
                        if limit >= 0:
                            _REVOLT_ACTIVE = True
                            _REVOLT_LIMIT = limit
                    except ValueError:
                        pass
                else:  # Empty input cancels/backs out of Revolt mode
                    _REVOLT_TRIGGERING = False
                    _REVOLT_INPUT_BUFFER = ""
                _REVOLT_TRIGGERING = False
                _REVOLT_INPUT_BUFFER = ""
            elif key in ('\x7f', '\x08'):  # Backspace key deletes last character
                _REVOLT_INPUT_BUFFER = _REVOLT_INPUT_BUFFER[:-1]
            elif key.isdigit():  # Accept digits only
                _REVOLT_INPUT_BUFFER += key
                
        time.sleep(0.05)

_ctrl_r_thread = threading.Thread(target=global_revolt_listener, daemon=True)
_ctrl_r_thread.start()

def set_active_live(live):
    global _LIVE_INSTANCE, _tty_fd, _old_tty_settings
    _LIVE_INSTANCE = live
    if live is not None:
        # Enable custom raw mode (ISIG and OPOST preserved) once for the duration of the Live visualizer
        import os, termios
        try:
            _tty_fd = os.open('/dev/tty', os.O_RDONLY)
            _old_tty_settings = termios.tcgetattr(_tty_fd)
            
            mode = termios.tcgetattr(_tty_fd)
            mode[0] = mode[0] & ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
            mode[2] = mode[2] & ~(termios.CSIZE | termios.PARENB)
            mode[2] = mode[2] | termios.CS8
            mode[3] = mode[3] & ~(termios.ECHO | termios.ICANON | termios.IEXTEN)
            mode[3] = mode[3] | termios.ISIG
            termios.tcsetattr(_tty_fd, termios.TCSADRAIN, mode)
        except Exception:
            _tty_fd = None
            _old_tty_settings = None

        original_update = live.update
        def custom_update(renderable, refresh=False):
            global _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_TRIGGERING, _REVOLT_INPUT_BUFFER
            if _REVOLT_TRIGGERING or _REVOLT_ACTIVE:
                from rich.tree import Tree
                from rich.console import Group
                from rich.panel import Panel
                
                if _REVOLT_TRIGGERING:
                    revolt_msg = f"[unselected]How many more downloads? (0 = current only):[/unselected] [selected]{_REVOLT_INPUT_BUFFER}[/selected]█\n[unselected]Press Enter to confirm, ESC/Empty to cancel[/unselected]"
                else:
                    revolt_msg = f"[unselected]Shutting down after {_REVOLT_LIMIT} more file(s)[/unselected]" if _REVOLT_LIMIT > 0 else "[unselected]Shutting down after current file[/unselected]"
                
                if isinstance(renderable, Tree):
                    node = Tree("[unselected]◆ Revolt[/unselected]", guide_style="unselected")
                    for line in revolt_msg.split("\n"):
                        node.add(line)
                    renderable.children.insert(0, node)
                else:
                    revolt_panel = Panel(revolt_msg, border_style="warning", title="Revolt", title_align="left")
                    renderable = Group(revolt_panel, renderable)
            return original_update(renderable, refresh=refresh)
        live.update = custom_update
    else:
        # Restore termios configuration when Live visualizer finishes
        if _tty_fd is not None and _old_tty_settings is not None:
            import termios, os
            try:
                termios.tcsetattr(_tty_fd, termios.TCSADRAIN, _old_tty_settings)
                os.close(_tty_fd)
            except Exception:
                pass
            _tty_fd = None
            _old_tty_settings = None

import contextlib

@contextlib.contextmanager
def active_status(msg: str, spinner: str = "dots"):
    status = console.status(msg, spinner=spinner)
    with status:
        set_active_live(status._live)
        try:
            yield status
        finally:
            set_active_live(None)


def clean_exit(forceful: bool = False):
    logging.info(f"clean_exit triggered (forceful={forceful}).")
    
    # Unload any active TTS models in memory
    try:
        import urllib.request, json
        from core.settings_tui import config
        comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
        req = urllib.request.Request(f"{comfy_url}/free", data=json.dumps({"unload_models":True,"free_memory":True}).encode(), method='POST')
        urllib.request.urlopen(req, timeout=1.0)
    except Exception:
        pass
    global _LIVE_INSTANCE
    if _LIVE_INSTANCE:
        try:
            _LIVE_INSTANCE.stop()
        except:
            pass
        _LIVE_INSTANCE = None
        
    console.show_cursor(True)
             
    import sys, os
    if os.name != 'nt':
        try:
            import termios
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            # Restore canonical mode and echo to recover from raw mode crashes
            attrs[3] = attrs[3] | termios.ICANON | termios.ECHO
            attrs[1] = attrs[1] | termios.OPOST
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass
            
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()
    console.clear()
    
    # Load Art based on exit type
    try:
        root_dir = Path(__file__).parent.parent
        asset_file = "forcefully_stop.txt" if forceful else "exit.txt"
        art_path = root_dir / "assets" / asset_file
        
        if art_path.exists():
            with open(art_path, "r", encoding="utf-8") as f:
                exit_art = f.read()
        else:
            # Fallback if file missing
            exit_art = "[error]Exit art missing![/error]"
    except Exception as e:
        exit_art = f"[error]Error loading exit art: {e}[/error]"

    sys.stdout.write("\n")
    lines = exit_art.strip("\n").split("\n")
    
    # Calculate max length for uniform gradient alignment
    max_len = 0
    clean_lines = []
    text_parts = []
    
    for line in lines:
        # Separate the "Baka!" text from the art if it exists
        if "   𝑩𝒂𝒌𝒂!" in line:
            parts = line.split("   𝑩𝒂𝒌𝒂!", 1)
            art_part = parts[0]
            text_part = "   𝑩𝒂𝒌𝒂!" + parts[1]
        else:
            art_part = line
            text_part = ""
            
        max_len = max(max_len, len(art_part))
        clean_lines.append(art_part)
        text_parts.append(text_part)

    for i, art_line in enumerate(clean_lines):
        text_line = text_parts[i]
        if forceful:
             # Magenta to Deep Red gradient
             # Consistent max_len ensures vertical alignment of colors
             gradient_art = make_gradient_text(art_line, (187, 154, 247), (219, 75, 75), total_length=max_len)
             if text_line:
                 # Keep text in the "Hot" end color
                 full_line = gradient_art.append(text_line, style="bold #db4b4b")
                 console.print(gradient_art)
             else:
                 console.print(gradient_art)
        else:
             # Blue to Magenta gradient
             gradient_art = make_gradient_text(art_line, (122, 162, 247), (187, 154, 247), total_length=max_len)
             console.print(gradient_art)
    console.print("")
    sys.stdout.flush()
    sys.exit(0)

def signal_handler(sig, frame):
    logging.warning("SIGINT (Ctrl+C) received. Forcing clean_exit.")
    clean_exit(forceful=True)

signal.signal(signal.SIGINT, signal_handler)

class Selector:
    def __init__(self, options: List[Tuple[str, Any]], title: str = "Select", vertical: bool = False, align_width: int = 8):
        self.options = options
        self.title = title
        self.index = 0
        self.vertical = vertical
        self.align_width = align_width

    def _get_key(self):
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
                if ch in (b'\r', b'\n'):
                    return '\r'
                if ch == b'\x03':  # Ctrl+C
                    return '\x03'
                try:
                    return ch.decode('utf-8')
                except Exception:
                    return str(ch)
            except Exception:
                pass
        else:
            try:
                import tty, termios, select as _sel
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd, termios.TCSADRAIN)
                    mode = termios.tcgetattr(fd)
                    mode[3] = mode[3] | termios.ISIG
                    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                    ch_bytes = os.read(fd, 1)
                    if not ch_bytes:
                        return ""
                    ch = ch_bytes.decode('utf-8', errors='ignore')
                    if ch == '\x1b':
                        r2, _, _ = _sel.select([fd], [], [], 0.05)
                        if r2:
                            ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                            if ch2 in ('[', 'O'):
                                r3, _, _ = _sel.select([fd], [], [], 0.05)
                                if r3:
                                    ch3 = os.read(fd, 1).decode('utf-8', errors='ignore')
                                    return ch2 + ch3
                        return 'ESC'
                    return ch
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception as e:
                pass
        return ""

    def _get_key_timeout(self, timeout: float = 0.25) -> str:
        """Like _get_key but returns '' after `timeout` seconds with no input."""
        if os.name == 'nt':
            import time
            deadline = time.time() + timeout
            try:
                import msvcrt
                while time.time() < deadline:
                    if msvcrt.kbhit():
                        return self._get_key()
                    time.sleep(0.02)
            except Exception:
                pass
            return ''
        else:
            try:
                import tty, termios, select as _sel
                fd = os.open('/dev/tty', os.O_RDONLY)
                old = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd, termios.TCSADRAIN)
                    # Re-enable ISIG so Ctrl+C immediately generates keyboard interrupt signals
                    mode = termios.tcgetattr(fd)
                    mode[3] = mode[3] | termios.ISIG
                    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                    ready, _, _ = _sel.select([fd], [], [], timeout)
                    if not ready:
                        return ''
                    ch_bytes = os.read(fd, 1)
                    ch = ch_bytes.decode('utf-8', errors='ignore')
                    if ch == '\x1b':
                        r2, _, _ = _sel.select([fd], [], [], 0.05)
                        if r2:
                            ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                            if ch2 == 'O': ch2 = '['
                            ch3 = os.read(fd, 1).decode('utf-8', errors='ignore')
                            return ch2 + ch3
                        return 'ESC'
                    return ch
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    os.close(fd)
            except Exception:
                pass
            return ''

    def select_fallback(self) -> Any:
        console.print(f"[menu]{self.title}[/menu]")
        for i, (label, _) in enumerate(self.options, 1):
            console.print(f" {i}) {label}")
        while True:
            console.print(f"[menu]Enter choice (1-{len(self.options)}):[/menu]")
            console.print("[menu]❯ [/menu]", end="")
            sys.stdout.flush()
            try:
                val = input().strip()
                idx = int(val) - 1
                if 0 <= idx < len(self.options):
                    return self.options[idx][1]
            except Exception:
                pass
            console.print("[error]● Invalid selection. Please try again.[/error]")

    def select(self) -> Any:
        if 'unittest' in sys.modules or not sys.stdin.isatty():
            return self.select_fallback()
        global _LIVE_INSTANCE, _MENU_ACTIVE
        old_menu_active = _MENU_ACTIVE
        _MENU_ACTIVE = True
        console.show_cursor(False)
        try:
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                _LIVE_INSTANCE = live
                live.update(self._render(), refresh=True)
                while True:
                    key = self._get_key()
                    if not key:
                        try:
                            from core.paths import PathAuthority
                            error_log = PathAuthority().get_logs_root() / "💩" / "error.log"
                            error_log.parent.mkdir(parents=True, exist_ok=True)
                            with open(error_log, "a") as f:
                                f.write("Selector.select: _get_key returned empty key\n")
                                f.write(f"sys.stdin: {sys.stdin}, isatty: {sys.stdin.isatty()}\n")
                        except Exception:
                            pass
                        return self.select_fallback()
                    if key in ('[D', 'OD') or key in ('[A', 'OA'):
                        self.index = (self.index - 1) % len(self.options)
                        live.update(self._render(), refresh=True)
                    elif key in ('[C', 'OC') or key in ('[B', 'OB'):
                        self.index = (self.index + 1) % len(self.options)
                        live.update(self._render(), refresh=True)
                    elif key in ('\r', '\n'):
                        return self.options[self.index][1]
                    elif key == '=':
                        return "="
                    elif key == 'ESC':
                        return "ESC"
                    elif key == '\x03':
                        clean_exit(forceful=True)
        except Exception as e:
            try:
                import traceback
                from core.paths import PathAuthority
                error_log = PathAuthority().get_logs_root() / "💩" / "error.log"
                error_log.parent.mkdir(parents=True, exist_ok=True)
                with open(error_log, "a") as f:
                    f.write("=== Exception in Selector.select ===\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            return self.select_fallback()
        finally:
            _LIVE_INSTANCE = None
            console.show_cursor(True)
            _MENU_ACTIVE = old_menu_active

    def _render(self) -> Text:
        full_text = Text()
        if self.vertical:
            title_prefix = f"{self.title:<{self.align_width}}: \n"
            full_text.append(title_prefix, style="menu")
            indent = " " * (self.align_width + 2)
            for i, (label, _) in enumerate(self.options):
                is_last = (i == len(self.options) - 1)
                newline = "" if is_last else "\n"
                
                full_text.append(indent, style="unselected")
                if i == self.index:
                    full_text.append(f"> {label}{newline}", style="selected")
                else:
                    full_text.append(f"  {label}{newline}", style="unselected")
        else:
            title_prefix = f"{self.title:<{self.align_width}}: "
            full_text.append(title_prefix, style="menu")
            for i, (label, _) in enumerate(self.options):
                if i == self.index:
                    full_text.append(f"> {label} ", style="selected")
                else:
                    full_text.append(f"  {label} ", style="unselected")
        return full_text

class MinimalPulseBar(ProgressColumn):
    def __init__(self, bar_width: int = 40):
        super().__init__()
        self.bar_width = bar_width

    def render(self, task) -> Text:
        bar = Text()
        if task.total is not None and task.total > 0:
            ratio = min(1.0, max(0.0, task.completed / task.total))
            completed_chars = int(self.bar_width * ratio)
            remaining_chars = self.bar_width - completed_chars
            
            if task.finished:
                bar.append("━" * completed_chars, style="bold success")
            else:
                bar.append("━" * completed_chars, style="bold sexy_pink")
            bar.append("━" * remaining_chars, style="unselected")
        else:
            import time
            speed = 15
            tick = int(time.time() * speed)
            block_width = 4
            pos = tick % (self.bar_width + block_width) - block_width
            
            for i in range(self.bar_width):
                if pos <= i < pos + block_width:
                    bar.append("━", style="bold sexy_pink")
                else:
                    bar.append("━", style="unselected")
        return bar

def align_header(label: str, value: Any) -> str:
    return f"{label:<18} : {value}"

class MultiSelector:
    """A multi-selector for file assets (like yazi/nnn) with scrolling support."""
    def __init__(self, options: List[dict], title: str = "Select Files"):
        self.options = options
        self.title = title
        self.index = 0
        self.selected = set()
        self.offset = 0
        self.page_size = 15 # Number of items to show at once

    def _get_key(self):
        if os.name == 'nt':
            try:
                import msvcrt
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    ch2 = msvcrt.getch()
                    if ch2 == b'H':  # Up
                        return '[A'
                    elif ch2 == b'P':  # Down
                        return '[B'
                if ch in (b'\r', b'\n'):
                    return '\r'
                if ch == b' ':
                    return ' '
                if ch == b'\x03':  # Ctrl+C
                    return '\x03'
                try:
                    return ch.decode('utf-8')
                except Exception:
                    return str(ch)
            except Exception:
                pass
        else:
            try:
                import tty
                import termios
                fd = sys.stdin.fileno()
                old_settings = termios.tcgetattr(fd)
                try:
                    tty.setraw(fd, termios.TCSADRAIN)
                    # Re-enable ISIG so Ctrl+C immediately generates keyboard interrupt signals
                    mode = termios.tcgetattr(fd)
                    mode[3] = mode[3] | termios.ISIG
                    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                    ch = sys.stdin.read(1)
                    if ch == '\x1b':
                        ch2 = sys.stdin.read(1)
                        if ch2 == 'O': ch2 = '['
                        ch3 = sys.stdin.read(1)
                        return ch2 + ch3
                    return ch
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass

    def select(self) -> List[dict]:
        global _LIVE_INSTANCE, _MENU_ACTIVE
        old_menu_active = _MENU_ACTIVE
        _MENU_ACTIVE = True
        console.show_cursor(False)
        try:
            with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                _LIVE_INSTANCE = live
                while True:
                    live.update(self._render(), refresh=True)
                    key = self._get_key()

                    if key in ('[A', 'OA'): # Up
                        self.index = (self.index - 1) % len(self.options)
                    elif key in ('[B', 'OB'): # Down
                        self.index = (self.index + 1) % len(self.options)
                    elif key == ' ': # Space to toggle
                        if self.index in self.selected:
                            self.selected.remove(self.index)
                        else:
                            self.selected.add(self.index)
                    elif key in ('\r', '\n'): # Enter to confirm
                        if not self.selected:
                            return [self.options[self.index]]
                        return [self.options[i] for i in sorted(self.selected)]
                    elif key == '\x03': # Ctrl+C
                        clean_exit(forceful=True)

                    # Adjust offset for scrolling
                    if self.index < self.offset:
                        self.offset = self.index
                    elif self.index >= self.offset + self.page_size:
                        self.offset = self.index - self.page_size + 1

        finally:
            _LIVE_INSTANCE = None
            console.show_cursor(True)
            _MENU_ACTIVE = old_menu_active

    def _render(self) -> Text:
        full_text = Text()
        full_text.append(f"{self.title} (Space to select, Enter to confirm):\n", style="menu")
        
        # Show scroll indicators
        if self.offset > 0:
            full_text.append(f"  ↑ ... {self.offset} more items ...\n", style="warning")
        else:
            full_text.append("\n")

        visible_options = self.options[self.offset : self.offset + self.page_size]
        for i_visible, opt in enumerate(visible_options):
            i = i_visible + self.offset
            is_hovered = (i == self.index)
            is_selected = (i in self.selected)
            if opt.get("is_action"):
                checkbox = "   "
            else:
                checkbox = "[x]" if is_selected else "[ ]"
            pointer = ">" if is_hovered else " "
            
            style = "selected" if is_hovered else ("success" if is_selected else "unselected")
            
            name = opt.get("name", "Unknown")
            desc = opt.get("desc", "")
            
            if "right_text" in opt:
                right_label = opt["right_text"]
            else:
                right_label = format_bytes(opt.get("size_bytes", 0))
            
            # Calculate display width accounting for East Asian wide characters
            import unicodedata
            def get_display_width(text):
                return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
            
            display_name = f"{name} ({desc})" if desc else name
            
            # Pad or truncate based on display width
            if get_display_width(display_name) > 48:
                # Truncate
                current_width = 0
                truncated = ""
                for char in display_name:
                    char_width = 2 if unicodedata.east_asian_width(char) in 'WF' else 1
                    if current_width + char_width > 45:
                        break
                    truncated += char
                    current_width += char_width
                name_padded = truncated + "..."
                name_padded += " " * (48 - get_display_width(name_padded))
            else:
                name_padded = display_name + " " * (48 - get_display_width(display_name))
            if right_label:
                full_text.append(f"{pointer} {checkbox} {name_padded} | {right_label:>15}\n", style=style)
            else:
                full_text.append(f"{pointer} {checkbox} {name_padded}\n", style=style)
        
        # Bottom scroll indicator
        remaining = len(self.options) - (self.offset + self.page_size)
        if remaining > 0:
            full_text.append(f"  ↓ ... {remaining} more items ...\n", style="warning")
        else:
            full_text.append("\n")
            
        return full_text

def format_bytes(size_bytes: int) -> str:
    if not size_bytes: return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return "Unknown"

def get_theme_input_ansi() -> str:
    """Returns the ANSI escape sequence for the active theme's 'selected' style color."""
    import theme
    return theme.get_theme_input_ansi(console)

def clean_user_input(raw: str) -> str:
    """Strips raw ANSI escape sequences, arrow key artifacts (^[[D, ^[[C), and ESC signals."""
    if not raw:
        return ""
    if raw.startswith('\x1b') and len(raw.strip('\x1b')) == 0:
        return ""
    cleaned = re.sub(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', raw)
    return cleaned.strip()

def theme_input(prompt_msg: str = "") -> str:
    """Prompts the user with Readline editing support and themed ANSI color formatting."""
    if prompt_msg:
        console.print(prompt_msg, end="")
    sys.stdout.write(get_theme_input_ansi())
    sys.stdout.flush()
    try:
        raw = input()
    except (EOFError, KeyboardInterrupt):
        return ""
    finally:
        sys.stdout.write("\033[0m")
        sys.stdout.flush()
    return clean_user_input(raw)

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
    if not chunk_bytes:
        return ("NONE", None)

    if b"\x03" in chunk_bytes:
        return ("CTRL_C", None)

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

    up_patterns = ["\x1b[A", "\x1bOA", "[A", "OA"]
    if any(clean_str == p or clean_str.startswith(p) for p in up_patterns):
        return ("UP", None)

    down_patterns = ["\x1b[B", "\x1bOB", "[B", "OB"]
    if any(clean_str == p or clean_str.startswith(p) for p in down_patterns):
        return ("DOWN", None)

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


def raw_prompt_input(prompt_title: str, hint: str = "", default_val: str = "") -> Optional[str]:
    """
    Universal Raw-TTY Interactive Input Prompt with Rich Panel & Live Rendering.
    - Zero escape sequence leaks (^[[D, ^[[C, ^[ are intercepted instantly).
    - Full Left/Right arrow cursor movement, Home, End, Backspace, Delete, Paste.
    - ESC or Ctrl+C immediately cancels and returns None.
    """
    if not sys.stdin.isatty():
        try:
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            return None

    buffer = str(default_val)
    cursor_pos = len(buffer)

    from rich.panel import Panel
    from rich.table import Table

    def _build_panel() -> Panel:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("content", width=74)

        if hint:
            table.add_row(Text(hint, style="unselected"))

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

        footer = Text(justify="center")
        footer.append("Enter", style="bold white");     footer.append(" Submit   ", style="unselected")
        footer.append("Esc", style="bold white");       footer.append(" Cancel   ", style="unselected")
        footer.append("Backspace", style="bold white"); footer.append(" Delete", style="unselected")

        return Panel(
            table,
            title=f"[bold white]◆ {prompt_title.upper()} ◆[/bold white]",
            subtitle=footer,
            subtitle_align="center",
            border_style="sexy_pink",
            padding=(1, 2),
            width=80,
        )

    if os.name != "nt":
        import tty, termios
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            termios.tcflush(fd, termios.TCIFLUSH)
            tty.setcbreak(fd)
        except Exception:
            try:
                val = input(f"{prompt_title}: ")
                return val.strip() if val.strip() else None
            except (EOFError, KeyboardInterrupt):
                return None

        try:
            with Live(_build_panel(), console=console, auto_refresh=False, transient=True) as live:
                set_active_live(live)
                live.update(_build_panel(), refresh=True)
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
                            live.update(_build_panel(), refresh=True)

                    elif action == "DELETE":
                        if cursor_pos < len(buffer):
                            buffer = buffer[:cursor_pos] + buffer[cursor_pos + 1:]
                            live.update(_build_panel(), refresh=True)

                    elif action == "LEFT":
                        if cursor_pos > 0:
                            cursor_pos -= 1
                            live.update(_build_panel(), refresh=True)

                    elif action == "RIGHT":
                        if cursor_pos < len(buffer):
                            cursor_pos += 1
                            live.update(_build_panel(), refresh=True)

                    elif action == "HOME":
                        cursor_pos = 0
                        live.update(_build_panel(), refresh=True)

                    elif action == "END":
                        cursor_pos = len(buffer)
                        live.update(_build_panel(), refresh=True)

                    elif action == "CLEAR_LINE":
                        buffer = buffer[cursor_pos:]
                        cursor_pos = 0
                        live.update(_build_panel(), refresh=True)

                    elif action == "DELETE_WORD":
                        before = buffer[:cursor_pos].rstrip()
                        idx = max(before.rfind("/"), before.rfind(" "), before.rfind("\\"))
                        idx = 0 if idx == -1 else idx
                        buffer = buffer[:idx] + buffer[cursor_pos:]
                        cursor_pos = idx
                        live.update(_build_panel(), refresh=True)

                    elif action == "TEXT" and payload:
                        buffer = buffer[:cursor_pos] + payload + buffer[cursor_pos:]
                        cursor_pos += len(payload)
                        live.update(_build_panel(), refresh=True)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            set_active_live(None)
    else:
        try:
            val = input(f"{prompt_title}: ")
            return val.strip() if val.strip() else None
        except (EOFError, KeyboardInterrupt):
            return None


def format_chapter_ranges(chapters: List[str]) -> str:
    """Consolidates chapter numbers into ranges for cleaner logging (e.g., 1-50, 52)."""
    if not chapters:
        return ""
    
    numeric = []
    others = []
    for c in chapters:
        try:
            numeric.append(float(c))
        except ValueError:
            others.append(c)
    
    numeric.sort()
    ranges = []
    
    if numeric:
        start = numeric[0]
        end = numeric[0]
        
        def to_str(val):
            return str(int(val)) if val == int(val) else str(val)

        for i in range(1, len(numeric)):
            if numeric[i] == end + 1:
                end = numeric[i]
            else:
                if start == end:
                    ranges.append(to_str(start))
                else:
                    ranges.append(f"{to_str(start)}-{to_str(end)}")
                start = numeric[i]
                end = numeric[i]
        
        if start == end:
            ranges.append(to_str(start))
        else:
            ranges.append(f"{to_str(start)}-{to_str(end)}")
            
    return ", ".join(ranges + others)

def format_video_ranges(ids: List[str]) -> str:
    if not ids: return "None"
    return f"{len(ids)} videos"

def clear_lines(num_lines: int):
    import sys
    for _ in range(num_lines):
        sys.stdout.write("\033[1A\033[2K")
    sys.stdout.flush()

def get_batch_save_path(store_layer) -> Optional[Path]:
    """Helper to get batch mode save location (Default or Custom)."""
    from core.paths import PathAuthority
    import json
    import time
    paths = PathAuthority()
    library_root = paths.get_downloads_root()
    
    # Read download_base from settings.json directly to avoid circular imports
    config_file = paths.get_config_file()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_base = data.get("download_base")
                if custom_base:
                    library_root = Path(custom_base)
        except Exception:
            pass
            
    default_batch = library_root / "Batch"
    
    while True:
        if not sys.stdin.isatty():
            loc_choice = "DEFAULT"
        else:
            loc_choice = Selector([
                ("Use Default Batch Location (Batch)", "DEFAULT"),
                ("Select Custom Location", "CUSTOM"),
                ("Back", "BACK")
            ], "Save Location").select()
        if loc_choice == "BACK":
            return None
        
        if loc_choice == "DEFAULT":
            return default_batch
        elif loc_choice == "CUSTOM":
            while True:
                console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
                sys.stdout.write(get_theme_input_ansi())
                sys.stdout.flush()
                custom_path_str = input().strip()
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                if not custom_path_str:
                    clear_lines(2)
                    break
                
                is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
                if not is_valid:
                    console.print(f"\n[error]Invalid directory.[/error]")
                    console.print(f"[warning]Reason:\n{err_msg}[/warning]")
                    time.sleep(2)
                    clear_lines(6)
                    continue
                
                clear_lines(2)
                return Path(custom_path_str)
            continue

def get_video_save_path(title: str, store_layer) -> Optional[Path]:
    """Helper to get non-YouTube video/music save location (Default or Custom)."""
    from core.paths import PathAuthority
    import json
    import time
    paths = PathAuthority()
    library_root = paths.get_downloads_root()
    
    # Read download_base from settings.json directly to avoid circular imports
    config_file = paths.get_config_file()
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                custom_base = data.get("download_base")
                if custom_base:
                    library_root = Path(custom_base)
        except Exception:
            pass
            
    video_save_root = library_root / "video"
    
    while True:
        loc_choice = Selector([
            ("Use Default Location", "DEFAULT"),
            ("Select Custom Location", "CUSTOM"),
            ("Back", "BACK")
        ], "Save Location").select()
        if loc_choice == "BACK": return None
        
        if loc_choice == "DEFAULT":
            return video_save_root
        elif loc_choice == "CUSTOM":
            while True:
                console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
                sys.stdout.write(get_theme_input_ansi())
                sys.stdout.flush()
                custom_path_str = input().strip()
                sys.stdout.write("\033[0m")
                sys.stdout.flush()
                if not custom_path_str:
                    clear_lines(2)
                    break
                
                is_valid, err_msg = store_layer.validate_directory(Path(custom_path_str))
                if not is_valid:
                    console.print(f"\n[error]Invalid directory.[/error]")
                    console.print(f"[warning]Reason:\n{err_msg}[/warning]")
                    time.sleep(2)
                    clear_lines(6)
                    continue
                clear_lines(2)
                return Path(custom_path_str)
            continue

def get_toon_save_path(url: str, scraper: Any, is_batch: bool, batch_path: Optional[Path], default_root: Path, store_layer: Any) -> Optional[Path]:
    if batch_path is not None:
        return batch_path

    library_root = default_root.parent
    site_folder = default_root.name

    if is_batch:
        return library_root / "Toon" / "SFW" / "OnGoing" / site_folder

    current_menu = library_root.name
    
    if getattr(scraper, "title", None):
        toon_name = scraper.title
    else:
        url_parts = [p for p in url.strip('/').split('/') if p]
        if "chapter" not in url.lower() and "-ch-" not in url.lower():
            toon_name = url_parts[-1] if url_parts else "unknown"
        else:
            toon_name = url_parts[-2] if len(url_parts) > 1 else url_parts[-1]
    
    def draw_header():
        startup_clear()
        print_banner()
        console.print(f"[menu]{'Menu':<12}:[/menu] [site]{current_menu}[/site]", overflow="ellipsis", no_wrap=True)
        console.print(f"[menu]{'URL':<12}:[/menu] [site]{url}[/site]", overflow="ellipsis", no_wrap=True)
        console.print(f"[menu]{'Toon':<12}:[/menu] [title]{toon_name}[/title]", overflow="ellipsis", no_wrap=True)
        console.print("")

    state = 0
    type_choice = None
    status_choice = None
    
    while True:
        if state == 0:
            draw_header()
            choice = Selector([("SFW", "SFW"), ("NSFW", "NSFW"), ("Back", "BACK")], "Type").select()
            if choice == "BACK":
                return None
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            type_choice = choice
            state = 1
        elif state == 1:
            draw_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
            choice = Selector([("Ongoing", "OnGoing"), ("Complete", "Completed"), ("Back", "BACK")], "Status").select()
            if choice == "BACK":
                state = 0
                continue
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            status_choice = choice
            state = 2
        elif state == 2:
            draw_header()
            console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
            console.print(f"[menu]{'Status':<12}:[/menu] [site]{status_choice}[/site]")
            choice = Selector([
                ("Use Default Location", "DEFAULT"),
                ("Select Custom Location", "CUSTOM"),
                ("Back", "BACK")
            ], "Save Location").select()
            if choice == "BACK":
                state = 1
                continue
            if choice == "=":
                current_menu = "Quick grab" if current_menu == "Vacuum" else "Vacuum"
                library_root = library_root.parent / current_menu
                continue
            elif choice == "DEFAULT":
                # Clear options to prevent them from staying on screen
                draw_header()
                console.print(f"[menu]{'Type':<12}:[/menu] [site]{type_choice}[/site]")
                console.print(f"[menu]{'Status':<12}:[/menu] [site]{status_choice}[/site]")
                console.print(f"[menu]{'Location':<12}:[/menu] [site]Default[/site]\n")
                return library_root / "Toon" / type_choice / status_choice / site_folder
            elif choice == "CUSTOM":
                state = 3
        elif state == 3:
            console.print("\n[menu]Enter Folder Path (Empty to cancel): [/menu]", end="")
            sys.stdout.write(get_theme_input_ansi())
            sys.stdout.flush()
            custom_path_str = input().strip()
            sys.stdout.write("\033[0m")
            sys.stdout.flush()
            if not custom_path_str:
                clear_lines(2)
                state = 2
                continue
            
            custom_path = Path(custom_path_str)
            is_valid, err_msg = store_layer.validate_directory(custom_path)
            if not is_valid:
                console.print(f"\n[error]Invalid directory.[/error]")
                console.print(f"[warning]Reason:\n{err_msg}[/warning]")
                time.sleep(2)
                clear_lines(6)
                continue
            
            try:
                custom_manhua_root = custom_path / "Toon"
                store_layer.create_directory(custom_manhua_root)
                final_path = store_layer.create_directory(custom_manhua_root / type_choice)
                clear_lines(2)
                return final_path
            except Exception as e:
                console.print(f"\n[error]Error creating directory: {e}[/error]")
                time.sleep(2)
                clear_lines(4)
                continue

# Global monkey-patch for requests to handle connection losses instantly
try:
    import requests
    original_session_request = requests.Session.request
    
    def custom_session_request(self, method, url, *args, **kwargs):
        global _INTERNET_DOWN
        if _INTERNET_DOWN:
            from core.video_engine import handle_internet_loss
            handle_internet_loss()
            
        while True:
            try:
                return original_session_request(self, method, url, *args, **kwargs)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                from butler.whistleblower import is_internet_restored
                if not is_internet_restored():
                    _INTERNET_DOWN = True
                    from core.video_engine import handle_internet_loss
                    if handle_internet_loss():
                        continue
                raise
                
    requests.Session.request = custom_session_request
except ImportError:
    pass



def filter_subchapters(url: str, title: str, chapters: List[Tuple[str, str]], is_batch: bool = False) -> List[Tuple[str, str]]:
    has_subchapters = False
    for ch_str, _ in chapters:
        try:
            val = float(ch_str)
            if val != int(val):
                has_subchapters = True
                break
        except Exception:
            pass

    if not has_subchapters:
        return chapters

    import sys
    if is_batch or not sys.stdin.isatty():
        return chapters

    startup_clear()
    print_banner()
    if is_batch:
        console.print("[menu]Menu[/menu]         : [site]Batch Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    console.print(f"[menu]Title[/menu]        : [title]{title}[/title]")
    console.print("")
    console.print("[warning]Found subchapters (e.g. 5.1, 6.5) in the chapter list![/warning]")
    console.print("")
    ans = Selector(
        [("Yes, download subchapters", True), ("No, skip them", False)],
        title="Download subchapters as well?",
        vertical=True,
        align_width=29
    ).select()
    
    if ans:
        return chapters

    new_chapters = []
    for ch_str, link in chapters:
        try:
            val = float(ch_str)
            if val == int(val):
                new_chapters.append((ch_str, link))
        except Exception:
            new_chapters.append((ch_str, link))
            
    return new_chapters

def clean_exit_revolt():
    """Used to exit after the Revolt limit is reached. Performs a clean, silent exit without ASCII art."""
    global _LIVE_INSTANCE
    if _LIVE_INSTANCE is not None:
        try:
            _LIVE_INSTANCE.stop()
            _LIVE_INSTANCE = None
        except Exception:
            pass
    # Show cursor
    print("\033[?25h", end="")
    sys.stdout.flush()
    import os
    os._exit(0)
