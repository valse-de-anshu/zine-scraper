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

def generate_subtitles(video_path: str, model_path: str, languages: list, target_lang: str, vram_target: str):
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
    
    header = Panel(f"[bold #bb9af7]AI Transcription Engine[/] - {os.path.basename(video_path)}", border_style="menu")
    
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
                
                if do_target and translator:
                    try:
                        target_text = translator.translate(orig_text)
                    except Exception:
                        target_text = orig_text
                
                if f_orig:
                    f_orig.write(f"{start_str} --> {end_str}\n{orig_text}\n\n")
                    log_orig.append(f"[{start_str} -> {end_str}] {orig_text}")
                    if len(log_orig) > 6: log_orig.pop(0)
                    status_orig = Panel("\n".join(log_orig), title="[success]Original Audio[/]", border_style="success")
                    
                if f_target:
                    f_target.write(f"{start_str} --> {end_str}\n{target_text}\n\n")
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
            os._exit(0) # Immediately exit child process to avoid resource_tracker hooks

def run_subtitle_tui():
    paths = PathAuthority()
    storage = StorageLayer()
    config = ConfigLayer(paths, storage)
    
    startup_clear()
    print_banner()
    
    console.print("[bold #bb9af7]AI Subtitle Engine[/]")
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
        
    project_root = Path(__file__).resolve().parent.parent
    configured_path = config.get("ai_subtitles_model", "~/Models/faster-whisper-large-v3-turbo")
    model_path = os.path.expanduser(configured_path)
    if not os.path.exists(model_path):
        # Check project root Models/ directory
        local_model = project_root / "Models" / "faster-whisper-large-v3-turbo"
        if local_model.exists():
            model_path = str(local_model)
        elif (Path.home() / "Models" / "faster-whisper-large-v3-turbo").exists():
            model_path = str(Path.home() / "Models" / "faster-whisper-large-v3-turbo")

    vram_target = config.get("ai_subtitles_vram", "6GB (INT8)")
    
    if sub_mode == "None":
        console.print("[warning]Subtitles are disabled in Settings. Please enable them to run.[/warning]")
        time.sleep(2)
        return
        
    if not os.path.exists(model_path):
        console.print(f"[error]Whisper Model not found at {model_path}![/error]")
        console.print("[info]Run this command to download the model into Models/:[/info]")
        console.print("[site]python -c \"from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/faster-whisper-large-v3-turbo')\"[/site]")
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
    
    p = multiprocessing.Process(target=generate_subtitles, args=(video_path, model_path, langs, target_lang, vram_target))
    p.start()
    
    try:
        p.join()
    except KeyboardInterrupt:
        p.kill() # Vaporize the child process instantly (SIGKILL)
        p.join()
        console.print("\n[error]Aborted by user (Ctrl+C).[/error]")
        time.sleep(1)
