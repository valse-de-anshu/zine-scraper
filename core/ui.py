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

_CURRENT_THEME_NAME: str = "tokyo-night-storm"

def apply_theme(theme_name: str):
    global _CURRENT_THEME_NAME
    _CURRENT_THEME_NAME = theme_name
    import theme
    theme.apply_theme(console, theme_name)

def get_exit_art_colors(forceful: bool = False) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], str]:
    """
    Dynamically resolves start color, end color, and text style from the active theme
    for rendering exit art (exit.txt and forcefully_stop.txt).
    
    Returns:
        (start_color_rgb, end_color_rgb, text_style_str)
    """
    entry = None
    try:
        entry = console._theme_stack._entries[-1]
    except Exception:
        pass

    theme_dict = THEMES.get(_CURRENT_THEME_NAME, THEMES["tokyo-night-storm"])

    def _get_rgb(key: str, fallback_key: Optional[str] = None, default_rgb: Tuple[int, int, int] = (187, 154, 247)) -> Tuple[int, int, int]:
        for k in (key, fallback_key):
            if not k:
                continue
            try:
                if entry and k in entry:
                    st = entry[k]
                    if st and hasattr(st, "color") and st.color:
                        return st.color.get_truecolor()
                if theme_dict and k in theme_dict:
                    st = Style.parse(theme_dict[k]) if isinstance(theme_dict[k], str) else theme_dict[k]
                    if st and st.color:
                        return st.color.get_truecolor()
            except Exception:
                pass
        return default_rgb

    if forceful:
        # Forceful exit (forcefully_stop.txt): warning/sexy_pink -> error
        end_color = _get_rgb("error", default_rgb=(219, 75, 75))
        start_color = _get_rgb("sexy_pink", fallback_key="warning", default_rgb=(187, 154, 247))
        if start_color == end_color:
            start_color = _get_rgb("warning", fallback_key="selected", default_rgb=(224, 175, 104))
            if start_color == end_color:
                start_color = _get_rgb("menu", default_rgb=(122, 162, 247))
        text_style = f"bold #{end_color[0]:02x}{end_color[1]:02x}{end_color[2]:02x}"
        return start_color, end_color, text_style
    else:
        # Normal exit (exit.txt): menu/info -> sexy_pink/selected
        start_color = _get_rgb("menu", fallback_key="info", default_rgb=(122, 162, 247))
        end_color = _get_rgb("sexy_pink", fallback_key="selected", default_rgb=(187, 154, 247))
        if start_color == end_color:
            end_color = _get_rgb("selected", fallback_key="title", default_rgb=(187, 154, 247))
            if start_color == end_color:
                end_color = _get_rgb("title", default_rgb=(200, 200, 200))
        text_style = f"bold #{end_color[0]:02x}{end_color[1]:02x}{end_color[2]:02x}"
        return start_color, end_color, text_style

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
_REVOLT_TRIGGERED_DURING_ITEM = False
_REVOLT_CURRENT_DONE = False
_REVOLT_EXIT_LOCK = threading.Lock()
_REVOLT_EXITING = False

_TRUNCATE_ACTIVE = False
_TRUNCATE_LIMIT = 0
_TRUNCATE_TRIGGERING = False
_TRUNCATE_INPUT_BUFFER = ""
_TRUNCATE_TRIGGERED_DURING_ITEM = False
_TRUNCATE_CURRENT_DONE = False

_tty_fd = None
_old_tty_settings = None
_is_custom_tty_fd = False

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

class TruncateStopException(Exception):
    """Raised when Ctrl+T early stop limit is reached to gracefully break out of scraping loops."""
    pass

