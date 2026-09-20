"""
core/cli_help.py
----------------
Comprehensive command-line interface utilities, documentation, diagnostics,
and system inspection tools for Zine Scraper Suite.
"""

import sys
import os
import shutil
import platform
import subprocess
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.box import ROUNDED, SIMPLE, DOUBLE_EDGE

console = Console()

ZINE_VERSION = "1.2.0"
ZINE_CODENAME = "Nightingale"


def print_cli_banner():
    banner_text = Text()
    banner_text.append("◆ ZINE SCRAPER SUITE ◆", style="bold cyan")
    banner_text.append(f"  v{ZINE_VERSION}", style="dim white")
    banner_text.append(f" ({ZINE_CODENAME})\n", style="bold magenta")
    banner_text.append("High-performance media archiving & CLI suite", style="dim italic white")
    console.print(Panel(banner_text, box=ROUNDED, border_style="cyan", padding=(0, 2)))


def print_cli_help():
    """Renders the master CLI manual for developers and users."""
    print_cli_banner()

    # USAGE
    usage_text = Text()
    usage_text.append("  zine ", style="bold green")
    usage_text.append("[OPTIONS] ", style="yellow")
    usage_text.append("<URL>\n", style="bold cyan")
    usage_text.append("  zine ", style="bold green")
    usage_text.append("[COMMAND] ", style="yellow")
    usage_text.append("[ARGS...]\n", style="bold white")
    usage_text.append("  python3 orchestrator.py ", style="bold green")
    usage_text.append("[OPTIONS] <URL>", style="yellow")
    console.print(Panel(usage_text, title="[bold white]USAGE[/bold white]", title_align="left", box=ROUNDED, border_style="blue"))

    # FLAGS & OPTIONS TABLE
    opt_table = Table(box=SIMPLE, show_header=True, header_style="bold cyan", padding=(0, 1))
    opt_table.add_column("Flag / Option", style="bold yellow", min_width=22)
    opt_table.add_column("Description", style="white")

    opt_table.add_row("--0", "Quick Grab mode: downloads single chapter/episode directly into 'Quick grab/' without series folder.")
    opt_table.add_row("-a, --a, --A, --all", "Vacuum mode: downloads entire franchise/series with full metadata, cover art & directory hierarchy into 'Vacuum/'.")
    opt_table.add_row("--meta, --metadata", "Metadata Extractor: extracts & writes .zine/metadata.json (and cover) into Vacuum/ without downloading media.")
    opt_table.add_row("-<N>, --<N>", "Sequential limit: continues from last read chapter in history and grabs exactly N chapters (e.g. --5, --10).")
    opt_table.add_row("--vacuum [FILE]\n--batch [FILE]", "Vacuum queue mode: processes URLs from specified text file headlessly into Vacuum/ (defaults to 'vacuum.txt').")
    opt_table.add_row("-h, --help", "Display this comprehensive CLI manual and exit.")
    opt_table.add_row("-v, --version", "Print version, system environment, and tool dependency status.")
    opt_table.add_row("sites, --sites", "List all supported categories, platforms, and primary domains.")
    opt_table.add_row("doctor, --doctor", "Run system diagnostic check (Python, FFmpeg, Aria2, Deno, Playwright, paths).")
    opt_table.add_row("clean, --clean", "Purge temporary fragment caches and intermediate buffer files in 💩/.")

    console.print(Panel(opt_table, title="[bold white]CORE CLI FLAGS & OPTIONS[/bold white]", title_align="left", box=ROUNDED, border_style="cyan"))

    # SUBCOMMANDS TABLE
    cmd_table = Table(box=SIMPLE, show_header=True, header_style="bold magenta", padding=(0, 1))
    cmd_table.add_column("Subcommand", style="bold green", min_width=16)
    cmd_table.add_column("Category", style="dim yellow", min_width=14)
    cmd_table.add_column("Description", style="white")

    cmd_table.add_row("bake", "Audio Tools", "Inspect, inject ID3/Vorbis tags, and bake high-res cover art into audio files.")
    cmd_table.add_row("lyrs", "Audio Tools", "Multi-tier synced .lrc lyrics search engine (LRCLIB, NetEase, Megalobiz).")
    cmd_table.add_row("sc-lyrics", "Audio Tools", "Recursive music folder scanner & automated companion .lrc synchronizer.")
    cmd_table.add_row("subs", "AI Subtitles", "GPU-accelerated local speech-to-text & translation subtitle generator (faster-whisper).")
    cmd_table.add_row("slice", "Comic Tools", "Webtoon & Manhua vertical strip page slicer (uniform 2000px height pages).")
    cmd_table.add_row("breeze", "Neural TTS", "Breeze-TTS-2 C++/GGUF speech synthesizer with Voice Design & Cloning.")
    cmd_table.add_row("tts", "Audiobook", "Universal audiobook synthesis hub (Breeze-TTS-2 or Qwen-TTS).")
    cmd_table.add_row("settings", "Configuration", "Interactive settings configurator (download directories, 80+ themes, network).")

    console.print(Panel(cmd_table, title="[bold white]BUILT-IN POWER TOOLS & SUBCOMMANDS[/bold white]", title_align="left", box=ROUNDED, border_style="magenta"))

    # EXAMPLES
    ex_text = Text()
    ex_text.append("  # Quick Grab a single video or chapter without series vacuuming:\n", style="dim white")
    ex_text.append("  zine \"https://hanime.red/watch/episode-1\" --0\n\n", style="bold cyan")
    ex_text.append("  # Vacuum an entire franchise into ~/Downloads/Zine/Vacuum/<Title>/:\n", style="dim white")
    ex_text.append("  zine \"https://hentaihaven.xxx/watch/series-slug/\" --a\n\n", style="bold cyan")
    ex_text.append("  # Download the next 5 unread manhwa chapters sequentially:\n", style="dim white")
    ex_text.append("  zine \"https://asurascans.com/comics/series-slug\" --5\n\n", style="bold cyan")
    ex_text.append("  # Run a custom queue file with per-line flags in headless mode:\n", style="dim white")
    ex_text.append("  zine --vacuum \"my_reading_queue.txt\"\n\n", style="bold cyan")
    ex_text.append("  # Verify all system binaries and permissions:\n", style="dim white")
    ex_text.append("  zine doctor\n", style="bold cyan")

    console.print(Panel(ex_text, title="[bold white]PRACTICAL CLI EXAMPLES[/bold white]", title_align="left", box=ROUNDED, border_style="green"))



