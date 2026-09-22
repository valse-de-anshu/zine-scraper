"""
core/server.py
--------------
Lightweight Companion Server for Zine Scraper.
Enables Hwaran and mobile clients to initiate scraping tasks, monitor progress,
and transfer completed media via LocalSend Protocol or direct streaming.
"""

import os
import sys
import time
import json
import uuid
import zipfile
import logging
import threading
import io
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, List

# Ensure scraper package is in sys.path
_repo_dir = Path(__file__).parent.parent.resolve()
if str(_repo_dir) not in sys.path:
    sys.path.insert(0, str(_repo_dir))

from core.paths import PathAuthority
from core.storage import StorageLayer
from core.history import HistoryLayer
from core.localsend_client import LocalSendClient

logger = logging.getLogger("core.server")

tasks: Dict[str, Dict[str, Any]] = {}

class ScrapeTask:
    def __init__(self, task_id: str, url: str, mode: str, target_ip: str = "", transfer: str = "hybrid"):
        self.task_id = task_id
        self.url = url
        self.mode = mode  # "quick_grab" or "vacuum"
        self.target_ip = target_ip
        self.transfer = transfer  # "hybrid", "localsend", "direct"
        self.status = "queued"  # "queued", "scraping", "transferring", "completed", "failed"
        self.progress = 0.0
        self.message = "Queued"
        self.downloaded_files: List[Path] = []
        self.base_dir: Path = Path()
        self.error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "mode": self.mode,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "file_count": len(self.downloaded_files),
            "error": self.error
        }

def run_scrape_worker(task: ScrapeTask):
    task.status = "scraping"
    task.message = f"Scraping media ({task.mode})..."
    task.progress = 0.15

    paths = PathAuthority()
    storage = StorageLayer()
    history = HistoryLayer(paths, storage)

    # Determine base directory before scraping to detect new files
    if task.mode == "quick_grab":
        target_root = paths.get_quick_grab_root()
    else:
        target_root = paths._downloads_root / "Vacuum"
    target_root.mkdir(parents=True, exist_ok=True)

    files_before = set(target_root.rglob("*"))

    from core.funnel import route_url
    is_quick_grab = (task.mode == "quick_grab")

    try:
        success = route_url(
            task.url,
            history,
            storage,
            batch_path=None,
            is_batch=True,
            batch_quick_grab=is_quick_grab,
            batch_all=True
        )

        files_after = set(target_root.rglob("*"))
        new_files = [f for f in (files_after - files_before) if f.is_file()]

        # If no new files detected by diff, find files modified in the last 10 minutes in the site folder
        if not new_files:
            recent_cutoff = time.time() - 600
            new_files = [f for f in target_root.rglob("*") if f.is_file() and f.stat().st_mtime >= recent_cutoff]

        task.downloaded_files = new_files
        task.base_dir = target_root

        if not success and not new_files:
            task.status = "failed"
            task.message = "Scraper failed or URL unsupported"
            task.error = "Could not extract media from URL"
            return

        task.progress = 0.70
        task.message = f"Scraped {len(new_files)} file(s). Preparing transfer..."

        # Transfer via LocalSend if requested or in hybrid mode
        localsend_success = False
        if task.transfer in ["hybrid", "localsend"] and task.target_ip:
            task.status = "transferring"
            client = LocalSendClient()

            def transfer_cb(msg: str, pct: float):
                task.message = msg
                task.progress = 0.70 + (0.30 * pct)

            localsend_success = client.send_files(
                target_ip=task.target_ip,
                files=new_files,
                base_dir=target_root,
                progress_cb=transfer_cb
            )

        if localsend_success:
            task.status = "completed"
            task.progress = 1.0
            task.message = "Sent to phone via LocalSend successfully!"
        else:
            if task.transfer == "localsend":
                task.status = "failed"
                task.message = "LocalSend push failed (Receiver unreachable)"
                task.error = "Target phone LocalSend receiver not reachable"
            else:
                task.status = "completed"
                task.progress = 1.0
                task.message = "Media ready for direct download"

    except Exception as e:
        logger.exception("Error running scrape task")
        task.status = "failed"
        task.message = "Execution error"
        task.error = str(e)

class ZineServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.debug("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), format % args))

    def _send_json(self, status_code: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ping":
            self._send_json(200, {
                "status": "ok",
                "app": "zine-scraper",
                "version": "2.1",
                "server_time": time.time()
            })
        elif path == "/api/discover":
            client = LocalSendClient()
            devices = client.discover_devices(timeout=1.5)
            self._send_json(200, {"devices": devices})
        elif path.startswith("/api/tasks/"):
            task_id = path.substringAfter("/api/tasks/") if hasattr(path, "substringAfter") else path.replace("/api/tasks/", "").strip()
            task = tasks.get(task_id)
            if task:
                self._send_json(200, task.to_dict())
            else:
                self._send_json(404, {"error": "Task not found"})
        elif path.startswith("/api/download/"):
            task_id = path.replace("/api/download/", "").strip()
            task = tasks.get(task_id)
            if not task or not task.downloaded_files:
                self._send_json(404, {"error": "Files not ready or task not found"})
                return

            # Stream files as a single ZIP archive directly to the client
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="zine_{task_id}.zip"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in task.downloaded_files:
                    if f.exists() and f.is_file():
                        arcname = str(f.relative_to(task.base_dir)) if f.is_relative_to(task.base_dir) else f.name
                        zf.write(f, arcname=arcname)

            self.wfile.write(zip_buffer.getvalue())
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/scrape":
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len)
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                self._send_json(400, {"error": "Invalid JSON payload"})
                return

            url = payload.get("url", "").strip()
            if not url:
                self._send_json(400, {"error": "Missing 'url' parameter"})
                return

            mode = payload.get("mode", "quick_grab")
            target_ip = payload.get("target_ip", self.client_address[0])
            transfer = payload.get("transfer", "hybrid")

            task_id = str(uuid.uuid4())[:8]
            task = ScrapeTask(task_id, url, mode, target_ip, transfer)
            tasks[task_id] = task

            # Run in worker thread
            thread = threading.Thread(target=run_scrape_worker, args=(task,), daemon=True)
            thread.start()

            self._send_json(200, task.to_dict())
        else:
            self._send_json(404, {"error": "Endpoint not found"})

def run_udp_beacon(server_port: int, stop_event: threading.Event):
    """
    Broadcasts UDP announcements on LAN so Hwaran can automatically find the server.
    """
    import socket
    beacon_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    beacon_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    beacon_data = json.dumps({
        "service": "zine-scraper-server",
        "port": server_port,
        "version": "2.1"
    }).encode("utf-8")

    while not stop_event.is_set():
        try:
            beacon_sock.sendto(beacon_data, ("<broadcast>", 53318))
        except Exception:
            pass
        time.sleep(3.0)
    beacon_sock.close()

def start_server(port: int = 53318, host: str = "0.0.0.0"):
    server = HTTPServer((host, port), ZineServerHandler)
    stop_event = threading.Event()
    beacon_thread = threading.Thread(target=run_udp_beacon, args=(port, stop_event), daemon=True)
    beacon_thread.start()

    print(f"\n[Zine Scraper Server] Listening on http://{host}:{port}")
    print("[Zine Scraper Server] Automatic LAN discovery beacon active on UDP 53318")
    print("[Zine Scraper Server] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
        print("\n[Zine Scraper Server] Stopped.")

if __name__ == "__main__":
    p = 53318
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except ValueError:
            pass
    start_server(port=p)