def inject_revolt_into_renderable(renderable):
    global _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_TRIGGERING, _REVOLT_INPUT_BUFFER
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_TRIGGERING, _TRUNCATE_INPUT_BUFFER
    from rich.tree import Tree
    from rich.console import Group
    from rich.panel import Panel

    has_revolt = (_REVOLT_TRIGGERING or _REVOLT_ACTIVE)
    has_truncate = (_TRUNCATE_TRIGGERING or _TRUNCATE_ACTIVE)

    if not (has_revolt or has_truncate):
        if isinstance(renderable, Tree) and renderable.children:
            renderable.children = [c for c in renderable.children if not getattr(c, "_is_revolt_node", False)]
        return renderable

    if has_truncate:
        tag_title = "[sexy_pink]◆ Stop Early (Ctrl+T)[/sexy_pink]"
        panel_title = "[sexy_pink]Stop Early (Ctrl+T)[/sexy_pink]"
        if _TRUNCATE_TRIGGERING:
            msg = (
                f"[unselected]How many more downloads? (0 = current only):[/unselected] [selected]{_TRUNCATE_INPUT_BUFFER}[/selected]█\n"
                f"[unselected]Press Enter to confirm, ESC/Empty to cancel[/unselected]"
            )
        else:
            msg = (
                f"[warning]Stopping after {_TRUNCATE_LIMIT} more file(s) and wrapping up...[/warning]"
                if _TRUNCATE_LIMIT > 0
                else "[warning]Stopping after current file and wrapping up...[/warning]"
            )
    else:
        tag_title = "[sexy_pink]◆ Revolt (Ctrl+R)[/sexy_pink]"
        panel_title = "[sexy_pink]Revolt (Ctrl+R)[/sexy_pink]"
        if _REVOLT_TRIGGERING:
            msg = (
                f"[unselected]How many more downloads? (0 = current only):[/unselected] [selected]{_REVOLT_INPUT_BUFFER}[/selected]█\n"
                f"[unselected]Press Enter to confirm, ESC/Empty to cancel[/unselected]"
            )
        else:
            msg = (
                f"[warning]Shutting down after {_REVOLT_LIMIT} more file(s)[/warning]"
                if _REVOLT_LIMIT > 0
                else "[warning]Shutting down after current file[/warning]"
            )

    if isinstance(renderable, Tree):
        node = Tree(tag_title, guide_style="unselected")
        node._is_revolt_node = True
        for line in msg.split("\n"):
            node.add(line)
        if renderable.children and getattr(renderable.children[0], "_is_revolt_node", False):
            renderable.children[0] = node
        else:
            renderable.children.insert(0, node)
        return renderable
    else:
        panel = Panel(msg, border_style="warning", title=panel_title, title_align="left")
        return Group(panel, renderable)

def trigger_revolt_exit(title: Optional[str] = None):
    global _REVOLT_EXITING, _LIVE_INSTANCE, _REVOLT_TRIGGERED
    _REVOLT_TRIGGERED = True
    with _REVOLT_EXIT_LOCK:
        if _REVOLT_EXITING:
            return
        _REVOLT_EXITING = True

    if _LIVE_INSTANCE:
        try:
            _LIVE_INSTANCE.stop()
        except Exception:
            pass
        _LIVE_INSTANCE = None

    console.show_cursor(True)
    import sys, os
    sys.stdout.write("\033[?25h\033[0m\n")
    sys.stdout.flush()
    if os.name != 'nt':
        try:
            import termios
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[3] = attrs[3] | termios.ICANON | termios.ECHO
            attrs[1] = attrs[1] | termios.OPOST
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass
    console.print("\n[warning]● Revolt shutdown triggered (Ctrl+R). Exiting cleanly...[/warning]\n")
    sys.stdout.flush()

    # Flush session telemetry and history before exit
    try:
        from core.journal import DownloadJournal
        journal = DownloadJournal.get_active()
        if journal.current_download:
            journal.finish_download(journal.current_download.get("url") or "", status="completed")
        journal.finish_session()
    except Exception:
        pass

    # Dispatch OS notification for Revolt completion
    try:
        from butler.notify import send_os_notification
        msg = f"Finished downloads for {title} and stopped cleanly." if title else "Revolt limit reached. Downloads stopped cleanly."
        send_os_notification("Zine Scraper — Revolt", msg, is_success=True)
    except Exception:
        pass

    try:
        from core.history import BatchHistoryManager
        if BatchHistoryManager._instance:
            BatchHistoryManager._instance.flush()
    except Exception:
        pass
    os._exit(0)

_TRUNCATE_TRIGGERED: bool = False
_REVOLT_TRIGGERED: bool = False

def trigger_truncate_stop(title: Optional[str] = None):
    """Gracefully ends current scrape item loop after user-requested limit without terminating process."""
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_CURRENT_DONE, _LIVE_INSTANCE, _TRUNCATE_TRIGGERED
    _TRUNCATE_TRIGGERED = True
    _TRUNCATE_ACTIVE = False
    _TRUNCATE_LIMIT = 0
    _TRUNCATE_CURRENT_DONE = False

    if _LIVE_INSTANCE:
        try:
            _LIVE_INSTANCE.stop()
        except Exception:
            pass
        _LIVE_INSTANCE = None

    console.show_cursor(True)
    import sys, os
    sys.stdout.write("\033[?25h\033[0m\n")
    sys.stdout.flush()
    if os.name != 'nt':
        try:
            import termios
            fd = sys.stdin.fileno()
            attrs = termios.tcgetattr(fd)
            attrs[3] = attrs[3] | termios.ICANON | termios.ECHO
            attrs[1] = attrs[1] | termios.OPOST
            termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        except Exception:
            pass

    target_name = f" for [title]{title}[/title]" if title else ""
    console.print(f"\n[warning]● Stop limit reached (Ctrl+T). Wrapping up{target_name}...[/warning]")
    console.print("[success]✦ All done! Requested files saved.[/success]\n")
    sys.stdout.flush()

    # Flush telemetry
    try:
        from core.journal import DownloadJournal
        journal = DownloadJournal.get_active()
        if journal.current_download:
            journal.finish_download(journal.current_download.get("url") or "", status="completed")
    except Exception:
        pass

    try:
        from butler.notify import send_os_notification
        msg = f"Completed requested downloads for {title} and stopped." if title else "Downloads stopped cleanly via Ctrl+T."
        send_os_notification("Zine Scraper — All Done", msg, is_success=True)
    except Exception:
        pass

    try:
        from core.history import BatchHistoryManager
        if BatchHistoryManager._instance:
            BatchHistoryManager._instance.flush()
    except Exception:
        pass

    raise TruncateStopException(f"Scrape truncated early via Ctrl+T for {title or 'current item'}")

