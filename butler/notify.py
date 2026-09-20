import os
import sys
import time
import subprocess
import logging
from typing import Optional

logger = logging.getLogger("butler.notify")

_LAST_NOTIFY_TIME: float = 0.0
_LAST_NOTIFY_MSG: Optional[str] = None
_GLOBAL_MIN_INTERVAL: float = 3.0
_DEBOUNCE_SECONDS: float = 4.0


def send_os_notification(title: str, message: str, is_success: bool = True):
    """
    Cross-platform OS notification dispatcher (Linux, Windows, macOS).
    Includes global throttling and message debouncing to prevent multi-bubble spam.
    """
    global _LAST_NOTIFY_TIME, _LAST_NOTIFY_MSG

    now = time.time()
    elapsed = now - _LAST_NOTIFY_TIME

    # Clean message text
    clean_title = str(title).strip()[:100]
    clean_msg = str(message).strip()[:200]
    msg_key = f"{clean_title}::{clean_msg}"

    # Global debounce & suppression of rapid redundant bubbles
    if elapsed < _DEBOUNCE_SECONDS:
        # Exact message match within debounce window -> drop
        if msg_key == _LAST_NOTIFY_MSG:
            return
        # Multiple success notifications dispatched within minimum interval -> drop
        if is_success and elapsed < _GLOBAL_MIN_INTERVAL:
            logger.debug(f"Suppressing redundant success notification within {elapsed:.2f}s: {clean_title} - {clean_msg}")
            return

    _LAST_NOTIFY_TIME = now
    _LAST_NOTIFY_MSG = msg_key

    logger.info(f"Dispatching OS notification ({'SUCCESS' if is_success else 'ERROR'}): {clean_title} - {clean_msg}")

    try:
        if sys.platform.startswith("linux"):
            icon = "dialog-information" if is_success else "dialog-error"
            subprocess.run(
                ["notify-send", "-a", "Zine Scraper", "-i", icon, clean_title, clean_msg],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )

        elif sys.platform == "darwin":
            apple_script = f'display notification "{clean_msg}" with title "{clean_title}"'
            subprocess.run(
                ["osascript", "-e", apple_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )

        elif sys.platform == "win32":
            ps_script = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            $xml = @"
            <toast>
                <visual>
                    <binding template="ToastText02">
                        <text id="1">{clean_title}</text>
                        <text id="2">{clean_msg}</text>
                    </binding>
                </visual>
            </toast>
"@
            $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
            $doc.LoadXml($xml)
            $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Zine Scraper").Show($toast)
            '''
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            subprocess.run(
                ["powershell", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                timeout=5,
            )
    except Exception as e:
        logger.debug(f"OS notification dispatch failed silently: {e}")
