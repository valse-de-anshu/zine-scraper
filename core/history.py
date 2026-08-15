from datetime import datetime
def _sort_and_dump_history(local_history: dict) -> str:
    def get_date_val(item):
        val = item[1]
        if isinstance(val, dict):
            return val.get("date") or ""
        return ""
    sorted_local = dict(sorted(local_history.items(), key=get_date_val, reverse=True))
    import json
    return json.dumps(sorted_local, indent=2, ensure_ascii=False)
"""
core/history.py
---------------
History Layer: Tracks downloaded item IDs and provides verification interfaces.
No path logic, no storage logic, and no routing logic. Delegates file operations
to StorageLayer and path definitions to PathAuthority.
"""

import re
import json
from typing import Set, Dict, List, Any, Tuple, Optional
from pathlib import Path
from datetime import datetime

from core.paths import PathAuthority
from core.storage import StorageLayer

def _parse_local_history_entry(entry: Any) -> Tuple[str, Optional[str]]:
    """Safely extracts filename and date from history.json value, supporting both old and new formats."""
    if isinstance(entry, dict):
        return entry.get("filename", ""), entry.get("date")
    return str(entry), None

def _is_quick_grab_dir(root_dir: Path) -> bool:
    if "Quick grab" in root_dir.parts or "Quick grab" in str(root_dir):
        return True
    try:
        from core.paths import PathAuthority
        from core.storage import StorageLayer
        from core.config import ConfigLayer
        cfg = ConfigLayer(PathAuthority(), StorageLayer())
        custom_music = cfg.get("music_quick_grab_path")
        if custom_music:
            c_path = Path(custom_music).resolve()
            r_path = Path(root_dir).resolve()
            if c_path == r_path or c_path in r_path.parents:
                return True
    except Exception:
        pass
    return False

