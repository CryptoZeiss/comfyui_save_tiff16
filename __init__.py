"""
16-bit colour-managed TIFF nodes for ComfyUI
--------------------------------------------
Save TIFF 16-bit (Colour Managed)
    Saves uncompressed 16-bit RGB TIFFs in ProPhoto RGB, Adobe RGB (1998) or
    sRGB with the matching ICC profile embedded. Converts from the source
    colour space (sRGB by default, or ProPhoto / Adobe RGB for camera files).
    Needs only numpy.

Load Image 16-bit TIFF
    Loads 8- or 16-bit TIFFs at full precision (ComfyUI's Load Image drops
    to 8-bit) and reports the embedded ICC profile. Needs `tifffile`
    (and `imagecodecs` for LZW/ZIP-compressed TIFFs).

Install: put this folder in ComfyUI/custom_nodes/ and restart ComfyUI.
"""

import os
import struct
import datetime

import numpy as np

try:
    import folder_paths  # provided by ComfyUI
except ImportError:  # allows testing outside ComfyUI
    folder_paths = None


# ---------------------------------------------------------------------------
# Colour science
# ---------------------------------------------------------------------------

D50 = np.array([0.9642, 1.0, 0.8249])
D65 = np.array([0.95047, 1.0, 1.08883])

BRADFORD = np.array([
    [0.8951, 0.2664, -0.1614],
    [-0.7502, 1.7135, 0.0367],
    [0.0389, -0.0685, 1.0296],
])


def _rgb_to_xyz(primaries, white):
    """RGB->XYZ matrix from xy primaries and white point XYZ."""
    cols = []
    for x, y in primaries:
        cols.append([x / y, 1.0, (1 - x - y) / y])
    P = np.array(cols).T
    S = np.linalg.solve(P, white)
    return P * S


def _adapt(src_white, dst_white):
    """Bradford chromatic adaptation matrix."""
    s = BRADFORD @ src_white
    d = BRADFORD @ dst_white
    return np.linalg.inv(BRADFORD) @ np.diag(d / s) @ BRADFORD


# Gamma values are stored exactly as the ICC curve will store them (u8Fixed8)
SPACES = {
    "Adobe RGB (1998)": {
        "primaries": [(0.64, 0.33), (0.21, 0.71), (0.15, 0.06)],
        "white": D65,
        "gamma_u88": 0x0233,  # 2.19921875 (563/256)
    },
    "ProPhoto RGB": {
        "primaries": [(0.7347, 0.2653), (0.1596, 0.8404), (0.0366, 0.0001)],
        "white": D50,
        "gamma_u88": 0x01CD,  # 1.80078125, as in Kodak's ProPhoto profile
    },
    "sRGB": {
        "primaries": [(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)],
        "white": D65,
        "gamma_u88": None,  # sRGB piecewise curve
    },
}


def _to_d50(space):
    """RGB(linear) -> PCS XYZ (D50) matrix for a space."""
    sp = SPACES[space]
    m = _rgb_to_xyz(sp["primaries"], sp["white"])
    if not np.allclose(sp["white"], D50):
        m = _adapt(sp["white"], D50) @ m
    return m


def _srgb_decode(v):
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def _srgb_encode(v):
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def _decode(v, space):
    """Encoded 0..1 -> linear."""
    if space == "sRGB":
        return _srgb_decode(v)
    return np.power(v, SPACES[space]["gamma_u88"] / 256.0)


def _encode(v, space):
    """Linear 0..1 -> encoded."""
    if space == "sRGB":
        return _srgb_encode(v)
    return np.power(v, 256.0 / SPACES[space]["gamma_u88"])


def convert_colour(img, source, target):
    """img: float HxWx3 encoded 0..1 in `source` -> encoded 0..1 in `target`."""
    img = np.clip(img.astype(np.float64), 0.0, 1.0)
    if source == target:
        return img  # same space: values pass straight through, no clipping of gamut
    lin = _decode(img, source)
    M = np.linalg.inv(_to_d50(target)) @ _to_d50(source)
    out = np.clip(lin @ M.T, 0.0, 1.0)  # colours outside the target gamut are clipped
    return _encode(out, target)


def convert_from_srgb(img, space):
    """Backwards-compatible helper: sRGB -> space."""
    return convert_colour(img, "sRGB", space)


