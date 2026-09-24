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
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, List, Optional

# Ensure scraper package is in sys.path
_repo_dir = Path(__file__).parent.parent.resolve()
if str(_repo_dir) not in sys.path:
    sys.path.insert(0, str(_repo_dir))

from core.paths import PathAuthority
from core.storage import StorageLayer
from core.history import HistoryLayer
from core.localsend_client import LocalSendClient
from core.link_resolver import resolve_link_info

logger = logging.getLogger("core.server")

tasks_lock = threading.Lock()
tasks: Dict[str, Any] = {}

class ScrapeTask:
    def __init__(
        self,
        task_id: str,
        url: str,
        mode: str,
        target_ip: str = "",
        transfer: str = "hybrid",
        device_name: str = "Android Device",
        device_brand: str = "Android",
        flags: Optional[List[str]] = None,
        limit: Optional[int] = None,
        site_name: str = "",
        category: str = "",
        link_type: str = "",
        target_root: Optional[Path] = None,
        keep_on_pc: bool = False
    ):
        self.task_id = task_id
        self.url = url
        self.mode = mode  # "quick_grab" or "vacuum"
        self.flags = flags or []
        self.limit = limit
        self.target_ip = target_ip
        self.transfer = transfer  # "hybrid", "localsend", "direct"
        self.device_name = device_name
        self.device_brand = device_brand
        self.site_name = site_name
        self.category = category
        self.link_type = link_type
        self.target_root = target_root
        self.keep_on_pc = keep_on_pc
        self.staging_dir: Optional[Path] = None
        self.is_stopping: bool = False
        self.status = "queued"  # "queued", "scraping", "transferring", "completed", "failed"
        self.progress = 0.0
        self.message = "Queued on server"
        self.downloaded_files: List[Path] = []
        self.base_dir: Path = Path()
        self.error: str = ""
        self.media_title: str = ""
        self.zip_path: Optional[Path] = None
        self.created_at: float = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "mode": self.mode,
            "flags": self.flags,
            "limit": self.limit,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "file_count": len(self.downloaded_files),
            "media_title": self.media_title,
            "error": self.error,
            "keep_on_pc": self.keep_on_pc,
            "is_stopping": self.is_stopping,
            "device_name": self.device_name,
            "device_brand": self.device_brand,
            "site_name": getattr(self, "site_name", ""),
            "category": getattr(self, "category", ""),
            "link_type": getattr(self, "link_type", ""),
            "created_at": self.created_at
        }

