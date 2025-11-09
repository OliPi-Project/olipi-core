#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

# screens/SSD1306SPI.py

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from ..core_config import get_config

def get_fb():
    for fb in os.listdir("/sys/class/graphics"):
        with open(f"/sys/class/graphics/{fb}/name") as f:
            if f.read().strip() == "fb_ssd1306":
                return f"/dev/{fb}"
    return None

FB_DEVICE = get_fb()

# --- Framebuffer size ---
FB_WIDTH = 128
FB_HEIGHT = 64

# --- Physical display size ---
PHYSICAL_WIDTH = 128
PHYSICAL_HEIGHT = 64
ROTATION = 0
DISPLAY_FORMAT = "MONO"
DIAG_INCH = 0.96

# Compute logical size
if ROTATION in (90, 270):
    width, height = PHYSICAL_HEIGHT, PHYSICAL_WIDTH
else:
    width, height = PHYSICAL_WIDTH, PHYSICAL_HEIGHT

# --- PIL image + draw context ---
# Use mode "1" (1-bit pixels, black and white)
image = Image.new("1", (width, height), 0)
draw = ImageDraw.Draw(image)

def refresh(img: Image.Image = None):
    """
    Refresh framebuffer with PIL monochrome image (1 bit per pixel).
    Automatically rotates if needed.
    """
    buf_img = img if img is not None else image

    if ROTATION != 0:
        buf_img = buf_img.rotate(ROTATION, expand=True)

    w, h = buf_img.size
    if w > FB_WIDTH or h > FB_HEIGHT:
        scale = min(FB_WIDTH / w, FB_HEIGHT / h)
        buf_img = buf_img.resize((int(w * scale), int(h * scale)), Image.NEAREST)
        w, h = buf_img.size

    # Convert PIL 1-bit image to packed bytes (8 pixels per byte)
    raw = buf_img.tobytes("raw", "1")

    # Center image vertically/horizontally
    x_off = (FB_WIDTH - w) // 2
    y_off = (FB_HEIGHT - h) // 2

    # Each line is FB_WIDTH bits = FB_WIDTH/8 bytes
    line_bytes = FB_WIDTH // 8
    try:
        fd = os.open(FB_DEVICE, os.O_WRONLY)
        try:
            # For each row, write 1-bit pixels (packed)
            for y in range(h):
                fb_offset = ((y_off + y) * line_bytes) + (x_off // 8)
                os.lseek(fd, fb_offset, os.SEEK_SET)
                start = y * (w // 8)
                os.write(fd, raw[start:start + (w // 8)])
        finally:
            os.close(fd)
    except PermissionError:
        raise PermissionError(f"need root or write perm for {FB_DEVICE}")
    except OSError as e:
        print("refresh write error:", e)

def clear_display():
    draw.rectangle((0, 0, width, height), fill=0)
    refresh()

def poweroff_safe():
    clear_display()

def poweron_safe():
    refresh()