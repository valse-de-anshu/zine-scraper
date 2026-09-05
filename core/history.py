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
    _active_instance = None

    def __init__(self, paths: PathAuthority, storage: StorageLayer):
        self._paths = paths
        self._storage = storage
        self._history_file = self._paths.get_history_file()
        self._history = self._load_history()
        HistoryLayer._active_instance = self

    @staticmethod
    def normalize_url(url: str) -> str:
        """Canonicalizes a URL by trimming whitespace, lowercasing scheme/host, stripping trailing slashes, and collapsing chapter endpoints."""
        if not url or not isinstance(url, str):
            return ""
        url = url.strip()
        try:
            from urllib.parse import urlsplit, urlunsplit
            parsed = urlsplit(url)
            if not parsed.scheme or not parsed.netloc:
                norm = url.rstrip("/")
            else:
                scheme = parsed.scheme.lower()
                netloc = parsed.netloc.lower()
                path = parsed.path.rstrip("/")
                norm = urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))
        except Exception:
            norm = url.rstrip("/")

        # Canonicalize chapter endpoints to parent series root
        try:
            # AsuraScans: /comics/{slug}/chapter/... -> /comics/{slug}
            m = re.match(r"(https?://(?:www\.)?asurascans\.[^/]+/comics/[^/]+)/chapter/.*", norm, re.I)
            if m: return m.group(1)
            # OmegaScans: /series/{slug}/{ch_slug} -> /series/{slug}
            m = re.match(r"(https?://(?:www\.)?omegascans\.[^/]+/series/[^/]+)/[^/]+", norm, re.I)
            if m: return m.group(1)
            # ProjectSuki: /read/{book_id}/... -> /book/{book_id}
            m = re.match(r"(https?://(?:www\.)?projectsuki\.[^/]+)/read/(\d+)(?:/.*)?", norm, re.I)
            if m: return f"{m.group(1)}/book/{m.group(2)}"
            # ManhuaPlus: /manga/{slug}/chapter-.* -> /manga/{slug}
            m = re.match(r"(https?://(?:www\.)?manhuaplus\.[^/]+/manga/[^/]+)/chapter-.*", norm, re.I)
            if m: return m.group(1)
            # MangaK: /{slug}/chapter-.* -> /{slug}
            m = re.match(r"(https?://(?:www\.)?mangak\.[^/]+/[^/]+)/(?:chapter|ch)-.*", norm, re.I)
            if m: return m.group(1)
            # ManhwaUS: /webtoon/{slug}/chapter-.* -> /webtoon/{slug}
            m = re.match(r"(https?://(?:www\.)?manhwaus\.[^/]+/webtoon/[^/]+)/chapter-.*", norm, re.I)
            if m: return m.group(1)
            # Generic pattern for /series/{slug}/chapter/..., /comic/{slug}/chapter/..., /manga/{slug}/chapter/...
            m = re.match(r"(https?://[^/]+/(?:series|manga|comic|comics|webtoon)/[^/]+)/(?:chapter|c|ch|read)[\d/.-].*", norm, re.I)
            if m: return m.group(1)
        except Exception:
            pass

        return norm

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
                    generic_suffixes = ("videos", "video", "uploads", "photos", "posts", "reels", "all", "tracks", "discography")
                    if len(parts) > 1 and (
                        "chapter" in last.lower()
                        or "episode" in last.lower()
                        or "season" in last.lower()
                        or "read-" in last.lower()
                        or last.lower() in generic_suffixes
                    ):
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
            for raw_url, val in data.items():
                url = self.normalize_url(raw_url)
                if not url:
                    continue
                flags = []
                if isinstance(val, list):
                    info_items = set(str(x) for x in val)
                    title = self._infer_title(url)
                    date_val = None
                elif isinstance(val, dict):
                    raw_items = val.get("info")
                    if raw_items is None:
                        raw_items = val.get("items", [])
                    info_items = set(str(x) for x in raw_items)
                    title = val.get("title") or self._infer_title(url)
                    date_val = val.get("date")
                    raw_flags = val.get("flags", [])
                    if isinstance(raw_flags, str):
                        flags = [raw_flags]
                    elif isinstance(raw_flags, list):
                        flags = [str(f) for f in raw_flags]
                else:
                    info_items = set()
                    title = self._infer_title(url)
                    date_val = None

                if url in result:
                    result[url]["info"].update(info_items)
                    existing_title = result[url]["title"]
                    if (not existing_title or existing_title == self._infer_title(url)) and title:
                        result[url]["title"] = title
                    if date_val and (not result[url]["date"] or date_val > result[url]["date"]):
                        result[url]["date"] = date_val
                    for flg in flags:
                        if flg not in result[url]["flags"]:
                            result[url]["flags"].append(flg)
                else:
                    result[url] = {
                        "title": title,
                        "date": date_val,
                        "flags": flags,
                        "info": info_items
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
        """Serializes and writes history to disk atomically through StorageLayer, merging with disk to preserve titles."""
        disk_data = {}
        if self._history_file.exists():
            try:
                raw_data = self._storage.read_file(self._history_file)
                if raw_data.strip():
                    disk_data = json.loads(raw_data)
            except Exception:
                pass

        def is_valid_title(t):
            if not t:
                return False
            t_str = str(t).strip()
            if not t_str or t_str.lower() in ("videos", "video", "unknown", "watch"):
                return False
            if t_str.startswith("PornHub Video ("):
                return False
            return True

        # Normalize disk entries into canonical URLs
        disk_normalized: Dict[str, Dict[str, Any]] = {}
        for raw_k, v in disk_data.items():
            norm_k = self.normalize_url(raw_k)
            if not norm_k:
                continue
            v_dict = v if isinstance(v, dict) else {"info": v if isinstance(v, list) else []}
            v_info = set(str(x) for x in v_dict.get("info", []))
            v_title = v_dict.get("title")
            v_date = v_dict.get("date")
            raw_fl = v_dict.get("flags", [])
            v_flags = [str(f) for f in raw_fl] if isinstance(raw_fl, list) else ([str(raw_fl)] if isinstance(raw_fl, str) else [])

            if norm_k in disk_normalized:
                disk_normalized[norm_k]["info"].update(v_info)
                if not is_valid_title(disk_normalized[norm_k]["title"]) and is_valid_title(v_title):
                    disk_normalized[norm_k]["title"] = v_title
                if v_date and v_date > (disk_normalized[norm_k].get("date") or ""):
                    disk_normalized[norm_k]["date"] = v_date
                for fl in v_flags:
                    if fl not in disk_normalized[norm_k]["flags"]:
                        disk_normalized[norm_k]["flags"].append(fl)
            else:
                disk_normalized[norm_k] = {
                    "title": v_title,
                    "date": v_date,
                    "flags": v_flags,
                    "info": v_info
                }

        # Normalize memory entries into canonical URLs
        mem_normalized: Dict[str, Dict[str, Any]] = {}
        for raw_k, v in self._history.items():
            norm_k = self.normalize_url(raw_k)
            if not norm_k:
                continue
            v_info = v.get("info", set())
            if isinstance(v_info, list):
                v_info = set(str(x) for x in v_info)
            else:
                v_info = set(str(x) for x in v_info)
            v_title = v.get("title")
            v_date = v.get("date")
            raw_fl = v.get("flags", [])
            v_flags = [str(f) for f in raw_fl] if isinstance(raw_fl, list) else ([str(raw_fl)] if isinstance(raw_fl, str) else [])

            if norm_k in mem_normalized:
                mem_normalized[norm_k]["info"].update(v_info)
                if not is_valid_title(mem_normalized[norm_k]["title"]) and is_valid_title(v_title):
                    mem_normalized[norm_k]["title"] = v_title
                if v_date and v_date > (mem_normalized[norm_k].get("date") or ""):
                    mem_normalized[norm_k]["date"] = v_date
                for fl in v_flags:
                    if fl not in mem_normalized[norm_k]["flags"]:
                        mem_normalized[norm_k]["flags"].append(fl)
            else:
                mem_normalized[norm_k] = {
                    "title": v_title,
                    "date": v_date,
                    "flags": v_flags,
                    "info": v_info
                }

        self._history = mem_normalized

        data = {}
        all_urls = list(dict.fromkeys(list(mem_normalized.keys()) + list(disk_normalized.keys())))

        for url in all_urls:
            mem_entry = mem_normalized.get(url, {})
            disk_entry = disk_normalized.get(url, {})

            mem_title = mem_entry.get("title")
            disk_title = disk_entry.get("title")

            if is_valid_title(mem_title):
                chosen_title = mem_title
            elif is_valid_title(disk_title):
                chosen_title = disk_title
            else:
                chosen_title = mem_title or disk_title or self._infer_title(url)

            dt = mem_entry.get("date") or disk_entry.get("date") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            combined_info = mem_entry.get("info", set()) | disk_entry.get("info", set())

            # Skip writing empty ghost entries with zero downloaded items
            if not combined_info:
                continue

            mem_flags = mem_entry.get("flags", [])
            disk_flags = disk_entry.get("flags", [])
            combined_flags = []
            for fl in (mem_flags + disk_flags):
                if fl and fl not in combined_flags:
                    combined_flags.append(fl)

            payload = {
                "title": chosen_title,
                "date": dt,
            }
            if combined_flags:
                payload["flags"] = combined_flags
            payload["info"] = sorted(list(combined_info), key=self._sort_key)

            data[url] = payload
            self._history[url] = {
                "title": chosen_title,
                "date": dt,
                "flags": combined_flags,
                "info": combined_info
            }

        raw_data = json.dumps(data, indent=4, ensure_ascii=False)
        self._storage.write_file(self._history_file, raw_data)

    def is_downloaded(self, site_url: str, item_id: str) -> bool:
        """Checks if a specific item has already been downloaded for a site URL."""
        site_url = self.normalize_url(site_url)
        entry = self._history.get(site_url)
        if not entry:
            return False
        info = entry.get("info", set())
        return str(item_id) in info or item_id in info

    def set_title(self, site_url: str, title: str, flags: Optional[List[str]] = None):
        """Explicitly sets or updates the title for a site URL in history."""
        site_url = self.normalize_url(site_url)
        if not site_url or not title:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not flags:
            flags = getattr(self, "_active_batch_flags", None)
        if site_url not in self._history:
            self._history[site_url] = {
                "title": title,
                "date": dt,
                "flags": list(flags) if flags else [],
                "info": set()
            }
        else:
            self._history[site_url]["title"] = title
            self._history[site_url]["date"] = dt
            if flags:
                existing_flags = self._history[site_url].setdefault("flags", [])
                for f in flags:
                    if f not in existing_flags:
                        existing_flags.append(f)
        self.save_history()

    def mark_url_tracked(self, site_url: str, title: Optional[str] = None):
        """Registers a site URL in history without any specific items and persists."""
        site_url = self.normalize_url(site_url)
        if not site_url:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        flags = getattr(self, "_active_batch_flags", None)
        if site_url not in self._history:
            self._history[site_url] = {
                "title": title or self._infer_title(site_url),
                "date": dt,
                "flags": list(flags) if flags else [],
                "info": set()
            }
        else:
            entry = self._history[site_url]
            if title:
                entry["title"] = title
            entry["date"] = dt
            if flags:
                existing_flags = entry.setdefault("flags", [])
                for f in flags:
                    if f not in existing_flags:
                        existing_flags.append(f)
        self.save_history()

    def mark_downloaded(self, site_url: str, item_id: str, title: Optional[str] = None, flags: Optional[List[str]] = None):
        """Marks an item as downloaded for a site URL and persists history."""
        site_url = self.normalize_url(site_url)
        if not site_url:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item_id_str = str(item_id)
        if not flags:
            flags = getattr(self, "_active_batch_flags", None)

        if site_url not in self._history:
            disk_history = self._load_history()
            if site_url in disk_history:
                self._history[site_url] = disk_history[site_url]
            else:
                self._history[site_url] = {
                    "title": title or self._infer_title(site_url),
                    "date": dt,
                    "flags": list(flags) if flags else [],
                    "info": set()
                }
        
        entry = self._history[site_url]
        if title and title != "Unknown":
            entry["title"] = title
        if flags:
            existing_flags = entry.setdefault("flags", [])
            for f in flags:
                if f not in existing_flags:
                    existing_flags.append(f)
        entry.setdefault("info", set()).add(item_id_str)
        entry["date"] = dt
        self.save_history()

        # Seamlessly update BatchHistoryManager if active
        if BatchHistoryManager._instance:
            BatchHistoryManager._instance.update_item(site_url, item_id_str, title=title or entry.get("title"))

    def unmark_downloaded(self, site_url: str, item_id: str):
        """Removes an item from downloaded registry for a site URL."""
        site_url = self.normalize_url(site_url)
        if not site_url:
            return
        item_id_str = str(item_id)
        if site_url in self._history:
            entry = self._history[site_url]
            info = entry.get("info", set())
            if item_id_str in info:
                info.remove(item_id_str)
                self.save_history()

    def get_downloaded_items(self, site_url: str) -> Set[str]:
        site_url = self.normalize_url(site_url)
        entry = self._history.get(site_url)
        if not entry:
            return set()
        return entry.get("info", set())

    def sync_local_history(self, root_dir: Path, items: List[Dict[str, Any]], default_ext: str, site_url: str) -> List[str]:
        """
        Synchronizes local .zine/history.json and the global history registry
        against files present on disk. Returns a list of verified item IDs.
        """
        site_url = self.normalize_url(site_url)
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
                                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "info": set()
                            }
                        self._history[site_url]["info"].add(item_id)
                        found = True
                        break
                    
        # Save both global and local history
        self.save_history()
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
            # Never prepend or keep leading numbers in Quick Grab
            title = re.sub(r'^\d+[\.\s\-]+\s*', '', title).strip() or title
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
        # Never prepend or keep leading numbers for songs
        if root_dir.name.lower() == "song" or "/song" in str(root_dir).lower():
            title = re.sub(r'^\d+[\.\s\-]+\s*', '', title).strip() or title
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