class HistoryLayer:
    def __init__(self, paths: PathAuthority, storage: StorageLayer):
        self._paths = paths
        self._storage = storage
        self._history_file = self._paths.get_history_file()
        self._history = self._load_history()

    def reload(self):
        """Forces a fresh reload of the history from disk."""
        self._history = self._load_history()

    def _infer_title(self, url: str) -> str:
        """Derives a human-readable title from a URL if no explicit title was provided."""
        if not url:
            return "Unknown"
        try:
            from urllib.parse import urlparse, unquote
            import html
            parsed = urlparse(url)
            path = unquote(parsed.path).strip("/")
            query = unquote(parsed.query)
            if "view_video.php" in path and "viewkey=" in query:
                m = re.search(r"viewkey=([^&]+)", query)
                if m:
                    return f"PornHub Video ({m.group(1)})"
            if path:
                parts = [p for p in path.split("/") if p]
                if parts:
                    last = parts[-1]
                    if len(parts) > 1 and ("chapter" in last.lower() or "episode" in last.lower() or "season" in last.lower() or "read-" in last.lower()):
                        slug = parts[-2]
                    else:
                        slug = last
                    title = slug.replace("-", " ").replace("_", " ").title()
                    return html.unescape(title)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return url

    def _load_history(self) -> Dict[str, Dict[str, Any]]:
        """Loads history registry from storage layer, supporting both legacy list and structured object schemas."""
        if not self._history_file.exists():
            return {}
        try:
            raw_data = self._storage.read_file(self._history_file)
            if not raw_data.strip():
                return {}
            data = json.loads(raw_data)
            result = {}
            for url, val in data.items():
                if isinstance(val, list):
                    result[url] = {
                        "title": self._infer_title(url),
                        "link": url,
                        "date": None,
                        "info": set(str(x) for x in val)
                    }
                elif isinstance(val, dict):
                    info_items = val.get("info")
                    if info_items is None:
                        info_items = val.get("items", [])
                    result[url] = {
                        "title": val.get("title") or self._infer_title(url),
                        "link": val.get("link") or url,
                        "date": val.get("date"),
                        "info": set(str(x) for x in info_items)
                    }
                else:
                    result[url] = {
                        "title": self._infer_title(url),
                        "link": url,
                        "date": None,
                        "info": set()
                    }
            return result
        except Exception:
            return {}

    def _sort_key(self, item_id: Any):
        try:
            return (0, float(item_id))
        except (ValueError, TypeError):
            return (1, str(item_id))

    def save_history(self):
        """Serializes and writes history to disk atomically through StorageLayer."""
        data = {}
        for url, entry in self._history.items():
            dt = entry.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            title = entry.get("title") or self._infer_title(url)
            info_list = sorted(list(entry.get("info", set())), key=self._sort_key)
            data[url] = {
                "title": title,
                "link": url,
                "date": dt,
                "info": info_list
            }
        raw_data = json.dumps(data, indent=4, ensure_ascii=False)
        self._storage.write_file(self._history_file, raw_data)

    def is_downloaded(self, site_url: str, item_id: str) -> bool:
        """Checks if a specific item has already been downloaded for a site URL."""
        entry = self._history.get(site_url)
        if not entry:
            return False
        info = entry.get("info", set())
        return str(item_id) in info or item_id in info

    def set_title(self, site_url: str, title: str):
        """Explicitly sets or updates the title for a site URL in history."""
        if not site_url or not title:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if site_url not in self._history:
            self._history[site_url] = {
                "title": title,
                "link": site_url,
                "date": dt,
                "info": set()
            }
        else:
            self._history[site_url]["title"] = title
            self._history[site_url]["date"] = dt
        self.save_history()

    def mark_url_tracked(self, site_url: str, title: Optional[str] = None):
        """Registers a site URL in history without any specific items and persists."""
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if site_url not in self._history:
            self._history[site_url] = {
                "title": title or self._infer_title(site_url),
                "link": site_url,
                "date": dt,
                "info": set()
            }
        else:
            entry = self._history[site_url]
            if title:
                entry["title"] = title
            entry["date"] = dt
        self.save_history()

        # Global Revolt shutdown check
        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT <= 0:
                def delayed_exit():
                    import time
                    time.sleep(0.3)
                    ui.clean_exit_revolt()
                import threading
                threading.Thread(target=delayed_exit, daemon=True).start()
            else:
                ui._REVOLT_LIMIT -= 1

    def mark_downloaded(self, site_url: str, item_id: str, title: Optional[str] = None):
        """Marks an item as downloaded for a site URL and persists history."""
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item_id_str = str(item_id)
        if site_url not in self._history:
            self._history[site_url] = {
                "title": title or self._infer_title(site_url),
                "link": site_url,
                "date": dt,
                "info": set()
            }
        
        entry = self._history[site_url]
        if title:
            entry["title"] = title
        entry["date"] = dt

        if item_id_str not in entry["info"]:
            entry["info"].add(item_id_str)
            self.save_history()

        # Global Revolt shutdown check
        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT <= 0:
                def delayed_exit():
                    import time
                    time.sleep(0.3)
                    ui.clean_exit_revolt()
                import threading
                threading.Thread(target=delayed_exit, daemon=True).start()
            else:
                ui._REVOLT_LIMIT -= 1

    def unmark_downloaded(self, site_url: str, item_id: str):
        """Removes an item from downloaded registry for a site URL."""
        item_id_str = str(item_id)
        if site_url in self._history:
            entry = self._history[site_url]
            info = entry.get("info", set())
            if item_id_str in info:
                info.remove(item_id_str)
                self.save_history()

        # Global Revolt shutdown check
        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT <= 0:
                def delayed_exit():
                    import time
                    time.sleep(0.3)
                    ui.clean_exit_revolt()
                import threading
                threading.Thread(target=delayed_exit, daemon=True).start()
            else:
                ui._REVOLT_LIMIT -= 1

    def get_downloaded_items(self, site_url: str) -> Set[str]:
        entry = self._history.get(site_url)
        if not entry:
            return set()
        return entry.get("info", set())

    def sync_local_history(self, root_dir: Path, items: List[Dict[str, Any]], default_ext: str, site_url: str) -> List[str]:
        """
        Synchronizes local .zine/history.json and the global history registry
        against files present on disk. Returns a list of verified item IDs.
        """
        is_quick_grab = "Quick grab" in root_dir.parts or "Quick grab" in str(root_dir)
        if is_quick_grab:
            return []
            
        zine_dir = root_dir / ".zine"
        self._storage.create_directory(zine_dir)
        local_history_file = zine_dir / "history.json"
        
        # Load local history
        local_history = {}
        if local_history_file.exists():
            try:
                local_history = json.loads(self._storage.read_file(local_history_file))
            except Exception:
                pass
                
        verified_ids = []
        claimed_files = set()
        
        # 1. First pass: Verify existing claims
        for item in items:
            item_id = str(item.get("id"))
            if not item_id:
                continue
            if item_id in local_history:
                entry = local_history[item_id]
                filename, _ = _parse_local_history_entry(entry)
                file_path = root_dir / filename
                if file_path.exists():
                    verified_ids.append(item_id)
                    claimed_files.add(filename)
                    # Update upload_date if available
                    up_date = item.get("upload_date")
                    if up_date:
                        if isinstance(entry, dict):
                            entry["date"] = up_date
                        else:
                            local_history[item_id] = {
                                "filename": filename,
                                "date": up_date
                            }
                    # Sync to global history
                    if site_url not in self._history:
                        self._history[site_url] = {
                            "title": self._infer_title(site_url),
                            "link": site_url,
                            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "info": set()
                        }
                    self._history[site_url]["info"].add(item_id)
                else:
                    # File deleted, unmark
                    del local_history[item_id]
                    if site_url in self._history and item_id in self._history[site_url].get("info", set()):
                        self._history[site_url]["info"].remove(item_id)
                    
        # 2. Second pass: Try to claim loose files matching titles for new items
        for item in items:
            item_id = str(item.get("id"))
            if not item_id or item_id in verified_ids:
                continue
                
            item_title = item.get("title") or item.get("filename") or ""
            if item_title and "." in item_title:
                item_title = "".join(item_title.split(".")[:-1])
            clean_title = "".join([c for c in item_title if c.isalnum() or c in " .-_()"]).strip()
            if not clean_title:
                clean_title = f"item_{item_id}"
                
            # Figure out possible extensions
            ext = default_ext.lstrip(".")
            if item.get("is_video"):
                exts = ["mp4"]
            else:
                exts = [ext, "jpg", "png", "jpeg", "flac", "mp3"]
                
            for e in exts:
                candidate_names = [f"{clean_title}.{e}"]
                candidate_names.append(f"{clean_title}_{item_id}.{e}")
                candidate_names.append(f"{clean_title} [{item_id}].{e}")
                
                found = False
                for candidate in candidate_names:
                    if candidate in claimed_files:
                        continue
                    file_path = root_dir / candidate
                    if file_path.exists():
                        dt = item.get("upload_date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        local_history[item_id] = {
                            "filename": candidate,
                            "date": dt
                        }
                        verified_ids.append(item_id)
                        claimed_files.add(candidate)
                        if site_url not in self._history:
                            self._history[site_url] = {
                                "title": self._infer_title(site_url),
                                "link": site_url,
                                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "info": set()
                            }
                        self._history[site_url]["info"].add(item_id)
                        found = True
                        break
                if found:
                    break
                    
            # Fallback: search the directory for any file containing [item_id]
            if not found:
                for f in root_dir.iterdir():
                    if f.is_file() and f.name not in claimed_files and f"[{item_id}]" in f.name:
                        dt = item.get("upload_date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        local_history[item_id] = {
                            "filename": f.name,
                            "date": dt
                        }
                        verified_ids.append(item_id)
                        claimed_files.add(f.name)
                        if site_url not in self._history:
                            self._history[site_url] = {
                                "title": self._infer_title(site_url),
                                "link": site_url,
                                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "info": set()
                            }
                        self._history[site_url]["info"].add(item_id)
                        found = True
                        break
                    
        # Save both global and local history
        self.save_history()

        # Global Revolt shutdown check
        import core.ui as ui
        if ui._REVOLT_ACTIVE:
            if ui._REVOLT_LIMIT <= 0:
                def delayed_exit():
                    import time
                    time.sleep(0.3)
                    ui.clean_exit_revolt()
                import threading
                threading.Thread(target=delayed_exit, daemon=True).start()
            else:
                ui._REVOLT_LIMIT -= 1
        self._storage.write_file(local_history_file, _sort_and_dump_history(local_history))
        return verified_ids

    def resolve_download_path(self, root_dir: Path, item_id: str, title: str, ext: str, date_str: Optional[str] = None, url: Optional[str] = None) -> Tuple[Path, bool]:
        """
        Resolves the final download path for an item, applying collision rules.
        Returns (Path, should_skip).
        """
        if url and title:
            self.set_title(url, title)

        is_quick_grab = _is_quick_grab_dir(root_dir)
        if is_quick_grab:
            import html
            title = html.unescape(title)
            clean_title = "".join([c for c in title if c.isalnum() or c in " .-_()'"]).strip()
            clean_title = re.sub(r'\s{2,}', ' ', clean_title)
            if len(clean_title) > 150:
                clean_title = clean_title[:150].strip()
            if not clean_title:
                clean_title = f"item_{item_id}"
            ext = ext.lstrip(".")
            candidate_name = f"{clean_title}.{ext}"
            candidate_path = root_dir / candidate_name
            return candidate_path, candidate_path.exists()
            
        zine_dir = root_dir / ".zine"
        self._storage.create_directory(zine_dir)
        local_history_file = zine_dir / "history.json"
        
        # Load local history
        local_history = {}
        if local_history_file.exists():
            try:
                local_history = json.loads(self._storage.read_file(local_history_file))
            except Exception:
                pass
                
        import html
        title = html.unescape(title)
        # Clean title for filename
        clean_title = "".join([c for c in title if c.isalnum() or c in " .-_()'"]).strip()
        clean_title = re.sub(r'\s{2,}', ' ', clean_title)
        if len(clean_title) > 150:
            clean_title = clean_title[:150].strip()
        if not clean_title:
            clean_title = f"item_{item_id}"
            
        ext = ext.lstrip(".")
        
        # Check if item_id is already downloaded
        if item_id in local_history:
            entry = local_history[item_id]
            filename, _ = _parse_local_history_entry(entry)
            final_path = root_dir / filename
            if final_path.exists():
                return final_path, True
            else:
                # Reuse the previously registered filename if it's not claimed by another item
                claimed = set()
                for key, val in local_history.items():
                    if key != item_id:
                        fn, _ = _parse_local_history_entry(val)
                        if fn:
                            claimed.add(fn)
                if filename not in claimed:
                    return final_path, False
                
        # Claimed filenames by other items (excluding the current item)
        claimed = set()
        for key, val in local_history.items():
            if key != item_id:
                fn, _ = _parse_local_history_entry(val)
                if fn:
                    claimed.add(fn)
        
        candidate_name = f"{clean_title}.{ext}"
        candidate_path = root_dir / candidate_name
        dt = date_str if date_str else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if candidate_path.exists():
            entry = {
                "filename": candidate_name,
                "date": dt
            }
            if url: entry["url"] = url
            local_history[item_id] = entry
            self._storage.write_file(local_history_file, _sort_and_dump_history(local_history))
            return candidate_path, True

        if candidate_name not in claimed:
            entry = {
                "filename": candidate_name,
                "date": dt
            }
            if url: entry["url"] = url
            local_history[item_id] = entry
            self._storage.write_file(local_history_file, _sort_and_dump_history(local_history))
            return candidate_path, False
            
        counter = 2
        while True:
            candidate_name = f"{clean_title} ({counter}).{ext}"
            candidate_path = root_dir / candidate_name
            if candidate_path.exists():
                entry = {
                    "filename": candidate_name,
                    "date": dt
                }
                if url: entry["url"] = url
                local_history[item_id] = entry
                self._storage.write_file(local_history_file, _sort_and_dump_history(local_history))
                return candidate_path, True
            if candidate_name not in claimed:
                entry = {
                    "filename": candidate_name,
                    "date": dt
                }
                if url: entry["url"] = url
                local_history[item_id] = entry
                self._storage.write_file(local_history_file, _sort_and_dump_history(local_history))
                return candidate_path, False
            counter += 1
