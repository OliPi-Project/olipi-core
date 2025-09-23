#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/ST7789W.py
# Write PIL images directly to framebuffer (/dev/fbN) for fbtft overlays.
# Requires numpy, handles resolution + rotation.

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..core_config import get_config
import numpy as _np

def get_oled_fb():
    for fb in os.listdir("/sys/class/graphics"):
        with open(f"/sys/class/graphics/{fb}/name") as f:
            if f.read().strip() == "fb_st7789v":
                return f"/dev/{fb}"
    return None

FB_DEVICE = get_oled_fb()
FB_ENDIAN = "little"  # 'little' or 'big' or 'native'

# --- Overlay framebuffer size (from fbtft overlay) ---
FB_WIDTH = 240
FB_HEIGHT = 320

# --- Physical screen size ---
PHYSICAL_WIDTH = 170
PHYSICAL_HEIGHT = 320
ROTATION = get_config("screen", "rotation", fallback=270, type=int)
DISPLAY_FORMAT = get_config("screen", "display_format", fallback="RGB", type=str)
DIAG_INCH = 1.9  # can be adjusted

# Validate rotation
if ROTATION not in (0, 90, 180, 270):
    ROTATION = 0

# Logical drawing surface
if ROTATION in (90, 270):
    width = PHYSICAL_HEIGHT
    height = PHYSICAL_WIDTH
else:
    width = PHYSICAL_WIDTH
    height = PHYSICAL_HEIGHT

# Offset for centering horizontal
X_OFFSET = (FB_WIDTH - PHYSICAL_WIDTH) // 2

# In-memory PIL image + draw handle
image = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(image)

# ---- Helpers: convert PIL -> framebuffer bytes (RGB565) ----
def _rgb_to_rgb565_bytes_numpy(img):
    """Convert PIL image to RGB565 bytes with chosen endian."""
    arr = _np.asarray(img.convert("RGB"), dtype=_np.uint16)
    r = (arr[:, :, 0] & 0xF8).astype(_np.uint16)
    g = (arr[:, :, 1] & 0xFC).astype(_np.uint16)
    b = (arr[:, :, 2] >> 3).astype(_np.uint16)
    color = (r << 8) | (g << 3) | b

    if FB_ENDIAN == "big":
        hi = (color >> 8) & 0xFF
        lo = color & 0xFF
        packed = _np.dstack((hi, lo)).astype(_np.uint8)
    else:
        lo = color & 0xFF
        hi = (color >> 8) & 0xFF
        packed = _np.dstack((lo, hi)).astype(_np.uint8)
    return packed.flatten().tobytes()

def pil_to_fb_bytes(img):
    out_img = img
    if ROTATION != 0:
        out_img = img.rotate(ROTATION, expand=True)
    ow, oh = out_img.size
    x_off = (FB_WIDTH - ow) // 2 if FB_WIDTH > ow else 0
    y_off = (FB_HEIGHT - oh) // 2 if FB_HEIGHT > oh else 0

    fb_img = Image.new("RGB", (FB_WIDTH, FB_HEIGHT), (0, 0, 0))
    fb_img.paste(out_img, (x_off, y_off))
    return _rgb_to_rgb565_bytes_numpy(fb_img)

def refresh(img=None):
    buf_img = img if img is not None else image
    fb_bytes = pil_to_fb_bytes(buf_img)
    try:
        fd = os.open(FB_DEVICE, os.O_WRONLY)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            total = 0
            chunk_size = 65536
            while total < len(fb_bytes):
                end = min(total + chunk_size, len(fb_bytes))
                written = os.write(fd, fb_bytes[total:end])
                if written == 0:
                    break
                total += written
        finally:
            os.close(fd)
    except PermissionError:
        raise PermissionError(f"need root or write perm for {FB_DEVICE}")
    except Exception:
        raise

def clear_display():
    draw.rectangle((0, 0, width, height), fill=(0, 0, 0))
    refresh()

def poweroff_safe():
    clear_display()

def poweron_safe():
    refresh()
