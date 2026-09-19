"""
core/logger.py
──────────────
Unified High-Fidelity Logging & Diagnostics Subsystem for Zine Scraper.

Guarantees:
  1. Unique timestamped session log for every single execution:
     `Logs/💩/session_YYYY-MM-DD_HH-MM-SS.log`
  2. Dedicated error log automatically created on failure/crash:
     `Logs/💩/error_YYYY-MM-DD_HH-MM-SS.log`
  3. Symlink / copy shortcuts (`latest_session.log`, `latest_error.log`)
     so developers and AI agents can immediately inspect results.
  4. Rich diagnostic metadata (CLI args, environment, OS, Python version,
     resolved scraper, target paths, and tracebacks).
  5. Clean stderr teeing with ANSI code stripping so logs are human- & AI-readable.
"""

import os
import sys
import re
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.paths import PathAuthority

_SESSION_LOGGER = None
_SESSION_LOG_FILE: Optional[Path] = None
_ERROR_LOG_FILE: Optional[Path] = None
_LOGS_DIR: Optional[Path] = None


class AnsiStrippingStream:
    """Tees a stream to a log file while stripping all ANSI terminal escape codes."""
    def __init__(self, target_stream, log_file):
        self.stream = target_stream
        self.log_file = log_file
        self._ansi_regex = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, message):
        self.stream.write(message)
        try:
            if isinstance(message, bytes):
                text = message.decode("utf-8", errors="replace")
            else:
                text = str(message)
            clean_text = self._ansi_regex.sub('', text)
            if clean_text:
                self.log_file.write(clean_text)
                self.log_file.flush()
        except Exception:
            pass

    def flush(self):
        self.stream.flush()
        try:
            self.log_file.flush()
        except Exception:
            pass

    def __getattr__(self, attr):
        return getattr(self.stream, attr)


def get_logs_dir() -> Path:
    global _LOGS_DIR
    if _LOGS_DIR is None:
        paths = PathAuthority()
        _LOGS_DIR = (paths.get_logs_root() / "💩").resolve()
        _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGS_DIR


def get_current_session_log() -> Optional[Path]:
    return _SESSION_LOG_FILE


def init_session_logger(cli_args: Optional[List[str]] = None) -> Path:
    """
    Initializes a new dedicated session log file for this execution.
    Never appends to an existing log; every run creates a unique file.
    """
    global _SESSION_LOGGER, _SESSION_LOG_FILE

    log_dir = get_logs_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"session_{timestamp}.log"
    _SESSION_LOG_FILE = log_file

    # Build diagnostic startup banner for the log
    py_ver = sys.version.replace("\n", " ")
    args_str = " ".join(cli_args if cli_args is not None else sys.argv[1:])
    
    header = (
        f"{'='*80}\n"
        f"  ZINE SCRAPER — EXECUTION SESSION LOG\n"
        f"{'='*80}\n"
        f"  Timestamp   : {datetime.now().isoformat()}\n"
        f"  Python      : {py_ver}\n"
        f"  Executable  : {sys.executable}\n"
        f"  Platform    : {sys.platform} ({os.name})\n"
        f"  PID         : {os.getpid()}\n"
        f"  Working Dir : {os.getcwd()}\n"
        f"  CLI Input   : {args_str or '(Interactive TUI Launch)'}\n"
        f"{'='*80}\n\n"
    )

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(header)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove previous handlers to prevent duplication
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root_logger.addHandler(file_handler)

    # Tee stderr to capture any unhandled exceptions or library warnings cleanly
    try:
        raw_log_f = open(log_file, "a", encoding="utf-8")
        sys.stderr = AnsiStrippingStream(sys.stderr, raw_log_f)
    except Exception:
        pass

    # Update latest_session.log pointer
    latest_ptr = log_dir / "latest_session.log"
    try:
        latest_ptr.write_text(f"Session Log: {log_file.resolve()}\nTimestamp: {datetime.now().isoformat()}\n\n" + log_file.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    except Exception:
        pass

    _SESSION_LOGGER = root_logger
    root_logger.info(f"Session logging initialized -> {log_file.name}")
    return log_file


def record_error_log(
    error: Any,
    context: Optional[Dict[str, Any]] = None,
    traceback_str: Optional[str] = None
) -> Path:
    """
    Creates a dedicated error log file in Logs/💩/ whenever a failure or crash occurs.
    Includes context, input, scraper, and full traceback for instant debugging by AI models.
    """
    global _ERROR_LOG_FILE
    log_dir = get_logs_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    err_file = log_dir / f"error_{timestamp}.log"
    _ERROR_LOG_FILE = err_file

    tb = traceback_str or traceback.format_exc()
    if tb.strip() == "NoneType: None":
        tb = "(No active exception traceback on stack)"

    ctx = context or {}
    ctx_lines = "\n".join(f"    {k:<16}: {v}" for k, v in ctx.items()) or "    (None provided)"

    content = (
        f"{'!'*80}\n"
        f"  ZINE SCRAPER — ERROR REPORT\n"
        f"{'!'*80}\n"
        f"  Timestamp   : {datetime.now().isoformat()}\n"
        f"  Session Log : {_SESSION_LOG_FILE or 'Unknown'}\n"
        f"  Error Type  : {type(error).__name__ if isinstance(error, Exception) else 'ScraperFailure'}\n"
        f"  Error Msg   : {str(error)}\n"
        f"  Context     :\n{ctx_lines}\n"
        f"{'='*80}\n"
        f"  TRACEBACK & DEBUG DETAILS:\n"
        f"{'='*80}\n"
        f"{tb}\n"
        f"{'='*80}\n"
    )

    try:
        err_file.write_text(content, encoding="utf-8")
        
        # Also update latest_error.log pointer
        latest_err = log_dir / "latest_error.log"
        latest_err.write_text(content, encoding="utf-8")

        # Also write into the active session log
        logging.getLogger("core.logger").error(f"FATAL ERROR RECORDED -> {err_file.name}: {error}")
    except Exception as e:
        sys.stderr.write(f"Failed to write error log: {e}\n")

    return err_file
