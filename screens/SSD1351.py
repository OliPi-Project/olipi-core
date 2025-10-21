#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/SSD1351.py

import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from ..core_config import get_config
import numpy as _np

def get_fb():
    for fb in os.listdir("/sys/class/graphics"):
        with open(f"/sys/class/graphics/{fb}/name") as f:
            if f.read().strip() == "fb_ssd1351":
                return f"/dev/{fb}"
    return None

FB_DEVICE = get_fb()

# --- Overlay framebuffer size (from fbtft overlay) ---
FB_WIDTH = 128
FB_HEIGHT = 128

# --- Physical screen size ---
PHYSICAL_WIDTH = 128
PHYSICAL_HEIGHT = 128

ROTATION = get_config("screen", "rotation", fallback=0, type=int)  # must be (0,90,180,270)
DISPLAY_FORMAT = get_config("screen", "display_format", fallback="BGR", type=str)
INVERT = get_config("screen", "invert", fallback=False, type=bool)
DIAG_INCH = get_config("screen", "diag", fallback=1.5, type=float)

# Validate rotation
if ROTATION not in (0, 90, 180, 270):
    # clamp/normalize to nearest valid
    ROTATION = 0

# Logical (drawing) width/height as exposed to core_common must reflect rotation
if ROTATION in (90, 270):
    width = PHYSICAL_HEIGHT
    height = PHYSICAL_WIDTH
else:
    width = PHYSICAL_WIDTH
    height = PHYSICAL_HEIGHT

# Create an in-memory PIL image and a draw handle (these are the logical drawing surface)
image = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(image)

WRITE_BLOCK_ROWS = 8  # 4..16 is a good sweet spot

# reusable buffers (module-level)
_rgb565_buf = None  # will be a bytearray sized >= w*h*2

def _ensure_rgb565_buf(w, h):
    """Ensure _rgb565_buf exists and is large enough for w*h*2 bytes."""
    global _rgb565_buf
    needed = w * h * 2
    if (_rgb565_buf is None) or (len(_rgb565_buf) < needed):
        # allocate as bytearray to allow fast memoryview slices and direct assignment
        _rgb565_buf = bytearray(needed)

def _convert_image_to_rgb565_into_buf(buf_img):
    """
    Convert PIL Image (RGB) to RGB565 bytes placed into the preallocated
    bytearray _rgb565_buf. Returns a memoryview of the filled portion.
    Vectorised numpy conversion; assumes little-endian CPU (Raspberry Pi).
    """
    w, h = buf_img.size
    _ensure_rgb565_buf(w, h)

    # get raw RGB bytes from PIL (no extra conversions)
    raw = buf_img.tobytes("raw", "RGB")  # bytes object, contiguous
    arr = _np.frombuffer(raw, dtype=_np.uint8).reshape((h, w, 3))

    # vectorised conversion to RGB565 (uint16)
    r = arr[:, :, 0].astype(_np.uint16)
    g = arr[:, :, 1].astype(_np.uint16)
    b = arr[:, :, 2].astype(_np.uint16)

    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)   # uint16 array shape (h,w)
    # view as uint8 (native byteorder). On little-endian this yields lo,hi order.
    rgb8 = rgb565.view(_np.uint8).reshape(-1)

    # copy into preallocated bytearray (fast assignment)
    _rgb565_buf[:w * h * 2] = rgb8.tobytes()

    # return a memoryview to avoid extra copying by caller
    return memoryview(_rgb565_buf)[: w * h * 2]

def refresh(img: Image.Image = None):
    """
    Optimized partial refresh for small TFT:
     - rotate the logical image first (so rotation is preserved)
     - optionally invert colors if requested via config
     - scale down if necessary
     - convert only the rotated logical image to RGB565 (into reuse buffer)
     - write blocks of rows into /dev/fbN using os.lseek + os.write
    """
    buf_img = img if img is not None else image

    # apply rotation first so offsets/size reflect rotated image
    if ROTATION != 0:
        buf_img = buf_img.rotate(ROTATION, expand=True)

    # Optional inversion: flip colors if INVERT is True
    if INVERT:
        try:
            # ensure RGB for invert; convert back to RGB below for conversion function
            buf_img = ImageOps.invert(buf_img.convert("RGB"))
        except Exception as e:
            print("ST7789V color invert error:", e)

    w, h = buf_img.size

    # ensure the logical image fits into the framebuffer
    if w > FB_WIDTH or h > FB_HEIGHT:
        scale = min(FB_WIDTH / w, FB_HEIGHT / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        buf_img = buf_img.resize((new_w, new_h), Image.NEAREST)
        w, h = buf_img.size

    # compute centered offsets (works for rotated sizes too)
    x_off = (FB_WIDTH - w) // 2
    y_off = (FB_HEIGHT - h) // 2

    # convert logical region to rgb565 into shared buffer
    # ensure image is RGB for the converter (ImageOps.invert already returned RGB)
    if buf_img.mode != "RGB":
        buf_img = buf_img.convert("RGB")
    rgb565_mv = _convert_image_to_rgb565_into_buf(buf_img)  # memoryview on bytes

    line_bytes = w * 2
    fb_line_bytes = FB_WIDTH * 2

    # open FD once and write in blocks of WRITE_BLOCK_ROWS
    try:
        fd = os.open(FB_DEVICE, os.O_WRONLY)
        try:
            start = 0
            for row in range(0, h, WRITE_BLOCK_ROWS):
                block_rows = min(WRITE_BLOCK_ROWS, h - row)
                block_bytes = block_rows * line_bytes
                fb_offset = ((y_off + row) * FB_WIDTH + x_off) * 2
                os.lseek(fd, fb_offset, os.SEEK_SET)

                mv = rgb565_mv[start:start + block_bytes]
                # ensure full write (loop in case of partial writes)
                written = 0
                # memoryview supports slicing into bytes
                while written < len(mv):
                    wlen = os.write(fd, mv[written:])
                    if wlen == 0:
                        raise OSError("fb write returned 0")
                    written += wlen
                start += block_bytes
        finally:
            os.close(fd)
    except PermissionError:
        raise PermissionError(f"need root or write perm for {FB_DEVICE}")
    except OSError as e:
        try:
            print("refresh write error:", e)
        except Exception:
            pass

def clear_display():
    draw.rectangle((0, 0, width, height), fill=(0, 0, 0))
    refresh()

def poweroff_safe():
    clear_display()

def poweron_safe():
    refresh()
