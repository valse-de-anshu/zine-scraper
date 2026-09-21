import os
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.text import Text
from rich.console import Group

from core.ui import console, Selector, clean_exit, startup_clear, print_banner
from core.paths import PathAuthority
from core.config import ConfigLayer
from core.storage import StorageLayer

# --- Auto-inject Pip-installed NVIDIA CUDA/cuDNN Libraries & User Site-Packages ---
try:
    import site
    import ctypes
    user_site = site.getusersitepackages()
    if user_site and os.path.exists(user_site) and user_site not in sys.path:
        sys.path.append(user_site)
    for p in site.getsitepackages() + ([user_site] if user_site else []):
        if not p or not os.path.exists(p):
            continue
        cublas_path = os.path.join(p, "nvidia/cublas/lib", "libcublas.so.12")
        cudnn_path = os.path.join(p, "nvidia/cudnn/lib", "libcudnn.so.9") # cuDNN 9
        if os.path.exists(cublas_path):
            ctypes.CDLL(cublas_path, mode=ctypes.RTLD_GLOBAL)
        if os.path.exists(cudnn_path):
            ctypes.CDLL(cudnn_path, mode=ctypes.RTLD_GLOBAL)
except Exception:
    pass
# -------------------------------------------------------------

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def extract_audio(media_path: str) -> str:
    import uuid
    paths = PathAuthority()
    temp_dir = paths.get_app_root() / "💩"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_wav = str(temp_dir / f"temp_{uuid.uuid4().hex[:8]}.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", media_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        temp_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return temp_wav

def isolate_vocals_demucs(media_path: str, live=None, get_renderable=None, status_target=None) -> str:
    """
    Extracts dialogue vocals and strips background music/sound effects using Demucs v4 (htdemucs).
    Engineered for 6GB VRAM GPUs (NVIDIA RTX 3050):
    - Runs in segmented streaming mode (segment=7.0s) to keep peak VRAM under 600MB (~9.5% of 6GB)
    - Downmixes and converts the vocal stem directly to 16kHz mono PCM WAV for Faster-Whisper
    - Purges Demucs model weights and CUDA cache from GPU immediately after completion
    - Smoothly falls back to standard audio extraction if Demucs fails or runs out of memory.
    """
    import uuid
    import numpy as np
    paths = PathAuthority()
    temp_dir = paths.get_app_root() / "💩"
    temp_dir.mkdir(parents=True, exist_ok=True)

    temp_stereo = str(temp_dir / f"temp_stereo_{uuid.uuid4().hex[:8]}.wav")
    temp_mono_44k = str(temp_dir / f"temp_mono_{uuid.uuid4().hex[:8]}.wav")
    temp_vocals_16k = str(temp_dir / f"temp_vocals_{uuid.uuid4().hex[:8]}.wav")

    try:
        if live and get_renderable:
            st = Panel(Text("Extracting audio stream for Demucs...", style="warning"), title="[warning]Phase 0: Vocal Isolation[/]", border_style="menu")
            live.update(get_renderable(st, status_target))

        # Extract 44.1kHz stereo WAV for Demucs
        res = subprocess.run([
            "ffmpeg", "-y", "-i", media_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            temp_stereo
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode != 0 or not os.path.exists(temp_stereo):
            return extract_audio(media_path)

        import torch
        import soundfile as sf
        from demucs.pretrained import get_model
        from demucs.apply import apply_model

        device = "cuda" if torch.cuda.is_available() else "cpu"

        if live and get_renderable:
            st = Panel(Text(f"Loading Demucs v4 (htdemucs) into {device.upper()} (Peak VRAM: ~590MB)...", style="info"), title="[info]Phase 0: Vocal Isolation[/]", border_style="menu")
            live.update(get_renderable(st, status_target))

        model = get_model("htdemucs")
        model.to(device)

        data, sr = sf.read(temp_stereo, dtype="float32")
        wav = torch.from_numpy(data).t()
        if wav.dim() == 1:
            wav = wav.repeat(2, 1)
        wav = wav.to(device)

        total_samples = wav.shape[-1]
        last_update = [time.time()]

        def progress_cb(info):
            now = time.time()
            if (now - last_update[0] >= 0.4) and live and get_renderable:
                last_update[0] = now
                offset = info.get("segment_offset", 0)
                pct = min(100.0, (offset / total_samples) * 100)
                st = Panel(
                    f"Isolating Dialogue Vocals (Demucs v4): [bold cyan]{pct:.1f}%[/]...\n"
                    f"[dim]Removing background music, OST, and sound effects for crystal-clear STT[/dim]",
                    title="[bold #bb9af7]Phase 0: Demucs Vocal Separation[/]",
                    border_style="menu"
                )
                live.update(get_renderable(st, status_target))

        with torch.no_grad():
            sources = apply_model(model, wav.unsqueeze(0), split=True, segment=7.0, callback=progress_cb)[0]

        # In htdemucs: sources = ['drums', 'bass', 'other', 'vocals'] -> index 3 is vocals
        vocals = sources[3].cpu().numpy()
        mono_vocals = np.mean(vocals, axis=0)

        sf.write(temp_mono_44k, mono_vocals, 44100)

        # Convert to 16kHz mono PCM for Whisper
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_mono_44k,
            "-ar", "16000", "-ac", "1", temp_vocals_16k
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Clean up Demucs memory immediately before Whisper loads
        del model, wav, sources
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        import gc
        gc.collect()

        if live and get_renderable:
            st = Panel(Text("Vocal isolation complete! Clean voice stem isolated.", style="bold green"), title="[bold green]Phase 0 Done[/]", border_style="success")
            live.update(get_renderable(st, status_target))

        return temp_vocals_16k

    except Exception:
        # If any failure occurs, gracefully fallback to raw audio extraction
        return extract_audio(media_path)
    finally:
        for p in [temp_stereo, temp_mono_44k]:
            if os.path.exists(p):
                try: os.remove(p)
                except Exception: pass


def detect_source_language(text: str, hint: str = None) -> str:
    # 1. First inspect actual script characters (ground truth)
    for ch in text:
        code = ord(ch)
        if 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
            return "ja-JP"
        if 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            return "ko-KR"
        if 0x0400 <= code <= 0x04FF:
            return "ru-RU"

    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            return "zh-CN"

    # 2. Fall back to hint if text is Latin / ASCII
    if hint and hint.lower() not in ["none", "unknown", "auto"]:
        h = hint.lower().strip()
        if any(x in h for x in ["jap", "ja"]): return "ja-JP"
        if any(x in h for x in ["chi", "zh"]): return "zh-CN"
        if any(x in h for x in ["kor", "ko"]): return "ko-KR"
        if any(x in h for x in ["eng", "en"]): return "en-US"
        if any(x in h for x in ["fre", "fr"]): return "fr-FR"
        if any(x in h for x in ["ger", "de"]): return "de-DE"
        if any(x in h for x in ["spa", "es"]): return "es-ES"
        if any(x in h for x in ["rus", "ru"]): return "ru-RU"

    return "en-US"

_ollama_model_cached = None
_ollama_checked = False

def get_all_ollama_models() -> List[str]:
    """Returns a list of all installed Ollama model tags."""
    try:
        import urllib.request, json
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []

def get_ollama_model(force_refresh: bool = False) -> Optional[str]:
    global _ollama_model_cached, _ollama_checked
    if _ollama_checked and not force_refresh:
        return _ollama_model_cached
    _ollama_checked = True
    models = get_all_ollama_models()
    if not models:
        _ollama_model_cached = None
        return None

    # Priority 1: emma (flagship uncensored 7.5B model for SFW & NSFW media)
    # Priority 2: luna, qwen, mistral, llama
    for cand in ["emma", "luna", "qwen", "mistral", "llama"]:
        for m in models:
            if cand in m.lower():
                _ollama_model_cached = m
                return _ollama_model_cached

    _ollama_model_cached = models[0]
    return _ollama_model_cached

def unload_ollama_model():
    m = get_ollama_model()
    if m:
        try:
            import urllib.request, json
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=json.dumps({"model": m, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass

def prewarm_ollama(model_name: str) -> Optional[str]:
    """Preload the Ollama model into GPU/memory so generation calls don't timeout on cold start."""
    try:
        import urllib.request, json
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": model_name}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return None
    except Exception as e:
        return str(e)

def translate_segment_ollama(text: str, target_lang: str = "English", model_name: str = "emma:latest") -> Tuple[str, Optional[str]]:
    """
    Translates a line of spoken dialogue using local Ollama LLM.
    Strictly handles both everyday SFW dialogue and explicit NSFW (adult/hentai) dialogue
    without censorship, moralizing, or refusal.
    Returns: (translated_text, error_message_or_None)
    """
    if not text or not text.strip():
        return ("", None)
    
    try:
        import urllib.request, json, re
        system_prompt = (
            f"You are a professional subtitle translator for media, anime, movies, and video games.\n"
            f"You MUST faithfully, accurately, and fluently translate ALL dialogue lines into natural conversational {target_lang}.\n"
            f"Both everyday SFW dialogue and explicit NSFW (adult / hentai / sexual) dialogue must be translated directly without censorship, moralizing, lecturing, or refusal.\n"
            f"Never act as an assistant or chatbot. Never introduce yourself, never apologize, never explain grammar or single words, and never offer assistance.\n"
            f"Output ONLY the direct {target_lang} subtitle translation on a single line without explanations, bullet points, numbered options, or quotation marks."
        )
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": text
                }
            ],
            "think": False,
            "stream": False
        }
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ans = data.get("message", {}).get("content", "").strip()
            if not ans:
                return ("", "Empty response from Ollama")

            # 1. Strip think blocks if any
            ans = re.sub(r'<think>.*?</think>', '', ans, flags=re.DOTALL).strip()

            # 2. Check if model output options like "1. Hinata... \n 2. ..."
            if "\n" in ans:
                opt_match = re.search(r'(?:(?:\*\*|\b)[1-9]\.|\*)\s*\**([A-Za-z0-9\s,\'!?—–-]+?)(?:\*\*|\n|\*|$)', ans)
                if opt_match and len(opt_match.group(1).strip()) > 1:
                    ans = opt_match.group(1).strip()
                else:
                    lines = [ln.strip() for ln in ans.split("\n") if ln.strip()]
                    clean_lines = [ln for ln in lines if not any(kw in ln.lower() for kw in ["breakdown", "options", "depending on", "nuance", "here are", "translate:"])]
                    if clean_lines:
                        ans = clean_lines[0]

            # 3. Strip refusal & assistant meta chatter
            ans = re.sub(r'\(?https?://[^\s)]+\)?', '', ans)
            ans = re.sub(r'(?:Hello!?\s*)?I am (?:Qwythos|Luna|Emma).*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'How (?:may|can) I assist.*?(?:\?|\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'Let me know (?:how|what|if).*?(?:\.|$|!)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'(?:an AI model )?created by .*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^(?:Here is|Here\'s) the translation:?\s*', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^Translation:\s*', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^(?:I\'m sorry|Sorry),? but I cannot.*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^As an AI.*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^The text [\"\'\‘].*?[\"\'\’] is a single.*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = re.sub(r'^The Japanese input.*?(?:\.|$)', '', ans, flags=re.IGNORECASE)
            ans = ans.strip()

            # 4. Strip surrounding quotation marks
            while (ans.startswith('"') and ans.endswith('"')) or (ans.startswith("'") and ans.endswith("'")) or (ans.startswith("“") and ans.endswith("”")):
                ans = ans[1:-1].strip()
            
            # 5. Clean markdown bold/italics markers
            ans = re.sub(r'^\*\*|\*\*$', '', ans).strip()
            ans = re.sub(r'^\*|\*$', '', ans).strip()

            # 6. Pick primary translation if multiple variants separated by slash
            if " / " in ans:
                ans = ans.split(" / ")[0].strip()

            return (ans, None)
    except Exception as e:
        return ("", str(e))

def split_words_by_pause(words, max_pause: float = 1.2, sentence_pause: float = 0.45):
    """
    Splits a list of word timestamps into subtitle chunks using smart linguistic triggers:
    1. Any pause > max_pause seconds (speaker change / scene change / music break).
    2. Any pause > sentence_pause seconds that follows a true Japanese sentence-ending
       punctuation (。！？…) — but NOT after incomplete topic particles (は, が, の, に, を, で)
       or conjunctions (でも, さて, いや, けど).
    3. Merges orphan single-character chunks and incomplete clauses forward into the next chunk.
    4. Merges repeated short crying/calling words (e.g. ママ... ママ -> ママ、ママ!).
    """
    _SENTENCE_END = frozenset("。！？…")
    _INCOMPLETE_PARTICLES = frozenset("はがのにをでへと")
    _INCOMPLETE_CONJUNCTIONS = frozenset(["でも", "さて", "いや", "けど", "しかし", "だから", "それで"])

    raw_chunks = []
    curr = []
    for w in words:
        if curr:
            gap = w.start - curr[-1].end
            prev_word_text = curr[-1].word.rstrip()

            # Check if previous word is an incomplete clause / dependent particle
            is_dependent = (
                (len(prev_word_text) > 0 and prev_word_text[-1] in _INCOMPLETE_PARTICLES)
                or prev_word_text in _INCOMPLETE_CONJUNCTIONS
            )

            # Trigger 1: long gap — speaker/scene change (allowed even on dependent particles if > 1.6s)
            long_gap = gap > (1.6 if is_dependent else max_pause)

            # Trigger 2: sentence boundary — pause after 。！？… (only if not an incomplete clause)
            sentence_boundary = (
                not is_dependent
                and gap > sentence_pause
                and len(prev_word_text) > 0
                and prev_word_text[-1] in _SENTENCE_END
            )

            if long_gap or sentence_boundary:
                raw_chunks.append(curr)
                curr = []
        curr.append(w)
    if curr:
        raw_chunks.append(curr)

    # Post-process:
    # 1. Merge orphan single characters or incomplete short clauses (<= 3 chars ending in particle)
    # 2. Merge identical short crying/calling words within 1.5s
    merged_chunks = []
    idx = 0
    while idx < len(raw_chunks):
        c = raw_chunks[idx]
        text = "".join(w.word for w in c).strip()

        # Check if this chunk is a tiny filler grunt (ん, あ, え)
        if text in ("ん", "あ", "え", "う", "お", "へ") and len(c) == 1:
            if (idx + 1) < len(raw_chunks) and (raw_chunks[idx + 1][0].start - c[-1].end) < 1.5:
                raw_chunks[idx + 1] = c + raw_chunks[idx + 1]
            idx += 1
            continue

        if (idx + 1) < len(raw_chunks):
            next_c = raw_chunks[idx + 1]
            next_text = "".join(w.word for w in next_c).strip()
            gap = next_c[0].start - c[-1].end

            # Case A: Incomplete clause (<= 3 chars ending in は/の/に/を/でも) within 2.5s
            is_fragment = (
                len(text) <= 3 
                and (text[-1] in _INCOMPLETE_PARTICLES or text in _INCOMPLETE_CONJUNCTIONS)
                and gap < 2.5
            )
            # Case B: Orphan single character within 2.0s
            is_orphan = (len(text) <= 1 and gap < 2.0)
            
            # Case C: Repeated crying / calling word (e.g. ママ... ママ / パパ... パパ) within 1.5s
            is_repeated_call = (
                text in ("ママ", "パパ", "待って", "だめ", "ダメ", "いや", "イヤ")
                and next_text.startswith(text)
                and gap < 1.5
            )

            if is_fragment or is_orphan or is_repeated_call:
                raw_chunks[idx + 1] = c + next_c
                idx += 1
                continue

        merged_chunks.append(c)
        idx += 1

    return merged_chunks


# Known YouTube / ASR training data hallucination signatures to discard
_HALLUCINATION_PATTERNS = [
    r"ご視聴ありがとう",
    r"チャンネル登録",
    r"高評価",
    r"Thanks for watching",
    r"Thank you for watching",
    r"Subtitles by",
    r"Translated by",
    r"^エンディフォレース$",
    r"^Endiferous$",
    r"^ご視聴$",
    r"お疲れ様でした[。！]*$",
    r"最後までご視聴",
    r"字幕.*制作",
]

def is_whisper_hallucination(text: str) -> bool:
    """Returns True if the text matches known YouTube/Whisper training hallucination boilerplate."""
    import re
    cleaned = text.strip()
    if not cleaned:
        return True
    for pat in _HALLUCINATION_PATTERNS:
        if re.search(pat, cleaned, re.IGNORECASE):
            return True
    return False


# Acoustic confusion & proper noun normalizer: Whisper-incorrect -> correct Japanese
_ANIME_PHONETIC_FIXUPS = [
    # SAO Character names & specific vocabulary
    (r"\b死後[、,\s]*甘い", "須郷、甘い"),
    (r"死後[、,\s]*貴様", "須郷、貴様"),
    (r"死後[、,\s]*絶対に", "須郷、絶対に"),
    (r"死後[、,\s]*お前", "須郷、お前"),
    (r"死後[、,\s]*許さ", "須郷、許さ"),
    (r"\b死後\b(?=.*(?:殺す|貴様|アスナ|キリト|甘い))", "須郷"),
    (r"コードを?戦車", "コードを転写"),
    (r"高度を?転写", "コードを転写"),
    (r"高度を?戦車", "コードを転写"),
    (r"(?:検討|転倒)されます", "転送されます"),
    (r"ユウ、これを使え", "ユイ、これを使え"),
    (r"ユウ、ここは", "ユイ、ここは"),
    (r"ユウ、大丈夫", "ユイ、大丈夫"),
    # Sung acoustic confusion
    (r"確かな機械を手に", "確かな誓いを手に"),
    (r"確かな機械を手", "確かな誓いを手"),
    (r"席だけを求め", "奇跡だけを求め"),
    (r"感情悲鳴を上げてる", "感情が悲鳴を上げてる"),
]

def normalize_anime_text(text: str) -> str:
    """Apply known acoustic-confusion and proper-noun corrections for anime speech."""
    import re
    for pattern, replacement in _ANIME_PHONETIC_FIXUPS:
        text = re.sub(pattern, replacement, text)
    return text

def fix_sung_kanji(text: str) -> str:
    """Legacy alias for backward compatibility."""
    return normalize_anime_text(text)


def is_confucius_model(model_path: str, engine_setting: str = "Auto") -> bool:
    if engine_setting == "Confucius4-R2T2":
        return True
    if engine_setting == "Faster-Whisper":
        return False
    mp = str(model_path).lower()
    return any(k in mp for k in ["confucius", "qwen3", "r2t2"])

def ensure_cuda_libraries():
    candidates = [
        "/home/valse-de-anshu/confucius-env/lib/python3.12/site-packages/nvidia/cublas/lib/libcublas.so.12",
        "/home/valse-de-anshu/confucius-env/lib/python3.12/site-packages/nvidia/cudnn/lib/libcudnn.so.9",
        "/home/valse-de-anshu/.local/lib/python3.14/site-packages/nvidia/cublas/lib/libcublas.so.12",
        "/home/valse-de-anshu/.local/share/translator-env/lib/python3.12/site-packages/nvidia/cublas/lib/libcublas.so.12",
    ]
    import ctypes
    for c in candidates:
        if os.path.exists(c):
            try:
                ctypes.CDLL(c)
            except Exception:
                pass

def free_stt_memory(model=None):
    """Forcefully frees all STT neural weights from GPU, CPU RAM, and swap cache."""
    if model is not None:
        del model
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

def run_ollama_translation_phase(collected_entries, vtt_target_path: str, target_lang: str, ollama_model: Optional[str], status_orig, live, get_renderable):
    """
    Phase 2: Translates all collected dialogue entries using local Ollama LLM.
    Runs ONLY after STT has been completely freed from GPU memory.
    """
    if not ollama_model:
        status_target = Panel(
            "[bold red]Cannot translate: No Ollama model detected at http://localhost:11434![/bold red]\n"
            "[warning]Google Translate has been permanently disabled as requested.\n"
            "To translate, start Ollama (e.g. 'ollama run luna:latest')[/warning]",
            title="[bold red]Translation Offline[/]",
            border_style="error"
        )
        live.update(get_renderable(status_orig, status_target))
        time.sleep(3)
        return

    status_target = Panel(
        f"[info]STT memory flushed from GPU.\nConnecting to Ollama ({ollama_model})...\nPre-warming weights in GPU...[/info]",
        title=f"[info]Phase 2: Local LLM ({ollama_model})[/]",
        border_style="menu"
    )
    live.update(get_renderable(status_orig, status_target))

    warm_err = prewarm_ollama(ollama_model)
    if warm_err:
        status_target = Panel(
            f"[bold red]Failed to initialize Ollama ({ollama_model}):[/bold red]\n"
            f"[error]{warm_err}[/error]\n"
            "[warning]Verify 'ollama ps' or 'systemctl status ollama'.[/warning]",
            title="[bold red]Ollama Connection Error[/]",
            border_style="error"
        )
        live.update(get_renderable(status_orig, status_target))
        time.sleep(4)
        return

    f_target = open(vtt_target_path, "w", encoding="utf-8")
    f_target.write("WEBVTT\n\n")

    tot = len(collected_entries)
    log_target = []

    for idx, (s_sec, e_sec, s_str, e_str, orig_text) in enumerate(collected_entries):
        status_target = Panel(
            f"[info]Translating ({idx+1}/{tot}):[/info]\n[dim]{orig_text}[/dim]",
            title=f"[info]Ollama ({ollama_model}) — Line {idx+1}/{tot}[/]",
            border_style="menu"
        )
        live.update(get_renderable(status_orig, status_target))

        trans_text, err = translate_segment_ollama(orig_text, target_lang, ollama_model)
        if err:
            err_msg = f"[bold red]Error:[/] {err}"
            log_target.append(f"[{s_str} -> {e_str}] {err_msg}")
        elif trans_text and trans_text.strip():
            clean_t = trans_text.strip()
            log_target.append(f"[{s_str} -> {e_str}] {clean_t}")
            f_target.write(f"{s_str} --> {e_str}\n{clean_t}\n\n")
            f_target.flush()

        if len(log_target) > 6:
            log_target.pop(0)
        status_target = Panel("\n".join(log_target), title=f"[success]Ollama ({ollama_model}) Translation ({idx+1}/{tot})[/]", border_style="success")
        live.update(get_renderable(status_orig, status_target))

    f_target.close()
    status_target = Panel(
        f"[bold #9ece6a]Translation Complete ({tot} lines)[/]\nSaved: {os.path.basename(vtt_target_path)}",
        title="[bold #9ece6a]Phase 2 Done[/]",
        border_style="success"
    )
    live.update(get_renderable(status_orig, status_target))

def generate_subtitles_whisper(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str, spoken_lang: str = "Auto", llm_model: Optional[str] = None, use_vocal_isolation: bool = True):
    ensure_cuda_libraries()
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    
    compute_type = "int8" if vram_target == "6GB (INT8)" else "float16"
    device = "cpu" if vram_target == "CPU-Only" else "cuda"
    
    do_target = "Target" in languages or "Both" in languages
    do_orig = "Original" in languages or "Both" in languages
    
    ollama_model = (llm_model or get_ollama_model()) if do_target else None
    llm_tag = f"[bold green]Ollama ({ollama_model})[/]" if ollama_model else "[bold red]None (Ollama Offline)[/]"
    vocal_tag = "[bold cyan]Demucs v4[/]" if use_vocal_isolation else "[dim]Raw Audio[/]"

    header = Panel(
        f"[bold #bb9af7]AI Subtitle Engine[/] - {os.path.basename(video_path)}\n"
        f"[info]Engine:[/] Faster-Whisper | [info]Spoken:[/] {spoken_lang} | [info]Audio:[/] {vocal_tag} | [info]LLM:[/] {llm_tag}",
        border_style="menu"
    )
    
    status_orig = Panel(Text("Initializing Whisper...", style="info"), title="[info]Phase 1: Transcription[/]", border_style="menu")
    if do_target:
        if ollama_model:
            status_target = Panel(f"[info]Local LLM Ready: {ollama_model}\nWaiting for transcription to finish before loading LLM into VRAM...[/info]", title=f"[info]Phase 2: Translation ({ollama_model})[/]", border_style="menu")
        else:
            status_target = Panel("[bold red]Ollama is NOT running or no model found at http://localhost:11434.[/bold red]\n[warning]Google Translate has been removed.\nStart Ollama (e.g. 'ollama run luna:latest') to translate.[/warning]", title="[bold red]Phase 2: Translation Offline[/]", border_style="error")
    else:
        status_target = Panel(Text("Disabled (Original Audio Only)", style="dim"), title="[dim]Translation[/]", border_style="menu")

    def get_renderable(orig_panel, target_panel):
        from rich.columns import Columns
        panels = []
        if do_orig: panels.append(orig_panel)
        if do_target: panels.append(target_panel)
        return Group(header, Columns(panels, expand=True))
    
    with Live(get_renderable(status_orig, status_target), refresh_per_second=4, console=console) as live:
        model = None
        temp_wav = ""
        f_orig = None
        vtt_orig_path = os.path.splitext(video_path)[0] + ".Original.vtt"
        vtt_target_path = os.path.splitext(video_path)[0] + f".{target_lang}.vtt"
        collected_entries = []
        
        try:
            # --- PHASE 0 & 1: AUDIO EXTRACTION / VOCAL ISOLATION ---
            if use_vocal_isolation:
                temp_wav = isolate_vocals_demucs(video_path, live=live, get_renderable=get_renderable, status_target=status_target)
            else:
                status_orig = Panel(Text("Extracting 16kHz mono audio track...", style="warning"), title="[warning]FFMPEG Extraction[/]", border_style="menu")
                live.update(get_renderable(status_orig, status_target))
                temp_wav = extract_audio(video_path)

            if not os.path.exists(temp_wav):
                live.stop()
                console.print("[error]Failed to extract or isolate audio using ffmpeg/demucs![/error]")
                time.sleep(3)
                return
                
            whisper_lang = None
            if spoken_lang and spoken_lang.lower() not in ["auto", "auto-detect", "none"]:
                sl = spoken_lang.lower()
                if "jap" in sl or sl == "ja": whisper_lang = "ja"
                elif "chi" in sl or sl == "zh": whisper_lang = "zh"
                elif "kor" in sl or sl == "ko": whisper_lang = "ko"
                elif "eng" in sl or sl == "en": whisper_lang = "en"
                else: whisper_lang = sl[:2]

            status_orig = Panel(Text(f"Loading Whisper into GPU ({compute_type})...", style="info"), title="[info]Loading Whisper[/]", border_style="menu")
            live.update(get_renderable(status_orig, status_target))
            
            unload_ollama_model()
            model = WhisperModel(model_path, device=device, compute_type=compute_type)

            is_turbo = "turbo" in model_path.lower()
            beam_size = 10 if is_turbo else 5
            best_of = 5 if is_turbo else 3
            # Custom fine-tuned models (e.g. anime-whisper) have modified cross-attention weights
            # that cause DTW alignment (add_word_timestamps) to throw std::bad_alloc in CTranslate2.
            # Large-v3-turbo has official alignment heads and uses word_timestamps safely.
            use_word_ts = is_turbo

            kwargs = {
                "task": "transcribe",
                "word_timestamps": use_word_ts,
                "beam_size": beam_size,
                "best_of": best_of,
                "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                "repetition_penalty": 1.1,    # Suppress hallucination loops
                "compression_ratio_threshold": 2.4,
                "log_prob_threshold": -1.0,   # Accept lower-confidence quiet/sung segments
                "condition_on_previous_text": False,  # Prevent hallucination cascades between segments
            }

            if use_vocal_isolation:
                # With Demucs vocal separation, audio is pure voice without background music.
                kwargs["vad_filter"] = True
                kwargs["vad_parameters"] = dict(min_silence_duration_ms=300)
                if is_turbo:
                    kwargs["batch_size"] = 8
                    kwargs["hallucination_silence_threshold"] = 2.0
                    transcribe_engine = BatchedInferencePipeline(model=model)
                    status_orig = Panel("Transcribing clean vocals with Batched Whisper & Word Timestamps...", title="[success]Transcribing Speech (Batched)[/]", border_style="success")
                else:
                    transcribe_engine = model
                    status_orig = Panel("Transcribing clean vocals with Anime-Whisper & Word Timestamps...", title="[success]Transcribing Speech (Anime-Whisper)[/]", border_style="success")
            else:
                # On raw audio, disable VAD to prevent Silero from dropping dialogue overlapping with loud BGM/SFX
                kwargs["vad_filter"] = False
                kwargs["no_speech_threshold"] = 0.3
                transcribe_engine = model
                status_orig = Panel("Transcribing raw audio with Word Timestamps (VAD off)...", title="[success]Transcribing Speech (Sequential)[/]", border_style="success")

            live.update(get_renderable(status_orig, status_target))

            if whisper_lang:
                kwargs["language"] = whisper_lang
                if whisper_lang == "ja":
                    kwargs["initial_prompt"] = (
                        # Style primer — tells Whisper what register to expect
                        "日本語のアニメ、ライトノベル、ゲーム、映画のセリフと歌詞です。"
                        # SAO character and world names
                        "キリト、アスナ、ユイ、リーファ、クライン、シノン、アリス、ユージオ、"
                        "スグハ、アジール、ヒースクリフ、茅場晶彦、須郷、須郷伸之、オベイロン、妖精王。"
                        # World / system vocabulary
                        "アインクラッド、アルヴヘイム、世界樹、グランドクエスト、"
                        "システムコンソール、コード転写、転送、ログアウト、ソードアート、オンライン。"
                        # Commonly misheared song/anime kanji — primes Whisper's token space
                        "誓い、奇跡、想い、願い、運命、約束、希望、絆、涙、叫び、"
                        "感情、悲鳴、彷徨う、輝く、煌めく、震える、解き放つ、乗り越える。"
                        # Common anime dialogue patterns
                        "仲間、戦い、勇気、守る、救う、負けない、諦めない、立ち向かう。"
                        # Verbatim song phrases — forces correct kanji on acoustically ambiguous sung lines
                        "隠してた感情が悲鳴を上げてる。確かな誓いを手に。"
                        "奇跡だけを求め、消えない闇を彷徨う。どこにいれば二度と未来が見えなくなる。"
                    )
                elif whisper_lang == "zh":
                    kwargs["initial_prompt"] = "这是中文动漫、轻小说和游戏的台词与歌词。"
                elif whisper_lang == "ko":
                    kwargs["initial_prompt"] = "한국 애니메이션, 드라마, 게임의 대사와 가사입니다."

            if do_orig or do_target:
                f_orig = open(vtt_orig_path, "w", encoding="utf-8")
                f_orig.write("WEBVTT\n\n")

            segments, info = transcribe_engine.transcribe(temp_wav, **kwargs)

            log_orig = []

            for segment in segments:
                # Discard segments with high silence/music probability (> 70%)
                if getattr(segment, "no_speech_prob", 0.0) > 0.70:
                    continue

                if segment.words:
                    chunks = split_words_by_pause(segment.words)
                    for chunk in chunks:
                        raw_t = "".join(w.word for w in chunk).strip()
                        text = normalize_anime_text(raw_t)
                        if not text or is_whisper_hallucination(text):
                            continue
                        s_sec = chunk[0].start
                        e_sec = chunk[-1].end
                        # Enforce 0.8s minimum display duration so subtitles don't flash in 0.2s
                        if (e_sec - s_sec) < 0.8:
                            e_sec = s_sec + 0.8
                        s_str = format_timestamp(s_sec)
                        e_str = format_timestamp(e_sec)
                        collected_entries.append((s_sec, e_sec, s_str, e_str, text))
                        if f_orig:
                            f_orig.write(f"{s_str} --> {e_str}\n{text}\n\n")
                            f_orig.flush()
                        log_orig.append(f"[{s_str} -> {e_str}] {text}")
                        if len(log_orig) > 6: log_orig.pop(0)
                        status_orig = Panel("\n".join(log_orig), title="[success]Original Dialogue[/]", border_style="success")
                        live.update(get_renderable(status_orig, status_target))
                else:
                    raw_t = segment.text.strip()
                    text = normalize_anime_text(raw_t)
                    if not text or is_whisper_hallucination(text):
                        continue
                    s_sec = segment.start
                    e_sec = segment.end
                    if (e_sec - s_sec) < 0.8:
                        e_sec = s_sec + 0.8
                    s_str = format_timestamp(s_sec)
                    e_str = format_timestamp(e_sec)
                    collected_entries.append((s_sec, e_sec, s_str, e_str, text))
                    if f_orig:
                        f_orig.write(f"{s_str} --> {e_str}\n{text}\n\n")
                        f_orig.flush()
                    log_orig.append(f"[{s_str} -> {e_str}] {text}")
                    if len(log_orig) > 6: log_orig.pop(0)
                    status_orig = Panel("\n".join(log_orig), title="[success]Original Dialogue[/]", border_style="success")
                    live.update(get_renderable(status_orig, status_target))

            if f_orig:
                f_orig.close()
                f_orig = None

            status_orig = Panel(f"[bold #9ece6a]Transcription Complete ({len(collected_entries)} dialogue lines)[/]\nSaved: {os.path.basename(vtt_orig_path)}", title="[bold #9ece6a]Phase 1 Done[/]", border_style="success")
            live.update(get_renderable(status_orig, status_target))
            
            # --- MEMORY FLUSH: KILL STT BEFORE LLM STARTS ---
            free_stt_memory(model)
            model = None

            # --- PHASE 2: LOCAL LLM TRANSLATION ---
            if do_target:
                run_ollama_translation_phase(collected_entries, vtt_target_path, target_lang, ollama_model, status_orig, live, get_renderable)

            try:
                from butler.notify import send_os_notification
                send_os_notification("Zine Scraper Subtitles", f"Successfully generated subtitles for {os.path.basename(video_path)}", is_success=True)
            except Exception:
                pass
                
            time.sleep(2)
            
        except KeyboardInterrupt:
            pass # Silently abort inside child process
        except Exception as e:
            import traceback
            traceback.print_exc()
            layout_err = Panel(f"Error: {e}", title="[error]Fatal Error[/]", border_style="error")
            live.update(layout_err)
            try:
                from butler.notify import send_os_notification
                send_os_notification("Zine Scraper Error", f"Failed to generate subtitles: {e}", is_success=False)
            except Exception:
                pass
            time.sleep(3)
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
            free_stt_memory(model)
            unload_ollama_model()

def generate_subtitles_confucius(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str, confucius_py: str = "", spoken_lang: str = "Auto", llm_model: Optional[str] = None, use_vocal_isolation: bool = True):
    import json

    do_target = "Target" in languages or "Both" in languages
    do_orig = "Original" in languages or "Both" in languages

    ollama_model = (llm_model or get_ollama_model()) if do_target else None
    llm_tag = f"[bold green]Ollama ({ollama_model})[/]" if ollama_model else "[bold red]None (Ollama Offline)[/]"
    vocal_tag = "[bold cyan]Demucs v4[/]" if use_vocal_isolation else "[dim]Raw Audio[/]"

    status_orig = Panel(Text("Initializing Confucius4-R2T2...", style="info"), title="[info]Phase 1: Transcription[/]", border_style="menu")
    if do_target:
        if ollama_model:
            status_target = Panel(f"[info]Local LLM Ready: {ollama_model}\nWaiting for transcription to finish before loading LLM into VRAM...[/info]", title=f"[info]Phase 2: Translation ({ollama_model})[/]", border_style="menu")
        else:
            status_target = Panel("[bold red]Ollama is NOT running or no model found at http://localhost:11434.[/bold red]\n[warning]Google Translate has been removed.\nStart Ollama (e.g. 'ollama run luna:latest') to translate.[/warning]", title="[bold red]Phase 2: Translation Offline[/]", border_style="error")
    else:
        status_target = Panel(Text("Disabled (Original Audio Only)", style="dim"), title="[dim]Translation[/]", border_style="menu")

    header = Panel(
        f"[bold #bb9af7]AI Transcription Engine (Confucius4-R2T2)[/] - {os.path.basename(video_path)}\n"
        f"[info]Engine:[/] Confucius4-R2T2 | [info]Spoken:[/] {spoken_lang} | [info]Audio:[/] {vocal_tag} | [info]LLM:[/] {llm_tag}",
        border_style="menu"
    )

    def get_renderable(orig_panel, target_panel):
        from rich.columns import Columns
        panels = []
        if do_orig: panels.append(orig_panel)
        if do_target: panels.append(target_panel)
        return Group(header, Columns(panels, expand=True))

    with Live(get_renderable(status_orig, status_target), refresh_per_second=4, console=console) as live:
        temp_wav = ""
        proc = None
        vtt_orig_path = os.path.splitext(video_path)[0] + ".Original.vtt"
        vtt_target_path = os.path.splitext(video_path)[0] + f".{target_lang}.vtt"
        f_orig = None
        collected_entries = []

        try:
            # --- PHASE 0 & 1: AUDIO EXTRACTION / VOCAL ISOLATION ---
            if use_vocal_isolation:
                temp_wav = isolate_vocals_demucs(video_path, live=live, get_renderable=get_renderable, status_target=status_target)
            else:
                status_orig = Panel(Text("Extracting 16kHz audio track...", style="warning"), title="[warning]FFMPEG Extraction[/]", border_style="menu")
                live.update(get_renderable(status_orig, status_target))
                temp_wav = extract_audio(video_path)

            if not os.path.exists(temp_wav):
                live.stop()
                console.print("[error]Failed to extract or isolate audio using ffmpeg/demucs![/error]")
                time.sleep(3)
                return

            paths = PathAuthority()
            if not confucius_py or not os.path.exists(confucius_py):
                confucius_py = sys.executable

            engine_script = (paths.get_confucius_stt_dir() / "confucius_engine.py").resolve()
            if not engine_script.exists():
                engine_script = (paths.get_app_root() / "Models" / "STT" / "Confucius4" / "confucius_engine.py").resolve()

            device = "cpu" if vram_target == "CPU-Only" else "cuda"
            actual_model = model_path
            # If pointing to folder without weights, fallback to repo id
            if os.path.isdir(model_path):
                safetensors = list(Path(model_path).glob("*.safetensors"))
                if not safetensors and not (Path(model_path) / "config.json").exists():
                    actual_model = "netease-youdao/Confucius4-R2T2"

            status_orig = Panel(Text("Starting Confucius4-R2T2 neural worker...", style="info"), title="[info]Status[/]", border_style="menu")
            live.update(get_renderable(status_orig, status_target))

            unload_ollama_model()
            cmd = [
                confucius_py,
                str(engine_script),
                "--audio", temp_wav,
                "--model_path", actual_model,
                "--backend", "transformers",
                "--device", device,
                "--max_chunk_sec", "8.0"
            ]
            if spoken_lang and spoken_lang.lower() not in ["auto", "auto-detect", "none"]:
                cmd.extend(["--language", spoken_lang])

            if do_orig or do_target:
                f_orig = open(vtt_orig_path, "w", encoding="utf-8")
                f_orig.write("WEBVTT\n\n")

            log_orig = []

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except Exception:
                    continue

                evt = data.get("event")
                if evt == "status":
                    msg = data.get("message", "")
                    status_orig = Panel(Text(msg, style="info"), title="[info]Model Status[/]", border_style="menu")
                    live.update(get_renderable(status_orig, status_target))
                elif evt == "segment":
                    start_sec = float(data.get("start", 0.0))
                    end_sec = float(data.get("end", 0.0))
                    start_str = data.get("start_str", format_timestamp(start_sec))
                    end_str = data.get("end_str", format_timestamp(end_sec))
                    orig_text = normalize_anime_text(data.get("text", "").strip())

                    if orig_text and not is_whisper_hallucination(orig_text):
                        if (end_sec - start_sec) < 0.8:
                            end_sec = start_sec + 0.8
                            end_str = format_timestamp(end_sec)
                        collected_entries.append((start_sec, end_sec, start_str, end_str, orig_text))
                        if f_orig:
                            f_orig.write(f"{start_str} --> {end_str}\n{orig_text}\n\n")
                            f_orig.flush()
                        log_orig.append(f"[{start_str} -> {end_str}] {orig_text}")
                        if len(log_orig) > 6:
                            log_orig.pop(0)
                        cur = data.get("chunk_index", "")
                        tot = data.get("total_chunks", "")
                        progress_tag = f" ({cur}/{tot})" if cur and tot else ""
                        status_orig = Panel("\n".join(log_orig), title=f"[success]Original Spoken Audio{progress_tag}[/]", border_style="success")
                        live.update(get_renderable(status_orig, status_target))
                elif evt == "error":
                    err_msg = data.get("message", "Unknown error")
                    status_orig = Panel(f"Error: {err_msg}", title="[error]Confucius4 Error[/]", border_style="error")
                    live.update(get_renderable(status_orig, status_target))

            proc.wait()
            proc = None

            if f_orig:
                f_orig.close()
                f_orig = None

            status_orig = Panel(f"[bold #9ece6a]Transcription Complete ({len(collected_entries)} dialogue lines)[/]\nSaved: {os.path.basename(vtt_orig_path)}", title="[bold #9ece6a]Phase 1 Done[/]", border_style="success")
            live.update(get_renderable(status_orig, status_target))

            # --- MEMORY FLUSH: KILL CONFUCIUS BEFORE LLM STARTS ---
            free_stt_memory()

            # --- PHASE 2: LOCAL LLM TRANSLATION ---
            if do_target:
                run_ollama_translation_phase(collected_entries, vtt_target_path, target_lang, ollama_model, status_orig, live, get_renderable)

            try:
                from butler.notify import send_os_notification
                send_os_notification("Zine Scraper Subtitles", f"Successfully generated subtitles for {os.path.basename(video_path)}", is_success=True)
            except Exception:
                pass

            time.sleep(2)

        except KeyboardInterrupt:
            if proc:
                try: proc.kill()
                except Exception: pass
        except Exception as e:
            layout_err = Panel(f"Error: {e}", title="[error]Fatal Error[/]", border_style="error")
            live.update(layout_err)
            try:
                from butler.notify import send_os_notification
                send_os_notification("Zine Scraper Error", f"Failed to generate subtitles: {e}", is_success=False)
            except Exception:
                pass
            time.sleep(3)
        finally:
            if proc and proc.poll() is None:
                try: proc.kill()
                except Exception: pass
            if os.path.exists(temp_wav):
                try: os.remove(temp_wav)
                except Exception: pass
            free_stt_memory()
            unload_ollama_model()

def generate_subtitles(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str, engine_type: str = "Auto", confucius_py: str = "", spoken_lang: str = "Auto", llm_model: Optional[str] = None, use_vocal_isolation: bool = True):
    if is_confucius_model(model_path, engine_type):
        generate_subtitles_confucius(video_path, model_path, languages, target_lang, vram_target, confucius_py, spoken_lang, llm_model, use_vocal_isolation)
    else:
        generate_subtitles_whisper(video_path, model_path, languages, target_lang, vram_target, spoken_lang, llm_model, use_vocal_isolation)

def run_subtitle_tui(initial_path: Optional[str] = None):
    paths = PathAuthority()
    storage = StorageLayer()
    config = ConfigLayer(paths, storage)
    
    startup_clear()
    print_banner()

    ollama_m = get_ollama_model()
    if ollama_m:
        console.print(f"[bold green]🤖 Local LLM Detected:[/] Ollama ([bold cyan]{ollama_m}[/]) ready for translation\n")
    else:
        console.print("[bold red]⚠️ No Local LLM Detected at http://localhost:11434[/bold red] [dim](Google Translate is permanently disabled)[/dim]\n")

    curr_engine = config.get("ai_subtitles_engine", "Auto")
    engine_opts = [
        ("🌸 Anime-Whisper (Fine-Tuned on 5,300 hrs Anime Speech & Character Emotion)", "Anime-Whisper"),
        ("🧠 Faster-Whisper (Large-v3-Turbo — Speaker-Accurate VAD & Timing)", "Faster-Whisper"),
        ("⚡ Confucius4-R2T2 (Qwen3-ASR — High Fidelity Streaming)", "Confucius4-R2T2"),
        (f"⚙️ Use Default from Settings ({curr_engine})", curr_engine)
    ]
    from core.ui import BoxSelector
    chosen_engine = BoxSelector(engine_opts, title="Select Subtitle STT Engine", width=78).select()
    if not chosen_engine or chosen_engine in ("ESC", "CTRL_C"):
        return

    engine_type = chosen_engine

    lang_opts = [
        ("🇯🇵 Japanese (Anime / J-Media — Speaker-Accurate Dialogue)", "Japanese"),
        ("🌐 Auto-Detect Spoken Language", "Auto"),
        ("🇺🇸 English (Western Media / Audiobooks / Videos)", "English"),
        ("🇨🇳 Chinese (Mandarin / Donghua)", "Chinese"),
        ("🇰🇷 Korean (K-Media / Audio)", "Korean")
    ]
    spoken_lang = BoxSelector(lang_opts, title="Select Spoken Audio Language", width=78).select()
    if not spoken_lang or spoken_lang in ("ESC", "CTRL_C"):
        return

    vocal_opts = [
        ("🎤 Demucs v4 Vocal Isolation (Strip BGM & SFX — SOTA for Anime / Action)", True),
        ("⏩ Standard Raw Audio (Fastest — No Stem Separation)", False)
    ]
    chosen_vocal = BoxSelector(vocal_opts, title="Select Audio Isolation Mode", width=78).select()
    if chosen_vocal is None or chosen_vocal in ("ESC", "CTRL_C"):
        return

    mode_opts = [
        ("🎯 Both (Pristine Original Audio .vtt + English Translation .vtt)", "Both"),
        ("🇯🇵 Original Spoken Audio Only (.Original.vtt — Character Dialogue)", "Original"),
        ("🌐 Translated Subtitles Only (.English.vtt)", "Target")
    ]
    chosen_mode = BoxSelector(mode_opts, title="Select Subtitle Mode", width=78).select()
    if not chosen_mode or chosen_mode in ("ESC", "CTRL_C"):
        return

    chosen_llm = None
    if chosen_mode in ("Both", "Target"):
        all_models = get_all_ollama_models()
        if len(all_models) > 1:
            sorted_models = sorted(all_models, key=lambda x: 0 if "emma" in x.lower() else 1)
            llm_opts = [
                (f"🤖 {m} {'(Recommended: Gemma 7.5B SFW+NSFW Uncensored)' if 'emma' in m.lower() else ''}".strip(), m)
                for m in sorted_models
            ]
            chosen_llm = BoxSelector(llm_opts, title="Select Translation LLM (Ollama)", width=78).select()
            if not chosen_llm or chosen_llm in ("ESC", "CTRL_C"):
                return
        elif len(all_models) == 1:
            chosen_llm = all_models[0]
        else:
            chosen_llm = get_ollama_model()

    console.print("\n[bold #bb9af7]AI Subtitle Engine[/]")
    from core.paths import sanitize_user_path
    video_path = ""
    if initial_path:
        video_path = sanitize_user_path(initial_path)
    else:
        from core.settings_tui import prompt_field_value
        video_path = prompt_field_value("Media File Path", "", "(Enter path to video or audio file — .mp4, .mkv, .mp3, .flac, .wav, etc.)")
    
    if not video_path:
        return
    video_path = sanitize_user_path(video_path)
    video_path = os.path.expanduser(video_path)
        
    if not os.path.exists(video_path):
        console.print(f"[error]Invalid or non-existent file path:\n{video_path}[/error]")
        time.sleep(3)
        return
        
    models_root = paths.get_models_root()
    stt_root = paths.get_stt_models_root()
    configured_path = config.get("ai_subtitles_model", "Models/STT/faster-whisper-large-v3-turbo")
    clean_configured = sanitize_user_path(configured_path)
    confucius_py = config.get("confucius_python_path", "/home/valse-de-anshu/confucius-env/bin/python")
    
    is_confucius = is_confucius_model(clean_configured, engine_type)

    if is_confucius:
        candidate_path = Path(clean_configured).expanduser().resolve() if os.path.isabs(clean_configured) else (paths.get_app_root() / clean_configured).resolve()
        if candidate_path.exists() and candidate_path.is_dir() and ((candidate_path / "model.safetensors").exists() or (candidate_path / "config.json").exists()):
            model_path = str(candidate_path)
        else:
            conf_dir = paths.get_confucius_stt_dir()
            weights_dir = conf_dir / "weights"
            if weights_dir.exists() and (weights_dir / "model.safetensors").exists():
                model_path = str(weights_dir)
            elif conf_dir.exists() and ((conf_dir / "model.safetensors").exists() or (conf_dir / "config.json").exists()):
                model_path = str(conf_dir)
            else:
                model_path = "netease-youdao/Confucius4-R2T2"
    elif engine_type == "Anime-Whisper":
        anime_stt = stt_root / "anime-whisper"
        anime_root = models_root / "anime-whisper"
        if anime_stt.exists() and (anime_stt / "model.bin").exists():
            model_path = str(anime_stt)
        elif anime_root.exists() and (anime_root / "model.bin").exists():
            model_path = str(anime_root)
        else:
            local_stt_model = stt_root / "faster-whisper-large-v3-turbo"
            model_path = str(local_stt_model)
    else:
        # Priority 1: Check absolute or relative configured path
        candidate_path = Path(clean_configured).expanduser().resolve() if os.path.isabs(clean_configured) else (paths.get_app_root() / clean_configured).resolve()
        if candidate_path.exists() and candidate_path.is_dir():
            model_path = str(candidate_path)
        else:
            # Priority 2: Check Models/STT/faster-whisper-large-v3-turbo
            local_stt_model = stt_root / "faster-whisper-large-v3-turbo"
            local_root_model = models_root / "faster-whisper-large-v3-turbo"
            if local_stt_model.exists():
                model_path = str(local_stt_model)
            elif local_root_model.exists():
                model_path = str(local_root_model)
            else:
                # Priority 3: Scan Models/STT/ then Models/ for any faster-whisper folder
                found_models = [p for p in stt_root.glob("faster-whisper*") if p.is_dir() and (p / "config.json").exists()]
                if not found_models:
                    found_models = [p for p in models_root.glob("faster-whisper*") if p.is_dir() and (p / "config.json").exists()]
                if found_models:
                    model_path = str(found_models[0])
                else:
                    model_path = str(local_stt_model)

    sub_mode = chosen_mode or config.get("ai_subtitles_mode", "Both")
    target_lang = config.get("ai_target_lang", "English")
    vram_target = config.get("ai_subtitles_vram", "6GB (INT8)")
    
    if sub_mode == "None":
        console.print("[warning]Subtitles are disabled in Settings. Please enable them to run.[/warning]")
        time.sleep(2)
        return
        
    if not is_confucius and (not os.path.exists(model_path) or not os.path.isdir(model_path)):
        console.print(f"[error]Whisper Model not found at {model_path}![/error]")
        console.print("[info]Run this command to download the model into Models/STT/:[/info]")
        console.print("[site]python -c \"from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/STT/faster-whisper-large-v3-turbo')\"[/site]")
        console.print("[info]See [site]Models/README to downlode ai model.md[/site] for all download options.[/info]")
        time.sleep(4)
        return
        
    langs = []
    if sub_mode in ["Target", "Both"]:
        langs.append("Target")
    if sub_mode in ["Original", "Both"]:
        langs.append("Original")
        
    import multiprocessing
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning, module="multiprocessing.resource_tracker")
    
    p = multiprocessing.Process(target=generate_subtitles, args=(video_path, model_path, langs, target_lang, vram_target, engine_type, confucius_py, spoken_lang, chosen_llm, chosen_vocal))
    p.start()
    
    try:
        p.join()
    except KeyboardInterrupt:
        p.kill() # Vaporize the child process instantly (SIGKILL)
        p.join()
        console.print("\n[error]Aborted by user (Ctrl+C).[/error]")
        time.sleep(1)
