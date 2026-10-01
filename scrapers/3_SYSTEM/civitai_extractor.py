"""
scrapers/3_SYSTEM/civitai_extractor.py
--------------------------------------
Centralized entry point for Civitai downloader, forwarding to scrapers/3_SYSTEM/civitai.
"""

import sys
from pathlib import Path
import importlib.util

_current_dir = Path(__file__).parent.resolve()
_civitai_dir = _current_dir / "civitai"

def _load_module(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_engine_mod = _load_module("civitai_engine", _civitai_dir / "engine.py")
_location_mod = _load_module("civitai_location", _civitai_dir / "location.py")
_tui_mod = _load_module("civitai_tui", _civitai_dir / "tui.py")

create_browser_session = _engine_mod.create_browser_session
get_browser_headers = _engine_mod.get_browser_headers
extract_api_key_from_lines = _engine_mod.extract_api_key_from_lines
parse_civitai_target = _engine_mod.parse_civitai_target
resolve_model_id_to_download_url = _engine_mod.resolve_model_id_to_download_url
get_filename_from_cd = _engine_mod.get_filename_from_cd
resolve_download_metadata = _engine_mod.resolve_download_metadata
download_chunk = _engine_mod.download_chunk
parallel_download_file = _engine_mod.parallel_download_file
single_stream_download = _engine_mod.single_stream_download
remove_line_from_file = _engine_mod.remove_line_from_file

resolve_model_destination = _location_mod.resolve_model_destination
get_vacuum_fallback_dir = _location_mod.get_vacuum_fallback_dir
get_comfyui_models_root = _location_mod.get_comfyui_models_root

run_civitai_tui = _tui_mod.run_civitai_tui

if __name__ == "__main__":
    target_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_civitai_tui(input_file=target_arg)