def check_revolt(title: Optional[str] = None) -> bool:
    """Check if Revolt or Truncate mode is active and limit reached."""
    global _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_CURRENT_DONE
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_CURRENT_DONE
    if _REVOLT_ACTIVE and _REVOLT_CURRENT_DONE and _REVOLT_LIMIT <= 0:
        trigger_revolt_exit(title=title)
        return True
    if _TRUNCATE_ACTIVE and _TRUNCATE_CURRENT_DONE and _TRUNCATE_LIMIT <= 0:
        trigger_truncate_stop(title=title)
        return True
    return False

def check_truncate(title: Optional[str] = None) -> bool:
    """Explicit check for Ctrl+T early stop."""
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_CURRENT_DONE
    if _TRUNCATE_ACTIVE and _TRUNCATE_CURRENT_DONE and _TRUNCATE_LIMIT <= 0:
        trigger_truncate_stop(title=title)
        return True
    return False

def global_revolt_listener():
    import time
    import sys
    global _LIVE_INSTANCE, _MENU_ACTIVE
    global _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_TRIGGERING, _REVOLT_INPUT_BUFFER, _REVOLT_TRIGGERED_DURING_ITEM, _REVOLT_CURRENT_DONE
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_TRIGGERING, _TRUNCATE_INPUT_BUFFER, _TRUNCATE_TRIGGERED_DURING_ITEM, _TRUNCATE_CURRENT_DONE

    while True:
        if _LIVE_INSTANCE is None or _MENU_ACTIVE:
            time.sleep(0.04)
            continue
            
        key = get_key_nonblocking()
        if not key:
            continue
            
        is_typing = _REVOLT_TRIGGERING or _TRUNCATE_TRIGGERING

        if not is_typing:
            if key == '\x12':  # Ctrl+R (Revolt - Shutdown)
                _REVOLT_TRIGGERING = True
                _REVOLT_INPUT_BUFFER = ""
                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
            elif key == '\x14':  # Ctrl+T (Truncate - Stop Early & Wrap Up)
                _TRUNCATE_TRIGGERING = True
                _TRUNCATE_INPUT_BUFFER = ""
                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
        else:
            target_is_truncate = _TRUNCATE_TRIGGERING

            if key in ('\x1b', 'ESC'):  # ESC cancels prompt
                if target_is_truncate:
                    _TRUNCATE_TRIGGERING = False
                    _TRUNCATE_INPUT_BUFFER = ""
                else:
                    _REVOLT_TRIGGERING = False
                    _REVOLT_INPUT_BUFFER = ""
                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
            elif key in ('\r', '\n'):  # Enter confirms
                buf = _TRUNCATE_INPUT_BUFFER if target_is_truncate else _REVOLT_INPUT_BUFFER
                val = buf.strip()
                if val:
                    try:
                        limit = int(val)
                        if limit >= 0:
                            if target_is_truncate:
                                _TRUNCATE_ACTIVE = True
                                _TRUNCATE_LIMIT = limit
                                if _LIVE_INSTANCE is not None:
                                    _TRUNCATE_CURRENT_DONE = False
                                    _TRUNCATE_TRIGGERED_DURING_ITEM = True
                                else:
                                    _TRUNCATE_CURRENT_DONE = True
                                    _TRUNCATE_TRIGGERED_DURING_ITEM = False
                                    if limit == 0:
                                        trigger_truncate_stop()
                            else:
                                _REVOLT_ACTIVE = True
                                _REVOLT_LIMIT = limit
                                if _LIVE_INSTANCE is not None:
                                    _REVOLT_CURRENT_DONE = False
                                    _REVOLT_TRIGGERED_DURING_ITEM = True
                                else:
                                    _REVOLT_CURRENT_DONE = True
                                    _REVOLT_TRIGGERED_DURING_ITEM = False
                                    if limit == 0:
                                        trigger_revolt_exit()
                    except ValueError:
                        pass
                else:
                    if target_is_truncate:
                        _TRUNCATE_ACTIVE = False
                        _TRUNCATE_LIMIT = 0
                        _TRUNCATE_CURRENT_DONE = False
                        _TRUNCATE_TRIGGERED_DURING_ITEM = False
                    else:
                        _REVOLT_ACTIVE = False
                        _REVOLT_LIMIT = 0
                        _REVOLT_CURRENT_DONE = False
                        _REVOLT_TRIGGERED_DURING_ITEM = False

                if target_is_truncate:
                    _TRUNCATE_TRIGGERING = False
                    _TRUNCATE_INPUT_BUFFER = ""
                else:
                    _REVOLT_TRIGGERING = False
                    _REVOLT_INPUT_BUFFER = ""

                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
            elif key in ('\x7f', '\x08'):  # Backspace
                if target_is_truncate:
                    _TRUNCATE_INPUT_BUFFER = _TRUNCATE_INPUT_BUFFER[:-1]
                else:
                    _REVOLT_INPUT_BUFFER = _REVOLT_INPUT_BUFFER[:-1]
                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
            elif key == '\x03':  # Ctrl+C
                clean_exit(forceful=True)
            elif key.isdigit():
                if target_is_truncate:
                    _TRUNCATE_INPUT_BUFFER += key
                else:
                    _REVOLT_INPUT_BUFFER += key
                if _LIVE_INSTANCE is not None:
                    try:
                        _LIVE_INSTANCE.refresh()
                    except Exception:
                        pass
                
        time.sleep(0.02)

