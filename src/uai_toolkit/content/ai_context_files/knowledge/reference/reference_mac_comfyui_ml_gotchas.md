---
name: reference_mac_comfyui_ml_gotchas
description: macOS/Apple-Silicon gotchas for ComfyUI custom nodes and HuggingFace
  downloads (onnxruntime-gpu, xet slowness)
status: active
---

Two macOS/Apple-Silicon traps hit while installing ComfyUI ControlNet on the Studio stack (2026-07):

1. **`onnxruntime-gpu` has no Apple-Silicon wheel** — GPU onnxruntime is CUDA-only. Many custom nodes list it in `requirements.txt` (e.g. `comfyui_controlnet_aux`), so a raw `pip install -r requirements.txt` dies with `No matching distribution found for onnxruntime-gpu`. Fix: filter the requirements, substituting plain **`onnxruntime`** (CPU/CoreML) for `onnxruntime-gpu`. General rule for Mac: strip cuda/gpu-only deps.

2. **HuggingFace `xet` transfer backend can crawl** — the `hf download` CLI routes through xet by default; saw it drop to **261 kB/s** (stalled a 2.5 GB pull for 1h40m). Two fixes, both ~26 MB/s (100× faster): set env **`HF_HUB_DISABLE_XET=1`** to force plain HTTP, OR download the file directly from the CDN: `curl -L -C - -o out.safetensors https://huggingface.co/<repo>/resolve/main/<file>` (resumable via `-C -`). Ungated repos need no auth. Direct-CDN is the reliable path when a big HF download stalls.

Context: Studio ControlNet = `xinsir/controlnet-openpose-sdxl-1.0` + `comfyui_controlnet_aux` (DWPose preprocessor), workflow `Studio_SDXL_pose` at `ComfyUI/user/default/workflows/`. The ComfyUI venv is internal-SSD (see [[reference_uai_needs_full_disk_access]]); model files on ModelVault. Setup approach when my UAI shell was locked out of ModelVault: author scripts on internal disk, user runs them in their own terminal (which has drive access), script self-verifies with a real render.