def run_scrape_worker(task: ScrapeTask):
    task.status = "scraping"
    task.message = f"Scraping media ({task.mode})..."
    task.progress = 0.15

    paths = PathAuthority()
    storage = StorageLayer()
    history = HistoryLayer(paths, storage)

    staging_dir = None
    if not getattr(task, "keep_on_pc", False):
        import tempfile
        staging_dir = Path(tempfile.gettempdir()) / "zine_staging" / task.task_id
        staging_dir.mkdir(parents=True, exist_ok=True)
        task.staging_dir = staging_dir
        target_root = staging_dir
    elif getattr(task, "target_root", None):
        target_root = Path(task.target_root)
    elif task.mode == "quick_grab":
        target_root = paths.get_quick_grab_root()
    else:
        target_root = paths.get_vacuum_root()
    target_root.mkdir(parents=True, exist_ok=True)

    files_before = set(target_root.rglob("*"))

    from core.funnel import route_url
    is_quick_grab = (task.mode == "quick_grab")

    try:
        # Check if metadata-only flag is active
        is_metadata_only = any(f in ["--meta", "--metadata"] for f in (task.flags or []))

        # Pass flags, limit, and metadata mode into route_url
        success = route_url(
            task.url,
            history,
            storage,
            batch_path=staging_dir,
            is_batch=True,
            batch_quick_grab=is_quick_grab,
            batch_all=(task.mode == "vacuum" and not task.limit),
            flags=task.flags if task.flags else None,
            chapter_limit=task.limit,
            only_metadata=is_metadata_only
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

        # Size threshold: <= 500MB -> Direct HTTP stream, > 500MB -> LocalSend
        total_bytes = sum(f.stat().st_size for f in new_files if f.is_file())
        size_mb = total_bytes / (1024 * 1024)
        use_localsend = (size_mb > 500.0) or (task.transfer == "localsend")

        task.progress = 0.70
        task.message = f"Scraped {len(new_files)} file(s) ({size_mb:.1f} MB). Preparing delivery..."

        localsend_success = False
        localsend_proc = None
        if use_localsend and task.target_ip:
            task.status = "transferring"
            task.message = f"Large payload ({size_mb:.1f} MB) -> LocalSend transfer..."

            # Auto-launch LocalSend in background on PC if installed and not running
            try:
                out = subprocess.check_output(["pgrep", "-f", "localsend"], text=True)
                is_running = bool(out.strip())
            except Exception:
                is_running = False

            if not is_running and shutil.which("localsend"):
                try:
                    logger.info("Auto-opening LocalSend in background on PC...")
                    localsend_proc = subprocess.Popen(
                        ["localsend", "--hidden"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    time.sleep(1.0)
                except Exception as e:
                    logger.debug(f"Could not auto-start LocalSend on PC: {e}")

            client = LocalSendClient()

            def transfer_cb(msg: str, pct: float):
                task.message = msg
                task.progress = 0.70 + (0.30 * pct)

            try:
                localsend_success = client.send_files(
                    target_ip=task.target_ip,
                    files=new_files,
                    base_dir=target_root,
                    progress_cb=transfer_cb
                )
            finally:
                # Automatically close LocalSend on PC once transfer completes
                if localsend_proc is not None:
                    try:
                        logger.info("Transfer finished. Closing background LocalSend on PC...")
                        localsend_proc.terminate()
                        localsend_proc.wait(timeout=2.0)
                    except Exception:
                        try:
                            localsend_proc.kill()
                        except Exception:
                            pass

        if localsend_success:
            task.status = "completed"
            task.progress = 1.0
            task.message = "Sent to phone via LocalSend successfully!"
        else:
            if use_localsend and task.transfer == "localsend":
                task.status = "failed"
                task.message = "LocalSend push failed (Please ensure LocalSend app is open on phone)"
                task.error = "LocalSend receiver unreachable on port 53317"
            else:
                # Pre-package ZIP asynchronously in background thread so download starts instantly without blocking
                task.message = f"Packaging {len(new_files)} file(s) ({size_mb:.1f} MB)..."
                task.progress = 0.90
                try:
                    import tempfile
                    tmp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
                    with zipfile.ZipFile(tmp_zip.name, "w", zipfile.ZIP_STORED) as zf:
                        for f in new_files:
                            if f.exists() and f.is_file():
                                arcname = str(f.relative_to(target_root)) if f.is_relative_to(target_root) else f.name
                                zf.write(f, arcname=arcname)
                    task.zip_path = Path(tmp_zip.name)
                except Exception as ze:
                    logger.warning(f"Could not pre-package zip: {ze}")

                task.status = "completed"
                task.progress = 1.0
                task.message = f"Media ready for direct download ({size_mb:.1f} MB)"

    except Exception as e:
        logger.exception("Error running scrape task")
        task.status = "failed"
        task.message = "Execution error"
        task.error = str(e)

class ZineServerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "keep-alive")
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
        elif path == "/api/tasks":
            with tasks_lock:
                all_tasks = [t.to_dict() for t in list(tasks.values())]
            all_tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)
            self._send_json(200, {"tasks": all_tasks})
        elif path == "/api/discover":
            client = LocalSendClient()
            devices = client.discover_devices(timeout=1.5)
            self._send_json(200, {"devices": devices})
        elif path.startswith("/api/tasks/"):
            task_id = path.replace("/api/tasks/", "").strip()
            with tasks_lock:
                task = tasks.get(task_id)
            if task:
                self._send_json(200, task.to_dict())
            else:
                self._send_json(404, {"error": "Task not found"})
        elif path.startswith("/api/download/"):
            task_id = path.replace("/api/download/", "").strip()
            with tasks_lock:
                task = tasks.get(task_id)
            if not task:
                self._send_json(404, {"error": "Task not found"})
                return

            zip_to_stream = task.zip_path
            if not zip_to_stream or not zip_to_stream.exists():
                if not task.downloaded_files:
                    self._send_json(404, {"error": "Files not ready or task not found"})
                    return
                # On-the-fly fallback packaging
                import tempfile
                tmp_zip = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
                with zipfile.ZipFile(tmp_zip.name, "w", zipfile.ZIP_STORED) as zf:
                    for f in task.downloaded_files:
                        if f.exists() and f.is_file():
                            arcname = str(f.relative_to(task.base_dir)) if f.is_relative_to(task.base_dir) else f.name
                            zf.write(f, arcname=arcname)
                zip_to_stream = Path(tmp_zip.name)
                task.zip_path = zip_to_stream

            file_size = zip_to_stream.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(file_size))
            self.send_header("Content-Disposition", f'attachment; filename="zine_{task_id}.zip"')
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            with open(zip_to_stream, "rb") as f_in:
                while True:
                    chunk = f_in.read(65536)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        logger.warning(f"Download stream aborted by client for task {task_id}")
                        break
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ["/api/tasks/clear", "/api/clear"]:
            with tasks_lock:
                for t in list(tasks.values()):
                    if getattr(t, "zip_path", None) and t.zip_path.exists():
                        try:
                            t.zip_path.unlink()
                        except Exception:
                            pass
                tasks.clear()
            logger.info("Cleared all scrape tasks on companion server.")
            self._send_json(200, {"status": "cleared", "message": "All tasks cleared"})
            return

        if path.startswith("/api/tasks/") and any(path.endswith(s) for s in ["/stop", "/revolt", "/truncate"]):
            parts = [p for p in path.replace("/api/tasks/", "").split("/") if p]
            task_id = parts[0] if parts else ""
            with tasks_lock:
                task = tasks.get(task_id)
            if not task:
                self._send_json(404, {"error": "Task not found", "task_id": task_id})
                return
            task.is_stopping = True
            task.message = "Stop signal sent (Ctrl+T). Finishing current media and wrapping up..."
            try:
                sig_file = Path(f"/tmp/zine_stop_{task_id}")
                sig_file.write_text("1")
            except Exception:
                pass
            logger.info(f"[TASK {task_id}] Stop signal received from client (Ctrl+T / Revolt).")
            self._send_json(200, {
                "status": "stopping",
                "action": "truncate",
                "message": "Stop signal sent (Ctrl+T). Scraper will wrap up after current media.",
                "task_id": task_id,
            })
            return

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

            mode = str(payload.get("mode", "auto")).strip().lower()
            if not mode:
                mode = "auto"
            flags = payload.get("flags", [])
            limit = payload.get("limit", None)
            if limit is not None:
                try:
                    limit = int(limit)
                except Exception:
                    limit = None

            # Resolve Link Architecture & Validate against Zine Scraper Engines
            resolved = resolve_link_info(url, flags_input=flags, mode_input=mode if mode != "auto" else None, limit_input=limit)
            if not resolved.get("valid"):
                err_msg = resolved.get("error", "Unsupported or invalid media URL")
                logger.warning(f"[REJECTED] URL rejected: {url} -> {err_msg}")
                self._send_json(400, {"error": err_msg, "url": url})
                return

            effective_url = resolved["url"]
            effective_mode = resolved["mode"]
            effective_flags = resolved["flags"]
            site_name = resolved["site_name"]
            category = resolved["category"]
            link_type = resolved["link_type"]
            target_root = Path(resolved["target_root"])
            media_title = resolved.get("title", "")

            target_ip = payload.get("target_ip", self.client_address[0])
            transfer = payload.get("transfer", "hybrid")
            device_name = payload.get("device_name", "Android Device")
            device_brand = payload.get("device_brand", "Android")
            app_name = payload.get("app_name", "Hwaran")
            app_version = payload.get("app_version", "2.1.0")
            client_ip = self.client_address[0]
            timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            task_id = f"tsk_{str(uuid.uuid4())[:8]}"
            task = ScrapeTask(
                task_id=task_id,
                url=effective_url,
                mode=effective_mode,
                target_ip=target_ip,
                transfer=transfer,
                device_name=device_name,
                device_brand=device_brand,
                flags=effective_flags,
                limit=limit,
                site_name=site_name,
                category=category,
                link_type=link_type,
                target_root=target_root,
                keep_on_pc=bool(payload.get("keep_on_pc", False))
            )
            if media_title:
                task.media_title = media_title

            with tasks_lock:
                tasks[task_id] = task

            flags_display = ", ".join(effective_flags) if effective_flags else ("-a (All)" if effective_mode == "vacuum" else "--0 (Single Item)")
            target_display = target_root if task.keep_on_pc else f"Ephemeral Staging (Task {task_id})"
            keep_display = "YES (Archived to PC Library)" if task.keep_on_pc else "NO (Ephemeral Relay / Auto-Cleaned)"
            banner = (
                f"\n{'='*64}\n"
                f"📡 [HWARAN INGESTION SIGNAL RECEIVED]\n"
                f"📱 Client Device : {device_brand} {device_name} ({client_ip})\n"
                f"📦 Source App    : {app_name} v{app_version}\n"
                f"🔗 Target URL    : {effective_url}\n"
                f"🏢 Site Engine   : {site_name} ({category}) [{link_type.upper()}]\n"
                f"🎯 Scrape Scope  : {effective_mode.upper()} (Flags: {flags_display})\n"
                f"📁 Target Root   : {target_display}\n"
                f"🚚 Delivery Mode : {transfer.upper()} (Threshold: Direct <=500MB | LocalSend >500MB)\n"
                f"💾 Keep on PC    : {keep_display}\n"
                f"🆔 Task Assigned : {task_id}\n"
                f"⏱️  Timestamp     : {timestamp_str}\n"
                f"{'='*64}\n"
            )
            print(banner, flush=True)
            logger.info(f"Signal received from {device_brand} {device_name} ({client_ip}): URL={effective_url}, Engine={site_name}, Mode={effective_mode}, Flags={effective_flags}, Task={task_id}")

            # Run in worker thread
            thread = threading.Thread(target=run_scrape_worker, args=(task,), daemon=True)
            thread.start()

            self._send_json(200, task.to_dict())
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ["/api/tasks", "/api/tasks/clear"]:
            with tasks_lock:
                for t in list(tasks.values()):
                    if getattr(t, "zip_path", None) and t.zip_path.exists():
                        try:
                            t.zip_path.unlink()
                        except Exception:
                            pass
                tasks.clear()
            self._send_json(200, {"status": "cleared", "message": "All tasks cleared"})
        elif path.startswith("/api/tasks/"):
            task_id = path.replace("/api/tasks/", "").strip()
            with tasks_lock:
                task = tasks.pop(task_id, None)
                if task and getattr(task, "zip_path", None) and task.zip_path.exists():
                    try:
                        task.zip_path.unlink()
                    except Exception:
                        pass
            self._send_json(200, {"status": "deleted", "task_id": task_id})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