_ctrl_r_thread = threading.Thread(target=global_revolt_listener, daemon=True)
_ctrl_r_thread.start()

def set_active_live(live):
    global _LIVE_INSTANCE, _tty_fd, _old_tty_settings, _is_custom_tty_fd
    global _REVOLT_ACTIVE, _REVOLT_LIMIT, _REVOLT_TRIGGERED_DURING_ITEM, _REVOLT_CURRENT_DONE
    global _TRUNCATE_ACTIVE, _TRUNCATE_LIMIT, _TRUNCATE_TRIGGERED_DURING_ITEM, _TRUNCATE_CURRENT_DONE

    if live is not None:
        # Check if either Revolt or Truncate reached 0
        if _REVOLT_ACTIVE and _REVOLT_CURRENT_DONE and _REVOLT_LIMIT <= 0:
            trigger_revolt_exit()
            return
        if _TRUNCATE_ACTIVE and _TRUNCATE_CURRENT_DONE and _TRUNCATE_LIMIT <= 0:
            trigger_truncate_stop()
            return

        _LIVE_INSTANCE = live
        # Enable custom raw mode (ISIG and OPOST preserved) once for the duration of the Live visualizer
        if os.name != 'nt':
            import termios
            fd = None
            is_custom = False
            candidates = [None, "/dev/tty"]
            for cand in candidates:
                try:
                    if cand is None:
                        if sys.stdin.isatty():
                            fd = sys.stdin.fileno()
                            is_custom = False
                        else:
                            continue
                    else:
                        fd = os.open(cand, os.O_RDONLY)
                        is_custom = True

                    old = termios.tcgetattr(fd)
                    mode = termios.tcgetattr(fd)
                    mode[0] = mode[0] & ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
                    mode[2] = mode[2] & ~(termios.CSIZE | termios.PARENB)
                    mode[2] = mode[2] | termios.CS8
                    mode[3] = mode[3] & ~(termios.ECHO | termios.ICANON | termios.IEXTEN)
                    mode[3] = mode[3] | termios.ISIG
                    termios.tcsetattr(fd, termios.TCSADRAIN, mode)
                    _tty_fd = fd
                    _old_tty_settings = old
                    _is_custom_tty_fd = is_custom
                    break
                except Exception:
                    if cand and is_custom and fd is not None:
                        try:
                            os.close(fd)
                        except Exception:
                            pass
                    continue

        if not getattr(live, "_revolt_wrapped", False):
            live._revolt_wrapped = True
            original_get_renderable = live.get_renderable
            def custom_get_renderable():
                renderable = original_get_renderable()
                return inject_revolt_into_renderable(renderable)
            live.get_renderable = custom_get_renderable

            original_update = live.update
            def custom_update(renderable, refresh=False):
                wrapped = inject_revolt_into_renderable(renderable)
                return original_update(wrapped, refresh=refresh)
            live.update = custom_update
    else:
        _LIVE_INSTANCE = None
        # Restore termios configuration when Live visualizer finishes
        if _tty_fd is not None and _old_tty_settings is not None and os.name != 'nt':
            import termios
            try:
                termios.tcsetattr(_tty_fd, termios.TCSADRAIN, _old_tty_settings)
                if _is_custom_tty_fd:
                    os.close(_tty_fd)
            except Exception:
                pass
        _tty_fd = None
        _old_tty_settings = None
        _is_custom_tty_fd = False

        if _REVOLT_ACTIVE:
            if not _REVOLT_CURRENT_DONE:
                _REVOLT_CURRENT_DONE = True
            else:
                if _REVOLT_LIMIT > 0:
                    _REVOLT_LIMIT -= 1

        if _TRUNCATE_ACTIVE:
            if not _TRUNCATE_CURRENT_DONE:
                _TRUNCATE_CURRENT_DONE = True
            else:
                if _TRUNCATE_LIMIT > 0:
                    _TRUNCATE_LIMIT -= 1

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

    start_color, end_color, text_style = get_exit_art_colors(forceful=forceful)

    for i, art_line in enumerate(clean_lines):
        text_line = text_parts[i]
        # Dynamically resolved theme gradient; consistent max_len ensures vertical alignment
        gradient_art = make_gradient_text(art_line, start_color, end_color, total_length=max_len)
        if text_line:
            # Highlight text line with active theme's accent/error style
            gradient_art.append(text_line, style=text_style)
        console.print(gradient_art)
    console.print("")
    sys.stdout.write("\033[?25h\033[0m\n")
    sys.stdout.flush()
    os._exit(0)

