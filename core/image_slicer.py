"""
core/image_slicer.py
--------------------
Manhua & Webtoon Image Slicer module for Zine Scraper Suite.
Slices tall vertical image strips into standard height page chunks with natural sequential numbering.
Leaves small/normal ratio images untouched.
"""

import os
import sys
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PIL import Image
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from core.ui import console, startup_clear, print_banner
from core.paths import PathAuthority
from core.storage import StorageLayer
from core.config import ConfigLayer

Image.MAX_IMAGE_PIXELS = None

DEFAULT_CHUNK_HEIGHT = 2000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def natural_sort_key(s: str) -> List[Any]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


def is_tall_strip(img: Image.Image, chunk_height: int = DEFAULT_CHUNK_HEIGHT) -> bool:
    """Returns True if the image is a tall vertical strip requiring slicing."""
    width, height = img.size
    # If height exceeds chunk_height or height is more than 1.8x the width
    return height > chunk_height or (height > width * 1.8 and height > 1500)


def slice_single_image(
    image_path: Path,
    output_dir: Path,
    chunk_height: int = DEFAULT_CHUNK_HEIGHT,
    jpeg_quality: int = 90
) -> Tuple[bool, int]:
    """
    Slices a single image into height chunks if it's a tall strip.
    If not tall, returns (False, 1) and skips slicing (copies to output if different dir).
    Returns (True, num_slices) if sliced.
    """
    try:
        was_tall = False
        count = 1
        with Image.open(image_path) as img:
            width, height = img.size
            if not is_tall_strip(img, chunk_height):
                if output_dir != image_path.parent:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    import shutil
                    shutil.copy2(image_path, output_dir / image_path.name)
                return False, 1

            was_tall = True
            base_name = image_path.stem
            output_dir.mkdir(parents=True, exist_ok=True)

            for top in range(0, height, chunk_height):
                bottom = min(top + chunk_height, height)
                # Skip tiny remainder slice if less than 50px
                if bottom - top < 50 and count > 1:
                    break

                crop = img.crop((0, top, width, bottom))
                out_path = output_dir / f"{base_name}_{count:03d}.jpg"
                crop.convert("RGB").save(out_path, "JPEG", quality=jpeg_quality)
                count += 1

        if was_tall and output_dir == image_path.parent:
            try:
                image_path.unlink()
            except Exception as e:
                pass

        return True, count - 1
    except Exception as e:
        console.print(f"[error]Failed to slice {image_path.name}: {e}[/error]")
        return False, 0


def process_image_target(
    target_path: Path,
    chunk_height: int = DEFAULT_CHUNK_HEIGHT,
    in_place: bool = True
) -> Tuple[int, int, Path]:
    """
    Processes a directory or single image file.
    Returns (sliced_count, untouched_count, out_dir_base).
    """
    target_path = Path(target_path).expanduser().resolve()
    if not target_path.exists():
        console.print(f"[error]Target path does not exist: {target_path}[/error]")
        return 0, 0, target_path

    if target_path.is_file():
        image_files = [target_path] if target_path.suffix.lower() in IMAGE_EXTENSIONS else []
    else:
        image_files = [
            p for p in target_path.rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ]
        image_files = sorted(image_files, key=lambda p: natural_sort_key(p.name))

    if not image_files:
        console.print(f"[warning]No supported image files (.png, .jpg, .webp) found in {target_path}[/warning]")
        return 0, 0, target_path

    if target_path.is_file():
        out_dir_base = target_path.parent if in_place else target_path.parent / f"{target_path.stem}_sliced"
    else:
        out_dir_base = target_path if in_place else target_path.parent / f"{target_path.name}_sliced"

    temp_dir = out_dir_base / ".slicer_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    sliced_count = 0
    untouched_count = 0
    
    current_file = ""
    is_done = False
    
    from rich.live import Live
    from rich.tree import Tree
    from core.ui import align_header
    import time
    import shutil
    
    def render_tree() -> Tree:
        tree = Tree(f"[info]●[/info] [menu]Slicer[/menu]", guide_style="unselected")
        tree.add(align_header("Output", str(out_dir_base)))
        tree.add(align_header("Images", str(len(image_files))))
        
        res_branch = tree.add("[success]○[/success] [menu]Progress[/menu]", guide_style="unselected")
        
        if is_done:
            res_branch.add(f"[success]●[/success] Complete! Sliced: [sexy_pink]{sliced_count}[/sexy_pink] | Untouched: [sexy_pink]{untouched_count}[/sexy_pink]")
        else:
            blink_state = int(time.time() * 3) % 2
            ball_style = "sexy_pink" if blink_state == 0 else "unselected"
            res_branch.add(f"[{ball_style}]●[/{ball_style}] Slicing: [bold white]{current_file}[/bold white]")
        return tree

    with Live(get_renderable=render_tree, console=console, refresh_per_second=15, transient=False) as live:
        for img_p in image_files:
            current_file = img_p.name
            was_sliced, num_chunks = slice_single_image(img_p, temp_dir, chunk_height)
            if was_sliced:
                sliced_count += 1
            else:
                untouched_count += 1
                
        # Safety transfer: move from temp to out_dir_base and delete originals
        for img_p in image_files:
            try:
                img_p.unlink()
            except Exception:
                pass
                
        for temp_file in temp_dir.iterdir():
            if temp_file.is_file():
                shutil.move(str(temp_file), str(out_dir_base / temp_file.name))
                
        try:
            temp_dir.rmdir()
        except Exception:
            pass
                
        is_done = True
        live.update(render_tree(), refresh=True)

    return sliced_count, untouched_count, out_dir_base


