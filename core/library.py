"""
core/library.py
---------------
Library Authority: Owns the Zine folder structure layout and two-step
verification logic.

Responsibilities:
  - scaffold_library()     → create the full Zine tree under a given root
  - two_step_verify()      → fast check before every download decision
  - path helpers           → canonical paths for quick_grab / vacuum / temp

Nothing here does network I/O or scraping logic.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ── Canonical sub-trees ────────────────────────────────────────────────────────

def scaffold_library(root: Path, storage) -> None:
    """
    Creates the complete Zine folder structure under *root*.
    Safe to call multiple times — uses exist_ok=True internally.

    Structure:
        <root>/
        ├── Quick grab/
        ├── Vacuum/
        ├── Batch/
        └── temp/
            ├── downloads/
            ├── transcodes/
            ├── extraction/
            └── sessions/
    """
    root = Path(root).resolve()

    # Zine root itself
    storage.create_directory(root)

    # Quick grab
    storage.create_directory(root / "Quick grab")

    # Vacuum
    storage.create_directory(root / "Vacuum")

    # Batch
    batch_dir = root / "Batch"
    storage.create_directory(batch_dir)
    batch_file = batch_dir / "Batch URL.txt"
    if not batch_file.exists():
        storage.write_file(batch_file, "")

    # temp (centralized in 💩)
    from core.paths import PathAuthority
    temp_dir = PathAuthority().get_temp_root()
    storage.create_directory(temp_dir)

    # Models directory & download guide
    project_root = Path(__file__).resolve().parent.parent
    models_dir = project_root / "Models"
    storage.create_directory(models_dir)

    models_guide = models_dir / "README to downlode ai model.md"
    models_main = models_dir / "README.md"
    if not models_guide.exists() and models_main.exists():
        try:
            storage.write_file(models_guide, models_main.read_text(encoding="utf-8"))
        except Exception:
            pass
    elif not models_main.exists() and models_guide.exists():
        try:
            storage.write_file(models_main, models_guide.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Qwen TTS directory & default templates
    qwen_dir = project_root / "Qween tts"
    storage.create_directory(qwen_dir)

    word_file = qwen_dir / "word.txt"
    if not word_file.exists():
        default_word_text = (
            "\"It's my responsibility to observe their evolution since I burnt my running into their eyes. "
            "Of course, I'm also looking forward to watching your return. Your fighting spirit and unamused amazed victory chasing instinct. "
            "What changes will it bring about?\n\n"
            "Please show me, won't you? , haha!\n\n"
            "Zeus! Is this how you face me? Coward! I am through doing the bidding of the gods. "
            "Come down here and face me now, Zeus!\n\n"
            "I'm so freaking funny bro.\"\n"
        )
        storage.write_file(word_file, default_word_text)

    prompt_file = qwen_dir / "TTS prompt.txt"
    if not prompt_file.exists():
        storage.write_file(prompt_file, "")

    # Logs directory
    logs_dir = project_root / "Logs"
    storage.create_directory(logs_dir)
    storage.create_directory(logs_dir / "💩")
    history_file = logs_dir / "Download History.json"
    if not history_file.exists():
        storage.write_file(history_file, "{}")

    logger.info(f"Zine library scaffold complete at: {root}")


def clean_temp(root: Path, storage) -> None:
    """Wipes all temporary files inside the centralized 💩 dump directory."""
    import shutil
    from core.paths import PathAuthority
    temp_root = PathAuthority().get_temp_root()
    if temp_root.exists():
        for item in temp_root.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                logger.warning(f"Could not clean temp item {item}: {e}")


# ── Path helpers ───────────────────────────────────────────────────────────────

def get_quick_grab_path(root: Path, site: str, creator: Optional[str] = None) -> Path:
    """Returns the Quick grab dir for a given site and creator."""
    if creator:
        return Path(root) / "Quick grab" / site / creator
    return Path(root) / "Quick grab" / site

def get_vacuum_path(root: Path, site: str, creator: Optional[str] = None) -> Path:
    """Returns the Vacuum dir for a given site and creator."""
    if creator:
        return Path(root) / "Vacuum" / site / creator
    return Path(root) / "Vacuum" / site

def get_batch_path(root: Path) -> Path:
    return Path(root) / "Batch"

def get_temp_path(root: Path, sub: str = "downloads") -> Path:
    from core.paths import PathAuthority
    return PathAuthority().get_temp_root()


# ── Two-step verification ──────────────────────────────────────────────────────

class VerificationResult:
    """Result of a two-step verification check."""

    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason

    def __bool__(self):
        return self.passed

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"VerificationResult({status}: {self.reason})"


def two_step_verify(
    zine_dir: Path,
    item_id: str,
    media_path: Optional[Path] = None,
    min_size_bytes: int = 1024,
) -> VerificationResult:
    """
    Fast two-step verification before a download decision.

    Step 1 – Metadata Verification:
        Check that .zine/ dir exists and contains history.json.
        Check that item_id appears in history.json.

    Step 2 – Media Verification (only when media_path is provided):
        Check that the actual media file exists on disk.
        Check that its size is above min_size_bytes.
        Check that the path recorded in history matches the file on disk.

    Returns VerificationResult(passed=True)  → safe to skip download.
    Returns VerificationResult(passed=False) → must download again.
    """
    # ── Step 1: Metadata ──────────────────────────────────────────────────────
    if not zine_dir.exists():
        return VerificationResult(False, ".zine dir missing")

    history_file = zine_dir / "history.json"
    if not history_file.exists():
        return VerificationResult(False, "history.json missing")

    try:
        history_data = json.loads(history_file.read_text(encoding="utf-8"))
    except Exception as e:
        return VerificationResult(False, f"history.json unreadable: {e}")

    if str(item_id) not in history_data:
        return VerificationResult(False, f"item_id '{item_id}' not in history")

    recorded_filename = history_data[str(item_id)]

    # ── Step 2: Media ─────────────────────────────────────────────────────────
    if media_path is None:
        # Derive path from the parent of .zine and the recorded filename
        parent = zine_dir.parent
        media_path = parent / recorded_filename

    media_path = Path(media_path)

    if not media_path.exists():
        return VerificationResult(False, f"media file missing: {media_path.name}")

    if media_path.stat().st_size < min_size_bytes:
        return VerificationResult(
            False,
            f"media file too small ({media_path.stat().st_size} B): {media_path.name}"
        )

    # Path consistency: recorded filename must match actual filename
    if media_path.name != str(recorded_filename):
        return VerificationResult(
            False,
            f"path mismatch: recorded='{recorded_filename}' actual='{media_path.name}'"
        )

    return VerificationResult(True, "both steps passed")