def signal_handler(sig, frame):
    logging.warning("SIGINT (Ctrl+C) received. Forcing clean_exit.")
    clean_exit(forceful=True)

signal.signal(signal.SIGINT, signal_handler)

class Selector:
    def __init__(self, options: List[Tuple[str, Any]], title: str = "Select", vertical: bool = False, align_width: int = 8, default_index: int = 0):
        self.options = options
        self.title = title
        self.index = default_index if (isinstance(default_index, int) and 0 <= default_index < len(options)) else 0
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
                        r2, _, _ = _sel.select([fd], [], [], 0.1)
                        if r2:
                            ch2 = os.read(fd, 1).decode('utf-8', errors='ignore')
                            if ch2 in ('[', 'O'):
                                r3, _, _ = _sel.select([fd], [], [], 0.1)
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
                        r2, _, _ = _sel.select([fd], [], [], 0.1)
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
                    chosen_label = self.options[idx][0]
                    chosen_val = self.options[idx][1]
                    try:
                        from core.journal import DownloadJournal
                        DownloadJournal.get_active().record_choice(self.title, chosen_label, chosen_val)
                    except Exception:
                        pass
                    return chosen_val
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

        if os.name != 'nt' and sys.stdin.isatty():
            import tty, termios, select as _sel
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd, termios.TCSADRAIN)
                with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                    _LIVE_INSTANCE = live
                    live.update(self._render(), refresh=True)
                    while True:
                        r, _, _ = _sel.select([fd], [], [], 0.05)
                        if not r:
                            continue
                        chunk = os.read(fd, 64)
                        if not chunk:
                            continue

                        if chunk in (b'\r', b'\n'):
                            chosen_label = self.options[self.index][0]
                            chosen_val = self.options[self.index][1]
                            try:
                                from core.journal import DownloadJournal
                                DownloadJournal.get_active().record_choice(self.title, chosen_label, chosen_val)
                            except Exception:
                                pass
                            return chosen_val

                        if chunk in (b'\x1b', b'q', b'Q'):
                            return "ESC"

                        if chunk == b'=':
                            return "="

                        if chunk == b'\x03':
                            clean_exit(forceful=True)

                        raw = chunk.decode('utf-8', errors='ignore')
                        if any(raw == p or raw.startswith(p) for p in ['\x1b[A', '\x1bOA', '[A', 'OA', 'k', '\x1b[D', '\x1bOD']):
                            self.index = (self.index - 1) % len(self.options)
                            live.update(self._render(), refresh=True)
                        elif any(raw == p or raw.startswith(p) for p in ['\x1b[B', '\x1bOB', '[B', 'OB', 'j', '\x1b[C', '\x1bOC']):
                            self.index = (self.index + 1) % len(self.options)
                            live.update(self._render(), refresh=True)
                        elif '\r' in raw or '\n' in raw:
                            chosen_label = self.options[self.index][0]
                            chosen_val = self.options[self.index][1]
                            try:
                                from core.journal import DownloadJournal
                                DownloadJournal.get_active().record_choice(self.title, chosen_label, chosen_val)
                            except Exception:
                                pass
                            return chosen_val
            except Exception as e:
                return self.select_fallback()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                _LIVE_INSTANCE = None
                console.show_cursor(True)
                _MENU_ACTIVE = old_menu_active
        else:
            try:
                with Live(self._render(), console=console, auto_refresh=False, transient=True) as live:
                    _LIVE_INSTANCE = live
                    live.update(self._render(), refresh=True)
                    while True:
                        key = self._get_key()
                        if not key:
                            return self.select_fallback()
                        if key in ('[D', 'OD') or key in ('[A', 'OA'):
                            self.index = (self.index - 1) % len(self.options)
                            live.update(self._render(), refresh=True)
                        elif key in ('[C', 'OC') or key in ('[B', 'OB'):
                            self.index = (self.index + 1) % len(self.options)
                            live.update(self._render(), refresh=True)
                        elif key in ('\r', '\n'):
                            chosen_label = self.options[self.index][0]
                            chosen_val = self.options[self.index][1]
                            try:
                                from core.journal import DownloadJournal
                                DownloadJournal.get_active().record_choice(self.title, chosen_label, chosen_val)
                            except Exception:
                                pass
                            return chosen_val
                        elif key == '=':
                            return "="
                        elif key == 'ESC':
                            return "ESC"
                        elif key == '\x03':
                            clean_exit(forceful=True)
            except Exception as e:
                return self.select_fallback()
            finally:
                _LIVE_INSTANCE = None
                console.show_cursor(True)
                _MENU_ACTIVE = old_menu_active

    def _render(self) -> Text:
        full_text = Text()
        if self.vertical:
            if self.title:
                full_text.append(f"{self.title}:\n", style="menu")
            indent = "  "
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