class BatchHistoryManager:
    """
    Manages structural JSON history for Batch execution.
    Tracks raw inputs, flags (e.g. --0), canonical URLs, titles, download statuses,
    and chapter/file IDs with atomic per-item persistence and non-destructive reload.
    Maintains synchronization across Logs/Batch History.json and Logs/💩/batch_history.json.
    """
    _instance = None

    def __init__(self, paths: PathAuthority, storage: StorageLayer):
        self._paths = paths
        self._storage = storage
        self._batch_file = self._paths.get_batch_history_file()
        self._poop_file = self._paths.get_batch_poop_log()
        self._history: Dict[str, Dict[str, Any]] = self._load()
        BatchHistoryManager._instance = self

    def _load(self) -> Dict[str, Dict[str, Any]]:
        data = {}
        for target in [self._batch_file, self._poop_file]:
            if target.exists():
                try:
                    content = self._storage.read_file(target)
                    if content.strip():
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                norm_k = HistoryLayer.normalize_url(k)
                                if not norm_k:
                                    continue
                                if norm_k not in data:
                                    data[norm_k] = v
                                else:
                                    # Non-destructive merge preserving completion status
                                    existing = data[norm_k]
                                    if isinstance(v, dict):
                                        if v.get("status") == "completed":
                                            existing["status"] = "completed"
                                        if v.get("title") and v.get("title") != "Unknown":
                                            existing["title"] = v.get("title")
                                        v_info = set(str(x) for x in v.get("info", []))
                                        e_info = set(str(x) for x in existing.get("info", []))
                                        existing["info"] = sorted(
                                            list(e_info | v_info),
                                            key=lambda x: (0, float(x)) if x.replace('.', '', 1).isdigit() else (1, str(x))
                                        )
                except Exception:
                    pass
        return data

    def save(self):
        """Atomically saves batch history to both Logs/Batch History.json and Logs/💩/batch_history.json."""
        try:
            def get_sort_date(item):
                v = item[1]
                if isinstance(v, dict):
                    return v.get("date") or v.get("finish_date") or v.get("start_date") or ""
                return ""

            sorted_history = dict(sorted(self._history.items(), key=get_sort_date, reverse=True))
            raw = json.dumps(sorted_history, indent=4, ensure_ascii=False)
            
            # Write to primary Logs/Batch History.json
            self._storage.write_file(self._batch_file, raw)
            
            # Mirror to Logs/💩/batch_history.json
            self._storage.create_directory(self._poop_file.parent)
            self._storage.write_file(self._poop_file, raw)
        except Exception:
            pass

    def record_start(self, raw_input: str, url: str, flags: List[str], mode: str, title: Optional[str] = None):
        """Initializes or updates a batch item record as in_progress without destroying existing progress."""
        norm_url = HistoryLayer.normalize_url(url)
        if not norm_url:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing = self._history.get(norm_url, {})
        existing_info = set(str(x) for x in existing.get("info", []))

        # Preserve existing flags
        combined_flags = list(dict.fromkeys(existing.get("flags", []) + flags))

        self._history[norm_url] = {
            "title": title or existing.get("title") or "Unknown",
            "url": norm_url,
            "raw_input": raw_input,
            "flags": combined_flags,
            "mode": mode,
            "status": "in_progress",
            "start_date": existing.get("start_date") or dt,
            "date": dt,
            "info": sorted(
                list(existing_info),
                key=lambda x: (0, float(x)) if x.replace('.', '', 1).isdigit() else (1, str(x))
            )
        }
        self.save()

    def update_item(self, url: str, item_id: str, title: Optional[str] = None):
        """Appends a downloaded item/chapter ID in real time during active scraping."""
        norm_url = HistoryLayer.normalize_url(url)
        if not norm_url:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = self._history.get(norm_url)
        if not entry:
            entry = {
                "title": title or "Unknown",
                "url": norm_url,
                "raw_input": norm_url,
                "flags": [],
                "mode": "Vacuum",
                "status": "in_progress",
                "start_date": dt,
                "date": dt,
                "info": []
            }
            self._history[norm_url] = entry
        if title and title != "Unknown":
            entry["title"] = title
        cur_info = set(str(x) for x in entry.get("info", []))
        cur_info.add(str(item_id))
        entry["info"] = sorted(
            list(cur_info),
            key=lambda x: (0, float(x)) if x.replace('.', '', 1).isdigit() else (1, str(x))
        )
        entry["date"] = dt
        self.save()

    def record_finish(self, url: str, status: str = "completed", title: Optional[str] = None, save_path: Optional[str] = None):
        """Marks a batch item as finished (completed/failed/interrupted) and updates final metadata."""
        norm_url = HistoryLayer.normalize_url(url)
        if not norm_url:
            return
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = self._history.get(norm_url)
        if not entry:
            entry = {
                "title": title or "Unknown",
                "url": norm_url,
                "raw_input": norm_url,
                "flags": [],
                "mode": "Vacuum",
                "status": status,
                "start_date": dt,
                "date": dt,
                "info": []
            }
            self._history[norm_url] = entry
        if title and title != "Unknown":
            entry["title"] = title
        entry["status"] = status
        entry["finish_date"] = dt
        entry["date"] = dt
        if save_path:
            entry["save_path"] = str(save_path)
        self.save()
