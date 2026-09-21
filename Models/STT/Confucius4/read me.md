# Confucius4-R2T2 (Qwen3-ASR) Speech-to-Text Engine

This folder contains the **Confucius4-R2T2 / Qwen3-ASR** neural subtitle engine for Zine Scraper.

## Model Weights Directory
The complete model weights must be placed in:
```
Models/STT/Confucius4/weights/
```

### 1-Click Python Download (Recommended)
```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='netease-youdao/Confucius4-R2T2', local_dir='weights')"
```

### Hugging Face CLI Download
```bash
huggingface-cli download netease-youdao/Confucius4-R2T2 --local-dir weights
```

> **Note:** Do NOT use GGUF conversions (`*.gguf`) for this model. GGUF conversions only contain the text LLM decoder and omit the audio encoder, rendering them non-functional for speech recognition. Always use the official `model.safetensors` full snapshot.

