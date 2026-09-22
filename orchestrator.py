import sys
import os

# Auto-relaunch inside virtual environment if not already running in it
_repo_dir = os.path.dirname(os.path.abspath(__file__))
_venv_python = (
    os.path.join(_repo_dir, "venv", "Scripts", "python.exe")
    if os.name == "nt"
    else os.path.join(_repo_dir, "venv", "bin", "python")
)
if os.path.exists(_venv_python) and sys.executable != _venv_python:
    os.execl(_venv_python, _venv_python, *sys.argv)

import re
import logging
from pathlib import Path
from datetime import datetime

script_dir = Path(__file__).parent.resolve()
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# Fast-path CLI commands (--help, --version, doctor, sites, clean)
if len(sys.argv) > 1:
    raw_arg = sys.argv[1].strip()
    arg_first = raw_arg.lower()
    if arg_first in ["--help", "-h", "-?", "help", "?", "--h"]:
        from core.cli_help import print_cli_help
        print_cli_help()
        sys.exit(0)
    elif arg_first in ["--version", "-v", "-v", "version", "ver", "--ver", "--verson"]:
        from core.cli_help import print_cli_version
        print_cli_version()
        sys.exit(0)
    elif arg_first in ["--doctor", "-doctor", "doctor", "check"]:
        from core.cli_help import run_cli_doctor
        run_cli_doctor()
        sys.exit(0)
    elif arg_first in ["--sites", "-sites", "sites", "list"]:
        from core.cli_help import print_cli_sites
        print_cli_sites()
        sys.exit(0)
    elif arg_first in ["--clean", "-clean", "clean"]:
        from core.cli_help import run_cli_clean
        run_cli_clean()
        sys.exit(0)
    elif arg_first in ["--server", "-server", "server"]:
        from core.server import start_server
        port = 53318
        if len(sys.argv) > 2:
            try:
                port = int(sys.argv[2])
            except ValueError:
                pass
        start_server(port=port)
        sys.exit(0)
    elif raw_arg.startswith("-") and not re.match(r"^--(\d+|[aA])\b", raw_arg) and not arg_first.startswith(("--batch", "--vacuum", "--meta", "--metadata")):
        from core.cli_help import handle_unknown_flag
        handle_unknown_flag(raw_arg)
        if sys.stdin.isatty():
            from core.ui import wait_for_error
            wait_for_error("Press Enter to exit...", force=True)
        sys.exit(2)

# Automatically clean temporary buffers, old session logs, and traces on startup
from core.cli_help import purge_logs_and_temp
purge_logs_and_temp(silent=True)

# Initialize unified session logger
from core.logger import init_session_logger, record_error_log
from core.journal import DownloadJournal

session_log_path = init_session_logger(sys.argv[1:])
session_journal = DownloadJournal.init_session(sys.argv[1:])

# Protect the central FileHandler from being removed by engine scripts
original_removeHandler = logging.Logger.removeHandler
def patched_removeHandler(self, handler):
    if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(session_log_path):
        return
    original_removeHandler(self, handler)
logging.Logger.removeHandler = patched_removeHandler

from core.funnel import main

if __name__ == "__main__":
    try:
        qwen_prompt_path = script_dir / "Models" / "TTS" / "Qween tts" / "TTS prompt.txt"
        if not qwen_prompt_path.exists():
            qwen_prompt_path.parent.mkdir(parents=True, exist_ok=True)
            qwen_prompt_path.write_text("")
            
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        record_error_log(e, context={"args": sys.argv[1:], "cwd": os.getcwd()})
        if sys.stdin.isatty():
            from core.ui import wait_for_error
            wait_for_error("Press Enter to exit...", force=True)
        raise
    finally:
        try:
            session_journal.finish_session()
        except Exception:
            pass
        try:
            import psutil
            current_process = psutil.Process(os.getpid())
            children = current_process.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            gone, alive = psutil.wait_procs(children, timeout=3)
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
        except Exception as e:
            logging.error(f"Failed to cleanup child processes: {e}")
        
        sys.exit(0)
