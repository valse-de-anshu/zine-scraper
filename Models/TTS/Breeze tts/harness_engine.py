"""
Harness TTS Engine for Zine Scraper Suite
-----------------------------------------
Specialized JSON-driven audio synthesis harness utilizing Breeze TTS 2 (GGUF / Vulkan C++).
Designed for structured manga/manhua chapter recaps and flexible custom voiceover workflows.

Supports:
- Full chapter recap scripts (script.json)
- Lightweight 2-field JSONs:
    * List format: [{"text": "...", "direction": "..."}, ...]
    * Object format: {"segments": [{"narration_text": "...", "tts_instruction": "..."}]}
    * Parallel array format: {"narration": [...], "direction": [...]}

Features:
- Direction vs Normal Narration split: segments with direction get steered dynamically;
  segments without direction maintain steady, natural narrator delivery.
- In-line vocal tags support with automatic CFG guidance boost.
- ACX standard loudness normalization (-16 LUFS).
- Automatic generation of the master clean narration transcript (narration.txt).
- Automatic generation of full audio stitch (chapter_full.wav) and subtitles (chapter_full.srt).
- In-place patching of script.json with real audio paths and measured durations.
- Interactive TUI and headless CLI modes for humans and autonomous agents.
"""

import os
import sys
import re
import json
import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Any
from datetime import datetime

_this_file = Path(__file__).resolve()
_repo_root = _this_file.parents[3]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

# Import core Breeze TTS functions from breeze_engine
try:
    from .breeze_engine import (
        BreezeTTS,
        resolve_model_path,
        resolve_binary,
        get_voices_dir,
        list_saved_voices,
        get_wav_duration,
        format_srt_time,
        split_text_into_subtitles,
        build_srt_cues_for_segment,
        normalize_chunk_loudness,
        contains_vocal_events,
        prepare_chunk_narration_text,
        check_breeze_server_online,
        update_download_history_tts,
        _log_event,
    )
except (ImportError, ValueError):
    from breeze_engine import (
        BreezeTTS,
        resolve_model_path,
        resolve_binary,
        get_voices_dir,
        list_saved_voices,
        get_wav_duration,
        format_srt_time,
        split_text_into_subtitles,
        build_srt_cues_for_segment,
        normalize_chunk_loudness,
        contains_vocal_events,
        prepare_chunk_narration_text,
        check_breeze_server_online,
        update_download_history_tts,
        _log_event,
    )

DEFAULT_NARRATOR_INSTRUCTION = "Speak clearly and naturally as a dramatic story narrator."


def parse_harness_json(json_path: Path | str) -> dict[str, Any]:
    """
    Parses and normalizes any supported JSON format into a standardized harness structure.

    Returns:
        {
            "format_type": "recap_script" | "items_list" | "parallel_arrays" | "generic_object",
            "series": str,
            "chapter": str,
            "segments": list[dict],  # Each dict has: segment_id, narration_text, tts_instruction, original_ref
            "has_direction_count": int,
            "normal_count": int,
            "total_segments": int,
            "raw_data": dict | list,
        }
    """
    p = Path(json_path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"JSON file not found: {p}")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    series = "Audio Series"
    chapter = "1"
    format_type = "generic_object"
    segments: list[dict] = []

    # Case 1: Recap script.json format
    if isinstance(data, dict) and "segments" in data and isinstance(data["segments"], list):
        series = str(data.get("series") or data.get("series_title") or (p.parent.parent.name if p.parent.name.startswith("chapter_") else p.stem))
        chapter = str(data.get("chapter") or data.get("chapter_id") or (p.parent.name.replace("chapter_", "") if p.parent.name.startswith("chapter_") else "1"))
        format_type = "recap_script"

        for idx, item in enumerate(data["segments"], 1):
            if not isinstance(item, dict):
                continue
            seg_id = item.get("segment_id", idx)
            text = str(item.get("narration_text") or item.get("text") or item.get("narration") or "").strip()
            # Direction is only used if specified and non-empty
            dir_raw = item.get("tts_instruction") or item.get("direction") or item.get("instruction")
            dir_val = str(dir_raw).strip() if dir_raw and str(dir_raw).strip().lower() not in ("none", "null", "default") else None

            segments.append({
                "segment_id": int(seg_id) if str(seg_id).isdigit() else idx,
                "narration_text": text,
                "tts_instruction": dir_val,
                "original_ref": item,
            })

    # Case 2: Array of items format
    elif isinstance(data, list):
        format_type = "items_list"
        series = p.stem
        chapter = "1"

        for idx, item in enumerate(data, 1):
            if isinstance(item, dict):
                text = str(item.get("narration_text") or item.get("text") or item.get("narration") or "").strip()
                dir_raw = item.get("tts_instruction") or item.get("direction") or item.get("instruction")
                dir_val = str(dir_raw).strip() if dir_raw and str(dir_raw).strip().lower() not in ("none", "null", "default") else None
            elif isinstance(item, str):
                text = item.strip()
                dir_val = None
            else:
                continue

            segments.append({
                "segment_id": idx,
                "narration_text": text,
                "tts_instruction": dir_val,
                "original_ref": item if isinstance(item, dict) else None,
            })

    # Case 3: Parallel arrays format: {"narration": [...], "direction": [...]} or {"texts": [...], "directions": [...]}
    elif isinstance(data, dict):
        text_array = None
        for k in ["narration", "texts", "text", "narration_text", "lines", "sentences"]:
            if k in data and isinstance(data[k], list):
                text_array = data[k]
                break

        dir_array = None
        for k in ["direction", "directions", "instructions", "tts_instruction", "voice_direction"]:
            if k in data and isinstance(data[k], list):
                dir_array = data[k]
                break

        if text_array is not None:
            format_type = "parallel_arrays"
            series = str(data.get("series", p.stem))
            chapter = str(data.get("chapter", "1"))

            for idx, text_item in enumerate(text_array, 1):
                text = str(text_item).strip()
                dir_val = None
                if dir_array and idx - 1 < len(dir_array):
                    raw_d = dir_array[idx - 1]
                    if raw_d and str(raw_d).strip().lower() not in ("none", "null", "default"):
                        dir_val = str(raw_d).strip()

                segments.append({
                    "segment_id": idx,
                    "narration_text": text,
                    "tts_instruction": dir_val,
                    "original_ref": None,
                })

    if not segments:
        raise ValueError(f"No valid narration segments found in JSON: {p}")

    has_direction_count = sum(1 for s in segments if s["tts_instruction"])
    normal_count = len(segments) - has_direction_count

    return {
        "format_type": format_type,
        "series": series,
        "chapter": chapter,
        "segments": segments,
        "has_direction_count": has_direction_count,
        "normal_count": normal_count,
        "total_segments": len(segments),
        "raw_data": data,
        "json_path": p,
    }


