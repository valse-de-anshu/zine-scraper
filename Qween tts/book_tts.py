import os
import sys
import time
import json
import uuid
import logging
import mimetypes
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
import subprocess

# ---------------------------------------------------------------------------
# Dev Logger — writes structured entries to zine tts/logs/<stem>_<ts>.log
# Call init_tts_logger(log_path) once at the start of each TTS run.
# ---------------------------------------------------------------------------
_tts_logger: logging.Logger = logging.getLogger("zine.tts")
_tts_logger.setLevel(logging.DEBUG)
_tts_logger.propagate = False  # Don't bleed into root logger

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
    # Plain text so tailing the log is easy
    _log_file_handler.setFormatter(logging.Formatter("%(message)s"))
    _tts_logger.addHandler(_log_file_handler)
    _log_event("SESSION_START", {"log_file": str(log_path), "pid": os.getpid()})


def _log_event(event: str, data: dict | None = None) -> None:
    """Append one timestamped JSON line to the dev log."""
    entry = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
    }
    if data:
        entry.update(data)
    _tts_logger.debug(json.dumps(entry, ensure_ascii=False, default=str))

# The base URL will be dynamically fetched from config when making requests

def get_wav_duration(wav_path: str) -> float:
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
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def check_comfy_online(comfy_url: str) -> bool:
    """Checks if the ComfyUI server is reachable on its /system_stats or /history endpoint."""
    try:
        req = urllib.request.Request(f"{comfy_url}/system_stats", headers={"User-Agent": "ZineTTS"})
        resp = urllib.request.urlopen(req, timeout=2.0)
        return resp.status == 200
    except Exception:
        return False