def print_cli_version():
    """Prints comprehensive runtime and environment telemetry."""
    print_cli_banner()

    table = Table(box=ROUNDED, show_header=True, header_style="bold cyan", border_style="blue")
    table.add_column("Component", style="bold yellow", min_width=20)
    table.add_column("Details", style="white")

    table.add_row("Zine Scraper", f"v{ZINE_VERSION} ({ZINE_CODENAME} Edition)")
    table.add_row("Python Interpreter", f"{sys.version.split()[0]} ({sys.executable})")
    table.add_row("Operating System", f"{platform.system()} {platform.release()} ({platform.machine()})")

    # Check external binaries
    def check_bin(name):
        path = shutil.which(name)
        if path:
            return f"[bold green]✔ Installed[/bold green] ({path})"
        return "[bold red]✖ Missing[/bold red]"

    table.add_row("FFmpeg", check_bin("ffmpeg"))
    table.add_row("Aria2c", check_bin("aria2c"))
    table.add_row("AtomicParsley", check_bin("atomicparsley"))
    table.add_row("Deno Runtime", check_bin("deno"))

    # Playwright check
    pw_chromium = Path.home() / ".cache" / "ms-playwright"
    pw_status = "[bold green]✔ Present[/bold green]" if pw_chromium.exists() else "[dim yellow]Not cached (auto-downloads on demand)[/dim yellow]"
    table.add_row("Playwright Chromium", pw_status)

    from core.paths import PathAuthority
    pa = PathAuthority()
    table.add_row("Downloads Root", str(pa.get_downloads_root()))
    table.add_row("Vacuum Directory", str(pa.get_vacuum_root()))
    table.add_row("Quick Grab Directory", str(pa.get_quick_grab_root()))
    table.add_row("Logs Directory", str(pa.get_logs_root() / "💩"))

    console.print(table)


