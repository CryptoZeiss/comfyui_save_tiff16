#!/bin/bash
# ------------------------------------------------------------------
# RunPod ComfyUI setup — Shane's SeedVR2 print upscaling kit
# Installs: Save TIFF 16-bit node, SeedVR2 node pack, saved workflows
# Run in the pod's terminal:
#   curl -sL https://raw.githubusercontent.com/cryptozeiss/comfyui_save_tiff16/main/setup.sh | bash
# ------------------------------------------------------------------
set -e

REPO="https://github.com/cryptozeiss/comfyui_save_tiff16"

# 1. Find ComfyUI (location differs between RunPod templates)
CN="$(find / -maxdepth 5 -type d -path '*/ComfyUI/custom_nodes' 2>/dev/null | head -1)"
if [ -z "$CN" ]; then echo "Could not find ComfyUI/custom_nodes"; exit 1; fi
COMFY="$(dirname "$CN")"
echo ">> ComfyUI found at: $COMFY"

# 2. Use ComfyUI's own Python if it has a virtual environment
if [ -x "$COMFY/.venv/bin/python" ]; then PY="$COMFY/.venv/bin/python"
elif [ -x "$COMFY/venv/bin/python" ]; then PY="$COMFY/venv/bin/python"
else PY="$(command -v python3)"; fi
echo ">> Using Python: $PY"

cd "$CN"

# 3. Save TIFF 16-bit (Colour Managed) node + workflows
if [ -d comfyui_save_tiff16 ]; then (cd comfyui_save_tiff16 && git pull -q)
else git clone -q "$REPO" comfyui_save_tiff16; fi
echo ">> Save TIFF 16-bit node installed"

# 4. SeedVR2 node pack
if [ ! -d ComfyUI-SeedVR2_VideoUpscaler ]; then
  git clone -q https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
fi
"$PY" -m pip install -q -r ComfyUI-SeedVR2_VideoUpscaler/requirements.txt
echo ">> SeedVR2 installed"

# 5. Put workflows in ComfyUI's Workflows sidebar
if ls comfyui_save_tiff16/workflows/*.json >/dev/null 2>&1; then
  mkdir -p "$COMFY/user/default/workflows"
  cp comfyui_save_tiff16/workflows/*.json "$COMFY/user/default/workflows/"
  echo ">> Workflows copied to the Workflows sidebar"
fi

echo ""
echo "DONE. In ComfyUI: Manager > Restart, then refresh the browser."
echo "SeedVR2 models download automatically on the first run (~16GB)."
