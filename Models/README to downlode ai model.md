# 🎙️ Zine Scraper — AI Speech & Subtitle Models Guide (`Models/`)

This directory is the local storage hub for offline AI Speech-to-Text models used by Zine Scraper's built-in **AI Subtitle Generator** (`subs` command).

---

## 📋 What is Faster-Whisper?

Zine uses **`faster-whisper`** (powered by CTranslate2), a reimplementation of OpenAI's Whisper model that runs up to **4x faster with lower memory usage**.

### Required Model Files
A valid model folder must contain these essential files:
```text
Models/faster-whisper-large-v3-turbo/
├── config.json
├── model.bin                      (~1.6 GB)
├── preprocessor_config.json
├── tokenizer.json
└── vocabulary.json
```

---

## 🚀 How to Download & Install the Model

Choose **ANY** of the 4 simple installation methods below based on your preferred tools:

---

### Method 1 — 1-Click Python Download (Easiest & Cross-Platform)

Run this single command in your terminal from the `zine scraper` root directory (inside your activated `venv`):

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='deepdml/faster-whisper-large-v3-turbo', local_dir='Models/faster-whisper-large-v3-turbo')"
```

---

### Method 2 — Hugging Face CLI

If you have `huggingface-hub` installed (`pip install huggingface_hub`):

#### 🏆 Flagship Model (Recommended for All Users):
```bash
# Large-v3-Turbo (~1.6 GB) — State-of-the-art accuracy & ultra-fast inference:
huggingface-cli download deepdml/faster-whisper-large-v3-turbo --local-dir Models/faster-whisper-large-v3-turbo
```

#### 📦 Alternate Model Sizes:
```bash
# Standard Large-v3 (~3.1 GB) — Maximum multi-lingual fidelity:
huggingface-cli download Systran/faster-whisper-large-v3 --local-dir Models/faster-whisper-large-v3

# Medium (~1.5 GB) — Optimized for 4GB VRAM GPUs:
huggingface-cli download Systran/faster-whisper-medium --local-dir Models/faster-whisper-medium

# Small (~480 MB) — Lightweight for CPU-only inference:
huggingface-cli download Systran/faster-whisper-small --local-dir Models/faster-whisper-small
```

---

### Method 3 — High-Speed Download via `aria2c` / `curl` / `wget`

If you prefer downloading without Python or Git:

#### 🐧 Linux / 🍏 macOS:
```bash
mkdir -p Models/faster-whisper-large-v3-turbo
cd Models/faster-whisper-large-v3-turbo

# Base URL for Hugging Face weights:
BASE="https://huggingface.co/deepdml/faster-whisper-large-v3-turbo/resolve/main"

# Download all 5 required files:
curl -L -O "$BASE/config.json"
curl -L -O "$BASE/model.bin"
curl -L -O "$BASE/preprocessor_config.json"
curl -L -O "$BASE/tokenizer.json"
curl -L -O "$BASE/vocabulary.json"

cd ../..
```

#### 🪟 Windows (PowerShell):
```powershell
New-Item -ItemType Directory -Force -Path "Models\faster-whisper-large-v3-turbo"
cd "Models\faster-whisper-large-v3-turbo"

$base = "https://huggingface.co/deepdml/faster-whisper-large-v3-turbo/resolve/main"
Invoke-WebRequest -Uri "$base/config.json" -OutFile "config.json"
Invoke-WebRequest -Uri "$base/model.bin" -OutFile "model.bin"
Invoke-WebRequest -Uri "$base/preprocessor_config.json" -OutFile "preprocessor_config.json"
Invoke-WebRequest -Uri "$base/tokenizer.json" -OutFile "tokenizer.json"
Invoke-WebRequest -Uri "$base/vocabulary.json" -OutFile "vocabulary.json"

cd ..\..
```

---

### Method 4 — Git LFS Clone

```bash
# Ensure git-lfs is installed:
git lfs install

# Clone the model repository:
git clone https://huggingface.co/deepdml/faster-whisper-large-v3-turbo Models/faster-whisper-large-v3-turbo
```

---

## 📊 Hardware Requirements & Comparison

| Model | Disk Size | Recommended VRAM | Precision | Recommended Hardware |
|---|---|---|---|---|
| **`large-v3-turbo`** *(Default)* | **~1.6 GB** | **4GB - 6GB** | INT8 / FP16 | **NVIDIA RTX 20/30/40 Series, Apple M-Series, Fast CPU** |
| **`large-v3`** | ~3.1 GB | 6GB - 8GB | INT8 / FP16 | NVIDIA RTX 3080/4080 or higher |
| **`medium`** | ~1.5 GB | 3GB - 4GB | INT8 | GTX 1660 / RTX 3050 laptops |
| **`small`** | ~480 MB | 2GB / CPU | INT8 | Low-spec laptops & CPU-only machines |

---

## ⚙️ How to Configure in Zine Scraper

1. Launch Zine Scraper:
   - Linux / macOS: `./"run me"/run.sh`
   - Windows: `run me\run.bat`
2. At the prompt, type **`settings`** and press **Enter**.
3. Under the **`AI & Subtitles`** section:
   - **AI Subtitles Mode**: Choose `Both` (Original + English Translated), `Target Only`, or `Original Only`.
   - **Target Language**: Select your preferred language (e.g. `English`, `Japanese`, `Spanish`, `French`, `German`).
   - **Subtitles Model Path**: Confirm it points to your model (Default: `~/Models/faster-whisper-large-v3-turbo` or `<project_root>/Models/faster-whisper-large-v3-turbo`).
   - **VRAM Target**: Select `6GB (INT8)` (recommended for speed/memory balance), `8GB (FP16)`, or `CPU`.

---

## 🎬 How to Use the Subtitle Generator (`subs`)

1. In the main Zine terminal prompt, run:
   ```text
   ❯ subs
   ```
2. Paste the file path of any downloaded video or audio file (`.mp4`, `.mkv`, `.flac`, `.mp3`).
3. Zine will transcribe the audio track with millisecond timestamps, translate the dialogue, and output a clean `.srt` subtitle file directly next to the media file!