class BoxSelector(Selector):
    """Renders options cleanly inside a stylized Panel box with title, border, and footer navigation."""
    def __init__(self, options: List[Tuple[str, Any]], title: str = "Select", border_style: str = "sexy_pink", width: int = 86):
        super().__init__(options, title=title, vertical=True)
        self.border_style = border_style
        self.width = width

    def _render(self) -> Any:
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_column("icon", width=3, justify="right")
        table.add_column("option", width=max(40, self.width - 12))

        for i, (label, _) in enumerate(self.options):
            is_active = (i == self.index)
            if is_active:
                table.add_row(
                    Text("▶", style="bold sexy_pink"),
                    Text(label, style="bold white")
                )
            else:
                table.add_row(
                    Text(" ", style="unselected"),
                    Text(label, style="unselected")
                )

        footer = Text(justify="center")
        footer.append("↑↓", style="bold white")
        footer.append(" Navigate  ", style="unselected")
        footer.append("Enter", style="bold white")
        footer.append(" Select  ", style="unselected")
        footer.append("Esc", style="bold white")
        footer.append(" Return to Menu", style="unselected")

        return Panel(
            table,
            title=f"[bold white]◆ {self.title.upper()} ◆[/bold white]",
            subtitle=footer,
            subtitle_align="center",
            border_style=self.border_style,
            padding=(1, 2),
            width=self.width,
        )


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
    def __init__(self, options: List[Any], title: str = "Select Files"):
        normalized = []
        for opt in options:
            if isinstance(opt, dict):
                normalized.append(opt)
            elif isinstance(opt, tuple):
                label = str(opt[0])
                val = opt[1] if len(opt) > 1 else opt[0]
                normalized.append({"name": label, "value": val, "size_bytes": 0})
            else:
                normalized.append({"name": str(opt), "value": opt, "size_bytes": 0})
        self.options = normalized
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
                            res = [self.options[self.index]]
                        else:
                            res = [self.options[i] for i in sorted(self.selected)]
                        try:
                            from core.journal import DownloadJournal
                            names = [opt.get("name") or opt.get("title") or str(opt) for opt in res]
                            DownloadJournal.get_active().record_choice(self.title, f"Selected {len(names)} items ({', '.join(names[:3])}{'...' if len(names) > 3 else ''})", names)
                        except Exception:
                            pass
                        return res
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

_error_wait_consumed = False

def reset_error_wait() -> None:
    global _error_wait_consumed
    _error_wait_consumed = False

def wait_for_error(prompt_msg: str = "Press Enter to return to menu...", force: bool = False) -> None:
    """
    Waits for a single keypress (Enter, Space, Esc, Q, etc.) when an error/failure occurs.
    Guarantees that failure messages and error panels stay on screen until user dismissal.
    Prevents duplicate pause prompts within the same failure cycle.
    """
    global _error_wait_consumed
    if not sys.stdin.isatty():
        return
    if _error_wait_consumed and not force:
        return
    _error_wait_consumed = True

    if prompt_msg:
        console.print(f"\n[menu]{prompt_msg}[/menu]", end="")
        sys.stdout.flush()

    if os.name != 'nt':
        import termios, tty, select as _sel
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
        except Exception:
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                pass
            console.print()
            return

        try:
            termios.tcflush(fd, termios.TCIFLUSH)
            tty.setcbreak(fd, termios.TCSADRAIN)
            while True:
                r, _, _ = _sel.select([fd], [], [], 0.05)
                if not r:
                    continue
                chunk = os.read(fd, 64)
                if not chunk:
                    continue
                if chunk == b'\x03':  # Ctrl+C
                    clean_exit(forceful=True)
                # Any single keystroke confirms return
                break
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass
            console.print()
    else:
        import msvcrt, time
        try:
            while msvcrt.kbhit():
                msvcrt.getch()
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\x03':
                        clean_exit(forceful=True)
                    break
                time.sleep(0.02)
        except Exception:
            pass
        console.print()

def prompt_return(prompt_msg: str = "Press Enter to return to main menu...") -> None:
    """Explicit pause for informational/utility screens (doctor, version, lyrics tools, etc.)."""
    wait_for_error(prompt_msg=prompt_msg, force=True)

def wait_for_return(prompt_msg: str = "") -> None:
    """
    Auto-returns immediately for successful workflows — no keypress required.
    Ctrl+C is still respected via normal signal handling.
    """
    sys.stdout.flush()

wait_for_enter = wait_for_return



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
    """Returns the Vacuum folder (was Batch/ — redirected)."""
    from core.paths import PathAuthority
    paths = PathAuthority()
    return paths.get_downloads_root() / "Vacuum"


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
        return Path(batch_path)

    library_root = default_root.parent
    site_folder = default_root.name

    if library_root.name == "Quick grab":
        return default_root

    target_dir = library_root / site_folder
    if store_layer:
        try:
            store_layer.create_directory(target_dir)
        except Exception:
            pass
    return target_dir

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



