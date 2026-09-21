import os
import sys
import time
import json
import uuid
import logging
import mimetypes
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime
import subprocess
import re
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Dev Logger — writes structured entries to zine tts/logs/<stem>_<ts>.log
# ---------------------------------------------------------------------------
_tts_logger: logging.Logger = logging.getLogger("zine.breeze_tts")
_tts_logger.setLevel(logging.DEBUG)
_tts_logger.propagate = False

_log_file_handler: logging.FileHandler | None = None


def init_tts_logger(log_path: Path) -> None:
    """Set up a FileHandler that writes newline-delimited JSON log entries."""
    global _log_file_handler
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if _log_file_handler:
        _tts_logger.removeHandler(_log_file_handler)
        _log_file_handler.close()

    _log_file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    _log_file_handler.setLevel(logging.DEBUG)
    _log_file_handler.setFormatter(logging.Formatter("%(message)s"))
    _tts_logger.addHandler(_log_file_handler)
    _log_event("BREEZE_SESSION_START", {"log_file": str(log_path), "pid": os.getpid()})


def _log_event(event: str, data: dict | None = None) -> None:
    """Append one timestamped JSON line to the dev log."""
    entry = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
    }
    if data:
        entry.update(data)
    _tts_logger.debug(json.dumps(entry, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Binary & Model Discovery Helpers (Rooted at suite Models/)
# ---------------------------------------------------------------------------

def get_tts_dir() -> Path:
    """Returns the unified zine tts directory."""
    tts_dir = Path(__file__).parent / "zine tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    return tts_dir


def resolve_model_path() -> str:
    """Finds the active Breeze GGUF model path from settings or Models/ directory."""
    from core.settings_tui import config
    from core.paths import sanitize_user_path, PathAuthority
    
    models_root = PathAuthority().get_models_root()
    
    cfg_path = config.get("breeze_model_path", "")
    if cfg_path:
        clean = sanitize_user_path(cfg_path)
        cand = Path(clean).expanduser().resolve() if os.path.isabs(clean) else (models_root.parent / clean).resolve()
        if cand.exists() and cand.is_file():
            return str(cand)
            
    models_root = PathAuthority().get_models_root()
    tts_root = PathAuthority().get_tts_models_root()

    # Priority 1: Check /mnt/maiden/tts and standard Models/TTS directories
    preferred = [
        Path("/mnt/maiden/tts/breeze-tts-2-q8_0.gguf"),
        Path("/mnt/maiden/tts/breeze-tts-2-q4_k.gguf"),
        Path("/mnt/maiden/tts/breeze-tts-2-f16.gguf"),
        tts_root / "breeze-tts-2-q8_0.gguf",
        tts_root / "breeze-tts-2-q4_k.gguf",
        tts_root / "breeze-tts-2-f16.gguf",
        tts_root / "breeze-tts-2-fp16.gguf",
        tts_root / "Breeze-TTS-2" / "breeze-tts-2-q8_0.gguf",
        models_root / "breeze-tts-2-q8_0.gguf",
        models_root / "breeze-tts-2-q4_k.gguf",
        models_root / "breeze-tts-2-f16.gguf",
        models_root / "breeze-tts-2-fp16.gguf",
        models_root / "Breeze-TTS-2" / "breeze-tts-2-q8_0.gguf",
    ]
    for p in preferred:
        if p.exists() and p.is_file():
            return str(p.resolve())
            
    # Priority 2: Glob any breeze .gguf in Models/TTS/, Models/, or /mnt/maiden/tts
    maiden_tts = Path("/mnt/maiden/tts")
    if maiden_tts.exists():
        for gguf in maiden_tts.rglob("*breeze*.gguf"):
            if gguf.is_file():
                return str(gguf.resolve())
    if tts_root.exists():
        for gguf in tts_root.rglob("*breeze*.gguf"):
            if gguf.is_file():
                return str(gguf.resolve())
    if models_root.exists():
        for gguf in models_root.rglob("*breeze*.gguf"):
            if gguf.is_file():
                return str(gguf.resolve())

    return str(Path("/mnt/maiden/tts/breeze-tts-2-q8_0.gguf"))


def resolve_binary(name: str) -> str:
    """Finds the given binary (e.g. breeze-cli, breeze-server, breeze-convert)."""
    from core.settings_tui import config
    from core.paths import sanitize_user_path, PathAuthority

    pa = PathAuthority()
    models_root = pa.get_models_root()
    tts_root = pa.get_tts_models_root()

    cfg_dir = config.get("breeze_bin_dir", "")
    if cfg_dir:
        clean_dir = sanitize_user_path(cfg_dir)
        cand_dir = Path(clean_dir).expanduser().resolve() if os.path.isabs(clean_dir) else (pa.get_app_root() / clean_dir).resolve()
        bin_path = cand_dir / name
        if bin_path.is_file() and os.access(bin_path, os.X_OK):
            return str(bin_path.resolve())
        # Try cand_dir / bin / name or cand_dir / build / bin / name
        for sub in [cand_dir / "bin" / name, cand_dir / "build" / "bin" / name, cand_dir / "build" / name]:
            if sub.is_file() and os.access(sub, os.X_OK):
                return str(sub.resolve())

    # Priority 1: Check /mnt/maiden/tts, Models/TTS/ and Models/ build directories
    model_bin_dirs = [
        Path("/mnt/maiden/tts/Breeze-TTS-2.cpp/build"),
        Path("/mnt/maiden/tts/Breeze-TTS-2.cpp/build/bin"),
        Path("/mnt/maiden/tts/Breeze-TTS-2.cpp"),
        tts_root / "Breeze-TTS-2.cpp" / "build" / "bin",
        tts_root / "Breeze-TTS-2.cpp" / "build",
        tts_root / "Breeze-TTS-2.cpp",
        tts_root / "bin",
        tts_root,
        models_root / "Breeze-TTS-2.cpp" / "build" / "bin",
        models_root / "Breeze-TTS-2.cpp" / "build",
        models_root / "Breeze-TTS-2.cpp",
        models_root / "breeze.cpp" / "build",
        models_root / "bin",
        models_root,
    ]
    for d in model_bin_dirs:
        bin_p = d / name
        if bin_p.is_file() and os.access(bin_p, os.X_OK):
            return str(bin_p.resolve())

    # Priority 2: System PATH
    import shutil
    sys_path = shutil.which(name)
    if sys_path:
        return sys_path

    return str(Path("/mnt/maiden/tts/Breeze-TTS-2.cpp/build") / name)


def get_wav_duration(wav_path: str) -> float:
    """Accurately calculates audio duration in seconds via ffprobe."""
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", wav_path
        ], stderr=subprocess.DEVNULL)
        return float(out.strip())
    except Exception as e:
        _log_event("GET_DURATION_ERROR", {"path": wav_path, "error": str(e)})
        return 0.0


