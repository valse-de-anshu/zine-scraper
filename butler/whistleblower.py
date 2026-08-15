import time
import socket
import logging
import threading
from typing import Callable, Optional
from core.config import ConfigLayer
from core.paths import PathAuthority
from core.storage import StorageLayer

logger = logging.getLogger(__name__)

# Global registry for the active TUI refresh callback
_active_tui_callback: Optional[Callable[[], None]] = None
_whistleblower_active = False

def set_tui_callback(callback: Optional[Callable[[], None]]):
    """Registers a callback to reload/redraw the currently active TUI."""
    global _active_tui_callback
    _active_tui_callback = callback

def is_internet_restored() -> bool:
    """Performs a quick, low-overhead check for internet connectivity."""
    try:
        # Check standard DNS resolution or reach a reliable host
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False

def get_check_interval() -> int:
    """Reads the custom internet check interval from settings, defaulting to 10s."""
    try:
        config = ConfigLayer(PathAuthority(), StorageLayer())
        return int(config.get("internet_check_interval", 10))
    except Exception:
        return 10

def start_whistleblower(on_restored: Callable[[], None]):
    """
    Spawns a background thread that periodically checks for internet restoration.
    Fires the callback when connection is back.
    """
    global _whistleblower_active
    if _whistleblower_active:
        return
        
    _whistleblower_active = True
    
    def monitor_loop():
        global _whistleblower_active
        interval = get_check_interval()
        while _whistleblower_active:
            if is_internet_restored():
                _whistleblower_active = False
                on_restored()
                break
            time.sleep(interval)
            
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()

def stop_whistleblower():
    """Manually stops the background whistleblower thread."""
    global _whistleblower_active
    _whistleblower_active = False
