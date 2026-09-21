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
    ├── Breeze-TTS-2.cpp/                  # Compiled C++ Vulkan Binaries (build/bin/breeze-cli)
    ├── Breeze tts/                         # Breeze-TTS-2 Engine package & TUI
    │   ├── breeze_engine.py
    │   ├── TTS prompt.txt
    │   └── zine tts/                       # Generated audio, srt, logs & .breeze voice profiles
    └── Qween tts/                          # Qwen-TTS Audiobook Synthesizer package
        ├── book_tts.py
        ├── TTS prompt.txt
        └── word.txt
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

### 🧠 Option 2: Confucius4-R2T2 (Qwen3-ASR) — Next-Gen High-Fidelity STT

Powered by NetEase Youdao & Alibaba Qwen3-ASR. Delivers ultra-high fidelity speech recognition across 30+ languages (with flagship conversational accuracy in Japanese, Chinese, Cantonese, English, etc.) with automatic low-energy silence-boundary audio chunking and real-time streaming translation.

* **VRAM Footprint**: ~3.9 GB VRAM (`bfloat16` / `float16`), runs smoothly on 6GB NVIDIA GPUs (e.g. RTX 3050 Laptop).
* **Location on Disk**: `Models/STT/Confucius4/weights/`

#### ⚠️ Critical Notice Regarding GGUF Files
> [!WARNING]
> Do **NOT** use community `.gguf` quantizations (such as `Confucius4-R2T2.f16.gguf`). Those conversions only contain the text LLM decoder and omit the audio encoder, rendering them completely incapable of speech recognition. You **must** download the official Hugging Face `model.safetensors` full snapshot.

#### 🛠️ Environment Prerequisites
Confucius4 runs via its isolated neural worker (`Models/STT/Confucius4/confucius_engine.py`). If running Python 3.14 on system, create a Python 3.10–3.12 virtual environment (e.g. `~/confucius-env`):

```bash
# 1. Create venv (Python 3.10 - 3.12)
python3.12 -m venv ~/confucius-env
source ~/confucius-env/bin/activate

# 2. Install PyTorch with CUDA & Dependencies
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install soundfile librosa deep-translator transformers accelerate sentencepiece

# 3. Install Qwen-ASR / R2T2 Package
pip install git+https://github.com/netease-youdao/Confucius4-R2T2.git
```

#### 📥 Download Model Weights

Download the complete snapshot into `Models/STT/Confucius4/weights`:

##### Method 1 — 1-Click Python Download (Recommended)
```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='netease-youdao/Confucius4-R2T2', local_dir='Models/STT/Confucius4/weights')"
```

##### Method 2 — Hugging Face CLI
```bash
huggingface-cli download netease-youdao/Confucius4-R2T2 --local-dir Models/STT/Confucius4/weights
```

##### Method 3 — Multi-Threaded aria2c Download
```bash
mkdir -p Models/STT/Confucius4/weights
cd Models/STT/Confucius4/weights

BASE="https://huggingface.co/netease-youdao/Confucius4-R2T2/resolve/main"
aria2c -x 16 -s 16 -k 1M -o "model.safetensors" "$BASE/model.safetensors"
curl -L -O "$BASE/config.json"
curl -L -O "$BASE/tokenizer.json"
curl -L -O "$BASE/tokenizer_config.json"
curl -L -O "$BASE/preprocessor_config.json"
curl -L -O "$BASE/generation_config.json"
curl -L -O "$BASE/chat_template.json"
curl -L -O "$BASE/special_tokens_map.json"
curl -L -O "$BASE/vocab.json"
curl -L -O "$BASE/merges.txt"
curl -L -O "$BASE/added_tokens.json"

cd ../../..
```

#### 🚀 How to Run in Zine Scraper
1. Type `subs` (or `/subs`) in the main menu.
2. Select `🧠 Confucius4-R2T2 (Qwen3-ASR — High Fidelity)` in the interactive engine prompt.
3. Paste the path to your video file to generate dual `.Original.vtt` and `.{Target}.vtt` subtitles with real-time streaming translation.

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

---

## 📍 Where to Store Models (Default vs External Drives)

| Component | Default In-Suite Path | External / Custom Drive Example |
|---|---|---|
| **Voice-to-Text (STT)** | `Models/STT/faster-whisper-large-v3-turbo/` | `/mnt/storage/ai/faster-whisper-large-v3-turbo/` or `~/models/whisper/` |
| **Breeze TTS Model** | `Models/TTS/breeze-tts-2-q8_0.gguf` | `/mnt/storage/tts/breeze-tts-2-q8_0.gguf` or `~/models/breeze-tts-2-q8_0.gguf` |
| **Breeze C++ Engine** | `Models/TTS/Breeze-TTS-2.cpp/build/` | `/opt/Breeze-TTS-2.cpp/build/bin/` or `~/builds/breeze/bin/` |
| **Qwen TTS Server** | `http://127.0.0.1:8188` (Local ComfyUI) | `http://192.168.1.100:8188` (Remote GPU Server) |

---

## ⚙️ How to Point Zine to Custom / External Model Locations

If you store your models on an **external SSD**, secondary partition (e.g. `/mnt/storage/`), or custom home directory (`~/AI/`), you can easily point Zine Scraper to them using the interactive Settings TUI:

### 1. Launch Settings
At the main Zine prompt, type:
```text
❯ settings
```

### 2. Pointing to Custom Voice-to-Text (STT) Models
1. Navigate to **`Whisper AI Subtitles`** $\rightarrow$ press **`Enter`**.
2. Select **`AI Model Path`**.
3. Type or paste your custom folder path:
   - *Example (Absolute):* `/mnt/nvme/models/faster-whisper-large-v3-turbo`
   - *Example (Home folder):* `~/AI/faster-whisper-large-v3-turbo`
4. Press **`Enter`** to save.

### 3. Pointing to Custom Breeze TTS Weights & Binaries
1. Navigate to **`Breeze TTS 2 (GGUF / C++)`** $\rightarrow$ press **`Enter`**.
2. **For the Neural Weights (`.gguf`)**:
   - Select **`Model GGUF Path`**.
   - Enter your file path (e.g. `/mnt/storage/tts/breeze-tts-2-q8_0.gguf` or `~/models/breeze-tts-2-q8_0.gguf`).
3. **For the Compiled C++ Binaries (`breeze-cli`)**:
   - Select **`Binaries Directory`**.
   - Enter the directory containing `breeze-cli` (e.g. `/opt/Breeze-TTS-2.cpp/build/bin` or `~/builds/breeze/build`).
4. Press **`Enter`** to save.

### 4. Pointing to a Custom / Remote Qwen TTS Server
1. Navigate to **`Qwen Audiobooks TTS`** $\rightarrow$ press **`Enter`**.
2. Select **`Qwen TTS Server URL`**.
3. Enter your ComfyUI server address (e.g. `http://192.168.1.50:8188` or `http://127.0.0.1:8188`).
4. Press **`Enter`** to save.

> [!TIP]
> **Path Auto-Sanitization:** Zine automatically handles shell drag-and-drop quotes (`'/path/with spaces/'`), `~` user expansion, relative paths, and absolute paths!

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