def write_clean_narration_transcript(segments: list[dict], transcript_path: Path) -> Path:
    """
    Writes or updates the clean master narration transcript (narration.txt).
    One paragraph per segment, separated by double newlines.
    """
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    paragraphs = [s["narration_text"] for s in segments if s.get("narration_text")]
    content = "\n\n".join(paragraphs).strip() + "\n"

    tmp = transcript_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    tmp.replace(transcript_path)
    return transcript_path


def render_harness_json(
    json_path: Path | str,
    voice_name: Optional[str] = None,
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    output_dir: Optional[Path | str] = None,
    use_cpu: Optional[bool] = None,
    force: bool = False,
    console=None,
    headless: bool = False,
) -> dict[str, Any]:
    """
    Renders any structured harness JSON file into segment audio, full audio stitch,
    synchronized subtitles, and master narration transcript.
    """
    from rich.console import Console
    from core.ui import custom_theme
    from core.settings_tui import config

    if console is None:
        console = Console(theme=custom_theme)

    json_file = Path(json_path).expanduser().resolve()
    parsed = parse_harness_json(json_file)

    series = parsed["series"]
    chapter = parsed["chapter"]
    segments = parsed["segments"]
    total_segments = parsed["total_segments"]
    has_dir = parsed["has_direction_count"]
    normal_dir = parsed["normal_count"]

    # Resolve directories
    if output_dir:
        audio_dir = Path(output_dir).expanduser().resolve()
    else:
        audio_dir = json_file.parent / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    segments_dir = audio_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    # Load segment content-hash cache index
    cache_index_file = segments_dir / ".cache_index.json"
    cache_index: dict[str, str] = {}
    if not force and cache_index_file.exists():
        try:
            with open(cache_index_file, "r", encoding="utf-8") as f:
                cache_index = json.load(f)
        except Exception:
            cache_index = {}

    # Automatically form the master narration.txt transcript file
    transcript_file = json_file.parent / "narration.txt"
    try:
        write_clean_narration_transcript(segments, transcript_file)
        if not headless:
            console.print(f"[bold green]✓ Master transcript generated:[/bold green] [dim]{transcript_file}[/dim]")
    except Exception as e:
        _log_event("TRANSCRIPT_GEN_ERROR", {"error": str(e)})

    # Determine relative audio prefix
    if json_file.parent.name.startswith("chapter_"):
        rel_prefix = f"chapters/{json_file.parent.name}/audio/segments"
    else:
        rel_prefix = "audio/segments"

    # Resolve voice profile and model parameters
    active_voice = voice_name or config.get("breeze_saved_voice", "seductive_director") or "seductive_director"
    # Fallback to seductive_director if voice doesn't exist
    voices_available = [v.get("name") or v.get("id") for v in list_saved_voices() if v.get("name") or v.get("id")]
    if active_voice not in voices_available:
        if "seductive_director" in voices_available:
            active_voice = "seductive_director"
        elif "narrator" in voices_available:
            active_voice = "narrator"
        elif voices_available:
            active_voice = voices_available[0]

    base_cfg = cfg_scale if cfg_scale is not None else float(config.get("breeze_cfg_scale", 1.5))
    active_seed = seed if seed is not None else int(config.get("breeze_seed", 42))
    split_chars = int(config.get("breeze_split_chars", 600))
    hardware = config.get("breeze_hardware", "Vulkan (GPU)")
    effective_use_cpu = use_cpu if use_cpu is not None else ("CPU" in hardware)
    server_url = config.get("breeze_server_url", "http://127.0.0.1:8080")

    console.print(f"\n[bold sexy_pink]🌬️ Harness TTS — Structured JSON Audio Engine[/bold sexy_pink]")
    console.print(f"[bold white]Target:[/bold white] {json_file.name} ([dim]{series} — Chapter {chapter}[/dim])")
    console.print(f"[dim]Total Segments: {total_segments} | Directed: {has_dir} | Normal: {normal_dir} | Voice: {active_voice} | Base CFG: {base_cfg}[/dim]\n")

    rendered_count = 0
    skipped_count = 0
    failed_count = 0
    segment_wavs: list[Path] = []
    srt_entries: list[tuple[int, str, str, str]] = []
    accumulated_time = 0.0

    # Render loop
    for idx, seg in enumerate(segments, 1):
        seg_id = seg["segment_id"]
        narration = seg["narration_text"]
        direction = seg["tts_instruction"]
        is_directed = bool(direction)

        # Normal narration uses default delivery; directed segments use custom instruction
        effective_instruction = direction if is_directed else DEFAULT_NARRATOR_INSTRUCTION

        seg_filename = f"segment_{int(seg_id):03d}.wav"
        seg_wav = segments_dir / seg_filename
        rel_wav_path = f"{rel_prefix}/{seg_filename}"

        if not narration:
            continue

        # Compute deterministic content hash for this segment
        content_sig = f"{narration}|{effective_instruction}|{active_voice}"
        content_hash = hashlib.sha256(content_sig.encode("utf-8")).hexdigest()[:16]

        # Smart Cache: Check both file presence and matching content hash
        cached_hash = cache_index.get(str(seg_id))
        is_cached = (
            not force
            and seg_wav.exists()
            and seg_wav.stat().st_size > 500
            and cached_hash == content_hash
        )

        if is_cached:
            skipped_count += 1
            real_dur = get_wav_duration(str(seg_wav))
            if seg["original_ref"] and isinstance(seg["original_ref"], dict):
                seg["original_ref"]["audio_file"] = rel_wav_path
                seg["original_ref"]["duration_seconds"] = round(real_dur, 2)
                seg["original_ref"]["estimated_duration_seconds"] = round(real_dur, 2)
            segment_wavs.append(seg_wav)
            console.print(f"  [dim]Segment {seg_id:03d}/{total_segments:03d}: cached ({real_dur:.2f}s)[/dim]")
        else:
            has_vocal = contains_vocal_events(narration)
            seg_cfg = min(max(base_cfg, 1.5), 1.7) if has_vocal else base_cfg
            speech_text = prepare_chunk_narration_text(narration)

            dir_badge = f"[bold yellow]⚡ Directed[/bold yellow]" if is_directed else "[dim]Normal[/dim]"
            tag_badge = f"[magenta]+Tags[/magenta]" if has_vocal else ""
            console.print(f"  [bold cyan]● Segment {seg_id:03d}/{total_segments:03d}:[/bold cyan] rendering... {dir_badge} {tag_badge}")

            success = False
            # 1. Direct CLI
            try:
                success = BreezeTTS.generate_chunk_cli(
                    text=speech_text,
                    output_wav=str(seg_wav),
                    instruction=effective_instruction,
                    mode="Saved Voice",
                    saved_voice=active_voice,
                    cfg_scale=seg_cfg,
                    seed=active_seed,
                    split_chars=split_chars,
                    use_cpu=effective_use_cpu,
                )
            except Exception as e:
                _log_event("HARNESS_CLI_FAIL", {"seg": seg_id, "error": str(e)})

            # 2. HTTP fallback
            if not success and check_breeze_server_online(server_url):
                try:
                    success = BreezeTTS.generate_chunk_http(
                        text=speech_text,
                        output_wav=str(seg_wav),
                        server_url=server_url,
                        instruction=effective_instruction,
                        mode="Saved Voice",
                        saved_voice=active_voice,
                        cfg_scale=seg_cfg,
                        seed=active_seed,
                        split_chars=split_chars,
                    )
                except Exception as e:
                    _log_event("HARNESS_HTTP_FAIL", {"seg": seg_id, "error": str(e)})

            if success and seg_wav.exists() and seg_wav.stat().st_size > 100:
                # ACX standard loudness normalization (-16 LUFS) with 15ms micro-fade
                normalize_chunk_loudness(seg_wav, seg_wav)
                real_dur = get_wav_duration(str(seg_wav))
                if seg["original_ref"] and isinstance(seg["original_ref"], dict):
                    seg["original_ref"]["audio_file"] = rel_wav_path
                    seg["original_ref"]["duration_seconds"] = round(real_dur, 2)
                    seg["original_ref"]["estimated_duration_seconds"] = round(real_dur, 2)
                cache_index[str(seg_id)] = content_hash
                segment_wavs.append(seg_wav)
                rendered_count += 1
                console.print(f"    [bold green]✓[/bold green] {real_dur:.2f}s → [dim]{seg_filename}[/dim]")
            else:
                failed_count += 1
                cache_index.pop(str(seg_id), None)
                console.print(f"    [bold red]✗ Failed to render segment {seg_id}[/bold red]")

        if seg_wav.exists() and seg_wav.stat().st_size > 100:
            dur = get_wav_duration(str(seg_wav))
            # Split segment narration into natural, short subtitle cues synchronized to the audio
            seg_cues = build_srt_cues_for_segment(
                narration=narration,
                seg_start=accumulated_time,
                seg_dur=dur,
                start_idx=len(srt_entries) + 1,
            )
            accumulated_time += dur + 0.25 # 250ms natural breathing pause
            srt_entries.extend(seg_cues)

    # Save segment content-hash cache index
    try:
        with open(cache_index_file, "w", encoding="utf-8") as f:
            json.dump(cache_index, f, indent=2)
    except Exception as e:
        _log_event("CACHE_INDEX_SAVE_ERROR", {"error": str(e)})

    # Stitch full audio & subtitles
    full_wav = audio_dir / "chapter_full.wav"
    full_srt = audio_dir / "chapter_full.srt"

    if segment_wavs:
        console.print(f"\n[bold cyan]● Stitching {len(segment_wavs)} segments with natural breathing pauses → chapter_full.wav...[/bold cyan]")
        concat_list = audio_dir / ".concat_list.txt"
        silence_wav = audio_dir / ".silence_250ms.wav"
        try:
            # Generate 250ms natural breathing silence block
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", "0.25", "-acodec", "pcm_s16le", str(silence_wav)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            with open(concat_list, "w", encoding="utf-8") as cf:
                for idx_w, w in enumerate(segment_wavs):
                    cf.write(f"file '{w.resolve()}'\n")
                    if idx_w < len(segment_wavs) - 1 and silence_wav.exists():
                        cf.write(f"file '{silence_wav.resolve()}'\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-acodec", "pcm_s16le", str(full_wav)]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if concat_list.exists():
                concat_list.unlink()
            if silence_wav.exists():
                silence_wav.unlink()

            if res.returncode == 0 and full_wav.exists():
                normalize_chunk_loudness(full_wav, full_wav, micro_fade=False)
                full_dur = get_wav_duration(str(full_wav))
                console.print(f"[bold green]✓ Full audio master generated:[/bold green] {full_wav} ({full_dur:.1f}s)")
            else:
                console.print(f"[bold yellow]⚠ Concat failed: {res.stderr.decode('utf-8', errors='replace')[:200]}[/bold yellow]")
        except Exception as e:
            console.print(f"[bold yellow]⚠ Stitch exception: {e}[/bold yellow]")
            if concat_list.exists():
                try: concat_list.unlink()
                except: pass

        # Generate synchronized SRT subtitles
        try:
            with open(full_srt, "w", encoding="utf-8") as sf:
                for srt_idx, start_s, end_s, text in srt_entries:
                    sf.write(f"{srt_idx}\n{start_s} --> {end_s}\n{text}\n\n")
            console.print(f"[bold green]✓ Synced subtitles generated:[/bold green] {full_srt}")
        except Exception as e:
            _log_event("SRT_SAVE_ERROR", {"error": str(e)})

    # Patch original script.json in-place if applicable
    if parsed["format_type"] == "recap_script" and isinstance(parsed["raw_data"], dict):
        try:
            tmp_script = json_file.with_suffix(".tmp")
            with open(tmp_script, "w", encoding="utf-8") as f:
                json.dump(parsed["raw_data"], f, indent=2, ensure_ascii=False)
            tmp_script.replace(json_file)
            console.print(f"[bold green]✓ script.json patched with real audio paths & measured durations[/bold green]")
        except Exception as e:
            console.print(f"[bold red]● Failed to update script.json: {e}[/bold red]")

    # Update Download History
    try:
        update_download_history_tts(
            stem=f"{series}_Chapter_{chapter}",
            source_file=str(json_file),
            audio_file=str(full_wav if full_wav.exists() else audio_dir),
            srt_file=str(full_srt if full_srt.exists() else ""),
            script_file=str(json_file),
            temp_voice_dir=str(audio_dir),
            voice=active_voice,
            chunks_count=rendered_count + skipped_count,
            duration_seconds=accumulated_time,
        )
    except Exception:
        pass

    result = {
        "status": "ok" if failed_count == 0 else "partial",
        "series": series,
        "chapter": chapter,
        "total_segments": total_segments,
        "rendered": rendered_count,
        "cached": skipped_count,
        "failed": failed_count,
        "duration_seconds": round(accumulated_time, 2),
        "transcript_file": str(transcript_file),
        "audio_dir": str(audio_dir),
        "full_audio": str(full_wav) if full_wav.exists() else None,
        "full_srt": str(full_srt) if full_srt.exists() else None,
        "json_path": str(json_file),
    }

    console.print(f"\n[bold green]● Harness Render Complete![/bold green] Total Duration: {accumulated_time:.1f}s ({rendered_count} rendered, {skipped_count} cached, {failed_count} failed)")
    return result