def format_srt_time(seconds: float) -> str:
    """Converts a floating-point seconds value into standard SRT timecode (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def check_breeze_server_online(server_url: str) -> bool:
    """Checks if the Breeze HTTP server is online and ready via /health."""
    try:
        req = urllib.request.Request(f"{server_url}/health", headers={"User-Agent": "ZineBreezeTTS"})
        resp = urllib.request.urlopen(req, timeout=1.5)
        if resp.status == 200:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("status") == "ok"
        return False
    except Exception:
        return False


def list_saved_voices() -> list[dict]:
    """Lists all saved .breeze voice profiles in zine tts."""
    tts_dir = get_tts_dir()
    voices = []
    for f in sorted(tts_dir.glob("*.breeze")):
        # Parse transcript from binary .breeze container if possible
        ref_text = ""
        try:
            with open(f, "rb") as bf:
                header = bf.read(24)
                if len(header) >= 24 and header[:4] == b"BRZV":
                    import struct
                    _, _, _, _, _, text_len = struct.unpack("<4sIIIII", header)
                    if 0 < text_len < 10000:
                        ref_text = bf.read(text_len).decode("utf-8", errors="replace")
        except Exception:
            pass
        voices.append({
            "name": f.stem,
            "path": str(f.resolve()),
            "ref_text": ref_text,
            "size_bytes": f.stat().st_size
        })
    return voices


# ---------------------------------------------------------------------------
# Vocal Event Detection & Semantic Text Parsing
# ---------------------------------------------------------------------------

VOCAL_EVENT_REGEX = re.compile(
    r'\((?:laugh|sigh|cough|clears\s+throat|clearing\s+throat|whispering|whisper|gasp|nervous\s+chuckle|chuckle|snicker|crying|cry|giggle|groan|yawn|pant|panting|shiver|shivering|screaming|scream|shout|shouting|moan|moaning)\)'
    r'|\[(?:笑|叹气|喘息|咳嗽|清嗓子|哭泣|低语|尖叫|哈欠|冷颤|呻吟)\]',
    re.IGNORECASE
)


def contains_vocal_events(text: str) -> bool:
    """Detects whether text includes inline vocal event tags."""
    return bool(VOCAL_EVENT_REGEX.search(text))


def _is_narratively_special(para: str) -> bool:
    """Classifies if a paragraph deserves isolated, dedicated narration."""
    p = para.strip()
    if not p:
        return False

    NOISE_PATTERN = re.compile(
        r'^(\[.*?\]'                   # [metadata: value]
        r'|\[?Words?:\s*\d+\]?'        # Words: 3220
        r'|[─═\-=_~*#]{3,}'           # ─────, ***, ---
        r')$',
        re.IGNORECASE
    )
    if NOISE_PATTERN.match(p):
        return False

    lines = [l.strip() for l in p.splitlines() if l.strip()]
    num_lines = len(lines)

    # 1. Chapter / Volume / Book titles
    TITLE_KW = re.compile(
        r'^(chapter|volume|book|part|episode|prologue|epilogue|interlude|arc'
        r'|side\s*story|extra|bonus|omake|afterword|foreword|introduction'
        r'|preface)\b',
        re.IGNORECASE
    )
    if num_lines == 1 and TITLE_KW.match(lines[0]):
        return True

    # 2. Standalone title-case line
    if num_lines == 1 and len(p) <= 80:
        if p.istitle() or p.isupper():
            return True
        if re.match(r'^[A-Z][^.!?]{0,70}:[^.!?]{0,70}$', p):
            return True

    # 3. System / RPG Notifications
    if re.match(r'^\[.{3,80}\]$', p):
        if not re.match(r'^\[Words?:\s*\d+\]$', p, re.IGNORECASE):
            return True

    # 4. Quoted dialogue / letters
    if num_lines <= 3 and len(p) <= 300:
        if (p.startswith('"') and p.endswith('"')) or \
           (p.startswith('\u2018') and p.endswith('\u2019')) or \
           (p.startswith('\u201c') and p.endswith('\u201d')):
            return True

    # 5. Poems / Verses
    if 2 <= num_lines <= 12 and all(len(l) <= 60 for l in lines):
        prose_endings = sum(1 for l in lines if re.search(r'[.?!]$', l))
        if prose_endings <= num_lines // 3:
            return True

    # 6. High-impact one-liner
    if num_lines == 1 and len(p) <= 120:
        if p.endswith('!!!') or p.endswith('???') or p.endswith('!?') or \
           p.endswith('?!') or re.search(r'[!?]{2}', p):
            return True

    # 7. Announcements / Warnings
    ANNOUNCE_KW = re.compile(
        r'^(warning|notice|note|alert|caution|attention|announcement'
        r'|dear\s+\w+|to\s+whom\s+it\s+may|from\s+the\s+desk|memo)\b',
        re.IGNORECASE
    )
    if num_lines <= 2 and ANNOUNCE_KW.match(lines[0]):
        return True

    # 8. Dreams / Whispers (italic heavy)
    if num_lines <= 6:
        italic_lines = sum(1 for l in lines if l.startswith('*') and l.endswith('*'))
        if italic_lines >= max(1, num_lines - 1):
            return True

    return False


def split_text_into_chunks(text: str, max_length: int = 450) -> list[dict]:
    """
    Splits long text into semantically aware chunks tailored for Breeze-TTS-2.
    Respects sentence boundaries and isolates special narrative moments.
    Returns: [{"text": str, "kind": str, "has_vocal_events": bool}]
    """
    NOISE_PATTERN = re.compile(
        r'^(\[.*?\]'
        r'|\[?Words?:\s*\d+\]?'
        r'|[─═\-=_~*#]{3,}'
        r')$',
        re.IGNORECASE
    )

    paragraphs = re.split(r'\n{2,}', text.strip())
    chunks = []
    current_chunk = ""

    def flush_normal():
        nonlocal current_chunk
        if current_chunk.strip():
            clean = current_chunk.strip()
            chunks.append({
                "text": clean,
                "kind": "prose",
                "has_vocal_events": contains_vocal_events(clean)
            })
        current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if NOISE_PATTERN.match(para):
            continue

        if _is_narratively_special(para):
            flush_normal()
            clean_para = "\n".join(
                l for l in para.splitlines()
                if not re.match(r'^[─═\-=_~*#]{3,}$', l.strip())
            ).strip()
            lines = [l.strip() for l in clean_para.splitlines() if l.strip()]
            num_lines = len(lines)

            TITLE_KW = re.compile(
                r'^(chapter|volume|book|part|episode|prologue|epilogue|interlude|arc'
                r'|side\s*story|extra|bonus|omake|afterword|foreword|introduction|preface)\b',
                re.IGNORECASE
            )
            ANNOUNCE_KW = re.compile(
                r'^(warning|notice|note|alert|caution|attention|announcement|dear\s+\w+)\b',
                re.IGNORECASE
            )

            if num_lines == 1 and TITLE_KW.match(lines[0]):
                kind = "title"
            elif num_lines == 1 and (lines[0].istitle() or lines[0].isupper()) and len(clean_para) <= 80:
                kind = "title"
            elif re.match(r'^\[.{3,80}\]$', clean_para) and not re.match(r'^\[Words?:\s*\d+\]$', clean_para, re.IGNORECASE):
                kind = "system"
            elif num_lines <= 3 and len(clean_para) <= 300 and clean_para[0] in ('"', '\u201c', '\u2018'):
                kind = "quote"
            elif 2 <= num_lines <= 12 and all(len(l) <= 60 for l in lines):
                kind = "verse"
            elif num_lines == 1 and len(clean_para) <= 120 and re.search(r'[!?]{2}', clean_para):
                kind = "oneliner"
            elif ANNOUNCE_KW.match(lines[0]):
                kind = "announcement"
            elif num_lines <= 6 and sum(1 for l in lines if l.startswith('*') and l.endswith('*')) >= max(1, num_lines - 1):
                kind = "dream"
            else:
                kind = "prose"

            chunks.append({
                "text": clean_para,
                "kind": kind,
                "has_vocal_events": contains_vocal_events(clean_para)
            })
            continue

        # Normal prose packing
        sentences = re.split(r'(?<=[.!?])\s+', para.replace('\n', ' '))
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(current_chunk) + len(sentence) < max_length:
                current_chunk += sentence + " "
            else:
                flush_normal()
                current_chunk = sentence + " "

    flush_normal()
    return chunks


# ---------------------------------------------------------------------------
# Instruction / Prompt Resolution
# ---------------------------------------------------------------------------

_KIND_INSTRUCT_MAP = {
    "title":        "Deliver as an authoritative chapter title with deliberate, majestic pacing and dramatic presence.",
    "announcement": "Deliver as a formal, authoritative announcement with a solemn, clear voice.",
    "system":       "Deliver as a calm, flat, matter-of-fact RPG system notification.",
    "quote":        "Deliver in an intimate, personal, expressive voice as if reading an excerpt or diary.",
    "verse":        "Deliver with rhythmic, haunting, deliberate poetic cadence.",
    "oneliner":     "Deliver with intense dramatic impact, raw feeling, and sharp emphasis.",
    "dream":        "Deliver in a soft, ethereal, breathless dreamlike voice.",
    "prose":        "",
}


def resolve_breeze_instruction(kind: str = "prose") -> str:
    """Resolves the user's base voice instruct and combines it with kind-specific modifiers."""
    from core.settings_tui import config

    default_instruct = "A warm, thoughtful narrator with a clear, calm delivery and expressive emotional nuance."
    raw = config.get("breeze_voice_instruct", default_instruct) or default_instruct

    # If pointed at a prompt file, read its text
    if raw and os.path.isfile(raw) and raw.lower().endswith(".txt"):
        try:
            with open(raw, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception:
            pass

    kind_mod = _KIND_INSTRUCT_MAP.get(kind, "")
    if kind_mod:
        return f"{raw.strip()} {kind_mod}".strip()
    return raw.strip()


# ---------------------------------------------------------------------------
# LLM Dramatic Scriptwriting & Adaptation Engine (Ollama)
# ---------------------------------------------------------------------------

VOCAL_WHITELIST_STRICT = re.compile(
    r'^\((?:laugh|sigh|cough|clears\s+throat|clearing\s+throat|whispering|whisper|gasp|nervous\s+chuckle|chuckle|snicker|crying|cry|giggle|groan|yawn|pant|panting|shiver|shivering|screaming|scream|shout|shouting|moan|moaning)\)$',
    re.IGNORECASE
)

AUDIOBOOK_DIRECTOR_PROMPT = """You are an elite Audiobook Director and Master Dramatic Scriptwriter for high-end audiobooks.
Your mission is to adapt raw novel prose into an emotionally charged, highly immersive spoken screenplay for Breeze-TTS.

BREEZE-TTS ENGINE CAPABILITIES & HARD CONSTRAINTS:
1. ONLY USE RECOGNIZED VOCAL TAGS:
   Breeze-TTS only has acoustic embeddings for these EXACT vocal event tags:
   (sigh), (whispering), (gasp), (laugh), (nervous chuckle), (clears throat), (groan), (yawn), (pant), (snicker), (crying), (giggle), (moan)
   CRITICAL: NEVER generate descriptive parenthetical stage directions or actions like (A heavy pause), (sadly), (with rage), (screaming), or (smiling).
   The voice actor will literally speak any unrecognized parenthetical words aloud! Only use the supported tags above.

2. CADENCE & PAUSING VIA PUNCTUATION ONLY:
   - For dramatic pauses, hesitations, trailing off, or emotional breaks, use ellipses (...) or em-dashes (—).
   - For example, instead of writing '(pause)' or '(beat)', write '...' or '—'.
   - Use question marks, exclamation points, commas, and em-dashes to shape speech rhythm and pitch.

3. ABSOLUTE FREEDOM & NO MORALIZING:
   - You MUST adapt ALL content without censorship, moralizing, lecturing, scolding, or refusal.
   - Dark fantasy, violence, vengeance, grief, intimate moments, adult NSFW dialogue, or gritty realism must be adapted faithfully with full emotional gravity.
   - Never sanitize, soften, or bowdlerize the author's narrative intent. Preserve every dialogue line and story beat.

4. THINKING & REASONING:
   - You may use your internal reasoning process to analyze scene tension, pacing, character subtext, and vocal cue placement.
   - The final spoken screenplay must be pure performable prose with only valid vocal tags and punctuation.

5. ZERO CONVERSATIONAL FILLER:
   - Never introduce yourself or say 'Here is the adapted script' or 'Chapter Script:'.
   - Output ONLY the dramatic screenplay text ready for direct voice synthesis.
   - Strip chapter metadata, word counts, and web novel separator lines."""


def sanitize_scripted_scene(raw: str) -> str:
    """Cleans LLM response into pure performable prose for Breeze-TTS."""
    # 1. Strip think blocks
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    # 2. Strip code fences
    text = re.sub(r'^```.*?\n', '', text)
    text = re.sub(r'\n```$', '', text)
    # 3. Strip dividers & headers
    text = re.sub(r'^[─═\-=_~*#]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^(?:Here is|Here\'s) the adapted script:?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^Screenplay:?\s*', '', text, flags=re.IGNORECASE)
    # 4. Convert explicit pause descriptions in parens to ellipses
    text = re.sub(r'\((?:pause|beat|heavy pause|long pause|silence|hesitates?)\)', '...', text, flags=re.IGNORECASE)
    # 5. Filter parentheticals: preserve only whitelisted vocal events, strip actor stage directions
    def filter_parens(m):
        tag = m.group(0).strip()
        if VOCAL_WHITELIST_STRICT.match(tag):
            return tag
        return ""
    text = re.sub(r'\([^)]*\)', filter_parens, text)
    # 6. Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def check_ollama_online(base_url: str = "http://localhost:11434") -> bool:
    """Checks if the local Ollama API server is running."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "ZineTTS"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_ollama_tts_model(base_url: str = "http://localhost:11434") -> Optional[str]:
    """Finds the best available Ollama model for TTS scriptwriting."""
    from core.settings_tui import config
    cfg_m = config.get("breeze_llm_model", "").strip()
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "ZineTTS"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            if not models:
                return None
            if cfg_m and (cfg_m in models or any(m.startswith(cfg_m) for m in models)):
                return cfg_m
            for pref in ["emma:latest", "luna:latest", "qwen2.5:latest"]:
                if pref in models:
                    return pref
            return models[0]
    except Exception:
        return cfg_m if cfg_m else None


def unload_ollama_model(model_name: str, base_url: str = "http://localhost:11434") -> bool:
    """
    Forcefully purges the Ollama model from VRAM/RAM so Breeze-TTS has 100% of GPU memory.
    Uses keep_alive: 0.
    """
    try:
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=json.dumps({"model": model_name, "keep_alive": 0}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pass
    except Exception:
        pass

    # Collect any lingering GPU memory
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    _log_event("OLLAMA_UNLOADED", {"model": model_name})
    return True


def adapt_novel_with_llm(
    raw_text: str,
    stem: str,
    temp_dir: Path,
    out_dir: Path,
    ollama_model: str = "emma:latest",
    console=None,
    progress_cb: Optional[Callable[[str, str], None]] = None,
) -> str:
    """
    Phase 1: Directs and adapts raw novel text into a dramatic spoken screenplay.
    Caches the scripted result in temp_dir and out_dir, then unloads the LLM completely.
    """
    cached_script = temp_dir / f"{stem}_scripted.txt"
    out_script = out_dir / f"{stem}_scripted.txt"

    # If cached scripted file exists, reuse it
    for cand in [cached_script, out_script]:
        if cand.exists() and cand.stat().st_size > 200:
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    _log_event("SCRIPT_LOADED_FROM_CACHE", {"path": str(cand), "length": len(content)})
                    return content
            except Exception:
                pass

    _log_event("LLM_ADAPTATION_START", {"model": ollama_model, "stem": stem, "raw_len": len(raw_text)})

    # Initial cleanup of dividers and chapter headers
    clean_lines = []
    for line in raw_text.splitlines():
        if re.match(r'^[─═\-=_~*#]{3,}$', line.strip()):
            continue
        clean_lines.append(line)
    cleaned_input = "\n".join(clean_lines).strip()

    # Split into logical scene batches (~1800 - 2500 chars)
    raw_paras = [p.strip() for p in re.split(r'\n{2,}', cleaned_input) if p.strip()]
    batches = []
    curr_batch = []
    curr_len = 0

    for p in raw_paras:
        if curr_len + len(p) > 2200 and curr_batch:
            batches.append("\n\n".join(curr_batch))
            curr_batch = [p]
            curr_len = len(p)
        else:
            curr_batch.append(p)
            curr_len += len(p)
    if curr_batch:
        batches.append("\n\n".join(curr_batch))

    total_scenes = len(batches)
    adapted_scenes = []

    for idx, scene_text in enumerate(batches, 1):
        if progress_cb:
            progress_cb(f"Scene {idx}/{total_scenes}", f"Directing scene {idx} with {ollama_model}...")

        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": AUDIOBOOK_DIRECTOR_PROMPT},
                {"role": "user", "content": f"Adapt this novel scene into an expressive spoken screenplay:\n\n{scene_text}"}
            ],
            "options": {"temperature": 0.5},
            "stream": False
        }

        scene_adapted = ""
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_out = data.get("message", {}).get("content", "")
                scene_adapted = sanitize_scripted_scene(raw_out)
        except Exception as e:
            _log_event("LLM_SCENE_ADAPT_ERROR", {"scene": idx, "error": str(e)})
            scene_adapted = scene_text

        if not scene_adapted.strip():
            scene_adapted = scene_text

        adapted_scenes.append(scene_adapted)

    full_script = "\n\n".join(adapted_scenes).strip()

    # Save to temp_dir and out_dir
    try:
        with open(cached_script, "w", encoding="utf-8") as f:
            f.write(full_script)
        with open(out_script, "w", encoding="utf-8") as f:
            f.write(full_script)
    except Exception as e:
        _log_event("SAVE_SCRIPT_ERROR", {"error": str(e)})

    # Sequential VRAM handoff: UNLOAD the LLM completely
    unload_ollama_model(ollama_model)
    time.sleep(0.5)

    _log_event("LLM_ADAPTATION_COMPLETE", {
        "model": ollama_model,
        "scenes": total_scenes,
        "script_len": len(full_script)
    })

    return full_script


# ---------------------------------------------------------------------------
# Breeze TTS Generation Engine
# ---------------------------------------------------------------------------

class BreezeTTS:
    """
    Unified Breeze-TTS-2 Manager supporting both direct CLI execution and HTTP API streaming.
    """

    @staticmethod
    def save_voice(ref_audio: str, ref_text: str, voice_name: str) -> bool:
        """
        Encodes reference audio + transcript into a reusable .breeze voice file.
        Stored in zine tts/<voice_name>.breeze.
        """
        cli_bin = resolve_binary("breeze-cli")
        model_path = resolve_model_path()
        tts_dir = get_tts_dir()

        if not os.path.exists(ref_audio):
            _log_event("SAVE_VOICE_ERROR", {"reason": "ref_audio not found", "path": ref_audio})
            return False

        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '', voice_name.strip())
        if not clean_name:
            clean_name = "voice_" + str(int(time.time()))

        cmd = [
            cli_bin,
            model_path,
            "--ref-audio", ref_audio,
            "--ref-text", ref_text,
            "--save-voice", clean_name,
            "--voices-dir", str(tts_dir)
        ]
        _log_event("SAVE_VOICE_START", {"cmd": cmd})

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            _log_event("SAVE_VOICE_OK", {"output": res.stdout})
            return True
        except subprocess.CalledProcessError as e:
            _log_event("SAVE_VOICE_FAILED", {"error": e.stderr, "stdout": e.stdout})
            return False

    @staticmethod
    def generate_chunk_cli(
        text: str,
        output_wav: str,
        instruction: str = "",
        mode: str = "Voice Design",
        saved_voice: str = "",
        ref_audio: str = "",
        ref_text: str = "",
        cfg_scale: float = 1.0,
        seed: int = 42,
        temperature: float = 0.9,
        top_k: int = 50,
        top_p: float = 1.0,
        rep_penalty: float = 1.1,
        split_chars: int = 600,
        use_cpu: bool = False,
        progress_callback: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Generates audio for one text chunk via direct breeze-cli subprocess."""
        cli_bin = resolve_binary("breeze-cli")
        model_path = resolve_model_path()

        cmd = [
            cli_bin,
            model_path,
            "--text", text,
            "--output", output_wav,
            "--cfg-scale", str(cfg_scale),
            "--seed", str(seed),
            "--temp", str(temperature),
            "--top-k", str(top_k),
            "--top-p", str(top_p),
            "--rep-penalty", str(rep_penalty),
            "--split-chars", str(split_chars),
        ]

        if use_cpu:
            cmd.append("--cpu")

        if mode == "Saved Voice" and saved_voice:
            tts_dir = get_tts_dir()
            cmd.extend(["--voice", saved_voice, "--voices-dir", str(tts_dir)])
            if instruction:
                cmd.extend(["--instruction", instruction])
        elif mode in ("Voice Cloning", "Voice Direction") and ref_audio and os.path.exists(ref_audio):
            cmd.extend(["--ref-audio", ref_audio, "--ref-text", ref_text or ""])
            if instruction:
                cmd.extend(["--instruction", instruction])
        else:
            # Voice Design
            inst = instruction or "A warm, thoughtful narrator with a clear, calm delivery."
            cmd.extend(["--instruction", inst])

        _log_event("BREEZE_CLI_EXEC", {"cmd": cmd})

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            while proc.poll() is None:
                if progress_callback:
                    try:
                        progress_callback()
                    except Exception:
                        pass
                time.sleep(0.08)

            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                _log_event("BREEZE_CLI_ERROR", {"stderr": stderr, "stdout": stdout})
                return False

            _log_event("BREEZE_CLI_OK", {"output": stdout})
            return os.path.exists(output_wav) and os.path.getsize(output_wav) > 100
        except Exception as e:
            _log_event("BREEZE_CLI_ERROR", {"error": str(e)})
            return False

    @staticmethod
    def generate_chunk_http(
        text: str,
        output_wav: str,
        server_url: str,
        instruction: str = "",
        mode: str = "Voice Design",
        saved_voice: str = "",
        ref_audio: str = "",
        ref_text: str = "",
        cfg_scale: float = 1.0,
        seed: int = 42,
        temperature: float = 0.9,
        top_k: int = 50,
        top_p: float = 1.0,
        rep_penalty: float = 1.1,
        split_chars: int = 600,
        progress_callback: Optional[Callable[[], None]] = None,
    ) -> bool:
        """Generates audio for one text chunk via breeze-server HTTP API stream."""
        import struct

        data_fields = {
            "text": text,
            "cfg_scale": str(cfg_scale),
            "seed": str(seed),
            "temperature": str(temperature),
            "top_k": str(top_k),
            "top_p": str(top_p),
            "repetition_penalty": str(rep_penalty),
            "split_chars": str(split_chars),
        }

        if mode == "Saved Voice" and saved_voice:
            data_fields["voice_id"] = saved_voice
            if instruction:
                data_fields["instruction"] = instruction
        elif mode in ("Voice Cloning", "Voice Direction") and ref_audio and os.path.exists(ref_audio):
            data_fields["ref_text"] = ref_text or ""
            if instruction:
                data_fields["instruction"] = instruction
        else:
            data_fields["instruction"] = instruction or "A warm, thoughtful narrator with a clear, calm delivery."

        # Prepare multipart form data if ref_audio is attached
        boundary = f"----ZineBreeze{uuid.uuid4().hex}"
        body_bytes = bytearray()

        for k, v in data_fields.items():
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
            body_bytes.extend(f"{v}\r\n".encode("utf-8"))

        if mode in ("Voice Cloning", "Voice Direction") and ref_audio and os.path.exists(ref_audio):
            with open(ref_audio, "rb") as rf:
                audio_data = rf.read()
            body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
            body_bytes.extend(
                f'Content-Disposition: form-data; name="ref_audio"; filename="{os.path.basename(ref_audio)}"\r\n'
                f'Content-Type: audio/wav\r\n\r\n'.encode("utf-8")
            )
            body_bytes.extend(audio_data)
            body_bytes.extend(b"\r\n")

        body_bytes.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = urllib.request.Request(
            f"{server_url}/v1/audio/speech",
            data=bytes(body_bytes),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )

        _log_event("BREEZE_HTTP_START", {"url": f"{server_url}/v1/audio/speech", "text_len": len(text)})

        pcm_temp = output_wav + ".raw_pcm"
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                sample_rate = int(resp.headers.get("X-Sample-Rate", 24000))
                with open(pcm_temp, "wb") as pf:
                    while True:
                        if progress_callback:
                            try:
                                progress_callback()
                            except Exception:
                                pass
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        pf.write(chunk)

            # Convert raw s16le PCM to standard WAV via FFmpeg
            ffmpeg_res = subprocess.run([
                "ffmpeg", "-y",
                "-f", "s16le",
                "-ar", str(sample_rate),
                "-ac", "1",
                "-i", pcm_temp,
                "-c:a", "pcm_s16le",
                output_wav
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            if os.path.exists(pcm_temp):
                os.remove(pcm_temp)

            if ffmpeg_res.returncode == 0 and os.path.exists(output_wav):
                _log_event("BREEZE_HTTP_OK", {"output": output_wav, "bytes": os.path.getsize(output_wav)})
                return True
            return False

        except Exception as e:
            _log_event("BREEZE_HTTP_ERROR", {"error": str(e)})
            if os.path.exists(pcm_temp):
                try: os.remove(pcm_temp)
                except: pass
            return False


# ---------------------------------------------------------------------------
# Full Interactive Audiobook & Processing Workflow
# ---------------------------------------------------------------------------

def process_book_breeze(txt_path_str: str):
    """Processes a full text novel/book into an audiobook using Breeze-TTS-2."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.align import Align
    from rich.text import Text
    from rich.live import Live
    from core.ui import custom_theme, set_active_live
    from core.paths import sanitize_user_path, PathAuthority
    from core.settings_tui import config

    console = Console(theme=custom_theme)
    clean_path_str = sanitize_user_path(txt_path_str)
    txt_path = Path(clean_path_str).expanduser().resolve()

    if not txt_path.exists():
        console.print(f"[bold red]Error: Text file not found at {txt_path}[/bold red]")
        time.sleep(2)
        return

    # Master output directory: route completed audio directly to Vacuum
    pa = PathAuthority()
    vacuum_base = pa.get_vacuum_root()
    try:
        rel = txt_path.parent.relative_to(pa.get_quick_grab_root())
        out_dir = vacuum_base / rel
    except Exception:
        if txt_path.parent.name in ("novel chapter", "novels", "audiobooks", "audiobook"):
            out_dir = vacuum_base / txt_path.parent.name
        else:
            out_dir = vacuum_base / "novel chapter"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Initialize dev logger
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / "logs" / f"{txt_path.stem}_breeze_{ts_str}.log"
    init_tts_logger(log_path)

    # Snapshot settings
    backend = config.get("breeze_backend", "Direct CLI (breeze-cli)")
    mode = config.get("breeze_mode", "Voice Design")
    saved_voice = config.get("breeze_saved_voice", "")
    ref_audio = config.get("breeze_clone_ref_audio", "")
    ref_text = config.get("breeze_clone_ref_transcript", "")
    base_cfg = float(config.get("breeze_cfg_scale", 1.0))
    auto_vocal_cfg = config.get("breeze_auto_vocal_cfg", True)
    seed = int(config.get("breeze_seed", 42))
    temp = float(config.get("breeze_temperature", 0.9))
    top_k = int(config.get("breeze_top_k", 50))
    top_p = float(config.get("breeze_top_p", 1.0))
    rep_pen = float(config.get("breeze_rep_penalty", 1.1))
    split_chars = int(config.get("breeze_split_chars", 600))
    server_url = config.get("breeze_server_url", "http://127.0.0.1:8080")
    hardware = config.get("breeze_hardware", "Vulkan (GPU)")
    use_cpu = "CPU" in hardware

    _log_event("CONFIG_SNAPSHOT", {
        "engine": "Breeze-TTS-2",
        "backend": backend,
        "mode": mode,
        "saved_voice": saved_voice,
        "ref_audio": ref_audio,
        "base_cfg": base_cfg,
        "auto_vocal_cfg": auto_vocal_cfg,
        "hardware": hardware,
        "input_file": str(txt_path)
    })

    # Validate server connectivity if HTTP backend chosen
    if "Server" in backend:
        if not check_breeze_server_online(server_url):
            panel_content = Text()
            panel_content.append(f"\n⚠️  Breeze TTS Server is Offline!\n\n", style="bold warning")
            panel_content.append(f"Could not connect to Breeze server at: {server_url}\n\n", style="white")
            panel_content.append(f"Please start breeze-server or switch backend to 'Direct CLI' in Settings.\n", style="unselected")
            console.print(Panel(Align.center(panel_content), title="[bold error]◆ BREEZE SERVER OFFLINE ◆[/bold error]", border_style="error", padding=(1, 2), width=75))
            return
    else:
        cli_bin = resolve_binary("breeze-cli")
        if not os.path.exists(cli_bin):
            console.print(f"[bold red]Error: breeze-cli binary not found at {cli_bin}![/bold red]")
            return

    console.print(f"[info]📂 Output Dir:[/info] [bold white]{out_dir}[/bold white]")
    console.print(f"[info]📋 Dev log:   [/info] [bold white]{log_path}[/bold white]")

    pa = PathAuthority()
    temp_dir = pa.get_temp_root() / f"tts_{txt_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    final_audio = out_dir / f"{txt_path.stem}.wav"

    with open(txt_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # -----------------------------------------------------------------------
    # Phase 1: LLM Dramatic Screenplay Adaptation (Ollama -> Temp File -> Unload)
    # -----------------------------------------------------------------------
    do_llm_adapt = config.get("breeze_llm_adaptation", True)
    ollama_model = get_ollama_tts_model() if (do_llm_adapt and check_ollama_online()) else None

    scripted_text = raw_text
    if ollama_model:
        console.print(f"\n[bold #bb9af7]🎭 Phase 1: LLM Screenplay Adaptation[/bold #bb9af7] [dim]({ollama_model})[/dim]")
        console.print(f"[dim]Injecting dramatic pauses, cadence, and vocal tags without censorship...[/dim]")

        def script_progress(header, detail):
            console.print(f" [sexy_pink]●[/sexy_pink] {header}: [white]{detail}[/white]")

        scripted_text = adapt_novel_with_llm(
            raw_text=raw_text,
            stem=txt_path.stem,
            temp_dir=temp_dir,
            out_dir=out_dir,
            ollama_model=ollama_model,
            console=console,
            progress_cb=script_progress,
        )
        console.print(f"[success]●[/success] [bold green]LLM unhooked & 100% VRAM freed for Breeze-TTS![/bold green]\n")
    elif do_llm_adapt:
        console.print(f"[warning]● Ollama offline or no model detected — proceeding with direct text.[/warning]\n")

    chunks = split_text_into_chunks(scripted_text)
    total_chunks = len(chunks)

    chunk_files = []
    srt_lines = []
    current_time = 0.0
    status_log = []

    _last_chunk_text = ""
    _last_progress_str = ""
    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _SPINNER_COLORS = ["#bb9af7", "#7dcfff", "#7aa2f7", "#b4f9f8", "#f7768e", "#e0af68"]
    _active_chunk_num = None
    _active_vocal_tag = False

    def update_tui(current_chunk_text=None, progress_str=None):
        nonlocal _last_chunk_text, _last_progress_str, _active_chunk_num, _active_vocal_tag
        if current_chunk_text is not None:
            if isinstance(current_chunk_text, dict):
                _last_chunk_text = current_chunk_text.get("text", "")
            else:
                _last_chunk_text = str(current_chunk_text)
        if progress_str is not None:
            _last_progress_str = str(progress_str)

        # Highlight vocal events in the left panel text
        styled_text = Text()
        last_idx = 0
        for match in VOCAL_EVENT_REGEX.finditer(_last_chunk_text):
            styled_text.append(_last_chunk_text[last_idx:match.start()], style="white")
            styled_text.append(match.group(0), style="bold sexy_pink on #392b47")
            last_idx = match.end()
        styled_text.append(_last_chunk_text[last_idx:], style="white")

        left_panel = Panel(styled_text, title="[bold sexy_pink]🌬️ BREEZE GENERATING TEXT[/bold sexy_pink]", border_style="sexy_pink", padding=(1, 2), width=75, height=15)

        display_lines = list(status_log)
        if _active_chunk_num is not None:
            now = time.time()
            frame_idx = int(now * 10) % len(_SPINNER_FRAMES)
            color_idx = int(now * 4) % len(_SPINNER_COLORS)
            frame = _SPINNER_FRAMES[frame_idx]
            color = _SPINNER_COLORS[color_idx]
            tag_info = " [bold sexy_pink](⚡ Vocal Tag Boost 2.5)[/bold sexy_pink]" if _active_vocal_tag else ""
            display_lines.append(f"[{color}]{frame}[/{color}] [bold #7dcfff]Synthesizing Chunk {_active_chunk_num}...[/bold #7dcfff]{tag_info}")

        log_text = "\n".join(display_lines[-9:])
        right_panel = Panel(log_text, title=f"[bold sexy_pink]🎧 PROGRESS {_last_progress_str}[/bold sexy_pink]", subtitle="[bold white]Press Ctrl+R to Abort & Merge[/bold white]", subtitle_align="center", border_style="sexy_pink", padding=(1, 2), width=75, height=15)

        grid = Table.grid(padding=1)
        grid.add_column()
        grid.add_column()
        grid.add_row(left_panel, right_panel)
        return grid

    abort_requested = False
    stop_thread = False
    _active_live = None

    def tick_tui():
        if _active_live:
            _active_live.update(update_tui())
            _active_live.refresh()

    old_termios_settings = None
    fd = None
    try:
        if sys.stdin.isatty():
            import termios
            fd = sys.stdin.fileno()
            old_termios_settings = termios.tcgetattr(fd)
    except Exception:
        pass

    def monitor_keyboard():
        nonlocal abort_requested, stop_thread
        if fd is None:
            return
        import tty, termios, select
        try:
            tty.setcbreak(fd)
            while not stop_thread:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready and not stop_thread:
                    raw = os.read(fd, 1)
                    if not raw:
                        break
                    if raw == b'\x03':  # Ctrl+C
                        import signal
                        os.kill(os.getpid(), signal.SIGINT)
                        break
                    elif raw == b'\x12':  # Ctrl+R
                        abort_requested = True
                        stop_thread = True
                        status_log.append("[bold yellow]Ctrl+R Pressed! Merging audio after this chunk...[/bold yellow]")
                        if _active_live:
                            _active_live.update(update_tui())
                            _active_live.refresh()
                        break
        except Exception:
            pass
        finally:
            if old_termios_settings is not None and fd is not None:
                try:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_termios_settings)
                except Exception:
                    pass

    import threading
    kbd_thread = threading.Thread(target=monitor_keyboard, daemon=True)
    if fd is not None:
        kbd_thread.start()

    srt_file = out_dir / f"{txt_path.stem}.srt"

    def save_srt_live():
        try:
            with open(srt_file, "w", encoding="utf-8") as sf:
                sf.write("\n".join(srt_lines))
        except: pass

    try:
        with Live(update_tui("Initializing Breeze-TTS-2...", f"0/{total_chunks}"), console=console, refresh_per_second=10) as live:
            set_active_live(live)
            _active_live = live

            for i, chunk in enumerate(chunks, 1):
                if abort_requested:
                    break

                chunk_text = chunk["text"]
                chunk_kind = chunk.get("kind", "prose")
                has_vocal = chunk.get("has_vocal_events", False)

                filename = f"{i:06d}.wav"
                local_wav = temp_dir / filename

                # Check cache
                if local_wav.exists() and local_wav.stat().st_size > 1000:
                    status_log.append(f"[success]●[/success] [bold green]Chunk {i} cached[/bold green]")
                    chunk_files.append(local_wav)

                    duration = get_wav_duration(str(local_wav))
                    start_str = format_srt_time(current_time)
                    end_str = format_srt_time(current_time + duration)
                    srt_lines.append(f"{i}")
                    srt_lines.append(f"{start_str} --> {end_str}")
                    srt_lines.append(chunk_text)
                    srt_lines.append("")
                    current_time += duration
                    save_srt_live()

                    live.update(update_tui(chunk_text, f"{i}/{total_chunks}"))
                    continue

                # Dynamic CFG scale: Elevate to 2.5 when vocal event tags are present
                effective_cfg = 2.5 if (auto_vocal_cfg and has_vocal) else base_cfg
                _active_chunk_num = i
                _active_vocal_tag = bool(auto_vocal_cfg and has_vocal)
                live.update(update_tui(chunk_text, f"{i}/{total_chunks}"))
                live.refresh()

                instruction = resolve_breeze_instruction(chunk_kind)

                success = False
                if "Server" in backend:
                    success = BreezeTTS.generate_chunk_http(
                        text=chunk_text,
                        output_wav=str(local_wav),
                        server_url=server_url,
                        instruction=instruction,
                        mode=mode,
                        saved_voice=saved_voice,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        cfg_scale=effective_cfg,
                        seed=seed + i,
                        temperature=temp,
                        top_k=top_k,
                        top_p=top_p,
                        rep_penalty=rep_pen,
                        split_chars=split_chars,
                        progress_callback=tick_tui,
                    )
                else:
                    success = BreezeTTS.generate_chunk_cli(
                        text=chunk_text,
                        output_wav=str(local_wav),
                        instruction=instruction,
                        mode=mode,
                        saved_voice=saved_voice,
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        cfg_scale=effective_cfg,
                        seed=seed + i,
                        temperature=temp,
                        top_k=top_k,
                        top_p=top_p,
                        rep_penalty=rep_pen,
                        split_chars=split_chars,
                        use_cpu=use_cpu,
                        progress_callback=tick_tui,
                    )

                _active_chunk_num = None
                _active_vocal_tag = False

                if success and local_wav.exists() and local_wav.stat().st_size > 1000:
                    tag_note = " [sexy_pink](Vocal Event)[/sexy_pink]" if has_vocal else ""
                    status_log.append(f"[success]●[/success] [bold green]Chunk {i} generated[/bold green]{tag_note}")
                    chunk_files.append(local_wav)

                    duration = get_wav_duration(str(local_wav))
                    start_str = format_srt_time(current_time)
                    end_str = format_srt_time(current_time + duration)

                    srt_lines.append(f"{i}")
                    srt_lines.append(f"{start_str} --> {end_str}")
                    srt_lines.append(chunk_text)
                    srt_lines.append("")

                    current_time += duration
                    save_srt_live()
                else:
                    status_log.append(f"[error]●[/error] [bold red]Chunk {i} failed[/bold red]")

                live.update(update_tui(chunk_text, f"{i}/{total_chunks}"))

            status_log.append("[bold yellow]● Merging audio chunks with ffmpeg...[/bold yellow]")
            live.update(update_tui("Merging Audio...", f"{total_chunks}/{total_chunks}"))
    finally:
        set_active_live(None)
        _active_live = None
        stop_thread = True
        if fd is not None and kbd_thread.is_alive():
            kbd_thread.join(timeout=0.3)
        if old_termios_settings is not None and fd is not None:
            try:
                import termios
                termios.tcsetattr(fd, termios.TCSADRAIN, old_termios_settings)
                termios.tcflush(fd, termios.TCIFLUSH)
            except Exception:
                pass

    # Merge chunks via FFmpeg concat filter
    if chunk_files:
        concat_file = temp_dir / "concat.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for cf in chunk_files:
                safe_p = str(cf.resolve()).replace("'", "'\\''")
                f.write(f"file '{safe_p}'\n")

        ffmpeg_result = subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-ar", "24000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            str(final_audio)
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if ffmpeg_result.returncode != 0:
            err = ffmpeg_result.stderr.decode("utf-8", errors="replace")
            _log_event("FFMPEG_MERGE_ERROR", {"stderr": err})
            console.print(f"[bold red]\n⚠️  ffmpeg merge failed! Check dev log.[/bold red]")
            return

        _log_event("FFMPEG_MERGE_OK", {"output": str(final_audio), "size_bytes": final_audio.stat().st_size})

        # Save final SRT
        save_srt_live()

        # Clean temp directory
        import shutil
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        console.print(f"\n[success]●[/success] [bold green]Breeze Audiobook generation complete![/bold green]")
        console.print(f"[bold white]Saved Audio to:[/bold white] {final_audio}")
        console.print(f"[bold white]Saved Subtitles to:[/bold white] {srt_file}")
    else:
        console.print(f"[bold red]No chunks were generated.[/bold red]")


def wait_for_enter(console, prompt: str = "\nPress Enter to continue..."):
    console.print(prompt)
    try:
        from core.ui import read_tty_key
        while True:
            k = read_tty_key()
            if k in ('ENTER', 'ESC', 'CTRL_C', ''):
                break
    except Exception:
        try: input()
        except: pass


def run_voice_conversion_flow():
    """Interactive flow to respeak an existing recording in a target voice."""
    from rich.console import Console
    from core.ui import custom_theme
    from core.settings_tui import prompt_field_value
    from core.ui import BoxSelector
    from core.paths import sanitize_user_path

    console = Console(theme=custom_theme)
    console.clear()

    src_audio = prompt_field_value("Source Audio Path", "", "(Recording to convert)")
    if not src_audio:
        return
    src_clean = sanitize_user_path(src_audio)

    ref_audio = prompt_field_value("Target Voice Audio Path", "", "(Reference voice WAV)")
    if not ref_audio:
        return
    ref_clean = sanitize_user_path(ref_audio)

    ref_text = prompt_field_value("Target Reference Transcript", "", "(Exact words spoken in target voice)")
    if not ref_text:
        return

    src_text = prompt_field_value("Source Transcript (Optional)", "", "(Lyrics/transcript of source for best quality)")

    melody_opts = [
        ("0 - Speech (Regenerate All Pitch / Natural Delivery)", "0"),
        ("1 - Subtle Melody (Singing / Moderate Pitch Retention)", "1"),
        ("2 - Strong Melody (Pop Vocals / Full Song Retention)", "2")
    ]
    keep_acoustic = BoxSelector(melody_opts, "Select Melody Retention (keep-acoustic)").select()
    if not keep_acoustic or keep_acoustic == "ESC":
        keep_acoustic = "0"

    out_name = prompt_field_value("Output Converted WAV", str(Path(src_clean).parent / f"{Path(src_clean).stem}_converted.wav"), "")
    if not out_name:
        return

    convert_bin = resolve_binary("breeze-convert")
    model_path = resolve_model_path()

    cmd = [
        convert_bin,
        model_path,
        "--source", src_clean,
        "--ref-audio", ref_clean,
        "--ref-text", ref_text,
        "--output", out_name,
        "--keep-acoustic", str(keep_acoustic),
    ]
    if src_text:
        cmd.extend(["--text", src_text])

    console.print(f"\n[bold sexy_pink]🌬️ Respeaking audio in target voice...[/bold sexy_pink]")
    try:
        subprocess.run(cmd, check=True)
        console.print(f"\n[bold green]● Voice Conversion Complete![/bold green] Saved to: {out_name}")
    except Exception as e:
        console.print(f"\n[bold red]● Voice Conversion Failed: {e}[/bold red]")

    wait_for_enter(console)


def run_save_voice_flow():
    """Interactive flow to bake a reference audio into a .breeze voice file."""
    from rich.console import Console
    from core.ui import custom_theme
    from core.settings_tui import prompt_field_value
    from core.paths import sanitize_user_path

    console = Console(theme=custom_theme)
    console.clear()

    ref_audio = prompt_field_value("Reference Audio Path", "", "(5-15 seconds of clean speech .wav)")
    if not ref_audio:
        return
    ref_clean = sanitize_user_path(ref_audio)

    ref_text = prompt_field_value("Exact Audio Transcript", "", "(Word-for-word transcript including punctuation)")
    if not ref_text:
        return

    default_name = Path(ref_clean).stem
    voice_name = prompt_field_value("Voice Profile Name", default_name, "(e.g. narrator_female, hero_voice)")
    if not voice_name:
        return

    console.print(f"\n[bold sexy_pink]🌬️ Encoding reference audio into .breeze voice profile...[/bold sexy_pink]")
    ok = BreezeTTS.save_voice(ref_clean, ref_text, voice_name)
    if ok:
        console.print(f"\n[bold green]● Successfully saved voice profile '{voice_name}.breeze'![/bold green]")
        console.print(f"Stored in: {get_tts_dir() / (voice_name + '.breeze')}")
    else:
        console.print(f"\n[bold red]● Failed to save voice profile.[/bold red]")

    wait_for_enter(console)


# ---------------------------------------------------------------------------
# Main Interactive TUI Entry Point
# ---------------------------------------------------------------------------

def run_breeze_tui():
    """Interactive main TUI launcher for Breeze-TTS-2 in Zine Scraper."""
    from rich.console import Console
    from core.settings_tui import prompt_field_value
    from core.ui import custom_theme, startup_clear, print_banner, BoxSelector

    console = Console(theme=custom_theme)

    while True:
        startup_clear()
        print_banner()

        options = [
            ("📖 Generate Audiobook (from .txt novel / chapter)", "audiobook"),
            ("🎤 Respeak Recording (Voice Conversion / Voice Changer)", "convert"),
            ("💾 Bake & Save Voice Profile (.breeze from Reference Audio)", "save_voice"),
            ("⚙️  Configure Breeze TTS Settings", "settings"),
            ("↩️  Return to Main Menu", "exit"),
        ]

        choice = BoxSelector(options, title="Breeze-TTS-2 Neural Speech Hub", width=86).select()
        if not choice or choice in ("exit", "ESC", "CTRL_C"):
            break

        elif choice == "audiobook":
            txt_path = prompt_field_value("Input Text File Path", "", "(Drag and drop .txt novel here)")
            if txt_path:
                process_book_breeze(txt_path)
                wait_for_enter(console, "\n[bold green]Generation Complete![/bold green] Press Enter to return...")

        elif choice == "convert":
            run_voice_conversion_flow()

        elif choice == "save_voice":
            run_save_voice_flow()

        elif choice == "settings":
            from core.settings_tui import breeze_tts_settings_tui
            breeze_tts_settings_tui()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_book_breeze(sys.argv[1])
    else:
        run_breeze_tui()
