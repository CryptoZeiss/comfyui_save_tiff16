"""
Save TIFF 16-bit (Colour Managed) — ComfyUI custom node
-------------------------------------------------------
Saves images as uncompressed 16-bit RGB TIFFs, converted from sRGB into
Adobe RGB (1998), ProPhoto RGB or sRGB, with a matching ICC profile embedded
so Photoshop / Lightroom / Capture One read the colour correctly.

Self-contained: needs only numpy (already part of ComfyUI). No extra installs.

Install: put this folder in ComfyUI/custom_nodes/ and restart ComfyUI.
Find it under: image > save > "Save TIFF 16-bit (Colour Managed)".
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


def convert_from_srgb(img, space):
    """img: float32 HxWx3 sRGB-encoded 0..1 -> target-space encoded 0..1."""
    img = np.clip(img.astype(np.float64), 0.0, 1.0)
    if space == "sRGB":
        return img
    lin = _srgb_decode(img)
    M = np.linalg.inv(_to_d50(space)) @ _to_d50("sRGB")
    out = lin @ M.T
    out = np.clip(out, 0.0, 1.0)  # sRGB sits inside both gamuts; clip guards rounding
    gamma = SPACES[space]["gamma_u88"] / 256.0
    return np.power(out, 1.0 / gamma)


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
    pixels = rgb16.astype("<u2").tobytes()
    if len(pixels) > 3_900_000_000:
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
        (279, LONG, 1, struct.pack("<I", len(pixels))),
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
        f.write(pixels)


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
            }
        }

    def save(self, images, filename_prefix, colour_profile, dpi):
        out_dir = folder_paths.get_output_directory()
        full_dir, fname, counter, subfolder, _ = folder_paths.get_save_image_path(
            filename_prefix, out_dir, images[0].shape[1], images[0].shape[0])
        icc = build_icc(colour_profile)
        tag = {"ProPhoto RGB": "ProPhoto", "Adobe RGB (1998)": "AdobeRGB", "sRGB": "sRGB"}[colour_profile]

        for img in images:
            arr = img.cpu().numpy()[..., :3]
            conv = convert_from_srgb(arr, colour_profile)
            rgb16 = np.round(conv * 65535.0).astype(np.uint16)
            file = f"{fname}_{counter:05}_{tag}_16bit.tif"
            write_tiff16(os.path.join(full_dir, file), rgb16, icc, dpi)
            print(f"[Save TIFF 16-bit] Saved {file} ({rgb16.shape[1]}x{rgb16.shape[0]}, {colour_profile})")
            counter += 1
        return {}


NODE_CLASS_MAPPINGS = {"SaveTIFF16ColourManaged": SaveTIFF16ColourManaged}
NODE_DISPLAY_NAME_MAPPINGS = {"SaveTIFF16ColourManaged": "Save TIFF 16-bit (Colour Managed)"}
