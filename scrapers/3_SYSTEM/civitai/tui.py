"""
scrapers/3_SYSTEM/civitai/tui.py
--------------------------------
Interactive Rich TUI for Civitai / Anima Model Ingestion.

Features:
- Minimalist, high-standard Zine Tree design language (matching asurascans).
- Full Revolt (Ctrl+R) and Truncate (Ctrl+T) integration via set_active_live.
- In-flight chunk cancellation if Ctrl+R is triggered.
- Reads model list from file (format: '<URL> -- <DEST>' or simply '<URL>').
- Never clutters user's Downloads folder; records history into Logs/Downlode 💩/civitai_completed.txt.
- Automatic smart routing to ComfyUI model directories (LoRA, Checkpoint, VAE, etc.).
- Safe fallback to Zine's Vacuum/Models/ directory if flags are missing or ComfyUI is absent.
- Strict no-overwrite protection for existing models.
- Minimalist progress tree with MinimalPulseBar.
- Domain fallback (civitai.red <-> civitai.com).
- Pauses with prompt_return("Press Enter to return to main menu...") before returning.
"""

import os
import sys
import re
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from rich.tree import Tree
from rich.live import Live
from rich.markup import escape
from rich.progress import (
    Progress, TextColumn, TaskProgressColumn,
    DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
)

from core.ui import (
    console,
    startup_clear,
    print_banner,
    prompt_return,
    align_header,
    MinimalPulseBar,
    set_active_live,
    check_revolt,
    check_truncate
)
from core.paths import PathAuthority, sanitize_user_path

try:
    from .location import resolve_model_destination
    from .engine import (
        create_browser_session,
        get_browser_headers,
        extract_api_key_from_lines,
        parse_civitai_target,
        resolve_model_id_to_download_url,
        resolve_download_metadata,
        parallel_download_file,
        remove_line_from_file
    )
except (ImportError, ValueError):
    import importlib.util
    _cur = Path(__file__).parent.resolve()

    def _load(name, path):
        sp = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        return m

    _loc = _load("civitai_location", _cur / "location.py")
    _eng = _load("civitai_engine", _cur / "engine.py")

    resolve_model_destination = _loc.resolve_model_destination
    create_browser_session = _eng.create_browser_session
    get_browser_headers = _eng.get_browser_headers
    extract_api_key_from_lines = _eng.extract_api_key_from_lines
    parse_civitai_target = _eng.parse_civitai_target
    resolve_model_id_to_download_url = _eng.resolve_model_id_to_download_url
    resolve_download_metadata = _eng.resolve_download_metadata
    parallel_download_file = _eng.parallel_download_file
    remove_line_from_file = _eng.remove_line_from_file


def is_stop_requested() -> bool:
    """Returns True if Revolt or Truncate requested immediate termination."""
    try:
        from core.ui import _REVOLT_TRIGGERED, _TRUNCATE_TRIGGERED, _REVOLT_ACTIVE, _REVOLT_LIMIT
        if _REVOLT_TRIGGERED or _TRUNCATE_TRIGGERED:
            return True
        if _REVOLT_ACTIVE and _REVOLT_LIMIT <= 0:
            return True
    except Exception:
        pass
    return False


def get_default_queue_file() -> Path:
    """Finds the default civitai queue file in Zine downloads or user Downloads."""
    paths = PathAuthority()
    candidates = [
        paths.get_downloads_root() / "cavitai.txt",
        paths.get_downloads_root() / "civitai.txt",
        Path.home() / "Downloads" / "Zine" / "cavitai.txt",
        Path.home() / "Downloads" / "Zine" / "civitai.txt",
        Path.home() / "Downloads" / "cavitai.txt",
        Path.home() / "Downloads" / "civitai.txt",
    ]
    for cand in candidates:
        if cand.exists():
            return cand

    default_f = paths.get_downloads_root() / "cavitai.txt"
    try:
        default_f.parent.mkdir(parents=True, exist_ok=True)
        default_f.write_text(
            "## api key - \n# Add Civitai / Anima model URLs here to download with multi-stream acceleration.\n# Format: <URL> [-- <DESTINATION_PATH>]\n# If destination is omitted, models automatically route to ComfyUI or Vacuum/Models/.\n# Example: https://civitai.com/models/12345/my-model?modelVersionId=67890 -- /mnt/maiden/comfyui-portable/ComfyUI/models/loras/anima/pose\n",
            encoding="utf-8"
        )
    except Exception:
        pass
    return default_f


