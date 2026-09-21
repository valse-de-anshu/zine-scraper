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

# --- Auto-inject Pip-installed NVIDIA CUDA/cuDNN Libraries ---
try:
    import site
    import ctypes
    for p in site.getsitepackages():
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

def extract_audio(video_path: str) -> str:
    temp_wav = os.path.splitext(video_path)[0] + "_temp_audio.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        temp_wav
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return temp_wav

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

_google_failed = False

def translate_text(text: str, target_lang: str = "English", source_hint: str = None) -> str:
    global _google_failed
    if not text or not text.strip():
        return text
    tl = target_lang.lower().strip()
    lang_map = {
        "english": "en-US", "spanish": "es-ES", "french": "fr-FR",
        "german": "de-DE", "italian": "it-IT", "japanese": "ja-JP",
        "chinese": "zh-CN", "korean": "ko-KR", "russian": "ru-RU",
        "portuguese": "pt-PT", "hindi": "hi-IN", "arabic": "ar-SA"
    }
    target_code = lang_map.get(tl, "en-US")
    source_code = detect_source_language(text, source_hint)
    if source_code == target_code:
        return text

    if not _google_failed:
        try:
            from deep_translator import GoogleTranslator
            res = GoogleTranslator(source='auto', target=tl).translate(text)
            if res:
                return res
        except Exception:
            _google_failed = True

    try:
        from deep_translator import MyMemoryTranslator
        res = MyMemoryTranslator(source=source_code, target=target_code).translate(text)
        if res:
            return res
    except Exception:
        pass

    try:
        import time
        time.sleep(0.5)
        from deep_translator import MyMemoryTranslator
        res = MyMemoryTranslator(source=source_code, target=target_code).translate(text)
        if res:
            return res
    except Exception:
        pass

    return text

def is_confucius_model(model_path: str, engine_setting: str = "Auto") -> bool:
    if engine_setting == "Confucius4-R2T2":
        return True
    if engine_setting == "Faster-Whisper":
        return False
    mp = str(model_path).lower()
    return any(k in mp for k in ["confucius", "qwen3", "r2t2"])

def generate_subtitles_whisper(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str):
    from faster_whisper import WhisperModel
    import gc
    
    compute_type = "int8" if vram_target == "6GB (INT8)" else "float16"
    device = "cpu" if vram_target == "CPU-Only" else "cuda"
    
    # Render layout
    do_target = "Target" in languages
    do_orig = "Original" in languages
    
    table = Table(show_header=False, show_edge=False, box=None, expand=True)
    if do_orig:
        table.add_column("Original")
    if do_target:
        table.add_column("Translation")
        
    status_orig = Panel(Text("Loading model...", style="info"), title="[info]Status[/]", border_style="menu")
    status_target = Panel(Text("Waiting...", style="info"), title="[info]Status[/]", border_style="menu")
    
    header = Panel(f"[bold #bb9af7]AI Transcription Engine (Faster-Whisper)[/] - {os.path.basename(video_path)}", border_style="menu")
    
    def get_renderable(orig_panel, target_panel):
        from rich.columns import Columns
        panels = []
        if do_orig: panels.append(orig_panel)
        if do_target: panels.append(target_panel)
        return Group(header, Columns(panels, expand=True))
    
    with Live(get_renderable(status_orig, status_target), refresh_per_second=4, console=console) as live:
        model = None
        temp_wav = ""
        try:
            model = WhisperModel(model_path, device=device, compute_type=compute_type)
            
            status_orig = Panel(Text("Extracting 16kHz audio track...", style="warning"), title="[warning]FFMPEG Extraction[/]", border_style="menu")
            live.update(get_renderable(status_orig, status_target))
            
            temp_wav = extract_audio(video_path)
            if not os.path.exists(temp_wav):
                live.stop()
                console.print("[error]Failed to extract audio using ffmpeg![/error]")
                time.sleep(3)
                return
                
            kwargs = {
                "task": "transcribe", 
                "vad_filter": True, 
                "beam_size": 5,
                "condition_on_previous_text": False
            }
            
            vtt_target_path = os.path.splitext(video_path)[0] + f".{target_lang}.vtt"
            vtt_orig_path = os.path.splitext(video_path)[0] + ".Original.vtt"
            
            translator = None
            if do_target:
                try:
                    from deep_translator import GoogleTranslator
                    translator = GoogleTranslator(source='auto', target=target_lang.lower())
                except ImportError:
                    pass
            
            if do_orig:
                status_orig = Panel("Starting...", title="[success]Transcribing Original...[/]", border_style="success")
            if do_target:
                status_target = Panel("Starting...", title=f"[success]Translating to {target_lang}...[/]", border_style="success")
            live.update(get_renderable(status_orig, status_target))
            
            segments, info = model.transcribe(temp_wav, **kwargs)
            
            f_orig = open(vtt_orig_path, "w", encoding="utf-8") if do_orig else None
            f_target = open(vtt_target_path, "w", encoding="utf-8") if do_target else None
            
            if f_orig: f_orig.write("WEBVTT\n\n")
            if f_target: f_target.write("WEBVTT\n\n")
            
            log_orig = []
            log_target = []
            
            for segment in segments:
                start_str = format_timestamp(segment.start)
                end_str = format_timestamp(segment.end)
                
                orig_text = segment.text.strip()
                target_text = ""
                
                if do_target and orig_text:
                    src_hint = getattr(info, "language", None) if "info" in locals() else None
                    target_text = translate_text(orig_text, target_lang, source_hint=src_hint)
                
                if f_orig:
                    f_orig.write(f"{start_str} --> {end_str}\n{orig_text}\n\n")
                    f_orig.flush()
                    log_orig.append(f"[{start_str} -> {end_str}] {orig_text}")
                    if len(log_orig) > 6: log_orig.pop(0)
                    status_orig = Panel("\n".join(log_orig), title="[success]Original Audio[/]", border_style="success")
                    
                if f_target:
                    f_target.write(f"{start_str} --> {end_str}\n{target_text}\n\n")
                    f_target.flush()
                    log_target.append(f"[{start_str} -> {end_str}] {target_text}")
                    if len(log_target) > 6: log_target.pop(0)
                    status_target = Panel("\n".join(log_target), title=f"[success]{target_lang} Translation[/]", border_style="success")
                
                live.update(get_renderable(status_orig, status_target))
            
            if f_orig: f_orig.close()
            if f_target: f_target.close()
            
            if do_orig: status_orig = Panel("Done.", title="[bold #9ece6a]Complete[/]", border_style="success")
            if do_target: status_target = Panel("Done.", title="[bold #9ece6a]Complete[/]", border_style="success")
            live.update(get_renderable(status_orig, status_target))
            
            try:
                from butler.notify import send_os_notification
                send_os_notification("Zine Scraper Subtitles", f"Successfully generated subtitles for {os.path.basename(video_path)}", is_success=True)
            except Exception:
                pass
                
            time.sleep(2)
            
        except KeyboardInterrupt:
            pass # Silently abort inside child process
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
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except Exception:
                    pass
            if model is not None:
                del model
            gc.collect()

