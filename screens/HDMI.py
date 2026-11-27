#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 OliPi Project

import time
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

PERF_DEBUG = True
_perf_count = 0
_perf_total = 0.0
_perf_rotate = 0.0
_perf_resize = 0.0
_perf_convert = 0.0
_perf_write = 0.0

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

# Offsets for horizontal and vertical centering
X_OFFSET = (FB_WIDTH - width) // 2
Y_OFFSET = (FB_HEIGHT - height) // 2

# Logical PIL Image
image = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(image)

# reusable buffers (module-level)
_rgb565_buf = None # will be a bytearray sized >= w*h*2

def _ensure_rgb565_buf(size):
    global _rgb565_buf
    if _rgb565_buf is None or len(_rgb565_buf) < size:
        _rgb565_buf = bytearray(size)

# ---- Helpers: convert PIL -> framebuffer bytes (RGB565) ----
def _rgb_to_rgb565_bytes_numpy(img):
    w, h = img.size
    size = w * h * 2
    _ensure_rgb565_buf(size)
    # Direct Access to RGB Pixels
    raw = img.tobytes("raw", "RGB")
    arr = _np.frombuffer(raw, dtype=_np.uint8).reshape((h, w, 3))
    # RGB565 Conversion
    rgb565 = _np.frombuffer(_rgb565_buf, dtype=_np.uint16, count=w * h)
    r = arr[:, :, 0].astype(_np.uint16)
    g = arr[:, :, 1].astype(_np.uint16)
    b = arr[:, :, 2].astype(_np.uint16)
    rgb565[:] = (
        ((r & 0xF8) << 8) |
        ((g & 0xFC) << 3) |
        (b >> 3)
    ).reshape(-1)
    return memoryview(_rgb565_buf)[:size]

def refresh(img: Image.Image = None):
    global _perf_count, _perf_total
    global _perf_rotate, _perf_resize, _perf_convert, _perf_write

    perf_start = time.perf_counter() if PERF_DEBUG else 0

    buf_img = img if img is not None else image

    # Apply rotation first so offsets/size reflect rotated image
    t = time.perf_counter() if PERF_DEBUG else 0

    if ROTATION != 0:
        buf_img = buf_img.rotate(ROTATION, expand=True)

    if PERF_DEBUG:
        _perf_rotate += time.perf_counter() - t

    w, h = buf_img.size

    # Ensure the logical image fits into the framebuffer
    if w > FB_WIDTH or h > FB_HEIGHT:
        t = time.perf_counter()

        scale = min(FB_WIDTH / w, FB_HEIGHT / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        buf_img = buf_img.resize((new_w, new_h), Image.NEAREST)
        w, h = buf_img.size

        _perf_resize += time.perf_counter() - t

    # Center the image on the FB
    x_off = (FB_WIDTH - w) // 2
    y_off = (FB_HEIGHT - h) // 2

    # Convert only the logical (rotated) image to RGB565 bytes
    t = time.perf_counter()
    rgb565 = _rgb_to_rgb565_bytes_numpy(buf_img)
    if PERF_DEBUG:
        _perf_convert += time.perf_counter() - t

    fb_line_bytes = FB_WIDTH * 2
    img_line_bytes = w * 2

    t = time.perf_counter()

    try:
        fd = os.open(FB_DEVICE, os.O_WRONLY)
        try:
            start = 0
            for row in range(h):
                fb_offset = ((y_off + row) * FB_WIDTH + x_off) * 2
                os.lseek(fd, fb_offset, os.SEEK_SET)

                row_start = start
                row_end = row_start + img_line_bytes
                mv = memoryview(rgb565)[row_start:row_end]
                os.write(fd, mv)
                start = row_end
        finally:
            os.close(fd)
    except PermissionError:
        raise PermissionError(f"need root or write perm for {FB_DEVICE}")
    except OSError as e:
        print("refresh write error:", e)

    if PERF_DEBUG:
        _perf_write += time.perf_counter() - t

        _perf_count += 1
        _perf_total += time.perf_counter() - perf_start

        if _perf_count >= 100:
            n = _perf_count
            avg_total = _perf_total / n
            perf_total = time.perf_counter() - perf_start

            print(
                f"HDMI PERF ({w}x{h}, FB {FB_WIDTH}x{FB_HEIGHT}) | "
                f"avg_total={avg_total * 1000:.2f} ms "
                f"rotate={_perf_rotate / n * 1000:.2f} ms "
                f"resize={_perf_resize / n * 1000:.2f} ms "
                f"convert={_perf_convert / n * 1000:.2f} ms "
                f"write={_perf_write / n * 1000:.2f} ms "
                f"FPS={1 / avg_total:.1f} "
                f"perf_total={perf_total * 1000:.2f} ms "
            )

            _perf_count = 0
            _perf_total = 0.0
            _perf_rotate = 0.0
            _perf_resize = 0.0
            _perf_convert = 0.0
            _perf_write = 0.0
            
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
