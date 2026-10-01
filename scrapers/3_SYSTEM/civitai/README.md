# Civitai / Anima Model Ingestion Engine

High-performance multi-stream downloader for Civitai models, checkpoints, LoRAs, and VAEs.

## Features
- **Parallel Chunk Acceleration**: Bypasses CDN single-stream speed caps via concurrent Range streams.
- **Smart Model Destination Routing**:
  - Automatically identifies model type (`LORA`, `Checkpoint`, `VAE`, `ControlNet`, etc.), base architecture (`Anima`), and tags.
  - Automatically routes into ComfyUI models (`/mnt/maiden/comfyui-portable/ComfyUI/models/loras/anima/<subfolder>/`).
  - **Vacuum Fallback**: If flags are missing and no ComfyUI directory is present, models safely fall back into `~/Downloads/Zine/Vacuum/Models/<Type>/`.
  - **Explicit Flags Supported**: Lines with `<URL> -- <DESTINATION_DIRECTORY>` route directly to the specified folder.
- **Uncluttered Downloads**:
  - Never litters temporary files or completed logs into `~/Downloads/`.
  - Completed logs are recorded in `Logs/Downlode 💩/civitai_completed.txt`.
- **Strict No-Overwrite Protection**:
  - Detects pre-existing non-empty models on disk, skips re-downloading, and updates the task queue.
- **Domain Fallback**:
  - Transparently switches between `civitai.red` and `civitai.com` if one domain fails.
- **Network Drop / Timeout Auto-Resume**:
  - Resumes partial chunk downloads upon connection failure with exponential backoff.