def apply_chapter_limit(
    to_process: List[Tuple[str, str]],
    scraper: Any,
    url: Optional[str] = None,
    target_path: Optional[Path] = None
) -> List[Tuple[str, str]]:
    """
    Limits the un-downloaded items/chapters according to active mode, URL type, and flags.
    --<N> (e.g. --2, --5) downloads the next N un-downloaded items in systematic order.
    --0 (Quick grab) / Quick grab mode downloads the single target item.
    --A / --a (Vacuum all) downloads all un-downloaded items.
    """
    if not to_process:
        return to_process

    # 1. Check explicit force vacuum / batch all flags
    if getattr(scraper, '_force_vacuum', False) or getattr(scraper, '_batch_all', False):
        return to_process

    # 2. Check explicit chapter limit flag (e.g. --2, --5)
    chapter_limit = getattr(scraper, '_chapter_limit', None)
    if isinstance(chapter_limit, int) and chapter_limit > 0:
        return to_process[:chapter_limit]

    # 3. Detect Quick grab mode from flags, scraper attributes, or target destination
    is_quick_grab = (
        getattr(scraper, '_batch_quick_grab', False)
        or getattr(scraper, 'is_quick_grab', False)
        or (target_path and "quick grab" in str(target_path).lower())
    )

    # 4. Check if the input URL is a single chapter/item link
    raw_url = str(url or getattr(scraper, 'url', '') or '').strip()
    is_chapter_link = False
    if hasattr(scraper, 'is_chapter_link'):
        try:
            is_chapter_link = bool(scraper.is_chapter_link())
        except Exception:
            is_chapter_link = False
    if not is_chapter_link:
        is_chapter_link = any(x in raw_url.lower() for x in ["/c/", "chapter", "/read/", "/ch-", "-chapter-", "/ch/", "/g/"])

    if is_chapter_link:
        # Match the specific chapter URL or chapter number if possible
        matched = []
        # Try exact URL match
        for item in to_process:
            ch_num, ch_url = item
            if ch_url and (ch_url.rstrip('/') == raw_url.rstrip('/') or raw_url.rstrip('/').endswith(ch_url.rstrip('/')) or ch_url.rstrip('/').endswith(raw_url.rstrip('/'))):
                matched.append(item)
                break
        if matched:
            return matched

        # Try matching chapter number from URL
        import re
        m = re.search(r"(?:chapter-|/c/|/ch-|/ch/|/read/\d+/|/read/|/chapter/)([\d]+(?:[\.-][\d]+)?)", raw_url.lower())
        if m:
            target_num = m.group(1).replace("-", ".")
            for item in to_process:
                ch_num, ch_url = item
                if str(ch_num).strip() == target_num or str(ch_num).strip() == str(int(float(target_num)) if '.' in target_num and target_num.endswith('.0') else target_num):
                    matched.append(item)
                    break
        if matched:
            return matched

        # If in Quick Grab or chapter link, take only the single chapter
        if is_quick_grab or not getattr(scraper, '_force_vacuum', False):
            return to_process[:1]

    if is_quick_grab:
        return to_process[:1]

    return to_process