def print_cli_sites():
    """Displays a clean catalog of all supported scrapers, categories and domains."""
    from core.site_map import SITE_MAP
    from collections import defaultdict

    categories = defaultdict(list)
    for domain, module_path in SITE_MAP.items():
        parts = module_path.split(".")
        if len(parts) >= 3:
            cat_root = parts[0].replace("1_SFW", "SFW").replace("2_NSFW_ADULT", "NSFW")
            sub_cat = parts[1]
            scraper_name = parts[2]
            categories[f"{cat_root} / {sub_cat}"].append((scraper_name, domain))

    print_cli_banner()
    console.print("[bold white]SUPPORTED SITES & DOMAIN DIRECTORY[/bold white]\n", style="underline")

    for cat, items in sorted(categories.items()):
        cat_table = Table(title=f"[bold cyan]◆ {cat}[/bold cyan]", box=ROUNDED, show_header=True, header_style="bold yellow", border_style="cyan")
        cat_table.add_column("Scraper Engine", style="bold green", min_width=20)
        cat_table.add_column("Domain / Endpoint", style="white")

        scraper_domains = defaultdict(list)
        for s_name, dom in items:
            scraper_domains[s_name].append(dom)

        for s_name, doms in sorted(scraper_domains.items()):
            cat_table.add_row(s_name, ", ".join(doms))

        console.print(cat_table)
        console.print("")

    console.print("[dim white]* Note: Torrent & DDL indexers (Nyaa, SeaDex, TsukiHime) are cataloged for informational reference in interactive mode via 'site'.[/dim white]\n")


def run_cli_doctor():
    """Runs a complete system diagnostic check."""
    print_cli_banner()
    console.print("[bold white]Running Zine System Diagnostics...[/bold white]\n")

    diag_table = Table(box=ROUNDED, show_header=True, header_style="bold cyan", border_style="blue")
    diag_table.add_column("Diagnostic Check", style="bold yellow", min_width=26)
    diag_table.add_column("Status", min_width=16)
    diag_table.add_column("Remedy / Notes", style="white")

    # 1. Python version >= 3.10
    py_ok = sys.version_info >= (3, 10)
    diag_table.add_row(
        "Python Version (>= 3.10)",
        "[bold green]✔ PASS[/bold green]" if py_ok else "[bold red]✖ FAIL[/bold red]",
        f"Detected Python {sys.version.split()[0]}"
    )

    # 2. FFmpeg
    ffmpeg_path = shutil.which("ffmpeg")
    diag_table.add_row(
        "FFmpeg Audio/Video Engine",
        "[bold green]✔ PASS[/bold green]" if ffmpeg_path else "[bold red]✖ MISSING[/bold red]",
        ffmpeg_path if ffmpeg_path else "Install via: sudo apt install ffmpeg / winget install Gyan.FFmpeg"
    )

    # 3. Aria2c
    aria_path = shutil.which("aria2c")
    diag_table.add_row(
        "Aria2 Multi-Connection Tool",
        "[bold green]✔ PASS[/bold green]" if aria_path else "[bold red]✖ MISSING[/bold red]",
        aria_path if aria_path else "Install via: sudo apt install aria2 / winget install aria2.aria2"
    )

    # 4. AtomicParsley
    ap_path = shutil.which("atomicparsley")
    diag_table.add_row(
        "AtomicParsley (M4A/MP4 tags)",
        "[bold green]✔ PASS[/bold green]" if ap_path else "[bold yellow]⚠ OPTIONAL[/bold yellow]",
        ap_path if ap_path else "Recommended for embedding lyrics into Apple M4A tracks"
    )

    # 5. Deno Runtime
    deno_path = shutil.which("deno")
    diag_table.add_row(
        "Deno Runtime (JS Decryption)",
        "[bold green]✔ PASS[/bold green]" if deno_path else "[bold yellow]⚠ OPTIONAL[/bold yellow]",
        deno_path if deno_path else "Required for Hanime decryption. Run: curl -fsSL https://deno.land/install.sh | sh"
    )

    # 6. Storage Write Permissions
    from core.paths import PathAuthority
    pa = PathAuthority()
    dl_root = pa.get_downloads_root()
    vacuum_dir = pa.get_vacuum_root()
    logs_dir = pa.get_logs_root() / "💩"

    def test_writable(p: Path):
        try:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            return True
        except Exception:
            return False

    dl_ok = test_writable(dl_root)
    diag_table.add_row(
        "Downloads Storage Access",
        "[bold green]✔ PASS[/bold green]" if dl_ok else "[bold red]✖ PERMISSION ERROR[/bold red]",
        str(dl_root)
    )

    log_ok = test_writable(logs_dir)
    diag_table.add_row(
        "Session Logs Storage Access",
        "[bold green]✔ PASS[/bold green]" if log_ok else "[bold red]✖ PERMISSION ERROR[/bold red]",
        str(logs_dir)
    )

    # 7. Secrets manager
    secrets_file = pa.get_project_root() / "secrets.json"
    diag_table.add_row(
        "Credentials (secrets.json)",
        "[bold green]✔ FOUND[/bold green]" if secrets_file.exists() else "[dim yellow]Not Created Yet[/dim yellow]",
        "Auto-scaffolds on MangaDex or API usage"
    )

    console.print(diag_table)
    console.print("\n[bold green]✦ All critical subsystem diagnostics completed.[/bold green]\n")