# ---------------------------------------------------------------------------
# ICC v2 matrix/TRC profile builder
# ---------------------------------------------------------------------------

def _s15f16(v):
    return struct.pack(">i", int(round(v * 65536)))


def _xyz_tag(xyz):
    return b"XYZ " + b"\0" * 4 + b"".join(_s15f16(c) for c in xyz)


def _desc_tag(text):
    a = text.encode("ascii") + b"\0"
    return (b"desc" + b"\0" * 4 + struct.pack(">I", len(a)) + a
            + struct.pack(">II", 0, 0) + struct.pack(">HB", 0, 0) + b"\0" * 67)


def _text_tag(text):
    return b"text" + b"\0" * 4 + text.encode("ascii") + b"\0"


def _curv_tag(space):
    g = SPACES[space]["gamma_u88"]
    if g is not None:
        return b"curv" + b"\0" * 4 + struct.pack(">IH", 1, g)
    # sRGB: 1024-point table
    x = np.linspace(0, 1, 1024)
    t = np.round(_srgb_decode(x) * 65535).astype(">u2").tobytes()
    return b"curv" + b"\0" * 4 + struct.pack(">I", 1024) + t


def build_icc(space):
    m = _to_d50(space)
    trc = _curv_tag(space)
    tags = [
        (b"desc", _desc_tag(space)),
        (b"cprt", _text_tag("No copyright, use freely")),
        (b"wtpt", _xyz_tag(D50)),
        (b"rXYZ", _xyz_tag(m[:, 0])),
        (b"gXYZ", _xyz_tag(m[:, 1])),
        (b"bXYZ", _xyz_tag(m[:, 2])),
        (b"rTRC", trc),
        (b"gTRC", trc),  # shared data
        (b"bTRC", trc),
    ]
    table_size = 4 + 12 * len(tags)
    offset = 128 + table_size
    table, data, seen = b"", b"", {}
    for sig, payload in tags:
        if payload in seen:
            off, size = seen[payload]
        else:
            while (offset + len(data)) % 4:
                data += b"\0"
            off, size = offset + len(data), len(payload)
            data += payload
            seen[payload] = (off, size)
        table += sig + struct.pack(">II", off, size)
    while len(data) % 4:
        data += b"\0"
    total = 128 + table_size + len(data)
    now = datetime.datetime.now(datetime.timezone.utc)
    header = (
        struct.pack(">I", total) + b"\0" * 4 + struct.pack(">I", 0x02100000)
        + b"mntr" + b"RGB " + b"XYZ "
        + struct.pack(">6H", now.year, now.month, now.day, now.hour, now.minute, now.second)
        + b"acsp" + b"APPL" + b"\0" * 4 + b"\0" * 8 + b"\0" * 8
        + struct.pack(">I", 0) + b"".join(_s15f16(c) for c in D50)
        + b"\0" * 4 + b"\0" * 16 + b"\0" * 28
    )
    assert len(header) == 128
    return header + struct.pack(">I", len(tags)) + table + data


# ---------------------------------------------------------------------------
# Minimal uncompressed 16-bit RGB TIFF writer (with ICC tag 34675)
# ---------------------------------------------------------------------------

