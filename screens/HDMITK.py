#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2026 OliPi Project

import time
time.sleep(10)
import os
import subprocess
os.environ["DISPLAY"] = ":0"
import threading
import queue
import tkinter as tk
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk, ImageFont
from ..core_config import get_config

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

# --- Configuration screen size (logical UI) ---
ROTATION = get_config("screen", "rotation", fallback=0, type=int)
DISPLAY_FORMAT = get_config("screen", "display_format", fallback="RGB", type=str)
INVERT = get_config("screen", "invert", fallback=False, type=bool)
DIAG_INCH = get_config("screen", "diag", fallback=17.5, type=float)
# --- Physical screen size ---
PHYSICAL_WIDTH = get_config("screen", "width", fallback=640, type=int)
PHYSICAL_HEIGHT = get_config("screen", "height", fallback=280, type=int)

if ROTATION in (90, 270):
    width = PHYSICAL_HEIGHT
    height = PHYSICAL_WIDTH
else:
    width = PHYSICAL_WIDTH
    height = PHYSICAL_HEIGHT

# Logical PIL image & drawer
image = Image.new("RGB", (width, height))
draw = ImageDraw.Draw(image)

# Thread-safe queue for images to display
_img_queue = queue.Queue(maxsize=4)

# Window state
_root = None
_label = None
_photo = None

# initial window geometry
_win_x, _win_y = 100, 100
_win_w, _win_h = width, height

# minimum window size
_MIN_W = 160
_MIN_H = int(_MIN_W * (height / width))

# corner grab size in px
_CORNER_GRAB = 14

# interaction flags
_dragging = _resize_mode = False
_drag_start_x = _drag_start_y = 0
_drag_orig_x = _drag_orig_y = 0
_resize_orig_w = _resize_orig_h = 0
_resize_start_x = _resize_start_y = 0

# update interval
_UPDATE_MS = 50

# last window size (for smooth redraw)
_last_w, _last_h = width, height

# ------------------- Helpers -------------------

def _scale_and_letterbox(buf_img, target_w, target_h):
    """Scale buf_img preserving aspect ratio and letterbox into target size."""
    src_w, src_h = buf_img.size
    scale = min(target_w / src_w, target_h / src_h)
    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    resized = buf_img.resize((new_w, new_h), Image.LANCZOS)
    # create background and paste centered
    bg = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    bg.paste(resized, (x, y))

    # draw corner handle for resizing
    draw_corner = ImageDraw.Draw(bg)
    handle_size = 12
    draw_corner.polygon([
        (target_w-handle_size, target_h),
        (target_w, target_h),
        (target_w, target_h-handle_size)
    ], fill=(255, 255, 255, 200))
    return bg

# ------------------- Public API -------------------

def refresh(img: Image.Image = None):
    """Queue an image to display."""
    try:
        _img_queue.put_nowait(img.copy() if img is not None else image.copy())
    except queue.Full:
        try:
            _img_queue.get_nowait()
            _img_queue.put_nowait(img.copy() if img is not None else image.copy())
        except queue.Full:
            pass

def clear_display():
    draw.rectangle((0, 0, width, height), fill=(0, 0, 0))
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

# ------------------- UI Thread -------------------

def _on_button_press(event):
    global _dragging, _resize_mode, _drag_start_x, _drag_start_y
    global _drag_orig_x, _drag_orig_y, _resize_orig_w, _resize_orig_h
    global _resize_start_x, _resize_start_y

    x, y = event.x_root, event.y_root
    gw, gh = _root.winfo_width(), _root.winfo_height()
    gx, gy = _root.winfo_x(), _root.winfo_y()
    rel_x, rel_y = event.x, event.y

    # corner resize
    if (gw - rel_x) <= _CORNER_GRAB and (gh - rel_y) <= _CORNER_GRAB:
        _resize_mode = True
        _resize_start_x = x
        _resize_start_y = y
        _resize_orig_w = gw
        _resize_orig_h = gh
    else:
        _dragging = True
        _drag_start_x = x
        _drag_start_y = y
        _drag_orig_x = gx
        _drag_orig_y = gy

def _on_button_release(event):
    global _dragging, _resize_mode
    _dragging = _resize_mode = False

def _on_motion(event):
    global _dragging, _resize_mode, _drag_start_x, _drag_start_y
    global _drag_orig_x, _drag_orig_y, _resize_orig_w, _resize_orig_h
    global _resize_start_x, _resize_start_y

    x, y = event.x_root, event.y_root
    if _dragging:
        dx, dy = x - _drag_start_x, y - _drag_start_y
        new_x, new_y = _drag_orig_x + dx, _drag_orig_y + dy
        _root.geometry(f"{_root.winfo_width()}x{_root.winfo_height()}+{new_x}+{new_y}")
    elif _resize_mode:
        dx = x - _resize_start_x
        new_w = max(_MIN_W, _resize_orig_w + dx)
        aspect = height / width
        new_h = max(_MIN_H, int(new_w * aspect))
        _root.geometry(f"{new_w}x{new_h}+{_root.winfo_x()}+{_root.winfo_y()}")

def _update_loop():
    global _photo, _last_w, _last_h
    img = None
    try:
        while True:
            img = _img_queue.get_nowait()
    except queue.Empty:
        pass

    if img is not None:
        w, h = _root.winfo_width(), _root.winfo_height()
        # scale only if size changed or new image
        buf = _scale_and_letterbox(img, max(1, w), max(1, h))
        _photo = ImageTk.PhotoImage(buf)
        _label.config(image=_photo)

    _root.after(_UPDATE_MS, _update_loop)

def _ui_thread():
    global _root, _label, _photo
    _root = tk.Tk()
    _root.title("OliPi HDMI Overlay")
    _root.overrideredirect(True)
    _root.attributes("-topmost", True)
    _root.attributes("-alpha", 0.96)
    _root.configure(bg="black")
    _root.geometry(f"{_win_w}x{_win_h}+{_win_x}+{_win_y}")

    _label = tk.Label(_root, borderwidth=0, highlightthickness=0)
    _label.pack(fill="both", expand=True)

    _root.bind("<ButtonPress-1>", _on_button_press)
    _root.bind("<ButtonRelease-1>", _on_button_release)
    _root.bind("<B1-Motion>", _on_motion)

    _root.after(_UPDATE_MS, _update_loop)
    clear_display()

    try:
        _root.mainloop()
    except Exception:
        pass

# Start UI thread
_ui_thread_obj = threading.Thread(target=_ui_thread, daemon=True)
_ui_thread_obj.start()

# ------------------- Standalone test -------------------
if __name__ == "__main__":
    import random
    for i in range(300):
        draw.rectangle((0, 0, width, height), fill=(0, 0, 0))
        draw.text((20, 20), f"OliPi Overlay\nFrame {i}", fill=(255, 200, 0))
        refresh()
        time.sleep(0.05)
