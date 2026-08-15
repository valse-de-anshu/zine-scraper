import os
import sys
import subprocess

def send_os_notification(title: str, message: str, is_success: bool = True):
    """
    Cross-platform OS notification dispatcher (Linux, Windows, macOS).
    """
    try:
        if sys.platform.startswith("linux"):
            # Linux (GNOME, KDE, XFCE, etc.)
            icon = "dialog-information" if is_success else "dialog-error"
            subprocess.run(
                ["notify-send", "-i", icon, title, message], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            
        elif sys.platform == "darwin":
            # macOS
            apple_script = f'display notification "{message}" with title "{title}"'
            subprocess.run(
                ["osascript", "-e", apple_script], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            
        elif sys.platform == "win32":
            # Windows 10/11 native PowerShell notification
            ps_script = f'''
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
            [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
            $xml = @"
            <toast>
                <visual>
                    <binding template="ToastText02">
                        <text id="1">{title}</text>
                        <text id="2">{message}</text>
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
                creationflags=creationflags
            )
    except Exception:
        pass
