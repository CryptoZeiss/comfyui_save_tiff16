# SeedVR2 Print Upscaling Kit for ComfyUI (RunPod)

A ready-to-run kit for upscaling images to **exhibition print size** with [SeedVR2](https://github.com/ByteDance-Seed/SeedVR) in ComfyUI on a rented [RunPod](https://www.runpod.io) GPU, then saving a **16-bit, colour-managed TIFF** ready for Photoshop and fine art printing.

One command sets up a fresh pod. You load the workflow, add your image and press Run.

**What's in this repo**

| File | What it does |
|---|---|
| `__init__.py` | **Save TIFF 16-bit (Colour Managed)**, a custom ComfyUI node that saves uncompressed 16-bit TIFFs in ProPhoto RGB, Adobe RGB (1998) or sRGB, with the matching ICC profile embedded |
| `setup.sh` | Installs everything on a new pod: this node, the SeedVR2 node pack and the workflow |
| `workflows/` | The ready-made ComfyUI workflow |

---

## What you get

- A **generative upscale** with SeedVR2 7B, which rebuilds fine detail rather than just enlarging pixels
- A **16-bit TIFF** with the colour converted correctly into ProPhoto RGB (or Adobe RGB) and the profile embedded, so it opens correctly in Photoshop, Lightroom and Capture One
- An **8-bit PNG backup** that appears in ComfyUI's Assets panel for quick checking and download

Tested: a 4608 × 3712 px image upscaled to **11,102 × 8,944 px** (about 99 MP) in about 1.5 minutes on an RTX PRO 6000. That's a 94 cm wide print at 300 ppi.

---

## Quick start

### 1. Start a pod on RunPod

- **GPU:** RTX PRO 6000 (96 GB VRAM). Large print sizes need at least 96 GB.
- **Template:** the official **ComfyUI** template
- **Container disk:** raise it to **80 GB** (the SeedVR2 7B model alone is about 15 GB)
- Click **Deploy** and wait until the pod shows **Running**

### 2. Run the setup command

On the pod, click **Connect → JupyterLab**, then **File → New → Terminal**. Paste this and press Enter:

```bash
curl -sL https://raw.githubusercontent.com/cryptozeiss/comfyui_save_tiff16/main/setup.sh | bash
```

Wait until it prints **DONE**.

### 3. Restart ComfyUI

Open ComfyUI (**Connect → ComfyUI**, port 8188), click **Manager → Restart**, wait about 30 seconds, then refresh the browser.

> ComfyUI opens with its own example workflow first. You can ignore it, along with any red boxes on it.

### 4. Open the workflow

Click **Workflows** in the left toolbar and open the SeedVR2 upscale workflow. You should see three groups (**Input**, **Models**, **Upscale + Save**) and no red nodes.

### 5. Add your image and set the size

1. In **Load Image**, click **choose file to upload** and pick your image.
2. On the **SeedVR2 Video Upscaler** node, set **resolution** for your print. See [Choosing the resolution](#choosing-the-resolution) below.
3. Click **Run**.

The first run downloads the models (about 15 GB, a few minutes). Later runs start straight away.

### 6. Download your files

- **16-bit TIFF (your print master):** **Connect → JupyterLab**, open **runpod-slim → ComfyUI → output**, right-click the `.tif` and choose **Download**. It doesn't appear in ComfyUI's Assets panel.
- **PNG backup:** in ComfyUI's **Assets** panel.

### 7. Stop the pod

**Stop the pod when you're finished.** You're billed for every minute it's running.

---

## Choosing the resolution

SeedVR2's **resolution** setting is the **shortest edge** of the output in pixels: the height for a landscape image, the width for a portrait. It is *not* the width.

**max_resolution** caps the longest edge. Leave it at **0** (no limit).

### Formula

1. Work out the print's **short edge** in cm (the image only, not the border).
2. **Resolution = short edge in cm ÷ 2.54 × 300** (for 300 ppi)
3. Round **up** to a multiple of 16.

### Worked examples (4608 × 3712 px source)

| Print (image area) | Output pixels | Resolution setting | Upscale |
|---|---|---|---|
| 78 × 63 cm | 9,216 × 7,424 | **7424** | 2× |
| 94 × 75.7 cm (110 cm paper, 8 cm borders) | 11,102 × 8,944 | **8944** | 2.4× |

### Preset: Nano Banana 4K → 44" roll paper (110 cm print)

Tried and tested. These are the settings for a large exhibition print from a **4K Nano Banana image** (any version: Nano Banana, Nano Banana 2, Nano Banana Pro) on **44-inch (111.8 cm) roll paper**, with an **8 cm white border** on each side.

| | |
|---|---|
| Source (Nano Banana 4K, 5:4) | 4608 × 3712 px |
| Paper | 110 cm wide (from a 44" roll, ~0.9 cm spare each side) |
| Border | 8 cm each side (16 cm total) |
| Image size on paper | **94 × 75.7 cm** |
| Paper size with borders | 110 × ~91.7 cm |
| **resolution** | **8944** |
| max_resolution | 0 |
| Output | **11,102 × 8,944 px** (~99 MP) = 94 cm wide at 300 ppi |
| Upscale | 2.4× |
| Run time (RTX PRO 6000) | ~1.5 minutes to upscale, plus ~15 seconds to save the TIFF |

The result needs no resizing in Photoshop: it's already exactly 300 ppi at print size. Add the border with **Image → Canvas Size** (110 cm wide), or set the margins in the printer driver, then soft-proof with your paper profile.

> **Check the result on a good, calibrated monitor at 100%.** Fine generated detail can look soft or odd on a cheap screen even when the file is excellent.

**Other Nano Banana aspect ratios:** 4K outputs have different pixel sizes for other aspect ratios (16:9, 4:3, 1:1 and so on). Check the image's pixel size (Photoshop: **Image → Image Size**), then use the formula above. For a 94 cm wide image, the output width is always **11,102 px**, so: **resolution = 11,102 × short edge ÷ long edge**, rounded up to a multiple of 16. **Portrait (3712 × 4608 px):** the same **resolution 8944** gives **8,944 × 11,102 px**, which is a **75.7 cm wide × 94 cm tall** image. That fits comfortably on 44" roll paper. Making a portrait image 94 cm *wide* would need resolution 11104, a 3× upscale that's likely to run out of memory on a 96 GB card.

### Tips

- **2× is the safe choice.** Set resolution to twice your image's short edge.
- **Up to about 2.5× works** on a 96 GB card (tested at 2.4×, 99 MP).
- **Beyond about 2.5×**, expect to run out of memory. Upscale 2× in SeedVR2, then use a dedicated upscaler such as Topaz Gigapixel for the rest, or rent a larger GPU (H200 or B200).

---

## Colour management (important)

### Input

ComfyUI treats **every input image as sRGB** and ignores embedded profiles. It also reads images as 8-bit.

- **Convert your image to sRGB before uploading.** In Photoshop: **Edit → Convert to Profile → sRGB IEC61966-2.1**, then save as PNG or TIFF.
- If you upload a ProPhoto or Adobe RGB file without converting, the colours are converted twice and come out flat and desaturated.
- Flatten layers before saving. LZW or ZIP-compressed TIFFs are fine.

### Output

The **Save TIFF 16-bit (Colour Managed)** node converts the image from sRGB into your chosen space and embeds the matching ICC profile:

| colour_profile | Use for |
|---|---|
| **ProPhoto RGB** | Fine art printing with the widest editing headroom (default) |
| **Adobe RGB (1998)** | Labs or workflows that expect Adobe RGB |
| **sRGB** | Screen and web use |

Files are saved as **uncompressed 16-bit RGB TIFF** at your chosen **dpi** (default 300). File names end in the profile, e.g. `..._00001_ProPhoto_16bit.tif`.

> Open the TIFF in **Photoshop** or another colour-managed app. Quick-look viewers often ignore the profile, which makes ProPhoto files look dull.

Converting sRGB to ProPhoto doesn't add colours that weren't in the original. It gives you a correctly tagged 16-bit file with headroom for editing and printing.

---

## Workflow settings reference

| Node | Setting | Value | Notes |
|---|---|---|---|
| SeedVR2 DiT loader | model | `seedvr2_ema_7b_sharp_fp16` | Try the standard 7B (non-sharp) for softer, more natural texture |
| | device | `cuda:0` | |
| | blocks_to_swap | `0` | Raise to 16–20 only if you run out of memory |
| | offload_device | `none` | |
| SeedVR2 VAE loader | encode/decode tiled | `true` | |
| | tile size / overlap | `1024` / `128` | If you see seams, raise overlap to 256. If you run out of memory, drop tile size to 512 |
| SeedVR2 Video Upscaler | resolution | e.g. `8944` | Short edge. See above |
| | max_resolution | `0` | |
| | color_correction | `lab` | Keeps colours matched to your original |
| Save TIFF 16-bit | colour_profile | `ProPhoto RGB` | |
| | dpi | `300` | |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Nodes are red or missing after setup | You haven't restarted yet. **Manager → Restart**, then refresh the browser |
| Workflow isn't in the Workflows list | Check the terminal ended with **DONE**. Run the setup command again |
| Settings look wrong (e.g. resolution stuck at 5000) | A different SeedVR2 pack is installed. Don't use **Install Missing Custom Nodes** for this workflow, because `setup.sh` installs the right one |
| Out of memory | Drop VAE tile size to 512, then raise blocks_to_swap to 16–20, or use a lower resolution |
| Save node stays green with no progress bar | It's working. Large TIFFs take 15–30 seconds to convert and write. Check the log for `[Save TIFF 16-bit] Saved` |
| TIFF isn't in Assets | That's expected. Download it from JupyterLab (step 6) |
| Colours look flat | The input wasn't sRGB (see Colour management), or you're viewing it in an app that ignores ICC profiles |

---

## Updating an existing pod

Run the same setup command again. It pulls the latest node and workflow from this repo. Then **Manager → Restart**, refresh, and reopen the workflow from the **Workflows** sidebar.

---

## A note on generative upscaling

SeedVR2 **invents** plausible detail rather than recovering detail that was in the original. The results can be remarkable, but they aren't a faithful record of the source. That's worth thinking about when you use it with photographs, especially where authenticity or the indexical nature of the image matters.

---

## Credits

- **SeedVR2** model: [ByteDance Seed](https://github.com/ByteDance-Seed/SeedVR) ([paper](https://arxiv.org/abs/2506.05301))
- **SeedVR2 ComfyUI nodes:** [numz / AInVFX](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler)
- **ComfyUI:** [comfyanonymous/ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- **This kit** (Save TIFF 16-bit node, setup script, workflow): Shane Hulbert

The Save TIFF 16-bit node needs only numpy, which comes with ComfyUI, so there's nothing extra to install.
