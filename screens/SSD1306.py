#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/SSD1306.py

from PIL import Image, ImageDraw, ImageFont
from ..core_config import get_config
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306, ssd1309

# --- I2C serial interface ---
I2C_ADRESS = get_config("screen", "i2c_address", fallback="0x3C", type=str)
SERIAL = i2c(port=1, address=I2C_ADRESS)
disp = ssd1306(SERIAL)

# --- Exposed attributes for core_common ---
width = disp.width
height = disp.height
DIAG_INCH = 0.96
DISPLAY_FORMAT = "MONO"

# --- Logical drawing surface ---
image = Image.new("1", (width, height))  # mode "1" = monochrome
draw = ImageDraw.Draw(image)

# --- Rotation (ignore, fixed 128x64) ---
ROTATION = 0

# ---- Display functions ----
def refresh(img=None):
    """Send current buffer (PIL Image) to OLED."""
    img_to_send = img if img else image
    disp.display(img_to_send)

def clear_display():
    """Clear buffer and physical display."""
    draw.rectangle((0, 0, width, height), fill=0)
    refresh()

def poweroff_safe():
    """Best-effort power off."""
    if hasattr(disp, "poweroff"):
        disp.poweroff()

def poweron_safe():
    """Best-effort power on."""
    if hasattr(disp, "poweron"):
        disp.poweron()
