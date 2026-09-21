#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Confucius4-R2T2 / Qwen3-ASR Speech-to-Text Engine
Part of the Zine Scraper Suite (Models/STT/Confucius4/)

Executes Qwen3-ASR / R2T2 speech recognition with chunked silence-boundary alignment
and outputs real-time JSON-lines stream for the Zine Subtitle UI.
"""

import os
import sys
import json
import argparse
import warnings
import numpy as np

warnings.filterwarnings("ignore")
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def emit_event(event: str, **kwargs):
    payload = {"event": event, **kwargs}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()

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

def translate_segment(text: str, target_lang: str, source_hint: str = None) -> str:
    global _google_failed
    if not text or not text.strip() or not target_lang:
        return ""
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

    # Single retry for transient network hiccups
    try:
        import time
        time.sleep(0.5)
        from deep_translator import MyMemoryTranslator
        res = MyMemoryTranslator(source=source_code, target=target_code).translate(text)
        if res:
            return res
    except Exception:
        pass

    return ""

def main():
    parser = argparse.ArgumentParser(description="Confucius4-R2T2 ASR Engine")
    parser.add_argument("--audio", required=True, help="Path to 16kHz mono WAV audio file")
    parser.add_argument("--model_path", default="netease-youdao/Confucius4-R2T2", help="Model path or HF repo ID")
    parser.add_argument("--language", default=None, help="Target/spoken language hint (e.g. Japanese, Chinese, English)")
    parser.add_argument("--backend", default="transformers", choices=["transformers", "vllm"], help="Inference backend")
    parser.add_argument("--max_chunk_sec", type=float, default=8.0, help="Maximum chunk size in seconds for silence-boundary splitting")
    parser.add_argument("--device", default="cuda", help="Target hardware device")
    parser.add_argument("--gpu_utilization", type=float, default=0.5, help="vLLM GPU memory utilization fraction")
    parser.add_argument("--target_lang", default=None, help="Target translation language (e.g. English, Spanish)")
    args = parser.parse_args()

    if not os.path.exists(args.audio):
        emit_event("error", message=f"Audio file not found: {args.audio}")
        sys.exit(1)

    emit_event("status", message="Loading Confucius4-R2T2 model...")

    try:
        import torch
        import soundfile as sf
        from qwen_asr import Qwen3ASRModel
        from qwen_asr.inference.utils import split_audio_into_chunks

        model_path = os.path.expanduser(args.model_path)
        
        # Initialize ASR Model
        if args.backend == "vllm":
            emit_event("status", message=f"Initializing vLLM backend (GPU util: {args.gpu_utilization})...")
            asr = Qwen3ASRModel.LLM(
                model=model_path,
                gpu_memory_utilization=args.gpu_utilization,
                max_new_tokens=512,
            )
        else:
            emit_event("status", message="Initializing Transformers backend (bfloat16)...")
            device_map = args.device if args.device != "cpu" else "cpu"
            torch_dtype = torch.bfloat16 if (torch.cuda.is_available() and args.device != "cpu") else torch.float32
            asr = Qwen3ASRModel.from_pretrained(
                pretrained_model_name_or_path=model_path,
                device_map=device_map,
                torch_dtype=torch_dtype,
                max_new_tokens=512,
            )

        emit_event("status", message="Reading audio waveform...")
        wav, sr = sf.read(args.audio, dtype="float32")
        if wav.ndim > 1:
            wav = np.mean(wav, axis=-1).astype(np.float32)

        # Resample if needed
        if sr != 16000:
            import librosa
            wav = librosa.resample(wav, orig_sr=sr, target_sr=16000)
            sr = 16000

        total_audio_sec = len(wav) / float(sr)
        emit_event("status", message=f"Splitting {total_audio_sec:.1f}s audio at silence boundaries...")

        chunks = split_audio_into_chunks(
            wav=wav,
            sr=sr,
            max_chunk_sec=args.max_chunk_sec,
            search_expand_sec=4.0,
            min_window_ms=100.0,
        )

        total_chunks = len(chunks)
        emit_event("chunk_info", total_chunks=total_chunks, total_duration=round(total_audio_sec, 2))

        # Transcribe each chunk sequentially
        lang_arg = args.language if args.language and args.language.lower() != "none" else None
        locked_lang = lang_arg

        for idx, (chunk_wav, offset_sec) in enumerate(chunks):
            dur_sec = len(chunk_wav) / float(sr)
            # Skip chunks that are practically silent or too short
            if dur_sec < 0.3:
                continue

            try:
                results = asr.transcribe(
                    audio=[(chunk_wav, sr)],
                    language=[locked_lang] if locked_lang else None,
                    return_time_stamps=False,
                )
                if results and len(results) > 0:
                    raw_text = results[0].text or ""
                    text = raw_text.replace("|", "").strip()
                    detected_lang = results[0].language or (locked_lang or "Unknown")
                    if not locked_lang and detected_lang and detected_lang.lower() not in ["none", "unknown"]:
                        locked_lang = detected_lang
                    if text and text != "None":
                        trans_text = translate_segment(text, args.target_lang, source_hint=detected_lang) if args.target_lang else ""
                        emit_event(
                            "segment",
                            start=round(offset_sec, 3),
                            end=round(offset_sec + dur_sec, 3),
                            start_str=format_timestamp(offset_sec),
                            end_str=format_timestamp(offset_sec + dur_sec),
                            text=text,
                            translation=trans_text,
                            language=detected_lang,
                            chunk_index=idx + 1,
                            total_chunks=total_chunks,
                        )
            except Exception as seg_err:
                emit_event("warn", message=f"Chunk {idx + 1} transcription warning: {seg_err}")

            emit_event(
                "progress",
                current=idx + 1,
                total=total_chunks,
                percent=round((idx + 1) / total_chunks * 100, 1),
            )

        emit_event("done", message="Transcription complete.")

    except KeyboardInterrupt:
        emit_event("abort", message="Aborted by user.")
        sys.exit(0)
    except Exception as e:
        emit_event("error", message=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()