def generate_subtitles_confucius(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str, confucius_py: str = ""):
    import gc
    import json

    do_target = "Target" in languages
    do_orig = "Original" in languages

    status_orig = Panel(Text("Initializing Confucius4-R2T2...", style="info"), title="[info]Status[/]", border_style="menu")
    status_target = Panel(Text("Waiting...", style="info"), title="[info]Status[/]", border_style="menu")
    header = Panel(f"[bold #bb9af7]AI Transcription Engine (Confucius4-R2T2)[/] - {os.path.basename(video_path)}", border_style="menu")

    def get_renderable(orig_panel, target_panel):
        from rich.columns import Columns
        panels = []
        if do_orig: panels.append(orig_panel)
        if do_target: panels.append(target_panel)
        return Group(header, Columns(panels, expand=True))

    with Live(get_renderable(status_orig, status_target), refresh_per_second=4, console=console) as live:
        temp_wav = ""
        proc = None
        try:
            status_orig = Panel(Text("Extracting 16kHz audio track...", style="warning"), title="[warning]FFMPEG Extraction[/]", border_style="menu")
            live.update(get_renderable(status_orig, status_target))

            temp_wav = extract_audio(video_path)
            if not os.path.exists(temp_wav):
                live.stop()
                console.print("[error]Failed to extract audio using ffmpeg![/error]")
                time.sleep(3)
                return

            paths = PathAuthority()
            if not confucius_py or not os.path.exists(confucius_py):
                candidate = Path("/home/valse-de-anshu/confucius-env/bin/python")
                confucius_py = str(candidate) if candidate.exists() else sys.executable

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

            cmd = [
                confucius_py,
                str(engine_script),
                "--audio", temp_wav,
                "--model_path", actual_model,
                "--backend", "transformers",
                "--device", device,
                "--max_chunk_sec", "8.0"
            ]
            if do_target and target_lang:
                cmd.extend(["--target_lang", target_lang])

            vtt_target_path = os.path.splitext(video_path)[0] + f".{target_lang}.vtt"
            vtt_orig_path = os.path.splitext(video_path)[0] + ".Original.vtt"

            f_orig = open(vtt_orig_path, "w", encoding="utf-8") if do_orig else None
            f_target = open(vtt_target_path, "w", encoding="utf-8") if do_target else None

            if f_orig:
                f_orig.write("WEBVTT\n\n")
                f_orig.flush()
            if f_target:
                f_target.write("WEBVTT\n\n")
                f_target.flush()

            log_orig = []
            log_target = []

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
                    start_str = data.get("start_str", format_timestamp(data.get("start", 0.0)))
                    end_str = data.get("end_str", format_timestamp(data.get("end", 0.0)))
                    orig_text = data.get("text", "").strip()
                    target_text = data.get("translation", "").strip()

                    if do_target and not target_text and orig_text:
                        target_text = translate_text(orig_text, target_lang, source_hint=data.get("language"))

                    if f_orig and orig_text:
                        f_orig.write(f"{start_str} --> {end_str}\n{orig_text}\n\n")
                        f_orig.flush()
                        log_orig.append(f"[{start_str} -> {end_str}] {orig_text}")
                        if len(log_orig) > 6:
                            log_orig.pop(0)
                        cur = data.get("chunk_index", "")
                        tot = data.get("total_chunks", "")
                        progress_tag = f" ({cur}/{tot})" if cur and tot else ""
                        status_orig = Panel("\n".join(log_orig), title=f"[success]Original Spoken Audio{progress_tag}[/]", border_style="success")

                    if f_target and (target_text or orig_text):
                        out_target = target_text or orig_text
                        f_target.write(f"{start_str} --> {end_str}\n{out_target}\n\n")
                        f_target.flush()
                        log_target.append(f"[{start_str} -> {end_str}] {out_target}")
                        if len(log_target) > 6:
                            log_target.pop(0)
                        status_target = Panel("\n".join(log_target), title=f"[success]{target_lang} Translation[/]", border_style="success")

                    live.update(get_renderable(status_orig, status_target))
                elif evt == "error":
                    err_msg = data.get("message", "Unknown error")
                    status_orig = Panel(f"Error: {err_msg}", title="[error]Confucius4 Error[/]", border_style="error")
                    live.update(get_renderable(status_orig, status_target))

            proc.wait()

            if f_orig: f_orig.close()
            if f_target: f_target.close()

            if do_orig: status_orig = Panel("Done.", title="[bold #9ece6a]Complete[/]", border_style="success")
            if do_target: status_target = Panel("Done.", title="[bold #9ece6a]Complete[/]", border_style="success")
            live.update(get_renderable(status_orig, status_target))

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
            gc.collect()