def purge_logs_and_temp(silent: bool = False):
    """
    Purges contents inside:
      - zine scraper/Logs/Downlode 💩/Sessions
      - zine scraper/Logs/💩
      - zine scraper/💩 (project root and downloads root)
    """
    from core.paths import PathAuthority
    pa = PathAuthority()

    targets = [
        pa.get_sessions_dir(),                       # Logs/Downlode 💩/Sessions
        pa.get_logs_root() / "💩",                   # Logs/💩
        pa.get_project_root() / "💩",               # 💩 (project root)
        pa.get_downloads_root() / "💩",             # 💩 (downloads root)
    ]

    purged_files = 0
    purged_dirs = 0
    bytes_freed = 0

    for target_dir in targets:
        if not target_dir.exists():
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            continue
        for item in list(target_dir.rglob("*")):
            if item.is_file() and not item.name.startswith(".gitkeep"):
                try:
                    bytes_freed += item.stat().st_size
                    item.unlink()
                    purged_files += 1
                except Exception:
                    pass
        for item in list(target_dir.rglob("*")):
            if item.is_dir() and item != target_dir:
                try:
                    if not any(item.iterdir()):
                        item.rmdir()
                        purged_dirs += 1
                except Exception:
                    pass

    if not silent:
        mb_freed = bytes_freed / (1024 * 1024)
        if purged_files > 0:
            console.print(f"[bold green]✔ Successfully purged {purged_files} logs & temporary session files ({mb_freed:.2f} MB freed).[/bold green]\n")
        else:
            console.print("[dim green]✔ All log directories and temporary buffers are completely clean.[/dim green]\n")


def run_cli_clean():
    """Purges intermediate fragments, session logs, crash traces, and cache buffers."""
    print_cli_banner()
    console.print("[bold white]Purging Zine Temporary Buffers, Session Journals & Crash Logs...[/bold white]\n")
    purge_logs_and_temp(silent=False)


def handle_unknown_flag(flag: str):
    """Detects invalid CLI options, offers fuzzy typo corrections, and guides the user."""
    import difflib

    known_flags = [
        "--help", "-h",
        "--version", "-v", "-V",
        "--doctor", "--sites", "--clean", "--batch",
        "--all", "--0"
    ]
    
    matches = difflib.get_close_matches(flag, known_flags, n=1, cutoff=0.5)

    err_text = Text()
    err_text.append("Unknown option: ", style="bold red")
    err_text.append(f"'{flag}'\n", style="bold yellow")

    if matches:
        err_text.append("\nDid you mean: ", style="white")
        err_text.append(f"{matches[0]}", style="bold cyan")
        err_text.append("?\n", style="white")

    err_text.append("\nRun ", style="dim white")
    err_text.append("zine --help", style="bold green")
    err_text.append(" to inspect all available flags, options, and commands.", style="dim white")

    console.print(Panel(err_text, title="[bold red]🔴 Invalid CLI Option[/bold red]", title_align="left", box=ROUNDED, border_style="red"))