def write_tiff16(path, rgb16, icc, dpi=300):
    h, w, c = rgb16.shape
    assert c == 3 and rgb16.dtype == np.uint16
    pixels = np.ascontiguousarray(rgb16, dtype="<u2")  # no copy on little-endian machines
    nbytes = pixels.nbytes
    if nbytes > 3_900_000_000:
        raise ValueError("Image too large for standard TIFF (>4GB). Reduce size or split.")

    software = b"ComfyUI Save TIFF 16-bit (Colour Managed)\0"
    entries = []  # (tag, type, count, value_bytes)
    SHORT, LONG, RATIONAL, ASCII, UNDEF = 3, 4, 5, 2, 7
    entries += [
        (256, LONG, 1, struct.pack("<I", w)),
        (257, LONG, 1, struct.pack("<I", h)),
        (258, SHORT, 3, struct.pack("<3H", 16, 16, 16)),
        (259, SHORT, 1, struct.pack("<H", 1)),         # no compression
        (262, SHORT, 1, struct.pack("<H", 2)),         # RGB
        (273, LONG, 1, None),                           # strip offset (filled later)
        (277, SHORT, 1, struct.pack("<H", 3)),
        (278, LONG, 1, struct.pack("<I", h)),
        (279, LONG, 1, struct.pack("<I", nbytes)),
        (282, RATIONAL, 1, struct.pack("<II", dpi, 1)),
        (283, RATIONAL, 1, struct.pack("<II", dpi, 1)),
        (284, SHORT, 1, struct.pack("<H", 1)),         # chunky
        (296, SHORT, 1, struct.pack("<H", 2)),         # inches
        (305, ASCII, len(software), software),
        (34675, UNDEF, len(icc), icc),
    ]
    n = len(entries)
    ifd_offset = 8
    ifd_size = 2 + 12 * n + 4
    extra_offset = ifd_offset + ifd_size
    extra = b""
    ifd = struct.pack("<H", n)
    strip_offset_pos = None
    for tag, typ, count, val in entries:
        if val is None:
            strip_offset_pos = len(ifd) + 8
            ifd += struct.pack("<HHI", tag, typ, count) + b"\0\0\0\0"
            continue
        if len(val) <= 4:
            ifd += struct.pack("<HHI", tag, typ, count) + val.ljust(4, b"\0")
        else:
            if (extra_offset + len(extra)) % 2:
                extra += b"\0"
            ifd += struct.pack("<HHI", tag, typ, count) + struct.pack("<I", extra_offset + len(extra))
            extra += val
    ifd += struct.pack("<I", 0)
    data_offset = extra_offset + len(extra)
    if data_offset % 2:
        extra += b"\0"
        data_offset += 1
    ifd = bytearray(ifd)
    ifd[strip_offset_pos:strip_offset_pos + 4] = struct.pack("<I", data_offset)

    with open(path, "wb") as f:
        f.write(b"II" + struct.pack("<HI", 42, ifd_offset))
        f.write(ifd)
        f.write(extra)
        pixels.tofile(f)


# ---------------------------------------------------------------------------
# ComfyUI node
# ---------------------------------------------------------------------------

class SaveTIFF16ColourManaged:
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    FUNCTION = "save"
    CATEGORY = "image/save"
    DESCRIPTION = ("Saves uncompressed 16-bit TIFFs converted from sRGB to Adobe RGB (1998), "
                   "ProPhoto RGB or sRGB, with the matching ICC profile embedded.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filename_prefix": ("STRING", {"default": "ComfyUI_TIFF16"}),
                "colour_profile": (["ProPhoto RGB", "Adobe RGB (1998)", "sRGB"],
                                   {"default": "ProPhoto RGB"}),
                "dpi": ("INT", {"default": 300, "min": 72, "max": 2400}),
            },
            "optional": {
                "source_colour_space": (["sRGB", "ProPhoto RGB", "Adobe RGB (1998)"], {
                    "default": "sRGB",
                    "tooltip": "Colour space of the image coming in. sRGB for AI images and ComfyUI's "
                               "Load Image. For camera TIFFs loaded with 'Load Image 16-bit TIFF', match "
                               "the file's profile (e.g. ProPhoto RGB from Lightroom)."}),
            },
        }

    def save(self, images, filename_prefix, colour_profile, dpi, source_colour_space="sRGB"):
        out_dir = folder_paths.get_output_directory()
        full_dir, fname, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, out_dir, images[0].shape[1], images[0].shape[0])
        icc = build_icc(colour_profile)
        tag = {"ProPhoto RGB": "ProPhoto", "Adobe RGB (1998)": "AdobeRGB", "sRGB": "sRGB"}[colour_profile]

        for img in images:
            print(f"[Save TIFF 16-bit] {source_colour_space} -> {colour_profile}, writing TIFF "
                  f"({img.shape[1]}x{img.shape[0]})... large prints can take a minute")
            arr = img.cpu().numpy()[..., :3]
            # Convert in strips of rows to keep memory low on very large prints (100MP+)
            h = arr.shape[0]
            rgb16 = np.empty(arr.shape, dtype=np.uint16)
            step = 256
            for y in range(0, h, step):
                conv = convert_colour(arr[y:y + step], source_colour_space, colour_profile)
                rgb16[y:y + step] = np.round(conv * 65535.0).astype(np.uint16)
            del arr
            file = f"{fname}_{counter:05}_{tag}_16bit.tif"
            write_tiff16(os.path.join(full_dir, file), rgb16, icc, dpi)
            print(f"[Save TIFF 16-bit] Saved {file} ({rgb16.shape[1]}x{rgb16.shape[0]}, {colour_profile})")
            counter += 1
        return {}


