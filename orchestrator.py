import sys
import os

# Auto-relaunch inside virtual environment if not already running in it
venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "python")
if os.path.exists(venv_python) and sys.executable != venv_python:
    os.execl(venv_python, venv_python, *sys.argv)
import re
import logging
from pathlib import Path
from datetime import datetime

script_dir = Path(__file__).parent.resolve()
# Add root folder to sys.path to guarantee imports resolve correctly
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from core.paths import PathAuthority

# Setup live logging dynamically without hardcoding root paths
paths = PathAuthority()
log_dir = paths.get_logs_root() / "💩"
log_dir.mkdir(parents=True, exist_ok=True)
log_file_path = (log_dir / f"scraper_{datetime.now().strftime('%Y-%m-%d')}.log").resolve()

# Protect the central FileHandler from being removed by engine scripts
original_removeHandler = logging.Logger.removeHandler
def patched_removeHandler(self, handler):
    if isinstance(handler, logging.FileHandler) and handler.baseFilename == str(log_file_path):
        return
    original_removeHandler(self, handler)
logging.Logger.removeHandler = patched_removeHandler

class Logger:
    def __init__(self, stream, log_file):
        self.stream = stream
        self.log_file = log_file
        # Regex to strip ANSI escape codes (colors, cursor movements, clear screen, etc.)
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

    def write(self, message):
        self.stream.write(message)
        try:
            if isinstance(message, bytes):
                text = message.decode("utf-8", "replace")
            else:
                text = str(message)
            
            clean_text = self.ansi_escape.sub('', text)
            
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

try:
    # 1. Capture all actual backend logs (DEBUG, INFO, ERROR) cleanly
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file_path, encoding="utf-8")
        ]
    )
    
    # 2. Tee only stderr to catch unhandled Python crashes/tracebacks.
    # We DO NOT tee stdout anymore, so UI rendering stays out of the log!
    log_f = open(log_file_path, "a", encoding="utf-8")
    sys.stderr = Logger(sys.stderr, log_f)
except Exception:
    pass

from core.funnel import main

if __name__ == "__main__":
    try:
        qwen_prompt_path = script_dir / "Qween tts" / "TTS prompt.txt"
        if not qwen_prompt_path.exists():
            qwen_prompt_path.parent.mkdir(parents=True, exist_ok=True)
            qwen_prompt_path.write_text("")
            
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        import traceback
        crash_log = log_dir / "crash_trace.txt"
        with open(crash_log, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        raise
    finally:
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
        
        # Ensure we actually exit to break any monolithic loops
        sys.exit(0)