def queue_prompt(prompt: dict) -> dict | None:
    from core.settings_tui import config
    comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
    p = {"prompt": prompt}
    data = json.dumps(p).encode("utf-8")
    req = urllib.request.Request(
        f"{comfy_url}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    _log_event("COMFY_QUEUE", {"url": f"{comfy_url}/prompt", "workflow": prompt})
    try:
        response = urllib.request.urlopen(req)
        result = json.loads(response.read())
        _log_event("COMFY_QUEUE_OK", {"response": result})
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        _log_event("COMFY_QUEUE_HTTP_ERROR", {"status": e.code, "body": body})
        return None
    except Exception as e:
        _log_event("COMFY_QUEUE_ERROR", {"error": str(e)})
        return None


def check_history(prompt_id: str) -> dict:
    from core.settings_tui import config
    comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
    req = urllib.request.Request(f"{comfy_url}/history/{prompt_id}")
    try:
        response = urllib.request.urlopen(req)
        data = json.loads(response.read())
        if prompt_id in data:
            status = data[prompt_id].get("status", {})
            _log_event("COMFY_HISTORY", {"prompt_id": prompt_id, "status": status})
        return data
    except Exception as e:
        _log_event("COMFY_HISTORY_ERROR", {"prompt_id": prompt_id, "error": str(e)})
        return {}


def download_audio(filename: str, output_path: str, subfolder: str = "") -> bool:
    from core.settings_tui import config
    comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
    params = {"filename": filename, "type": "output"}
    if subfolder:
        params["subfolder"] = subfolder
    url = f"{comfy_url}/view?{urllib.parse.urlencode(params)}"
    _log_event("DOWNLOAD_START", {"url": url, "dest": output_path, "subfolder": subfolder})
    try:
        urllib.request.urlretrieve(url, output_path)
        size = os.path.getsize(output_path)
        _log_event("DOWNLOAD_OK", {"filename": filename, "bytes": size})
        return True
    except Exception as e:
        _log_event("DOWNLOAD_ERROR", {"filename": filename, "error": str(e)})
        return False

def _is_narratively_special(para: str) -> bool:
    """
    Semantic filter — returns True if a paragraph deserves isolated TTS rendering.
    
    The goal is NOT to detect visual formatting. The goal is to detect whether
    a paragraph's NARRATIVE ROLE benefits from standalone, dedicated narration.
    A listener-first heuristic: would this sound wrong or diluted if blended
    with the surrounding prose?
    """
    import re
    
    p = para.strip()
    if not p:
        return False

    # Reject pure metadata / decoration — these should be silently dropped
    # by the caller, not isolated. We flag False so they get skipped.
    # Examples: "[Words: 3220]", "──────────────────", "* * *"
    NOISE_PATTERN = re.compile(
        r'^(\[.*?\]'                   # [metadata: value]
        r'|\[?Words?:\s*\d+\]?'        # Words: 3220
        r'|[─═\-=_~*#]{3,}'           # ─────, ***, ---
        r')$',
        re.IGNORECASE
    )
    if NOISE_PATTERN.match(p):
        return False  # Pure noise — caller will discard

    lines = [l.strip() for l in p.splitlines() if l.strip()]
    num_lines = len(lines)

    # ── Rule 1: Chapter / Volume / Book / Part titles ──────────────────────
    # Even without a number — "Prologue: The Last Day" qualifies.
    TITLE_KW = re.compile(
        r'^(chapter|volume|book|part|episode|prologue|epilogue|interlude|arc'
        r'|side\s*story|extra|bonus|omake|afterword|foreword|introduction'
        r'|preface)\b',
        re.IGNORECASE
    )
    if num_lines == 1 and TITLE_KW.match(lines[0]):
        return True

    # ── Rule 2: Short standalone title-case or ALLCAPS line ───────────────
    # e.g. "THE IRON THRONE", "Guttermeat", "The Betrayal"
    if num_lines == 1 and len(p) <= 80:
        if p.istitle() or p.isupper():
            return True
        # Title-case with colon (subtitle pattern): "Chapter 1: Guttermeat"
        if re.match(r'^[A-Z][^.!?]{0,70}:[^.!?]{0,70}$', p):
            return True

    # ── Rule 3: System / Notification messages (light-novel trope) ─────────
    # e.g. "[Skill Obtained: Iron Body]", "[Quest Complete]"
    if re.match(r'^\[.{3,80}\]$', p):
        # Exclude pure word-count noise already caught above
        if not re.match(r'^\[Words?:\s*\d+\]$', p, re.IGNORECASE):
            return True

    # ── Rule 4: Pure quoted speech / letters / diary entries ──────────────
    # Short paragraph that is entirely in quotes.
    if num_lines <= 3 and len(p) <= 300:
        if (p.startswith('"') and p.endswith('"')) or \
           (p.startswith('\u2018') and p.endswith('\u2019')) or \
           (p.startswith('\u201c') and p.endswith('\u201d')):
            return True

    # ── Rule 5: Poems / Prophecies / Verses ───────────────────────────────
    # Multiple short lines (≤60 chars each), none ending in normal prose punctuation.
    if 2 <= num_lines <= 12 and all(len(l) <= 60 for l in lines):
        prose_endings = sum(1 for l in lines if re.search(r'[.?!]$', l))
        if prose_endings <= num_lines // 3:  # Mostly non-prose endings → verse
            return True

    # ── Rule 6: High-impact one-liner ─────────────────────────────────────
    # Single short sentence with strong emotional punctuation at end.
    if num_lines == 1 and len(p) <= 120:
        if p.endswith('!!!') or p.endswith('???') or p.endswith('!?') or \
           p.endswith('?!') or re.search(r'[!?]{2}', p):
            return True

    # ── Rule 7: Announcement / Warning / Notice labels ────────────────────
    ANNOUNCE_KW = re.compile(
        r'^(warning|notice|note|alert|caution|attention|announcement'
        r'|dear\s+\w+|to\s+whom\s+it\s+may|from\s+the\s+desk|memo)\b',
        re.IGNORECASE
    )
    if num_lines <= 2 and ANNOUNCE_KW.match(lines[0]):
        return True

    # ── Rule 8: Dreams / Visions / Italics-heavy passages ─────────────────
    # Lines mostly wrapped in asterisks (common markdown for italics)
    if num_lines <= 6:
        italic_lines = sum(1 for l in lines if l.startswith('*') and l.endswith('*'))
        if italic_lines >= max(1, num_lines - 1):
            return True

    return False


def _tag_chunk(text: str, kind: str = "prose") -> str:
    """
    Wraps a chunk of text with a Qwen-TTS-appropriate instruct preamble.
    
    Qwen TTS is context-driven — it reads the CONTENT and adapts its voice.
    The preamble here sets the REGISTER and DELIVERY MODE so the model knows
    BEFORE it starts reading whether this is a title, a dramatic one-liner,
    a soft verse, or plain flowing narration.
    
    These are NOT markup tags. They are natural-language instructions that
    Qwen's instruction-following core uses to shape prosody.
    """
    PREAMBLES = {
        "title":        "[Chapter title — speak with gravitas, a dramatic pause before and after] ",
        "announcement": "[Important announcement — authoritative, clear, slow delivery] ",
        "system":       "[System notification — robotic, flat, matter-of-fact tone] ",
        "quote":        "[Quoted letter or diary — intimate, personal, slightly hushed voice] ",
        "verse":        "[Poem or prophecy — rhythmic, deliberate, haunting cadence] ",
        "oneliner":     "[Intense emotional beat — raw, clipped, maximum weight] ",
        "dream":        "[Dream or vision — ethereal, distant, breathless whisper] ",
        "dialogue":     "[Narrator] ",
        "prose":        "[Narrator] ",
    }
    return PREAMBLES.get(kind, "[Narrator] ") + text


def split_text_into_chunks(text: str, max_length: int = 400) -> list:
    """
    Two-phase chunker:
    1. Split text into natural paragraphs (blank-line delimited).
    2. Classify each paragraph semantically:
       - NOISE    → discard silently (metadata, decorations)
       - SPECIAL  → isolated single chunk with specific kind
       - NORMAL   → packed into max_length chunks like before
    
    Returns a list of dicts: [{"text": str, "kind": str}]
    """
    import re

    NOISE_PATTERN = re.compile(
        r'^(\[.*?\]'
        r'|\[?Words?:\s*\d+\]?'
        r'|[─═\-=_~*#]{3,}'
        r')$',
        re.IGNORECASE
    )

    # Split into raw paragraphs by one or more blank lines
    paragraphs = re.split(r'\n{2,}', text.strip())

    chunks = []
    current_chunk = ""

    def flush_normal():
        nonlocal current_chunk
        if current_chunk.strip():
            chunks.append({"text": current_chunk.strip(), "kind": "prose"})
        current_chunk = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Phase 1: Discard pure noise (metadata, separators)
        if NOISE_PATTERN.match(para):
            continue

        # Phase 2: Semantic importance classification → assign semantic kind
        if _is_narratively_special(para):
            flush_normal()
            import re as _re
            # Strip decorative separator lines from inside the paragraph before classifying
            clean_para = "\n".join(
                l for l in para.splitlines()
                if not _re.match(r'^[─═\-=_~*#]{3,}$', l.strip())
            ).strip()
            lines = [l.strip() for l in clean_para.splitlines() if l.strip()]
            num_lines = len(lines)
            TITLE_KW = _re.compile(
                r'^(chapter|volume|book|part|episode|prologue|epilogue|interlude|arc'
                r'|side\s*story|extra|bonus|omake|afterword|foreword|introduction|preface)\b',
                _re.IGNORECASE
            )
            ANNOUNCE_KW = _re.compile(
                r'^(warning|notice|note|alert|caution|attention|announcement|dear\s+\w+)\b',
                _re.IGNORECASE
            )
            # Determine the specific kind for Qwen instruct mapping
            if num_lines == 1 and TITLE_KW.match(lines[0]):
                kind = "title"
            elif num_lines == 1 and (lines[0].istitle() or lines[0].isupper()) and len(clean_para) <= 80:
                kind = "title"
            elif _re.match(r'^\[.{3,80}\]$', clean_para) and not _re.match(r'^\[Words?:\s*\d+\]$', clean_para, _re.IGNORECASE):
                kind = "system"
            elif num_lines <= 3 and len(clean_para) <= 300 and clean_para[0] in ('"', '\u201c', '\u2018'):
                kind = "quote"
            elif 2 <= num_lines <= 12 and all(len(l) <= 60 for l in lines):
                kind = "verse"
            elif num_lines == 1 and len(clean_para) <= 120 and _re.search(r'[!?]{2}', clean_para):
                kind = "oneliner"
            elif ANNOUNCE_KW.match(lines[0]):
                kind = "announcement"
            elif num_lines <= 6 and sum(1 for l in lines if l.startswith('*') and l.endswith('*')) >= max(1, num_lines - 1):
                kind = "dream"
            else:
                kind = "prose"
            chunks.append({"text": clean_para, "kind": kind})
            continue

        # Phase 3: Normal prose packing — split by sentences, pack by length
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
# Audio upload helper (Voice Cloning mode)
# ---------------------------------------------------------------------------

def upload_audio_to_comfy(audio_path: str) -> str:
    """
    Uploads a local WAV/MP3/FLAC/etc. reference audio file into ComfyUI's
    input/ folder via the /upload/image endpoint (ComfyUI reuses that endpoint
    for audio too). Returns the filename that ComfyUI assigned inside input/.
    Falls back to the bare filename on any error so callers can still attempt.
    """
    from core.settings_tui import config
    comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
    filename = os.path.basename(audio_path)
    _log_event("UPLOAD_REF_AUDIO_START", {"local_path": audio_path, "filename": filename})

    # Detect actual MIME type from file extension so ComfyUI parses it correctly
    mime_type, _ = mimetypes.guess_type(audio_path)
    if not mime_type or not mime_type.startswith("audio"):
        mime_type = "audio/wav"  # safe fallback

    try:
        with open(audio_path, "rb") as f:
            file_data = f.read()

        boundary = "----ZineTTSBoundary7MA4YWxkTrZ"
        CRLF = b"\r\n"
        body = (
            f"--{boundary}".encode() + CRLF
            + f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode() + CRLF
            + f"Content-Type: {mime_type}".encode() + CRLF
            + CRLF
            + file_data + CRLF
            + f"--{boundary}--".encode() + CRLF
        )

        req = urllib.request.Request(
            f"{comfy_url}/upload/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        resp = urllib.request.urlopen(req, timeout=15.0)
        res_json = json.loads(resp.read())
        uploaded_name = res_json.get("name", filename)
        _log_event("UPLOAD_REF_AUDIO_OK", {"uploaded_name": uploaded_name, "mime": mime_type, "response": res_json})
        return uploaded_name

    except Exception as e:
        _log_event("UPLOAD_REF_AUDIO_ERROR", {"error": str(e), "fallback": filename})
        return filename


# ---------------------------------------------------------------------------
# Core TTS generation dispatcher
# ---------------------------------------------------------------------------

# Kind → instruct suffix that rides alongside the user's base instruct prompt
_KIND_INSTRUCT_SUFFIX: dict[str, str] = {
    "title":        "Speak as a majestic chapter title with an authoritative tone, deliberate pace, and dramatic pause.",
    "announcement": "Speak as an authoritative announcement, clear, measured, and solemn.",
    "system":       "Speak as a robotic, flat, emotionless RPG system notification.",
    "quote":        "Speak in an intimate, personal, slightly hushed narrative voice as if reading a letter.",
    "verse":        "Speak with a rhythmic, haunting, deliberate poetic cadence.",
    "oneliner":     "Speak with intense emotional weight, drama, and raw emphasis.",
    "dream":        "Speak in a breathless, ethereal, whispered dreamlike voice.",
    "prose":        "",
}


def _resolve_instruct_text(config: dict, kind: str) -> str:
    """
    Reads the user's voice instruct setting (may be a .txt file path or raw
    string), then appends a kind-based tone modifier.
    """
    default = (
        "Dynamic and expressive narrator. Seamlessly switch between professional "
        "normal narration, deep emotional acting, and sultry/horny character voices "
        "based on the text. Emphasize feelings and intonations naturally."
    )
    raw = config.get("tts_voice_instruct", default) or default

    # If the user pointed at a .txt file, read it
    if raw and os.path.isfile(raw) and raw.lower().endswith(".txt"):
        try:
            with open(raw, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception as e:
            _log_event("INSTRUCT_FILE_READ_ERROR", {"path": raw, "error": str(e)})

    suffix = _KIND_INSTRUCT_SUFFIX.get(kind, "")
    return f"{raw.strip()} {suffix}".strip() if suffix else raw.strip()


def _resolve_ref_text(config: dict) -> str:
    """
    For Voice Cloning: returns the exact transcription of what was spoken
    in the reference audio clip. Cleaned of newlines, tabs, and outer quotes.
    """
    raw = config.get("tts_clone_ref_transcript", "") or ""
    if raw and os.path.isfile(raw) and raw.lower().endswith(".txt"):
        try:
            with open(raw, "r", encoding="utf-8") as f:
                raw = f.read().strip()
        except Exception as e:
            _log_event("REF_TEXT_FILE_READ_ERROR", {"path": raw, "error": str(e)})
    cleaned = raw.strip(' "\'\n\r')
    cleaned = ' '.join(cleaned.split())
    return cleaned


def _add_tail_padding(text: str) -> str:
    """Appends subtle ellipsis '...' to prevent neural vocoder tail truncation without synthesizing exclamation noise."""
    if not text:
        return text
    if text.endswith("...") or text.endswith("…"):
        return text
    return text + "..." if text[-1] in ".!?" else text + "..."


def generate_tts_for_chunk(chunk_input, progress_callback=None) -> str | None:
    """
    Dispatches one text chunk to ComfyUI-Qwen-TTS and returns the server-side
    filename of the generated WAV, or None on failure.

    Per-mode minimal workflows (only the params each node actually needs):
      Voice Design  → FB_Qwen3TTSVoiceDesign: text + instruct + sampling
      Voice Cloning → LoadAudio → FB_Qwen3TTSVoiceClone: target_text + ref_audio + ref_text + sampling
      Custom Voice  → FB_Qwen3TTSCustomVoice: text + speaker + optional instruct + sampling
    """
    # --- Unpack chunk -------------------------------------------------------
    if isinstance(chunk_input, dict):
        raw_text = chunk_input.get("text", "").strip()
        kind     = chunk_input.get("kind", "prose")
    else:
        raw_text = str(chunk_input).strip()
        kind     = "prose"

    if not raw_text:
        _log_event("CHUNK_SKIP_EMPTY", {})
        return None

    spoken_text = raw_text

    # --- Load config --------------------------------------------------------
    from core.settings_tui import config
    from core.paths import sanitize_user_path

    tts_mode    = config.get("tts_mode", "Custom Voice")
    model       = config.get("tts_model_choice", "1.7B")
    precision   = config.get("tts_precision", "bf16")
    temperature = float(config.get("tts_temperature", 1.0))
    top_p       = float(config.get("tts_top_p", 0.8))
    top_k       = int(config.get("tts_top_k", 20))
    rep_pen     = float(config.get("tts_repetition_penalty", 1.05))
    max_tokens  = int(config.get("tts_max_new_tokens", 2048))
    seed        = int(config.get("tts_seed", 0))

    # Shared sampling block passed straight to ComfyUI nodes
    sampling = {
        "model_choice":             model,
        "device":                   "auto",
        "precision":                precision,
        "language":                 "Auto",
        "seed":                     seed,
        "max_new_tokens":           max_tokens,
        "top_p":                    top_p,
        "top_k":                    top_k,
        "temperature":              temperature,
        "repetition_penalty":       rep_pen,
        "attention":                "sdpa",
        "unload_model_after_generate": False,
    }

    _log_event("CHUNK_START", {
        "mode": tts_mode,
        "kind": kind,
        "raw_text_preview": raw_text[:120],
        "spoken_text_preview": spoken_text[:120],
        "sampling": sampling,
    })

    # --- Build mode-specific workflow ---------------------------------------

    if "Voice Cloning" in tts_mode:
        # ── Voice Cloning ─────────────────────────────────────────────────
        # Required: ref_audio (AUDIO dict from LoadAudio), target_text
        # Optional: ref_text (transcription of reference audio — NOT a style prompt)
        ref_audio_raw = config.get("tts_clone_ref_audio", "") or ""
        ref_audio_path = sanitize_user_path(ref_audio_raw) if ref_audio_raw else ""

        if not (ref_audio_path and os.path.exists(ref_audio_path)
                and ref_audio_path.lower().endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"))):
            _log_event("VOICE_CLONE_FALLBACK", {
                "reason": "ref_audio invalid or missing",
                "path": ref_audio_path,
            })
            # Hard-fail — voice cloning without a reference makes no sense
            return None

        uploaded_name = upload_audio_to_comfy(ref_audio_path)
        ref_text = _resolve_ref_text(config)  # transcription of ref audio
        use_xvec = config.get("tts_x_vector_only", True)
        if not ref_text:
            use_xvec = True

        _log_event("VOICE_CLONE_PARAMS", {
            "ref_audio_local": ref_audio_path,
            "uploaded_name": uploaded_name,
            "ref_text_preview": ref_text[:120],
            "x_vector_only": use_xvec,
        })

        # Node graph:
        #   1: LoadAudio (loads ref audio into ComfyUI AUDIO dict)
        #   2: FB_Qwen3TTSVoiceClone (ref_audio=AUDIO from node 1)
        #   3: SaveAudio
        workflow = {
            "1": {
                "class_type": "LoadAudio",
                "inputs": {"audio": uploaded_name},
            },
            "2": {
                "class_type": "FB_Qwen3TTSVoiceClone",
                "inputs": {
                    "target_text": spoken_text,
                    "ref_audio":   ["1", 0],    # wire to LoadAudio output
                    "ref_text":    ref_text,     # transcription (NOT style prompt)
                    "x_vector_only": use_xvec,
                    **sampling,
                },
            },
            "3": {
                "class_type": "SaveAudio",
                "inputs": {
                    "filename_prefix": "zine_clone",
                    "audio": ["2", 0],
                },
            },
        }

    elif "Voice Design" in tts_mode:
        # ── Voice Design ──────────────────────────────────────────────────
        # Required: text, instruct (style description that defines the voice)
        # The instruct IS the voice — make it rich and detailed.
        instruct = _resolve_instruct_text(config, kind)

        if not instruct:
            _log_event("VOICE_DESIGN_MISSING_INSTRUCT", {})
            return None  # VoiceDesign raises RuntimeError if instruct is empty

        _log_event("VOICE_DESIGN_PARAMS", {"instruct_preview": instruct[:200]})

        workflow = {
            "1": {
                "class_type": "FB_Qwen3TTSVoiceDesign",
                "inputs": {
                    "text":     spoken_text,
                    "instruct": instruct,
                    **sampling,
                },
            },
            "2": {
                "class_type": "SaveAudio",
                "inputs": {
                    "filename_prefix": "zine_design",
                    "audio": ["1", 0],
                },
            },
        }

    else:
        # ── Custom Voice (default / fallback) ─────────────────────────────
        # Required: text, speaker
        # Optional: instruct (style modifier — can be empty)
        speaker  = config.get("tts_custom_speaker", "Ryan") or "Ryan"
        instruct = _resolve_instruct_text(config, kind)   # empty = node default behaviour

        _log_event("CUSTOM_VOICE_PARAMS", {"speaker": speaker, "instruct_preview": instruct[:120]})

        workflow = {
            "1": {
                "class_type": "FB_Qwen3TTSCustomVoice",
                "inputs": {
                    "text":     spoken_text,
                    "speaker":  speaker,
                    "instruct": instruct,   # empty string = node treats it as None
                    **sampling,
                },
            },
            "2": {
                "class_type": "SaveAudio",
                "inputs": {
                    "filename_prefix": "zine_custom",
                    "audio": ["1", 0],
                },
            },
        }

    # --- Queue and poll -----------------------------------------------------
    res = queue_prompt(workflow)
    if not res or "prompt_id" not in res:
        _log_event("CHUNK_QUEUE_FAILED", {"mode": tts_mode})
        return None

    prompt_id = res["prompt_id"]
    _log_event("CHUNK_QUEUED", {"prompt_id": prompt_id})

    # Poll /history until done or error, triggering progress_callback on each tick
    poll_count = 0
    while True:
        if progress_callback:
            try:
                progress_callback()
            except Exception:
                pass
        history = check_history(prompt_id)
        if prompt_id in history:
            prompt_data = history[prompt_id]
            status      = prompt_data.get("status", {})
            status_str  = status.get("status_str", "")

            if status_str == "error":
                messages = status.get("messages", [])
                _log_event("CHUNK_COMFY_ERROR", {
                    "prompt_id": prompt_id,
                    "status": status,
                    "messages": messages,
                })
                return None, None

            outputs = prompt_data.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "audio" in node_output:
                    audios = node_output["audio"]
                    if audios:
                        audio_entry = audios[0]
                        fname     = audio_entry.get("filename", "")
                        subfolder = audio_entry.get("subfolder", "")
                        _log_event("CHUNK_DONE", {
                            "prompt_id": prompt_id,
                            "output_filename": fname,
                            "subfolder": subfolder,
                            "polls": poll_count,
                        })
                        return fname, subfolder
            # outputs not yet populated — keep polling
        poll_count += 1
        time.sleep(0.1)

    return None, None  # unreachable but satisfies type checkers

def process_book_live(txt_path_str: str):
    from rich.console import Console
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.align import Align
    from rich.text import Text
    from rich.live import Live
    from rich.table import Table
    from core.ui import custom_theme, set_active_live
    from core.paths import sanitize_user_path
    
    console = Console(theme=custom_theme)
    clean_path_str = sanitize_user_path(txt_path_str)
        
    txt_path = Path(clean_path_str).expanduser().resolve()
    
    if not txt_path.exists():
        console.print(f"[bold red]Error: Text file not found at {txt_path}[/bold red]")
        time.sleep(2)
        return
        
    # Master unified folder for all TTS audio & subtitles: "zine tts" in the text file's parent directory
    out_dir = txt_path.parent / "zine tts"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Dev log ─────────────────────────────────────────────────────────────
    from core.settings_tui import config as _cfg
    ts_str   = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / "logs" / f"{txt_path.stem}_{ts_str}.log"
    init_tts_logger(log_path)
    # Log the full settings snapshot so devs can see what was active this run
    _log_event("CONFIG_SNAPSHOT", {
        "tts_mode":               _cfg.get("tts_mode"),
        "tts_model_choice":       _cfg.get("tts_model_choice"),
        "tts_precision":          _cfg.get("tts_precision"),
        "tts_temperature":        _cfg.get("tts_temperature"),
        "tts_top_p":              _cfg.get("tts_top_p"),
        "tts_top_k":              _cfg.get("tts_top_k"),
        "tts_repetition_penalty": _cfg.get("tts_repetition_penalty"),
        "tts_max_new_tokens":     _cfg.get("tts_max_new_tokens"),
        "tts_custom_speaker":     _cfg.get("tts_custom_speaker"),
        "tts_voice_instruct":     _cfg.get("tts_voice_instruct"),
        "tts_clone_ref_audio":    _cfg.get("tts_clone_ref_audio"),
        "tts_comfyui_url":        _cfg.get("tts_comfyui_url"),
        "input_file":             str(txt_path),
    })
    comfy_url = _cfg.get("tts_comfyui_url", "http://127.0.0.1:8188")
    if not check_comfy_online(comfy_url):
        panel_content = Text()
        panel_content.append(f"\n⚠️  ComfyUI / Gradio Server is Offline!\n\n", style="bold warning")
        panel_content.append(f"Could not connect to TTS server at: {comfy_url}\n\n", style="white")
        panel_content.append(f"Please ensure your ComfyUI or Gradio server is turned ON\nand running before starting TTS generation.\n", style="unselected")
        console.print()
        console.print(Panel(Align.center(panel_content), title="[bold error]◆ SERVER CONNECTION ERROR ◆[/bold error]", border_style="error", padding=(1, 2), width=75))
        return
        
    console.print(f"[info]📂 Output Dir:[/info] [bold white]{out_dir}[/bold white]")
    console.print(f"[info]📋 Dev log:   [/info] [bold white]{log_path}[/bold white]")
    # ─────────────────────────────────────────────────────────────────────────
    
    # Temporary directory for intermediate chunk .wav files during processing
    temp_dir = out_dir / "_temp_" / txt_path.stem
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Early-exit guard: if final merged audiobook already exists and ALL chunks
    # are already cached on disk, just tell the user and return cleanly.
    final_audio_check = out_dir / f"{txt_path.stem}.wav"
    if final_audio_check.exists() and final_audio_check.stat().st_size > 10000:
        existing_chunks = list(temp_dir.glob("*.wav"))
        with open(txt_path, 'r', encoding='utf-8') as _f:
            _preview_chunks = split_text_into_chunks(_f.read())
        if len(existing_chunks) >= len(_preview_chunks):
            console.print(f"\n[success]●[/success] [bold green]Audiobook already complete![/bold green]")
            console.print(f"[bold white]Audio:[/bold white] {final_audio_check}")
            console.print(f"[unselected]All {len(existing_chunks)} chunks cached. Delete the _temp_ folder to re-generate.[/unselected]")
            return
    
    with open(txt_path, 'r', encoding='utf-8') as f:
        text = f.read()
        
    chunks = split_text_into_chunks(text)
    total_chunks = len(chunks)
    
    chunk_files = []
    srt_lines = []
    current_time = 0.0
    status_log = []
    
    history_file = out_dir / "tts_history.json"
    tts_history = {}
    if history_file.exists():
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                tts_history = json.load(f)
        except Exception:
            tts_history = {}

    _last_chunk_text = ""
    _last_progress_str = ""
    _spinner_idx = 0
    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _SPINNER_COLORS = ["#bb9af7", "#7dcfff", "#7aa2f7", "#b4f9f8", "#f7768e", "#e0af68"]
    _active_chunk_num = None

    def update_tui(current_chunk_text=None, progress_str=None):
        nonlocal _last_chunk_text, _last_progress_str, _spinner_idx, _active_chunk_num
        if current_chunk_text is not None:
            if isinstance(current_chunk_text, dict):
                _last_chunk_text = current_chunk_text.get("text", "")
            else:
                _last_chunk_text = str(current_chunk_text)
        if progress_str is not None:
            _last_progress_str = str(progress_str)
        
        # Left Panel (Text generation)
        left_content = Text(_last_chunk_text, style="white", justify="left")
        left_panel = Panel(left_content, title="[bold sexy_pink]📖 GENERATING TEXT[/bold sexy_pink]", border_style="sexy_pink", padding=(1, 2), width=75, height=15)
        
        # Right Panel (Status log with cycling color spinner for active chunk)
        display_lines = list(status_log)
        if _active_chunk_num is not None:
            frame = _SPINNER_FRAMES[_spinner_idx % len(_SPINNER_FRAMES)]
            color = _SPINNER_COLORS[_spinner_idx % len(_SPINNER_COLORS)]
            _spinner_idx += 1
            display_lines.append(f"[{color}]{frame}[/{color}] [bold #7dcfff]Creating audio for Chunk {_active_chunk_num}...[/bold #7dcfff]")

        log_text = "\n".join(display_lines[-9:]) # Keep last 9 entries to fit usable height (11 lines max) without cropping bottom spinner
        right_panel = Panel(log_text, title=f"[bold sexy_pink]🎧 PROGRESS {_last_progress_str}[/bold sexy_pink]", subtitle="[bold white]Press Ctrl+R to Abort & Merge[/bold white]", subtitle_align="center", border_style="sexy_pink", padding=(1, 2), width=75, height=15)
        
        grid = Table.grid(padding=1)
        grid.add_column()
        grid.add_column()
        grid.add_row(left_panel, right_panel)
        return grid

    from core.ui import read_tty_key
    import threading
    
    abort_requested = False
    stop_thread = False
    
    _active_live = None
    
    def tick_tui():
        if _active_live:
            _active_live.update(update_tui())
            _active_live.refresh()

    def monitor_keyboard():
        nonlocal abort_requested, stop_thread
        import tty, termios, select, os
        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            while not stop_thread:
                ready, _, _ = select.select([fd], [], [], 0.2)
                if ready:
                    raw = os.read(fd, 1)
                    if raw == b'\x03': # Ctrl+C
                        import signal
                        os.kill(os.getpid(), signal.SIGINT)
                        break
                    elif raw == b'\x12': # Ctrl+R
                        abort_requested = True
                        stop_thread = True
                        status_log.append("[bold yellow]Ctrl+R Pressed! Will merge and exit after this chunk...[/bold yellow]")
                        if _active_live:
                            _active_live.update(update_tui())
                            _active_live.refresh()
                        break
        except Exception:
            pass
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except:
                pass
                
    kbd_thread = threading.Thread(target=monitor_keyboard, daemon=True)
    kbd_thread.start()

    srt_file = out_dir / f"{txt_path.stem}.srt"
    
    def save_srt_live():
        try:
            with open(srt_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(srt_lines))
        except:
            pass

    with Live(update_tui("Initializing...", f"0/{total_chunks}"), console=console, refresh_per_second=10) as live:
        set_active_live(live)
        _active_live = live
        
        for i, chunk in enumerate(chunks, 1):
            if abort_requested:
                break
                
            chunk_text = chunk["text"] if isinstance(chunk, dict) else str(chunk)
            filename = f"{i:011d}.wav"
            local_path = temp_dir / filename
            
            # Check if chunk is already generated and cached on disk
            is_cached = local_path.exists() and local_path.stat().st_size > 1000
            if is_cached:
                status_log.append(f"[success]●[/success] [bold green]Chunk {i} cached[/bold green]")
                chunk_files.append(local_path)
                
                duration = get_wav_duration(str(local_path))
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
            
            # Mark chunk i as active -> update_tui renders spinning Braille line automatically
            _active_chunk_num = i
            live.update(update_tui(chunk_text, f"{i}/{total_chunks}"))
            live.refresh()
            
            server_filename, server_subfolder = generate_tts_for_chunk(chunk, progress_callback=tick_tui)
            _active_chunk_num = None  # Clear active spinner line
            
            if not server_filename:
                status_log.append(f"[error]●[/error] [bold red]Chunk {i} failed[/bold red]")
                live.update(update_tui(chunk_text, f"{i}/{total_chunks}"))
                continue
                
            success = download_audio(server_filename, str(local_path), subfolder=server_subfolder or "")
            if success:
                status_log.append(f"[success]●[/success] [bold green]Chunk {i} generated[/bold green]")
                chunk_files.append(local_path)
                
                tts_history[str(i)] = {
                    "filename": filename,
                    "server_filename": server_filename,
                    "server_subfolder": server_subfolder or "",
                    "timestamp": time.time(),
                }
                try:
                    with open(history_file, 'w', encoding='utf-8') as f:
                        json.dump(tts_history, f, indent=4)
                except Exception:
                    pass
                
                duration = get_wav_duration(str(local_path))
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

        status_log.append("[bold yellow]● Merging audio chunks...[/bold yellow]")
        live.update(update_tui("Merging...", f"{total_chunks}/{total_chunks}"))
        set_active_live(None)

    # Write concat list with ABSOLUTE paths so ffmpeg can find files
    # regardless of cwd
    concat_file = temp_dir / "concat.txt"
    with open(concat_file, 'w', encoding='utf-8') as f:
        for cf in chunk_files:
            # Use absolute path; escape single quotes in path
            safe_path = str(cf.resolve()).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")
            
    final_audio = out_dir / f"{txt_path.stem}.wav"
    # ComfyUI's SaveAudio node saves FLAC streams inside .wav wrappers.
    # We MUST re-encode to proper PCM s16le to get a clean, universally
    # playable WAV file. Using -c copy here produces a broken/looping file.
    ffmpeg_result = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-ar", "24000",   # Qwen3-TTS native sample rate
        "-ac", "1",       # mono
        "-c:a", "pcm_s16le",  # standard 16-bit PCM WAV — universally playable
        str(final_audio)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    
    if ffmpeg_result.returncode != 0:
        err = ffmpeg_result.stderr.decode("utf-8", errors="replace")
        _log_event("FFMPEG_MERGE_ERROR", {"returncode": ffmpeg_result.returncode, "stderr": err})
        console.print(f"[bold red]\n⚠️  ffmpeg merge failed! Check dev log for details.[/bold red]")
        console.print(f"[unselected]{err[-500:]}[/unselected]")
        return
    
    _log_event("FFMPEG_MERGE_OK", {"output": str(final_audio), "size_bytes": final_audio.stat().st_size})
    
    # Write SRT final copy
    srt_file = out_dir / f"{txt_path.stem}.srt"
    with open(srt_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(srt_lines))
    
    # Clean up _temp_ folder now that we have a confirmed merged audiobook
    import shutil
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        parent_temp = temp_dir.parent  # the _temp_/ parent
        if parent_temp.exists() and not any(parent_temp.iterdir()):
            parent_temp.rmdir()
    except Exception as e:
        _log_event("TEMP_CLEANUP_ERROR", {"error": str(e)})

    console.print(f"\n[success]●[/success] [bold green]Audiobook generation fully complete![/bold green]")
    console.print(f"[bold white]Saved Audio to:[/bold white] {final_audio}")
    console.print(f"[bold white]Saved Subtitles to:[/bold white] {srt_file}")
    
    # Free VRAM model memory
    try:
        from core.settings_tui import config
        comfy_url = config.get("tts_comfyui_url", "http://127.0.0.1:8188")
        req = urllib.request.Request(f"{comfy_url}/free", data=json.dumps({"unload_models":True,"free_memory":True}).encode(), method='POST')
        urllib.request.urlopen(req, timeout=1.0)
    except:
        pass
    
def run_tts_tui():
    from rich.console import Console
    from rich.panel import Panel
    from rich.align import Align
    from rich.text import Text
    from core.settings_tui import prompt_field_value
    from core.ui import custom_theme
    
    console = Console(theme=custom_theme)
    console.clear()
    
    warning_panel = Panel(
        Align.center(Text("⚠️  IMPORTANT: Please ensure your ComfyUI / Gradio server (Port 8188) is turned ON before proceeding!\nThis scraper sends backend signals to generate the TTS.", justify="center", style="bold #e0af68")),
        border_style="#e0af68",
        padding=(1, 2)
    )
    console.print(warning_panel)
    console.print()
    
    txt_path = prompt_field_value("Input Text File Path", "", "(Drag and drop file here)")
    if not txt_path:
        return
        
    process_book_live(txt_path)
    console.print("\n[bold green]Generation Complete![/bold green] Press Enter to return to main menu...")
    input()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python book_tts.py <input_text_file>")
        sys.exit(1)
        
    process_book_live(sys.argv[1])