def run_image_slicer_tui():
    """Interactive CLI TUI command for running the Manhua Image Slicer."""
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from core.ui import get_theme_input_ansi

    startup_clear()
    print_banner()

    paths = PathAuthority()
    storage = StorageLayer()
    config = ConfigLayer(paths, storage)
    default_dir = config.get("download_base") or str(paths.get_downloads_root())

    table = Table(box=None, show_header=False, padding=(0, 1))
    table.add_column("info", width=70)
    table.add_row(Text("Manhua & Webtoon Image Slicer Tool", style="bold sexy_pink"))
    table.add_row(Text("Slices tall vertical image strips into standard 2000px height pages.", style="unselected"))
    table.add_row(Text("Normal ratio images are left untouched and smoothly copied over.", style="unselected"))

    panel = Panel(
        table,
        title="[bold white]◆ MANHUA IMAGE SLICER ◆[/bold white]",
        border_style="sexy_pink",
        padding=(1, 2),
        width=80
    )
    console.print(panel)

    while True:
        console.print("\n[menu]Enter folder or image file path to slice[/menu] (or press ESC to exit):")
        
        from core.funnel import get_key_with_esc
        from core.ui import get_theme_input_ansi
        user_input = ""
        cursor_pos = 0
        
        prompt_ansi = get_theme_input_ansi()
        
        while True:
            sys.stdout.write(f"\r\033[K{prompt_ansi}❯ \033[0m{user_input}")
            if cursor_pos < len(user_input):
                diff = len(user_input) - cursor_pos
                sys.stdout.write(f"\033[{diff}D")
            sys.stdout.flush()

            key = get_key_with_esc()
            if not key:
                break
                
            if key in ('\r', '\n', 'ENTER'):
                print()
                break
            elif key == 'ESC' or key == '\x1b':
                user_input = "esc"
                print()
                break
            elif key in ('\x7f', '\x08', 'BACKSPACE'):
                if cursor_pos > 0:
                    user_input = user_input[:cursor_pos-1] + user_input[cursor_pos:]
                    cursor_pos -= 1
            elif key in ('[D', 'OD'): # Left Arrow
                if cursor_pos > 0:
                    cursor_pos -= 1
            elif key in ('[C', 'OC'): # Right Arrow
                if cursor_pos < len(user_input):
                    cursor_pos += 1
            elif key == '\x03' or key == 'CTRL_C':
                user_input = "esc"
                print()
                break
            elif len(key) >= 1 and not key.startswith('['):
                # Clean pasted text from newlines if any
                clean_key = key.replace('\n', '').replace('\r', '')
                user_input = user_input[:cursor_pos] + clean_key + user_input[cursor_pos:]
                cursor_pos += len(clean_key)
        
        user_input = user_input.strip()

        if not user_input or user_input.lower() in ("esc", "exit", "q") or "\x1b" in user_input:
            break

        target = Path(user_input).expanduser().resolve()
        if not target.exists():
            console.print(f"\n[error]Path does not exist: {target}[/error]")
            import time
            time.sleep(1.5)
            continue

        console.print("\n[info]Processing images...[/info]\n")
        sliced, untouched, out_dir = process_image_target(target, chunk_height=DEFAULT_CHUNK_HEIGHT)

        console.print(f"\n[success]● Complete! Sliced: {sliced} strips | Untouched: {untouched} pages[/success]\n")
        
        console.input("[info]Press Enter to continue...[/info]")
        
        startup_clear()
        print_banner()
        console.print(panel)
