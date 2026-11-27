#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 OliPi Project

import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..core_config import get_config
import numpy as _np

FB_NAME = "vc4drmfb"
# --- Detect HDMI framebuffer ---
def get_hdmi_fb():
    for fb in os.listdir("/sys/class/graphics"):
        with open(f"/sys/class/graphics/{fb}/name") as f:
            if f.read().strip() == FB_NAME:
                return f"/dev/{fb}"
    return None

FB_DEVICE = get_hdmi_fb()
BACKLIGHT_PATH = f"/sys/class/backlight/{FB_NAME}/bl_power"

# --- Query actual framebuffer resolution ---
def get_fb_size(fb_dev):
    virtual_size_path = f"/sys/class/graphics/{os.path.basename(fb_dev)}/virtual_size"
    if os.path.exists(virtual_size_path):
        with open(virtual_size_path) as f:
            w, h = map(int, f.read().strip().split(","))
            return w, h
    return 1920, 1080  # default fallback

FB_WIDTH, FB_HEIGHT = get_fb_size(FB_DEVICE)
ROTATION = get_config("screen", "rotation", fallback=0, type=int)  # must be one of (0,90,180,270)
DISPLAY_FORMAT = get_config("screen", "display_format", fallback="RGB", type=str)
INVERT = get_config("screen", "invert", fallback=False, type=bool)
DIAG_INCH = get_config("screen", "diag", fallback=17.5, type=float)

# --- UI screen size ---
UI_WIDTH = get_config("screen", "width", fallback=800, type=int)
UI_HEIGHT = get_config("screen", "height", fallback=400, type=int)

# Rotation already gérée
if ROTATION in (90, 270):
    width = UI_HEIGHT
    height = UI_WIDTH
else:
    width = UI_WIDTH
    height = UI_HEIGHT

# Offsets pour centrer horizontalement et verticalement
X_OFFSET = (FB_WIDTH - width) // 2
Y_OFFSET = (FB_HEIGHT - height) // 2

# Image PIL logique
image = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(image)

# ---- Helpers: convert PIL -> framebuffer bytes (RGB565) ----
def _rgb_to_rgb565_bytes_numpy(img):
    arr = _np.asarray(img.convert("RGB"), dtype=_np.uint16)
    r = (arr[:, :, 0] & 0xF8).astype(_np.uint16)
    g = (arr[:, :, 1] & 0xFC).astype(_np.uint16)
    b = (arr[:, :, 2] >> 3).astype(_np.uint16)
    color = (r << 8) | (g << 3) | b
    lo = color & 0xFF
    hi = (color >> 8) & 0xFF
    packed = _np.dstack((lo, hi)).astype(_np.uint8)
    return packed.flatten().tobytes()

def refresh(img: Image.Image = None):
    """
    Partial write refresh:
    - rotate the logical image first (so rotation is preserved)
    - convert only the rotated logical image to RGB565
    - write only the rectangle centered in the framebuffer (line by line)
    """
    buf_img = img if img is not None else image

    # Apply rotation first so offsets/size reflect rotated image
    if ROTATION != 0:
        # expand=True ensures rotated image has correct dimensions
        buf_img = buf_img.rotate(ROTATION, expand=True)

    w, h = buf_img.size

    # Ensure the logical image fits into the framebuffer
    if w > FB_WIDTH or h > FB_HEIGHT:
        # optional: scale down to fit (nearest neighbour to keep pixel look)
        scale = min(FB_WIDTH / w, FB_HEIGHT / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        buf_img = buf_img.resize((new_w, new_h), Image.NEAREST)
        w, h = buf_img.size

    # Center the image on the FB
    x_off = (FB_WIDTH - w) // 2
    y_off = (FB_HEIGHT - h) // 2

    # Convert only the logical (rotated) image to RGB565 bytes
    rgb565 = _rgb_to_rgb565_bytes_numpy(buf_img)  # length == w*h*2

    # Strides (bytes per line)
    fb_line_bytes = FB_WIDTH * 2       # framebuffer line stride (bytes)
    img_line_bytes = w * 2             # image line stride (bytes)

    try:
        fd = os.open(FB_DEVICE, os.O_WRONLY)
        try:
            # Write row by row (avoid building full-FB buffer)
            # We can write each row in one os.write to reduce seeks.
            start = 0
            for row in range(h):
                # compute offset in bytes inside fb for this row
                fb_offset = ((y_off + row) * FB_WIDTH + x_off) * 2
                os.lseek(fd, fb_offset, os.SEEK_SET)

                row_start = start
                row_end = row_start + img_line_bytes
                # using memoryview avoids making copies
                mv = memoryview(rgb565)[row_start:row_end]
                os.write(fd, mv)
                start = row_end
        finally:
            os.close(fd)
    except PermissionError:
        raise PermissionError(f"need root or write perm for {FB_DEVICE}")
    except OSError as e:
        # catch partial writes / busy device
        if core.DEBUG:
            print("refresh write error:", e)

def clear_display():
    draw.rectangle((0, 0, FB_WIDTH, FB_HEIGHT), fill=(0, 0, 0))
    refresh()

def poweroff_safe():
    if os.path.exists(BACKLIGHT_PATH):
        try:
            subprocess.run(
                ["sudo", "tee", BACKLIGHT_PATH],
                input=b"1\n", check=False, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Backlight OFF failed for {FB_NAME}: {e.stderr.decode().strip()}")
    clear_display()

def poweron_safe():
    if os.path.exists(BACKLIGHT_PATH):
        try:
            subprocess.run(
                ["sudo", "tee", BACKLIGHT_PATH],
                input=b"0\n", check=False, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Backlight ON failed for {FB_NAME}: {e.stderr.decode().strip()}")
    refresh()

clear_display()
