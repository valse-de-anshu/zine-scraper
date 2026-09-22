"""
core/localsend_client.py
------------------------
Native implementation of the LocalSend Protocol v2 client.
Discovers LocalSend receivers on the local network and pushes files via REST API.
"""

import os
import json
import socket
import struct
import logging
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any

logger = logging.getLogger("core.localsend")

MULTICAST_GROUP = "224.0.0.167"
MULTICAST_PORT = 53317

class LocalSendClient:
    def __init__(self, alias: str = "Zine Scraper", port: int = 53318):
        self.alias = alias
        self.port = port
        self.fingerprint = f"zine-scraper-{socket.gethostname()}"

    def discover_devices(self, timeout: float = 2.0) -> List[Dict[str, Any]]:
        """
        Sends a UDP multicast announcement to discover LocalSend devices on the LAN.
        """
        devices = []
        seen_ips = set()

        announcement = {
            "alias": self.alias,
            "version": "2.1",
            "deviceModel": "Linux Desktop",
            "deviceType": "desktop",
            "fingerprint": self.fingerprint,
            "port": self.port,
            "protocol": "http",
            "download": False,
            "announcement": True,
            "announce": True
        }
        data = json.dumps(announcement).encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)

        try:
            sock.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
            start_time = socket.getdefaulttimeout() or timeout
            while True:
                try:
                    resp_data, (ip, port) = sock.recvfrom(4096)
                    if ip in seen_ips:
                        continue
                    seen_ips.add(ip)
                    try:
                        info = json.loads(resp_data.decode("utf-8"))
                        info["ip"] = ip
                        devices.append(info)
                    except Exception:
                        pass
                except socket.timeout:
                    break
        except Exception as e:
            logger.debug(f"UDP discovery error: {e}")
        finally:
            sock.close()

        return devices

    def check_receiver(self, ip: str, port: int = 53317) -> Optional[Dict[str, Any]]:
        """
        Probes an IP directly to see if a LocalSend receiver is running on it.
        """
        for protocol in ["http", "https"]:
            url = f"{protocol}://{ip}:{port}/api/localsend/v2/info"
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        data["ip"] = ip
                        data["port"] = port
                        data["protocol"] = protocol
                        return data
            except Exception:
                pass
        return None

    def send_files(
        self,
        target_ip: str,
        files: List[Path],
        base_dir: Optional[Path] = None,
        port: int = 53317,
        protocol: str = "http",
        pin: Optional[str] = None,
        progress_cb: Optional[Callable[[str, float], None]] = None
    ) -> bool:
        """
        Uploads a list of files to a LocalSend receiver.
        Preserves relative paths if base_dir is supplied.
        """
        if not files:
            return True

        if progress_cb:
            progress_cb("Preparing transfer...", 0.05)

        # 1. Prepare upload payload
        files_dict = {}
        file_paths_by_id = {}

        for idx, f in enumerate(files):
            if not f.exists() or not f.is_file():
                continue
            file_id = f"file_{idx}_{f.name}"
            rel_name = str(f.relative_to(base_dir)) if base_dir and f.is_relative_to(base_dir) else f.name
            size = f.stat().st_size
            
            ext = f.suffix.lower().lstrip(".")
            mime = "application/octet-stream"
            if ext in ["jpg", "jpeg", "png", "webp"]:
                mime = f"image/{ext}"
            elif ext in ["mp4", "mkv", "webm"]:
                mime = f"video/{ext}"
            elif ext in ["mp3", "flac", "m4a", "wav"]:
                mime = f"audio/{ext}"
            elif ext in ["json"]:
                mime = "application/json"
            elif ext in ["srt", "vtt", "ass"]:
                mime = "text/plain"

            files_dict[file_id] = {
                "id": file_id,
                "fileName": rel_name,
                "size": size,
                "fileType": mime
            }
            file_paths_by_id[file_id] = f

        if not files_dict:
            return False

        prepare_payload = {
            "info": {
                "alias": self.alias,
                "version": "2.1",
                "deviceModel": "Linux Desktop",
                "deviceType": "desktop",
                "fingerprint": self.fingerprint,
                "port": self.port,
                "protocol": protocol,
                "download": False
            },
            "files": files_dict
        }

        prepare_url = f"{protocol}://{target_ip}:{port}/api/localsend/v2/prepare-upload"
        if pin:
            prepare_url += f"?pin={pin}"

        res_json = None
        for attempt in range(5):
            try:
                req_data = json.dumps(prepare_payload).encode("utf-8")
                req = urllib.request.Request(
                    prepare_url,
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    if resp.status == 200:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        break
                    else:
                        logger.error(f"prepare-upload failed with status {resp.status}")
                        return False
            except Exception as e:
                if attempt < 4:
                    if progress_cb:
                        progress_cb(f"Connecting to LocalSend on phone ({attempt+1}/5)...", 0.05)
                    import time
                    time.sleep(1.2)
                else:
                    logger.error(f"Failed to communicate with LocalSend receiver at {target_ip}:{port} -> {e}")
                    return False

        if not res_json:
            return False

        session_id = res_json.get("sessionId")
        token_map = res_json.get("files", {})
        if not session_id or not token_map:
            logger.error(f"Invalid prepare-upload response: {res_json}")
            return False

        # 2. Upload file contents
        total_files = len(token_map)
        uploaded_count = 0

        for file_id, token in token_map.items():
            f_path = file_paths_by_id.get(file_id)
            if not f_path or not f_path.exists():
                continue

            uploaded_count += 1
            if progress_cb:
                pct = 0.1 + (0.9 * (uploaded_count / total_files))
                progress_cb(f"Sending {f_path.name} ({uploaded_count}/{total_files})", pct)

            upload_url = f"{protocol}://{target_ip}:{port}/api/localsend/v2/upload?sessionId={session_id}&fileId={file_id}&token={token}"
            try:
                with open(f_path, "rb") as fp:
                    upload_req = urllib.request.Request(
                        upload_url,
                        data=fp.read(),  # stream upload
                        headers={"Content-Type": "application/octet-stream"},
                        method="POST"
                    )
                    with urllib.request.urlopen(upload_req, timeout=60.0) as up_resp:
                        if up_resp.status != 200:
                            logger.error(f"Failed uploading {f_path.name}: {up_resp.status}")
                            return False
            except Exception as e:
                logger.error(f"Error streaming file {f_path.name} to {target_ip} -> {e}")
                return False

        if progress_cb:
            progress_cb("Transfer complete!", 1.0)
        return True