def generate_subtitles(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str, engine_type: str = "Auto", confucius_py: str = ""):
    if is_confucius_model(model_path, engine_type):
        generate_subtitles_confucius(video_path, model_path, languages, target_lang, vram_target, confucius_py)
    else:
        generate_subtitles_whisper(video_path, model_path, languages, target_lang, vram_target)

def run_subtitle_tui():
    paths = PathAuthority()
    storage = StorageLayer()
    config = ConfigLayer(paths, storage)
    
    startup_clear()
    print_banner()

    curr_engine = config.get("ai_subtitles_engine", "Auto")
    engine_opts = [
        ("🧠 Confucius4-R2T2 (Qwen3-ASR — High Fidelity, 30+ Langs)", "Confucius4-R2T2"),
        ("⚡ Faster-Whisper (Large-v3-Turbo — Fast Standard Whisper)", "Faster-Whisper"),
        (f"⚙️ Use Default from Settings ({curr_engine})", curr_engine)
    ]
    from core.ui import BoxSelector
    chosen_engine = BoxSelector(engine_opts, title="Select Subtitle STT Engine", width=76).select()
    if not chosen_engine or chosen_engine in ("ESC", "CTRL_C"):
        return

    engine_type = chosen_engine
    
    console.print("\n[bold #bb9af7]AI Subtitle Engine[/]")
    from core.settings_tui import prompt_field_value
    video_path = prompt_field_value("Video File Path", "", "(Enter absolute path to the video file)")
    
    if not video_path:
        return
    from core.paths import sanitize_user_path
    video_path = sanitize_user_path(video_path)
    video_path = os.path.expanduser(video_path)
        
    if not os.path.exists(video_path) and '\\ ' in video_path:
        video_path = video_path.replace('\\ ', ' ')
        
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

    sub_mode = config.get("ai_subtitles_mode", "Both")
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
    
    p = multiprocessing.Process(target=generate_subtitles, args=(video_path, model_path, langs, target_lang, vram_target, engine_type, confucius_py))
    p.start()
    
    try:
        p.join()
    except KeyboardInterrupt:
        p.kill() # Vaporize the child process instantly (SIGKILL)
        p.join()
        console.print("\n[error]Aborted by user (Ctrl+C).[/error]")
        time.sleep(1)
