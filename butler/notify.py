import os
import sys
import time
import subprocess
import logging
from typing import Optional

logger = logging.getLogger("butler.notify")

_LAST_NOTIFY_TIME: float = 0.0
_LAST_NOTIFY_MSG: Optional[str] = None
_DEBOUNCE_SECONDS: float = 2.5


def send_os_notification(title: str, message: str, is_success: bool = True):
    """
    Cross-platform OS notification dispatcher (Linux, Windows, macOS).
    Includes debouncing to prevent spamming/misfires in rapid succession.
    """
    global _LAST_NOTIFY_TIME, _LAST_NOTIFY_MSG

    now = time.time()
    msg_key = f"{title}::{message}"
    if msg_key == _LAST_NOTIFY_MSG and (now - _LAST_NOTIFY_TIME) < _DEBOUNCE_SECONDS:
        return
    _LAST_NOTIFY_TIME = now
    _LAST_NOTIFY_MSG = msg_key

    # Clean message text
    clean_title = str(title).strip()[:100]
    clean_msg = str(message).strip()[:200]

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