def natural_chapter_sort_key(p: Path) -> tuple:
    """Natural numerical sort key for chapter paths like chapter_1, chapter_2, chapter_10."""
    ch_name = p.parent.name
    nums = re.findall(r'\d+(?:\.\d+)?', ch_name)
    if nums:
        try:
            return (0, float(nums[0]), p.name)
        except ValueError:
            pass
    return (1, 0, str(p))


def _extract_series_name_from_path(sp: Path) -> str:
    """Extracts human-readable series name from a script.json path."""
    ch_name = sp.parent.name
    series_cand = "Series"
    for part in reversed(sp.parts):
        if part not in ("script.json", ch_name, "chapters", "recap", ".zine"):
            series_cand = part
            break
    return series_cand


def discover_all_recap_chapters() -> dict[str, list[Path]]:
    """
    Discovers all recap chapters in library and groups them by series title.
    Returns: {series_name: [Path(chapter_1/script.json), Path(chapter_2/script.json), ...]}
    Each list is naturally sorted by chapter number.
    """
    from core.paths import PathAuthority
    paths_auth = PathAuthority()
    scan_roots = [
        paths_auth.get_downloads_root() / "Vacuum",
        paths_auth.get_downloads_root(),
        Path.home() / "Downloads" / "Zine" / "Vacuum",
        Path.home() / "Downloads" / "Zine",
    ]
    seen_set = set()
    series_map: dict[str, list[Path]] = {}

    for r in scan_roots:
        if not r.exists():
            continue
        for s in r.glob("**/.zine/recap/chapters/*/script.json"):
            res_p = s.resolve()
            if res_p not in seen_set:
                seen_set.add(res_p)
                series_name = _extract_series_name_from_path(res_p)
                series_map.setdefault(series_name, []).append(res_p)
        for s in r.glob("**/script.json"):
            res_p = s.resolve()
            if res_p not in seen_set and ".zine" in str(res_p):
                seen_set.add(res_p)
                series_name = _extract_series_name_from_path(res_p)
                series_map.setdefault(series_name, []).append(res_p)

    for s_name in series_map:
        series_map[s_name].sort(key=natural_chapter_sort_key)

    return series_map