# ---------------------------------------------------------------------------
# Load Image 16-bit TIFF
# ---------------------------------------------------------------------------

def _profile_name(icc_bytes):
    """Human-readable ICC profile description, or None."""
    if not icc_bytes:
        return None
    try:
        import io
        from PIL import ImageCms
        return ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc_bytes))).strip()
    except Exception:
        return "unreadable profile"


def _guess_space(name):
    n = (name or "").lower()
    if "prophoto" in n or "romm" in n:
        return "ProPhoto RGB"
    if "adobe rgb" in n or "adobergb" in n or "compatible with adobe" in n:
        return "Adobe RGB (1998)"
    if "srgb" in n:
        return "sRGB"
    return None


def read_tiff(path):
    """Return (float32 HxWx3 array 0..1, bit depth, ICC bytes or None)."""
    try:
        import tifffile
    except ImportError:
        raise RuntimeError("Load Image 16-bit TIFF needs the 'tifffile' package. "
                           "Install it with: pip install tifffile imagecodecs")
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]  # Photoshop/Lightroom store the flattened image first
        if int(page.photometric) == 5:
            raise ValueError("This TIFF is CMYK. Convert it to RGB in Photoshop first.")
        tag = page.tags.get(34675)
        icc = bytes(tag.value) if tag is not None else None
        arr = page.asarray()

    if arr.ndim == 3 and arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
        arr = np.moveaxis(arr, 0, -1)  # planar -> interleaved
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)  # greyscale -> RGB
    arr = arr[..., :3]  # drop alpha / extra channels

    if arr.dtype == np.uint8:
        bits, out = 8, arr.astype(np.float32) / 255.0
    elif arr.dtype == np.uint16:
        bits, out = 16, arr.astype(np.float32) / 65535.0
    elif arr.dtype == np.uint32:
        bits, out = 32, (arr.astype(np.float64) / 4294967295.0).astype(np.float32)
    elif np.issubdtype(arr.dtype, np.floating):
        bits, out = 32, np.clip(arr.astype(np.float32), 0.0, 1.0)
    else:
        raise ValueError(f"Unsupported TIFF data type: {arr.dtype}")
    return np.ascontiguousarray(out), bits, icc


class LoadImage16bitTIFF:
    CATEGORY = "image"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "colour_space")
    FUNCTION = "load"
    DESCRIPTION = ("Loads a TIFF at full 8- or 16-bit precision (ComfyUI's Load Image reduces everything "
                   "to 8-bit) and reports the embedded colour profile. Put .tif files in ComfyUI/input.")

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir)
                 if os.path.isfile(os.path.join(input_dir, f)) and f.lower().endswith((".tif", ".tiff"))]
        return {"required": {"image": (sorted(files), {"image_upload": True})}}

    def load(self, image):
        import torch
        path = folder_paths.get_annotated_filepath(image)
        arr, bits, icc = read_tiff(path)
        name = _profile_name(icc)
        space = _guess_space(name)
        h, w = arr.shape[:2]
        print(f"[Load 16-bit TIFF] {image}: {w}x{h}, {bits}-bit, profile: {name or 'none embedded'}")
        if space and space != "sRGB":
            print(f"[Load 16-bit TIFF] >> Set 'source_colour_space' on Save TIFF 16-bit to: {space}")
        elif not space:
            print("[Load 16-bit TIFF] >> Profile not recognised. Export as ProPhoto RGB, Adobe RGB (1998) or sRGB.")
        return (torch.from_numpy(arr)[None, ...], space or "unknown")

    @classmethod
    def IS_CHANGED(cls, image):
        import hashlib
        h = hashlib.sha256()
        with open(folder_paths.get_annotated_filepath(image), "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True


NODE_CLASS_MAPPINGS = {
    "SaveTIFF16ColourManaged": SaveTIFF16ColourManaged,
    "LoadImage16bitTIFF": LoadImage16bitTIFF,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveTIFF16ColourManaged": "Save TIFF 16-bit (Colour Managed)",
    "LoadImage16bitTIFF": "Load Image 16-bit TIFF",
}