def get_completed_log_path() -> Path:
    """Returns the central completed history file, avoiding cluttering the Downloads folder."""
    paths = PathAuthority()
    log_dir = paths.get_suite_root() / "Logs" / "Downlode 💩"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "civitai_completed.txt"


def format_bytes(num_bytes: int) -> str:
    """Formats raw byte count into human-readable string."""
    if not num_bytes:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def run_civitai_tui(input_file: Optional[str] = None, threads: int = 6, max_retries: int = 5) -> bool:
    """
    Launches the Civitai / Anima Model Downloader TUI in clean Zine standard.
    """
    startup_clear()
    print_banner()

    target_path: Path
    if input_file and input_file.strip().lower() not in ("", "model", "models", "default", "none"):
        sanitized = sanitize_user_path(input_file)
        target_path = Path(sanitized).expanduser().resolve()
        if not target_path.exists():
            default_cand = get_default_queue_file()
            if default_cand.exists():
                console.print(f"[warning]● Specified file [site]{escape(str(target_path))}[/site] not found. Falling back to default queue:[/warning] [site]{escape(str(default_cand))}[/site]\n")
                target_path = default_cand
    else:
        target_path = get_default_queue_file()

    completed_path = get_completed_log_path()

    if not target_path.exists():
        console.print(f"[error]● Queue file not found:[/error] [site]{escape(str(target_path))}[/site]")
        console.print(f"[info]Create a file with format: [/info][warning]<Civitai_URL> [-- <DESTINATION_PATH>][/warning]")
        console.print(f"[dim white]If no destination flag is provided, models auto-route to ComfyUI or Vacuum/Models/.[/dim white]\n")
        prompt_return("Press Enter to return to main menu...")
        return False

    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            raw_lines = f.readlines()
    except Exception as e:
        console.print(f"[error]● Failed to read queue file:[/error] {escape(str(e))}")
        prompt_return("Press Enter to return to main menu...")
        return False

    from core.secrets import get_secret, set_secret
    api_key = os.environ.get('CIVITAI_API_KEY') or get_secret("civitai.api_key") or extract_api_key_from_lines(raw_lines)
    if api_key and not get_secret("civitai.api_key"):
        try:
            set_secret("civitai.api_key", api_key)
        except Exception:
            pass
    session = create_browser_session(pool_size=threads * 2)
    headers = get_browser_headers(api_key=api_key)

    delim_regex = re.compile(r'\s+--\s*|\s*--\s+|--(?=/)')
    tasks: List[Tuple[str, str, Optional[str]]] = []
    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = delim_regex.search(stripped)
        if match:
            url = stripped[:match.start()].strip()
            explicit_dest = stripped[match.end():].strip()
        else:
            url = stripped
            explicit_dest = None

        if url.count("://") > 1:
            extracted = re.findall(r'https?://[^\s]+', url)
            url = extracted[-1] if extracted else url

        tasks.append((line, url, explicit_dest if explicit_dest else None))

    # Clean minimalist header matching asurascans
    console.print(f"[menu]Menu[/menu]         : [site]Anima / Civitai Downloader[/site]")
    console.print(f"[menu]Queue[/menu]        : [sexy_pink]{target_path.resolve()}[/sexy_pink]")
    console.print(f"[menu]Destination[/menu]  : [info]Smart ComfyUI Auto-Route (Vacuum Fallback)[/info]")
    if api_key:
        masked_key = f"{api_key[:6]}...{api_key[-4:]}"
        console.print(f"[menu]API Key[/menu]      : [success]● Active ({masked_key})[/success]")
    else:
        console.print(f"[menu]API Key[/menu]      : [dim white]None detected (public models only)[/dim white]")
    console.print(f"[menu]Pending[/menu]      : [info]{len(tasks)} model(s)[/info]")
    console.print("")

    if not tasks:
        console.print("[success]All models are already downloaded.[/success]\n")
        prompt_return("Press Enter to return to main menu...")
        return True

    results: List[Dict[str, Any]] = []
    console.show_cursor(False)

    try:
        for step, (orig_line, url, explicit_dest) in enumerate(tasks, start=1):
            # Check Revolt / Truncate before starting next model
            if check_revolt(title="Civitai Model Ingestion"):
                break
            if check_truncate(title="Civitai Model Ingestion"):
                break

            # 1. Parse URL & resolve download link + model metadata
            try:
                download_url, domain, mvid, model_id = parse_civitai_target(url)
                if not download_url:
                    download_url, mvid, m_info = resolve_model_id_to_download_url(
                        session=session,
                        model_id=model_id,
                        domain=domain,
                        headers=headers,
                        api_key=api_key
                    )

                if api_key and 'token=' not in download_url:
                    delimiter = '&' if '?' in download_url else '?'
                    download_url = f"{download_url}{delimiter}token={api_key}"

                try:
                    meta = resolve_download_metadata(
                        session=session,
                        download_url=download_url,
                        domain=domain,
                        mvid=mvid,
                        model_id=model_id,
                        headers=headers,
                        api_key=api_key
                    )
                except Exception as e_domain:
                    if "civitai.red" in download_url:
                        fallback_url = download_url.replace("civitai.red", "civitai.com")
                        meta = resolve_download_metadata(
                            session=session,
                            download_url=fallback_url,
                            domain="civitai.com",
                            mvid=mvid,
                            model_id=model_id,
                            headers=headers,
                            api_key=api_key
                        )
                        download_url = fallback_url
                    else:
                        raise e_domain

            except Exception as e:
                console.print(f"  [error]✘[/error] [unselected]{escape(url[:50])}[/unselected] [error]Failed to resolve ({escape(str(e))})[/error]\n")
                results.append({
                    "url": url,
                    "filename": "Unknown",
                    "size": 0,
                    "dest": explicit_dest or "Unknown",
                    "status": "Failed",
                    "error": str(e)
                })
                continue

            filename = meta["filename"]
            total_size = meta["total_size"]
            final_download_url = meta["final_url"]

            # 2. Destination Resolution
            dest_dir_path, dest_reason = resolve_model_destination(
                explicit_dest=explicit_dest,
                model_type=meta.get("model_type"),
                base_model=meta.get("base_model"),
                model_name=meta.get("model_name"),
                tags=meta.get("tags")
            )
            dest_dir_path.mkdir(parents=True, exist_ok=True)
            target_file = dest_dir_path / filename

            # 3. Strict No-Overwrite Protection
            if target_file.exists():
                if target_file.stat().st_size > 0:
                    console.print(f"  [warning]●[/warning] [unselected]{filename}[/unselected] [dim yellow]Already on disk (Skipped)[/dim yellow]")
                    try:
                        with open(completed_path, 'a', encoding='utf-8') as cf:
                            cf.write(orig_line.rstrip('\n') + f"  # [EXISTED ON DISK: {filename}]\n")
                        remove_line_from_file(target_path, orig_line)
                    except Exception:
                        pass
                    results.append({
                        "url": url,
                        "filename": filename,
                        "size": target_file.stat().st_size,
                        "dest": str(target_file.parent),
                        "status": "Existed (Skipped)"
                    })
                    continue
                else:
                    try:
                        target_file.unlink()
                    except Exception:
                        pass

            # 4. Active Download with Live Tree + MinimalPulseBar & Full Revolt/Truncate integration
            dl_data = {
                "downloaded": 0,
                "total": total_size,
                "done": False,
                "success": False,
                "status": ""
            }

            progress_bar = Progress(
                TextColumn("[bold cyan]{task.description}"),
                MinimalPulseBar(bar_width=28),
                TaskProgressColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                transient=False,
            )
            task_id = progress_bar.add_task("Stream", total=total_size if total_size > 0 else None)

            def render_model_tree() -> Tree:
                tree = Tree(f"[info]●[/info] [menu]Progress[/menu] [dim white]({step}/{len(tasks)})[/dim white]", guide_style="unselected")
                tree.add(f"{'Current':<14}: [site]{filename[:36]}[/site]")
                tree.add(f"{'Saved To':<14}: [sexy_pink]{dest_dir_path.resolve()}[/sexy_pink]")
                tree.add(f"{'Size':<14}: [dim white]{format_bytes(total_size)}[/dim white]")

                res_branch = tree.add("[success]○[/success] [menu]Result[/menu]", guide_style="unselected")
                if not dl_data["done"]:
                    res_branch.add(progress_bar)
                else:
                    succ = dl_data.get("success", False)
                    res_color = "success" if succ else "error"
                    res_text = "Complete" if succ else f"Failed ({dl_data.get('status', 'Error')})"
                    res_branch.add(f"[{res_color}]● {res_text}[/{res_color}]")
                return tree

            def progress_cb(chunk_len: int):
                progress_bar.update(task_id, advance=chunk_len)

            success = False
            with Live(get_renderable=render_model_tree, console=console, refresh_per_second=12, transient=True) as live:
                set_active_live(live)
                try:
                    success = parallel_download_file(
                        session=session,
                        download_url=final_download_url,
                        target_path=str(target_file),
                        total_size=total_size,
                        headers=headers,
                        threads=threads,
                        max_retries=max_retries,
                        progress_callback=progress_cb,
                        stop_check=is_stop_requested
                    )
                    dl_data["done"] = True
                    dl_data["success"] = success
                except Exception as dl_err:
                    dl_data["done"] = True
                    dl_data["success"] = False
                    dl_data["status"] = str(dl_err)
                    success = False
                finally:
                    set_active_live(None)

            # Live has exited normally here
            if success and target_file.exists():
                actual_size = target_file.stat().st_size
                console.print(f"  [success]●[/success] [unselected]{filename}[/unselected] [dim white]({format_bytes(actual_size)})[/dim white] ⬩➤ [sexy_pink]{dest_dir_path.resolve()}[/sexy_pink]")
                try:
                    with open(completed_path, 'a', encoding='utf-8') as cf:
                        cf.write(orig_line.rstrip('\n') + f"  # [SAVED: {filename}]\n")
                    remove_line_from_file(target_path, orig_line)
                except Exception:
                    pass
                results.append({
                    "url": url,
                    "filename": filename,
                    "size": actual_size,
                    "dest": str(target_file.parent),
                    "status": "Downloaded"
                })
            else:
                err_text = dl_data.get("status") or "Interrupted"
                console.print(f"  [error]✘[/error] [unselected]{filename}[/unselected] [error]Failed ({err_text})[/error]")
                results.append({
                    "url": url,
                    "filename": filename,
                    "size": total_size,
                    "dest": str(dest_dir_path),
                    "status": "Failed"
                })

            console.print(" ")

            # Check Revolt / Truncate post-item
            if check_revolt(title="Civitai Model Ingestion"):
                break
            if check_truncate(title="Civitai Model Ingestion"):
                break

    finally:
        console.show_cursor(True)

    # 5. Final Results Summary Report (clean minimalist)
    downloaded_count = sum(1 for r in results if r["status"] == "Downloaded")
    existed_count = sum(1 for r in results if "Existed" in r["status"])
    failed_count = sum(1 for r in results if r["status"] == "Failed")

    console.print("")
    console.print(f"[success]✦[/success] [bold white]Done: Ingestion Summary[/bold white]")
    console.print(f"  {'Total Processed':<18} : [info]{len(results)}[/info]")
    console.print(f"  {'Downloaded':<18} : [success]{downloaded_count}[/success]")
    console.print(f"  {'Already on Disk':<18} : [warning]{existed_count}[/warning]")
    if failed_count > 0:
        console.print(f"  {'Failed':<18} : [error]{failed_count}[/error]")
    console.print("")

    prompt_return("Press Enter to return to main menu...")
    return failed_count == 0
