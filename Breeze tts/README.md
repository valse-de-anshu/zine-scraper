# 🌬️ Breeze-TTS-2 Integration Guide

## Overview

**Breeze-TTS-2.cpp** is a high-performance, bilingual (English & Mandarin) instruction-following Text-to-Speech engine built in C++ on [ggml](https://github.com/ggml-org/ggml) with Vulkan GPU acceleration and CPU fallback. It operates on quantized GGUF weights, providing studio-grade neural voice synthesis, zero-shot voice design, reference voice cloning, emotional direction, vocal event acting, and experimental voice conversion.

Inside **Zine Scraper**, Breeze TTS provides an ultra-fast, local audiobook generator with frame-accurate `.srt` subtitles, dynamic vocal event triggering, and saved `.breeze` voice profiles.

---

## 🌟 Core Capabilities

| Mode | Input | Output | Description |
|---|---|---|---|
| **Voice Design** | Natural language text description | Invented Voice | Shapes vocal traits entirely from prompt (e.g. *"A deep, authoritative male narrator with dramatic gravitas"*). |
| **Voice Cloning** | Reference audio (`.wav`) + exact transcript | Cloned Voice | Replicates speaker timbre and pronunciation from 5–15 seconds of clean reference speech. |
| **Voice Direction** | Reference audio/profile + instruction | Steered Voice | Guides the emotion, pace, or intensity of a cloned voice (e.g. *"Whisper anxiously with trembling breath"*). |
| **Saved Voices** | `.breeze` voice profile file | Instant Voice | Encodes reference voice once into a binary cache, dropping Time-To-First-Audio (TTFA) from ~900ms to ~280ms. |
| **Voice Conversion** | Source recording + target voice | Respoke Audio | Keeps original timing, rhythm, and phrasing while replacing the speaker identity with target voice. |

---

## 🎭 Vocal Event Tags & Dynamic CFG Scaling

Breeze TTS 2 supports inline descriptive vocal tags enclosed in round brackets `(...)` or Chinese brackets `[...]`:

- **Reliable Vocal Tags**: `(laugh)`, `(sigh)`, `(cough)`, `(clears throat)`, `(whispering)`, `(gasp)`, `(nervous chuckle)`, `(giggle)`, `(groan)`, `(yawn)`, `(pant)`, `(shiver)`, `(screaming)`, `[笑]`, `[叹气]`, `[低语]`, `[清嗓子]`.
- **Dynamic Guidance (`--cfg-scale`)**:
  - **Standard Reading (`CFG = 1.0`)**: Produces natural, smooth flowing narrative prosody. At CFG 1.0, vocal event tags are treated as subtle suggestions.
  - **Vocal Event Elevation (`CFG = 2.0 – 2.8`)**: When Zine's chunker detects vocal tags, it dynamically boosts the CFG scale to **2.5**, compelling the model to audibly perform the breath, chuckle, sigh, or whisper, and immediately returns to CFG 1.0 for standard narration.

---

## 🧠 Model Architecture & Weights

```text
Pipeline:
  Text + Instruction 
        │
        ▼
  Gemma BPE Tokenizer
        │
        ▼
  T5Gemma2 Text Encoder (26 layers, 1152 hidden)
        │
        ▼
  Projection (1152 → 2048)
        │
        ▼
  Qwen3 Backbone (28 layers, 2048 hidden) ──► Codebook 0 (Emits 1 frame @ 12.5 fps)
        │                                         │
        ├─────────────────────────────────────────┘
        ▼
  Depth Decoder (12 layers, 1024 hidden)  ──► Codebooks 1–15 (15 autoregressive steps)
        │
        ▼
  Qwen3TTSTokenizerV2 Vocoder             ──► 24 kHz Mono Waveform (1920 samples/frame)
```

### Quantized GGUF Models

| Variant | Size | VRAM Usage | Recommendation |
|---|---|---|---|
| **`breeze-tts-2-q8_0.gguf`** | ~3.3 GB | ~4.0 GB | **Recommended** (Flawless audio fidelity, zero spectral drift) |
| **`breeze-tts-2-q4_k.gguf`** | ~2.4 GB | ~3.0 GB | Fast & Lightweight |
| **`breeze-tts-2-f16.gguf`** | ~5.9 GB | ~7.0 GB | Reference unquantized quality |

Weights are located by default at `/mnt/maiden/tts/breeze-tts-2-q8_0.gguf` or customizable in Settings.

---

## 🚀 Execution Backends

### 1. Direct CLI (`breeze-cli`)
- Zero daemon/server setup required.
- Launches local C++ engine directly with Vulkan GPU acceleration.
- Ideal for standard batch generation and CLI usage.

### 2. Streaming HTTP Server (`breeze-server`)
- Runs a standalone HTTP & WebSocket server on `http://127.0.0.1:8080`.
- Streams raw 24 kHz 16-bit PCM chunks as they are generated.
- Features a built-in Dark UI accessible at `http://127.0.0.1:8080/`.

---

## 📁 Directory Structure

```text
Breeze tts/
├── __init__.py           # Package exports
├── breeze_engine.py      # Core audiobook engine, TUI, chunker & vocal dispatcher
├── README.md             # This comprehensive guide
├── TTS prompt.txt        # Container for voice design & direction instructions
└── voices/               # Storage directory for saved .breeze voice profiles
```

---

## ⌨️ CLI Usage in Zine Scraper

Type any of the following commands in the main Zine prompt:

- **`breeze`** or **`/breeze`**: Opens the dedicated Breeze TTS 2 TUI suite.
- **`tts`** or **`/tts`**: Opens the universal Audiobook Generator selector (choose between Breeze-TTS-2 or Qwen3-TTS).
- **`settings`** → **`Breeze TTS 2 (GGUF / C++)`**: Configure model paths, voice profiles, CFG scale, temperature, and hardware targets.

### Global Shortcuts during Audiobook Generation
- **`Ctrl + R`**: Halt generation after the active chunk, cleanly merge all completed audio chunks via FFmpeg, export synced `.srt` subtitles, and return safely.
- **`Ctrl + C`**: Force cancel and cleanup.
