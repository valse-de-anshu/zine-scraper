# 🎙️ Zine Scraper — AI Models Hub (`Models/`)

The `Models/` directory serves as the unified local storage hub for all offline AI models used across the Zine Scraper suite, organized into two dedicated subdirectories:
- **`Models/STT/`** (Speech-to-Text): Models for the **AI Subtitle Generator** (`subs` command) powered by `faster-whisper`.
- **`Models/TTS/`** (Text-to-Speech): Models and binaries for **Breeze-TTS-2** (`breeze` command) and **Qwen-TTS** (`tts` command).

---

## 📁 Directory Structure Overview

```text
Models/
├── README to downlode ai model.md          # This setup guide
│
├── STT/                                    # [Speech-to-Text / Voice-to-Text Models]
│   └── faster-whisper-large-v3-turbo/      # Flagship Subtitle Model (~1.6 GB)
│       ├── config.json
│       ├── model.bin
│       ├── preprocessor_config.json
│       ├── tokenizer.json
│       └── vocabulary.json
│
└── TTS/                                    # [Text-to-Speech / Voice Synthesizer Hub]
    ├── breeze-tts-2-q8_0.gguf              # Breeze-TTS-2 8-bit Quantized GGUF (~3.2 GB)
    ├── breeze-tts-2-fp16.gguf              # Breeze-TTS-2 Full Precision (Optional, ~6.5 GB)
    │
    └── Breeze-TTS-2.cpp/                  # Compiled C++ Vulkan Binaries
        └── build/
            └── bin/
                ├── breeze-cli              # High-speed Vulkan CLI generator
                └── breeze-server           # Streaming API server
```

---

## 🎧 Part 1: Speech-to-Text (`Models/STT/`) — `faster-whisper`

Used by Zine's built-in **AI Subtitle Generator** (`subs` command) to transcribe, translate, and timestamp videos and audio into `.srt` subtitles.

### 🚀 Download & Installation Options

#### Method 1 — 1-Click Python Download (Easiest)
Run in your terminal from the `zine scraper` root directory:
```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/STT/faster-whisper-large-v3-turbo')"
```

#### Method 2 — Hugging Face CLI
```bash
# Large-v3-Turbo (~1.6 GB) — State-of-the-art accuracy & ultra-fast inference (Recommended):
huggingface-cli download deepdml/faster-whisper-large-v3-turbo --local-dir Models/STT/faster-whisper-large-v3-turbo

# Standard Large-v3 (~3.1 GB) — Maximum multi-lingual fidelity:
huggingface-cli download Systran/faster-whisper-large-v3 --local-dir Models/STT/faster-whisper-large-v3

# Medium (~1.5 GB) — Optimized for 4GB VRAM GPUs:
huggingface-cli download Systran/faster-whisper-medium --local-dir Models/STT/faster-whisper-medium

# Small (~480 MB) — Lightweight for CPU-only inference:
huggingface-cli download Systran/faster-whisper-small --local-dir Models/STT/faster-whisper-small
```

#### Method 3 — Direct Download (`curl` / `wget`)
```bash
mkdir -p Models/STT/faster-whisper-large-v3-turbo
cd Models/STT/faster-whisper-large-v3-turbo
BASE="https://huggingface.co/deepdml/faster-whisper-large-v3-turbo/resolve/main"

curl -L -O "$BASE/config.json"
curl -L -O "$BASE/model.bin"
curl -L -O "$BASE/preprocessor_config.json"
curl -L -O "$BASE/tokenizer.json"
curl -L -O "$BASE/vocabulary.json"
cd ../../..
```

#### Method 4 — Git LFS
```bash
git clone https://huggingface.co/deepdml/faster-whisper-large-v3-turbo Models/STT/faster-whisper-large-v3-turbo
```

---

## 🗣️ Part 2: Text-to-Speech (`Models/TTS/`) — `Breeze-TTS-2` (GGUF / C++)

Used by Zine's **Breeze TTS Engine** (`breeze` command) for lightning-fast, high-fidelity neural audiobook and voice generation with zero Python overhead using Vulkan GPU acceleration.

### 📥 1. Download Model Weights (`.gguf`)

Place the `.gguf` weight file directly inside `Models/TTS/`:

#### Option A: Q8_0 Quantized (Recommended — ~3.2 GB, ~4GB VRAM)
```bash
# Using Hugging Face CLI:
huggingface-cli download MediaTek-Research/Breeze-TTS-2-GGUF breeze-tts-2-q8_0.gguf --local-dir Models/TTS

# OR using curl:
curl -L -o Models/TTS/breeze-tts-2-q8_0.gguf "https://huggingface.co/MediaTek-Research/Breeze-TTS-2-GGUF/resolve/main/breeze-tts-2-q8_0.gguf"
```

#### Option B: FP16 Unquantized (~6.5 GB, ~8GB VRAM)
```bash
curl -L -o Models/TTS/breeze-tts-2-fp16.gguf "https://huggingface.co/MediaTek-Research/Breeze-TTS-2-GGUF/resolve/main/breeze-tts-2-fp16.gguf"
```

### ⚡ 2. Build or Install `Breeze-TTS-2.cpp` Vulkan Engine

Clone and build the lightweight C++ Vulkan runtime inside `Models/TTS/`:

```bash
cd Models/TTS
git clone https://github.com/MediaTek-Research/Breeze-TTS-2.cpp.git
cd Breeze-TTS-2.cpp
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j$(nproc)
cd ../../..
```

Once built, the binary will reside at `Models/TTS/Breeze-TTS-2.cpp/build/bin/breeze-cli` (or `build/breeze-cli`). Zine will automatically discover and utilize it without requiring manual configuration!

---

## ⚙️ Configuration in Zine Scraper

1. Launch Zine Scraper:
   - Linux / macOS: `./"run me"/run.sh`
   - Windows: `run me\run.bat`
2. Type **`settings`** and press **Enter**.
3. Configure model options under the respective sub-menus:
   - **Whisper AI Subtitles**:
     - *Subtitles Model Path*: `Models/STT/faster-whisper-large-v3-turbo`
     - *Hardware Target*: `6GB (INT8)` (Fastest/Safest), `8GB+ (FP16)`, or `CPU-Only`
     - *Translation Mode*: `Both (Original + Target)`, `Target Only`, or `Original Only`
   - **Breeze TTS 2 (GGUF / C++)**:
     - *Model GGUF Path*: `Models/TTS/breeze-tts-2-q8_0.gguf`
     - *Binaries Directory*: `Models/TTS/Breeze-TTS-2.cpp/build`
     - *Execution Backend*: `Direct CLI (breeze-cli)` or `HTTP Server (breeze-server)`
     - *Hardware Acceleration*: `Vulkan (GPU)` or `CPU`

---

## 🎬 How to Use

### Subtitle Generator (`subs`)
```text
❯ subs
```
Paste the path to any `.mp4`, `.mkv`, `.flac`, or `.mp3` file to generate synchronized `.srt` subtitles.

### Breeze TTS Generator (`breeze`)
```text
❯ breeze
```
Convert text, novel chapters, or `.txt` files into expressive natural speech audio (`.wav`).
