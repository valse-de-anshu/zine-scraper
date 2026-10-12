"""
scrapers/3_SYSTEM/civitai/location.py
-------------------------------------
Smart destination directory resolution for Civitai / Anima models.

Rules:
1. If the user explicitly provided '-- <DESTINATION_PATH>', route to that directory.
2. If flags are missing:
   - Identify model type (LORA, Checkpoint, VAE, ControlNet, etc.), baseModel (Anima, SD, etc.), and tags.
   - If ComfyUI models directory is present (/mnt/maiden/comfyui-portable/ComfyUI/models/):
     - Route LORAs to models/loras/ (and into anima/<category> for Anima LoRAs).
     - Route Checkpoints to models/checkpoints/.
     - Route VAEs to models/vae/.
     - Route ControlNets to models/controlnet/.
     - Route Upscalers to models/upscale_models/.
     - Route Embeddings to models/embeddings/.
   - Fallback destination:
     - Save to Zine's Vacuum folder: <downloads_root>/Vacuum/Models/<Category>/
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from core.paths import PathAuthority, sanitize_user_path


# Known ComfyUI installation roots to probe
COMFYUI_MODEL_CANDIDATES = [
    Path("/mnt/maiden/comfyui-portable/ComfyUI/models"),
    Path.home() / "ComfyUI" / "models",
    Path.home() / "comfyui" / "models",
]


def get_comfyui_models_root() -> Optional[Path]:
    """Finds the primary ComfyUI models directory if available."""
    for cand in COMFYUI_MODEL_CANDIDATES:
        if cand.exists() and cand.is_dir():
            return cand
    return None


def get_vacuum_fallback_dir(category: Optional[str] = None) -> Path:
    """Returns the fallback directory inside Zine's Vacuum folder."""
    paths = PathAuthority()
    base = paths.get_downloads_root() / "Vacuum" / "Models"
    if category:
        clean_cat = "".join(c for c in category if c.isalnum() or c in (" ", "_", "-")).strip()
        if clean_cat:
            return base / clean_cat
    return base


def resolve_model_destination(
    explicit_dest: Optional[str] = None,
    model_type: Optional[str] = None,
    base_model: Optional[str] = None,
    model_name: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Tuple[Path, str]:
    """
    Resolves the target destination folder.
    Returns: (target_directory_path, reason_string)
    """
    # 1. Explicit user-provided flag
    if explicit_dest and explicit_dest.strip():
        raw_dest = explicit_dest.strip()
        # Auto-recover if an accidental URL was embedded inside the destination path
        if "http://" in raw_dest or "https://" in raw_dest:
            cleaned = re.sub(r'https?://[^\s/]+(/models/\d+/[^\s/]+)?', '', raw_dest).strip()
            if not cleaned.startswith('/') and not cleaned.startswith('~'):
                cleaned = re.sub(r'https?://[^\s]+', '', raw_dest).strip()
            if cleaned.startswith('/') or cleaned.startswith('~'):
                raw_dest = cleaned
            else:
                raw_dest = ""

        if raw_dest:
            sanitized = sanitize_user_path(raw_dest)
            try:
                target = Path(sanitized).expanduser().resolve()
                target.mkdir(parents=True, exist_ok=True)
                return target, "Explicit flag (--)"
            except (PermissionError, OSError):
                # Cannot create or write to explicit path, fall through to auto-route
                pass

    # 2. Inspect ComfyUI structure
    comfy_root = get_comfyui_models_root()
    clean_type = (model_type or "").strip().upper()
    tags_lower = [t.lower() for t in (tags or [])]
    name_lower = (model_name or "").lower()
    base_lower = (base_model or "").lower()

    is_anima = "anima" in base_lower or "anima" in name_lower or any("anima" in t for t in tags_lower)

    if comfy_root and comfy_root.exists():
        # LoRA / DoRA / LoCon
        if clean_type in ("LORA", "LOCON", "DORA"):
            loras_dir = comfy_root / "loras"
            anima_dir = loras_dir / "anima"

            if is_anima and anima_dir.exists():
                # Check for matching category subfolders inside anima/
                subfolders = [
                    "concept", "style", "pose", "sex", "sex detailer",
                    "nsfw action", "nsfw detailer", "detailer", "cloth",
                    "expression", "chracter", "lighting concept", "meme", "pov"
                ]
                # Match tags or name against subfolders
                for sub in subfolders:
                    if sub in tags_lower or sub in name_lower:
                        dest = anima_dir / sub
                        dest.mkdir(parents=True, exist_ok=True)
                        return dest, f"ComfyUI Anima LoRA ({sub})"

                # If no specific subfolder matched, place in anima root
                return anima_dir, "ComfyUI Anima LoRA (General)"

            if loras_dir.exists():
                return loras_dir, "ComfyUI LoRA"

        # Checkpoint
        elif clean_type in ("CHECKPOINT", "CHECKPOINT TRAINED"):
            ckpt_dir = comfy_root / "checkpoints"
            if ckpt_dir.exists():
                return ckpt_dir, "ComfyUI Checkpoints"

        # VAE
        elif clean_type == "VAE":
            vae_dir = comfy_root / "vae"
            if vae_dir.exists():
                return vae_dir, "ComfyUI VAE"

        # ControlNet
        elif clean_type == "CONTROLNET":
            cnet_dir = comfy_root / "controlnet"
            if cnet_dir.exists():
                return cnet_dir, "ComfyUI ControlNet"

        # Upscaler
        elif clean_type == "UPSCALER":
            up_dir = comfy_root / "upscale_models"
            if up_dir.exists():
                return up_dir, "ComfyUI Upscalers"

        # Embeddings
        elif clean_type in ("TEXTUALINVERSION", "EMBEDDING"):
            emb_dir = comfy_root / "embeddings"
            if emb_dir.exists():
                return emb_dir, "ComfyUI Embeddings"

    # 3. Fallback: Save into Zine's Vacuum/Models folder
    cat_label = clean_type if clean_type else "General"
    fallback_path = get_vacuum_fallback_dir(cat_label)
    fallback_path.mkdir(parents=True, exist_ok=True)
    return fallback_path, f"Vacuum Fallback (Vacuum/Models/{cat_label})"