def get_lan_ips() -> List[str]:
    ips = []
    try:
        import socket
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.append(ip)
    except Exception:
        pass
    return ips

def run_udp_beacon(server_port: int, stop_event: threading.Event):
    """
    Broadcasts UDP announcements on LAN so Hwaran can automatically find the server.
    Uses dedicated discovery port 53319 (separate from the HTTP server port 53318)
    so Android clients cannot confuse HTTP traffic with beacon packets.
    Includes socket error recovery so the beacon thread never crashes silently.
    """
    import socket
    BEACON_PORT = 53319  # Dedicated discovery channel, never collides with HTTP

    beacon_data = json.dumps({
        "service": "zine-scraper-server",
        "port": server_port,
        "version": "2.1"
    }).encode("utf-8")

    lan_ips = get_lan_ips()
    broadcast_targets = ["255.255.255.255"]
    for ip in lan_ips:
        parts = ip.split(".")
        if len(parts) == 4:
            subnet_bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
            if subnet_bcast not in broadcast_targets:
                broadcast_targets.append(subnet_bcast)

    beacon_sock = None
    while not stop_event.is_set():
        try:
            if beacon_sock is None:
                beacon_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                beacon_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                beacon_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            for target in broadcast_targets:
                try:
                    beacon_sock.sendto(beacon_data, (target, BEACON_PORT))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Beacon socket error, recreating: {e}")
            try:
                if beacon_sock:
                    beacon_sock.close()
            except Exception:
                pass
            beacon_sock = None
        stop_event.wait(timeout=2.5)

    if beacon_sock:
        try:
            beacon_sock.close()
        except Exception:
            pass

def start_server(port: int = 53318, host: str = "0.0.0.0"):
    server = ThreadingHTTPServer((host, port), ZineServerHandler)
    server.daemon_threads = True
    stop_event = threading.Event()
    beacon_thread = threading.Thread(target=run_udp_beacon, args=(port, stop_event), daemon=True)
    beacon_thread.start()

    lan_ips = get_lan_ips()
    primary_ip = lan_ips[0] if lan_ips else "127.0.0.1"

    print("\n" + "=" * 60)
    print(" 🚀 [Zine Scraper Server] Active & Listening!")
    print(f"    • Local URL:   http://127.0.0.1:{port}")
    for ip in lan_ips:
        print(f"    • Network URL: http://{ip}:{port}")
    print("=" * 60)
    print(f" 📡 LAN Discovery Beacon broadcasting on UDP {port}")
    print(f" 📱 In Hwaran on your phone, connect to: {primary_ip}:{port}")
    print("    Press Ctrl+C to stop.\n")

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