def parse_queue_file(queue_path: Path | str) -> list[Path]:
    """
    Parses a text queue file (e.g. queue.txt) containing paths to script.json or chapter folders.
    Lines starting with # or empty lines are ignored.
    """
    from core.paths import sanitize_user_path
    qp = Path(queue_path).expanduser().resolve()
    if not qp.exists() or not qp.is_file():
        raise FileNotFoundError(f"Queue file not found: {qp}")

    resolved_targets: list[Path] = []
    with open(qp, "r", encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue
            clean_str = sanitize_user_path(line_str)
            cand = Path(clean_str).expanduser().resolve()
            if cand.is_file() and cand.suffix.lower() == ".json":
                resolved_targets.append(cand)
            elif cand.is_dir():
                if (cand / "script.json").exists():
                    resolved_targets.append(cand / "script.json")
                else:
                    scripts = sorted(cand.rglob("script.json"), key=natural_chapter_sort_key)
                    if scripts:
                        resolved_targets.extend(scripts)
                    else:
                        jsons = sorted(cand.glob("*.json"))
                        if jsons:
                            resolved_targets.extend(jsons)
    return resolved_targets


def render_harness_queue(
    queue_targets: list[Path],
    voice_name: Optional[str] = None,
    cfg_scale: Optional[float] = None,
    seed: Optional[int] = None,
    output_dir: Optional[Path | str] = None,
    use_cpu: Optional[bool] = None,
    force: bool = False,
    console=None,
    headless: bool = False,
) -> list[dict[str, Any]]:
    """
    Executes Harness TTS sequentially across an ordered queue of JSON targets.
    Automatically advances to the next chapter upon completion.
    """
    from rich.console import Console
    from core.ui import custom_theme

    if console is None:
        console = Console(theme=custom_theme)

    total_items = len(queue_targets)
    results = []

    console.print(f"\n[bold sexy_pink]🚀 Launching Harness Queue — {total_items} Chapter Target{'s' if total_items != 1 else ''}[/bold sexy_pink]\n")

    for idx, target in enumerate(queue_targets, 1):
        ch_label = target.parent.name.replace("_", " ").title() if target.parent.name.startswith("chapter_") else target.stem
        series_label = _extract_series_name_from_path(target)

        console.print(f"[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
        console.print(f"[bold white]● Queue [{idx}/{total_items}]:[/bold white] [bold sexy_pink]{series_label}[/bold sexy_pink] — [bold yellow]{ch_label}[/bold yellow] ([dim]{target.name}[/dim])")
        console.print(f"[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n")

        try:
            res = render_harness_json(
                json_path=target,
                voice_name=voice_name,
                cfg_scale=cfg_scale,
                seed=seed,
                output_dir=output_dir,
                use_cpu=use_cpu,
                force=force,
                console=console,
                headless=headless,
            )
            results.append({"target": str(target), "status": "success", "result": res})
            console.print(f"\n[bold green]✓ Queue [{idx}/{total_items}] finished {ch_label}![/bold green] Advancing to next chapter...\n")
        except KeyboardInterrupt:
            console.print(f"\n[bold yellow]⚠ Queue execution stopped by user at item {idx}/{total_items}.[/bold yellow]")
            break
        except Exception as e:
            console.print(f"\n[bold red]✗ Failed to process {target}: {e}[/bold red]\n")
            results.append({"target": str(target), "status": "error", "error": str(e)})

    console.print(f"[bold green]🎉 Harness Queue Execution Complete: {len(results)}/{total_items} items processed.[/bold green]\n")
    return results


def run_harness_tui() -> None:
    """Interactive TUI for Harness TTS."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.box import ROUNDED, SIMPLE
    from core.ui import custom_theme, startup_clear, print_banner, BoxSelector, MultiSelector, prompt_return
    from core.settings_tui import prompt_field_value, config
    from core.paths import sanitize_user_path

    console = Console(theme=custom_theme)

    while True:
        startup_clear()
        print_banner()

        console.print(Panel(
            "[bold white]Structured JSON Voice Harness Hub[/bold white]\n"
            "[dim]Render chapter recaps and custom JSON voiceovers with selective voice direction & multi-file queues.[/dim]",
            title="[bold sexy_pink]🌬️ Harness TTS[/bold sexy_pink]",
            box=ROUNDED,
            border_style="magenta",
        ))

        options = [
            ("📚 Auto-Scan & Select Chapter", "browse"),
            ("📋 Queue Entire Series (Sequential Batch)", "queue_series"),
            ("☑️  Multi-Select Chapters to Queue", "queue_multi"),
            ("📄 Load Queue from File (queue.txt)", "queue_file"),
            ("📁 Drag-and-Drop / Enter Custom Path", "file"),
            ("🎙️  Select Default Voice Profile", "voice"),
            ("↩️  Return to Main Menu", "exit"),
        ]

        choice = BoxSelector(options, title="Harness Actions", width=86).select()
        if not choice or choice in ("exit", "ESC", "CTRL_C"):
            break

        if choice == "voice":
            voices = list_saved_voices()
            if not voices:
                console.print("[bold yellow]No saved voices found in voices/ directory.[/bold yellow]")
                prompt_return("Press Enter to return...")
                continue
            v_opts = [(f"🎙️ {v.get('name') or v.get('id')} — {str(v.get('ref_text') or v.get('text', ''))[:45]}...", v.get('name') or v.get('id')) for v in voices if v.get('name') or v.get('id')]
            v_opts.append(("↩️ Back", "back"))
            sel_v = BoxSelector(v_opts, title="Choose Harness Voice Profile", width=86).select()
            if sel_v and sel_v != "back":
                config["breeze_saved_voice"] = sel_v
                from core.settings_tui import save_settings
                save_settings()
                console.print(f"[bold green]✓ Default harness voice set to: {sel_v}[/bold green]")
                prompt_return("Press Enter to return...")
            continue

        elif choice == "browse":
            series_map = discover_all_recap_chapters()
            if not series_map:
                console.print("\n[bold yellow]No chapter recap scripts found in library.[/bold yellow]")
                console.print("[dim]Create recap scripts via /manhua-recap or choose 'Drag-and-Drop' to supply a custom path.[/dim]\n")
                prompt_return("Press Enter to return...")
                continue

            browse_opts = []
            for s_name, chs in sorted(series_map.items()):
                for sp in chs:
                    ch_name = sp.parent.name
                    label = f"📖 {s_name} — {ch_name.replace('_', ' ').title()}"
                    browse_opts.append((label, str(sp)))
            browse_opts.append(("↩️ Back", "back"))

            sel_script = BoxSelector(browse_opts, title="Select Recap Chapter", width=86).select()
            if not sel_script or sel_script == "back":
                continue

            target_json = Path(sel_script)
            try:
                parsed = parse_harness_json(target_json)
            except Exception as e:
                console.print(f"\n[bold red]● Failed to parse JSON file:[/bold red] {e}")
                prompt_return("Press Enter to return...")
                continue

            # Preview Card
            startup_clear()
            print_banner()
            t = Table(box=SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("Key", style="bold cyan")
            t.add_column("Value", style="bold white")
            t.add_row("File", target_json.name)
            t.add_row("Detected Format", parsed["format_type"])
            t.add_row("Series / Chapter", f"{parsed['series']} — Chapter {parsed['chapter']}")
            t.add_row("Total Segments", str(parsed["total_segments"]))
            t.add_row("Directed Segments (⚡)", f"[yellow]{parsed['has_direction_count']}[/yellow]")
            t.add_row("Normal Segments", f"[green]{parsed['normal_count']}[/green]")
            t.add_row("Active Voice", config.get("breeze_saved_voice", "seductive_director"))
            console.print(Panel(t, title="[bold sexy_pink]Harness Plan Overview[/bold sexy_pink]", box=ROUNDED, border_style="magenta"))

            confirm_opts = [
                ("🚀 Start Audio Generation", "run"),
                ("↩️  Cancel", "cancel"),
            ]
            act = BoxSelector(confirm_opts, title="Confirm Execution", width=86).select()
            if act == "run":
                render_harness_json(target_json, console=console, headless=False)
                prompt_return("\n[bold green]Rendering Finished![/bold green] Press Enter to return to menu...")
            continue

        elif choice == "queue_series":
            series_map = discover_all_recap_chapters()
            if not series_map:
                console.print("\n[bold yellow]No chapter recap scripts found in library.[/bold yellow]")
                prompt_return("Press Enter to return...")
                continue

            series_opts = [(f"📖 {s_name} ({len(chs)} chapters)", s_name) for s_name, chs in sorted(series_map.items())]
            series_opts.append(("↩️ Back", "back"))

            sel_s = BoxSelector(series_opts, title="Select Series to Queue", width=86).select()
            if not sel_s or sel_s == "back":
                continue

            queue_targets = series_map[sel_s]
            startup_clear()
            print_banner()
            t = Table(box=SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("Key", style="bold cyan")
            t.add_column("Value", style="bold white")
            t.add_row("Queued Series", sel_s)
            t.add_row("Total Chapters", str(len(queue_targets)))
            t.add_row("Chapter Range", f"{queue_targets[0].parent.name} → {queue_targets[-1].parent.name}")
            t.add_row("Active Voice", config.get("breeze_saved_voice", "seductive_director"))
            console.print(Panel(t, title="[bold sexy_pink]Series Queue Plan Overview[/bold sexy_pink]", box=ROUNDED, border_style="magenta"))

            confirm_opts = [
                (f"🚀 Start Sequential Queue ({len(queue_targets)} Chapters)", "run"),
                ("↩️  Cancel", "cancel"),
            ]
            act = BoxSelector(confirm_opts, title="Confirm Queue Execution", width=86).select()
            if act == "run":
                render_harness_queue(queue_targets, console=console, headless=False)
                prompt_return("\n[bold green]Queue Finished![/bold green] Press Enter to return to menu...")
            continue

        elif choice == "queue_multi":
            series_map = discover_all_recap_chapters()
            if not series_map:
                console.print("\n[bold yellow]No chapter recap scripts found in library.[/bold yellow]")
                prompt_return("Press Enter to return...")
                continue

            series_opts = [(f"📖 {s_name} ({len(chs)} chapters)", s_name) for s_name, chs in sorted(series_map.items())]
            series_opts.append(("↩️ Back", "back"))

            sel_s = BoxSelector(series_opts, title="Select Series to Pick Chapters", width=86).select()
            if not sel_s or sel_s == "back":
                continue

            ch_items = [
                {"name": f"📖 {ch.parent.name.replace('_', ' ').title()}", "value": str(ch), "size_bytes": 0}
                for ch in series_map[sel_s]
            ]
            selected = MultiSelector(ch_items, title=f"Select Chapters for {sel_s}").select()
            if not selected:
                continue

            queue_targets = [Path(item["value"]) for item in selected]
            queue_targets.sort(key=natural_chapter_sort_key)

            startup_clear()
            print_banner()
            t = Table(box=SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("Key", style="bold cyan")
            t.add_column("Value", style="bold white")
            t.add_row("Selected Series", sel_s)
            t.add_row("Selected Chapters", str(len(queue_targets)))
            t.add_row("Active Voice", config.get("breeze_saved_voice", "seductive_director"))
            console.print(Panel(t, title="[bold sexy_pink]Multi-Chapter Queue Overview[/bold sexy_pink]", box=ROUNDED, border_style="magenta"))

            confirm_opts = [
                (f"🚀 Start Sequential Queue ({len(queue_targets)} Chapters)", "run"),
                ("↩️  Cancel", "cancel"),
            ]
            act = BoxSelector(confirm_opts, title="Confirm Queue Execution", width=86).select()
            if act == "run":
                render_harness_queue(queue_targets, console=console, headless=False)
                prompt_return("\n[bold green]Queue Finished![/bold green] Press Enter to return to menu...")
            continue

        elif choice == "queue_file":
            val = prompt_field_value("Queue File Path", "", "(Drag & drop queue.txt or custom file here)")
            if not val or val == "ESC":
                continue

            clean_str = sanitize_user_path(val)
            cand = Path(clean_str).expanduser().resolve()
            try:
                queue_targets = parse_queue_file(cand)
            except Exception as e:
                console.print(f"\n[bold red]● Failed to load queue file:[/bold red] {e}")
                prompt_return("Press Enter to return...")
                continue

            if not queue_targets:
                console.print("\n[bold yellow]No valid JSON paths found in queue file.[/bold yellow]")
                prompt_return("Press Enter to return...")
                continue

            startup_clear()
            print_banner()
            t = Table(box=SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("Key", style="bold cyan")
            t.add_column("Value", style="bold white")
            t.add_row("Queue File", cand.name)
            t.add_row("Total Queued Targets", str(len(queue_targets)))
            t.add_row("Active Voice", config.get("breeze_saved_voice", "seductive_director"))
            console.print(Panel(t, title="[bold sexy_pink]File Queue Overview[/bold sexy_pink]", box=ROUNDED, border_style="magenta"))

            confirm_opts = [
                (f"🚀 Start Sequential Queue ({len(queue_targets)} Chapters)", "run"),
                ("↩️  Cancel", "cancel"),
            ]
            act = BoxSelector(confirm_opts, title="Confirm Queue Execution", width=86).select()
            if act == "run":
                render_harness_queue(queue_targets, console=console, headless=False)
                prompt_return("\n[bold green]Queue Finished![/bold green] Press Enter to return to menu...")
            continue

        elif choice == "file":
            val = prompt_field_value("JSON or Queue File Path", "", "(Drag & drop script.json, queue.txt, or chapter directory)")
            if not val or val == "ESC":
                continue

            clean_str = sanitize_user_path(val)
            cand = Path(clean_str).expanduser().resolve()

            if cand.is_file() and cand.suffix.lower() == ".txt":
                try:
                    queue_targets = parse_queue_file(cand)
                    if queue_targets:
                        render_harness_queue(queue_targets, console=console, headless=False)
                        prompt_return("\n[bold green]Queue Finished![/bold green] Press Enter to return to menu...")
                        continue
                except Exception as e:
                    console.print(f"[bold red]Failed to load queue file: {e}[/bold red]")
                    prompt_return("Press Enter to return...")
                    continue

            target_json: Optional[Path] = None
            if cand.is_dir():
                scripts = sorted(cand.rglob("script.json"), key=natural_chapter_sort_key)
                if len(scripts) > 1:
                    conf = [
                        (f"📋 Queue All {len(scripts)} Chapters in Folder", "all"),
                        ("📖 Choose Single Chapter", "pick"),
                        ("↩️ Cancel", "cancel"),
                    ]
                    act = BoxSelector(conf, title="Folder Detected", width=86).select()
                    if act == "all":
                        render_harness_queue(scripts, console=console, headless=False)
                        prompt_return("\n[bold green]Queue Finished![/bold green] Press Enter to return to menu...")
                        continue
                    elif act == "pick":
                        opts = [(f"📖 {s.parent.name.replace('_', ' ').title()}", str(s)) for s in scripts]
                        picked = BoxSelector(opts, title="Select Chapter", width=86).select()
                        if picked and picked != "cancel":
                            target_json = Path(picked)
                        else:
                            continue
                    else:
                        continue
                elif len(scripts) == 1:
                    target_json = scripts[0]
                else:
                    target_json = cand
            else:
                target_json = cand

            if not target_json or not target_json.exists():
                console.print(f"\n[bold red]● Invalid or missing file:[/bold red] [yellow]{target_json or 'None'}[/yellow]")
                prompt_return("Press Enter to return...")
                continue

            try:
                parsed = parse_harness_json(target_json)
            except Exception as e:
                console.print(f"\n[bold red]● Failed to parse JSON file:[/bold red] {e}")
                prompt_return("Press Enter to return...")
                continue

            # Preview Card
            startup_clear()
            print_banner()
            t = Table(box=SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("Key", style="bold cyan")
            t.add_column("Value", style="bold white")
            t.add_row("File", target_json.name)
            t.add_row("Detected Format", parsed["format_type"])
            t.add_row("Series / Chapter", f"{parsed['series']} — Chapter {parsed['chapter']}")
            t.add_row("Total Segments", str(parsed["total_segments"]))
            t.add_row("Directed Segments (⚡)", f"[yellow]{parsed['has_direction_count']}[/yellow]")
            t.add_row("Normal Segments", f"[green]{parsed['normal_count']}[/green]")
            t.add_row("Active Voice", config.get("breeze_saved_voice", "seductive_director"))
            console.print(Panel(t, title="[bold sexy_pink]Harness Plan Overview[/bold sexy_pink]", box=ROUNDED, border_style="magenta"))

            confirm_opts = [
                ("🚀 Start Audio Generation (Smart Cache)", "run"),
                ("🔄 Force Fresh Re-render All Segments (Bypass Cache)", "force_run"),
                ("↩️  Cancel", "cancel"),
            ]
            act = BoxSelector(confirm_opts, title="Confirm Execution", width=86).select()
            if act == "run":
                render_harness_json(target_json, console=console, headless=False, force=False)
                prompt_return("\n[bold green]Rendering Finished![/bold green] Press Enter to return to menu...")
            elif act == "force_run":
                render_harness_json(target_json, console=console, headless=False, force=True)
                prompt_return("\n[bold green]Rendering Finished![/bold green] Press Enter to return to menu...")


def run_harness_cli(argv: list[str]) -> None:
    """CLI Entrypoint for Harness TTS."""
    from rich.console import Console
    from core.ui import custom_theme

    console = Console(theme=custom_theme)

    if not argv:
        run_harness_tui()
        return

    if argv[0] in ["--help", "-h", "-?", "help", "--h"]:
        console.print("[bold sexy_pink]Zine Scraper — Harness TTS (JSON-Driven Audio Hub & Multi-Chapter Queue)[/bold sexy_pink]\n")
        console.print("[bold white]Usage:[/bold white]")
        console.print("  [cyan]python3 orchestrator.py harness-tts[/cyan] [dim][target(s) | queue.txt | directory][/dim] [flags]\n")
        console.print("[bold white]Flags:[/bold white]")
        console.print("  [green]--voice <name>[/green]       Saved voice profile to use (default: seductive_director)")
        console.print("  [green]--queue <file.txt>[/green]    Load queue from text file (one path per line)")
        console.print("  [green]--cfg-scale <float>[/green]  Classifier-free guidance strength (default: 1.5)")
        console.print("  [green]--seed <int>[/green]          RNG seed (default: 42)")
        console.print("  [green]--output <dir>[/green]        Custom audio output directory")
        console.print("  [green]--force, -f[/green]           Force fresh re-render of all segments (bypass cache)")
        console.print("  [green]--cpu[/green]                 Force CPU synthesis (bypasses GPU/Vulkan)\n")
        console.print("[bold white]Queue & Batch Examples:[/bold white]")
        console.print("  [cyan]zine harness-tts chapter_1/script.json --force[/cyan]")
        console.print("  [cyan]zine harness-tts chapter_1/script.json chapter_2/script.json[/cyan]")
        console.print("  [cyan]zine harness-tts queue.txt[/cyan]")
        console.print("  [cyan]zine harness-tts \"Downloads/Zine/Vacuum/AsuraScans/The World After The End\"[/cyan]\n")
        return

    # Parse arguments
    voice_name: Optional[str] = None
    cfg_scale: Optional[float] = None
    seed: Optional[int] = None
    output_dir: Optional[str] = None
    use_cpu: Optional[bool] = None
    force: bool = False
    targets: list[Path] = []

    i = 0
    while i < len(argv):
        arg = argv[i].strip()
        if arg == "--voice" and i + 1 < len(argv):
            voice_name = argv[i + 1].strip()
            i += 2
        elif arg in ("--queue", "-q", "--batch") and i + 1 < len(argv):
            try:
                targets.extend(parse_queue_file(argv[i + 1].strip()))
            except Exception as e:
                console.print(f"[bold red]Failed to load queue file: {e}[/bold red]")
            i += 2
        elif arg == "--cfg-scale" and i + 1 < len(argv):
            try: cfg_scale = float(argv[i + 1].strip())
            except: pass
            i += 2
        elif arg == "--seed" and i + 1 < len(argv):
            try: seed = int(argv[i + 1].strip())
            except: pass
            i += 2
        elif arg in ("--output", "--output-dir") and i + 1 < len(argv):
            output_dir = argv[i + 1].strip()
            i += 2
        elif arg in ("--force", "-f", "--clean", "--no-cache", "--re-render"):
            force = True
            i += 1
        elif arg == "--cpu":
            use_cpu = True
            i += 1
        elif not arg.startswith("-"):
            p = Path(arg).expanduser().resolve()
            if p.is_file() and p.suffix.lower() == ".json":
                targets.append(p)
            elif p.is_file() and p.suffix.lower() == ".txt":
                try:
                    targets.extend(parse_queue_file(p))
                except Exception as e:
                    console.print(f"[bold red]Failed to load queue file: {e}[/bold red]")
            elif p.is_dir():
                scripts = sorted(p.rglob("script.json"), key=natural_chapter_sort_key)
                if scripts:
                    targets.extend(scripts)
                else:
                    jsons = sorted(p.glob("*.json"))
                    if jsons:
                        targets.extend(jsons)
            i += 1
        else:
            i += 1

    if not targets:
        console.print("[bold red]Error: No valid JSON files or chapter directories specified.[/bold red]")
        console.print("[dim]Run 'python3 orchestrator.py harness-tts --help' for usage.[/dim]")
        return

    if len(targets) > 1:
        render_harness_queue(
            queue_targets=targets,
            voice_name=voice_name,
            cfg_scale=cfg_scale,
            seed=seed,
            output_dir=output_dir,
            use_cpu=use_cpu,
            force=force,
            console=console,
            headless=True,
        )
    else:
        render_harness_json(
            json_path=targets[0],
            voice_name=voice_name,
            cfg_scale=cfg_scale,
            seed=seed,
            output_dir=output_dir,
            use_cpu=use_cpu,
            force=force,
            console=console,
            headless=True,
        )


if __name__ == "__main__":
    run_harness_cli(sys.argv[1:])