def filter_subchapters(url: str, title: str, chapters: List[Tuple[str, str]], is_batch: bool = False, scraper: Any = None) -> List[Tuple[str, str]]:
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
    import re
    if is_batch or not sys.stdin.isatty():
        return chapters

    # Never prompt if any flags, batch flags, or chapter limits are active
    has_flags = False
    if scraper:
        if getattr(scraper, "_force_vacuum", False) or getattr(scraper, "_batch_all", False):
            has_flags = True
        if getattr(scraper, "_chapter_limit", None) is not None:
            has_flags = True
        if getattr(scraper, "_batch_quick_grab", False):
            has_flags = True
        if getattr(scraper, "_batch_flags", None):
            has_flags = True

    from core.history import HistoryLayer
    if getattr(HistoryLayer, "_active_instance", None) and getattr(HistoryLayer._active_instance, "_active_batch_flags", None):
        has_flags = True

    if re.search(r"--(\d+|[aA])\b", url):
        has_flags = True

    if has_flags:
        return chapters

    startup_clear()
    print_banner()
    if is_batch:
        console.print("[menu]Menu[/menu]         : [site]Vacuum Mode[/site]")
    console.print(f"[menu]URL[/menu]          : [sexy_pink]{url}[/sexy_pink]")
    console.print(f"[menu]Title[/menu]        : [title]{title}[/title]")
    console.print("")
    console.print("[warning]Found subchapters (e.g. 5.1, 6.5) in the chapter list![/warning]")
    console.print("")
    ans = Selector(
        [("Yes, download subchapters", True), ("No, skip them", False)],
        title="Download subchapters as well?",
        vertical=True,
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

def clean_exit_revolt(title: Optional[str] = None):
    """Used to exit after the Revolt limit is reached. Delegates cleanly to trigger_revolt_exit."""
    trigger_revolt_exit(title=title)


def print_alternative_anime_sources(anime_title: str, current_site: str = "Anime"):
    """Renders a clean Rich tree informing the user that web streaming is deprecated and points to permanent torrent indexers."""
    from rich.tree import Tree
    clean_t = str(anime_title or "this anime").strip()
    tree = Tree(f"[warning]⚠ Web streaming is deprecated / unavailable for '{clean_t}'[/warning]")
    tree.add("[unselected]Web streaming sites suffer from frequent domain takedowns and CDN throttling.[/unselected]")
    alt_branch = tree.add("[menu]Recommended torrent indexers (download via qBittorrent):[/menu]")
    alt_branch.add("[site]Nyaa[/site]        : [sexy_pink]https://nyaa.si[/sexy_pink] [unselected](Premier anime torrent tracker)[/unselected]")
    alt_branch.add("[site]SeaDex[/site]      : [sexy_pink]https://releases.moe[/sexy_pink] [unselected](Curated best releases database)[/unselected]")
    alt_branch.add("[site]TsukiHime[/site]    : [sexy_pink]https://tsukihime.org[/sexy_pink] [unselected](Torrent, DDL & NZB aggregator)[/unselected]")
    console.print("")
    console.print(tree)
    console.print("")


def print_alternative_adult_anime_sources(anime_title: str, current_site: str = "Hentai"):
    """Renders a clean Rich tree informing the user that the host stream is dead and lists verified alternative adult anime platforms in Zine."""
    from rich.tree import Tree
    clean_t = str(anime_title or "this title").strip()
    tree = Tree(f"[warning]⚠ Stream unavailable or missing pieces on {current_site}[/warning]")
    tree.add(f"[unselected]Host CDN returned missing or unplayable media chunks for '{clean_t}'.[/unselected]")
    alt_branch = tree.add("[menu]Alternative adult anime sources supported in Zine Scraper:[/menu]")
    alt_branch.add("[site]Hanime[/site]       : [sexy_pink]https://hanime1.me[/sexy_pink] / [sexy_pink]https://hanime.red[/sexy_pink]")
    alt_branch.add("[site]HentaiHaven[/site]  : [sexy_pink]https://hentaihaven.xxx[/sexy_pink] / [sexy_pink]https://hentaihaven.red[/sexy_pink]")
    alt_branch.add("[site]HStream[/site]      : [sexy_pink]https://hstream.moe[/sexy_pink]")
    alt_branch.add("[site]OHentai[/site]      : [sexy_pink]https://ohentai.org[/sexy_pink]")
    alt_branch.add("[site]OppaiStream[/site]  : [sexy_pink]https://oppai.stream[/sexy_pink]")
    alt_branch.add("[site]HentaiCity[/site]   : [sexy_pink]https://www.hentaicity.com[/sexy_pink]")
    alt_branch.add("[site]HentaiMama[/site]   : [sexy_pink]https://hentaimama.io[/sexy_pink]")
    console.print("")
    console.print(tree)
    console.print("")


def render_failure_box(
    title: str,
    failed_items: Optional[List[str]] = None,
    reason: Optional[str] = None,
    width: int = 86
):
    """
    Renders a minimal, high-visibility failure notification box with red ball marker:
    🔴 [failed]
    """
    from rich.panel import Panel
    from rich.table import Table
    from rich.markup import escape
    from rich import box

    body = Table(show_header=False, show_edge=False, box=None, padding=(0, 1), expand=True)
    body.add_column("Key", style="bold red", width=10, no_wrap=True)
    body.add_column("Val", style="white")

    body.add_row("Status", f"🔴 [bold red]{escape('[failed]')}[/bold red]")
    body.add_row("Target", f"[title]{escape(str(title))}[/title]")

    if reason:
        body.add_row("Reason", f"[warning]{escape(str(reason))}[/warning]")

    if failed_items:
        items_preview = ", ".join(str(x) for x in failed_items[:6])
        if len(failed_items) > 6:
            items_preview += f" ... (+{len(failed_items) - 6} more)"
        body.add_row("Failed", f"[sexy_pink]{items_preview}[/sexy_pink] ({len(failed_items)} item(s))")

    body.add_row("Logs", "[unselected]Check Logs/💩/latest_session.log or latest_error.log[/unselected]")

    return Panel(
        body,
        title="[bold red]🔴 Download Incomplete / Failed[/bold red]",
        title_align="left",
        border_style="red",
        box=box.ROUNDED,
        width=min(width, console.width or 86),
        padding=(0, 1)
    )


def print_failure_box(
    title: str,
    failed_items: Optional[List[str]] = None,
    reason: Optional[str] = None
):
    """Prints the minimal 🔴 [failed] box directly to the console."""
    console.print("")
    console.print(render_failure_box(title, failed_items=failed_items, reason=reason))
    console.print("")

