#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

# screens/SSD1306.py

from PIL import Image, ImageDraw, ImageFont
from ..core_config import get_config
from luma.core.interface.serial import i2c, spi
from luma.oled.device import ssd1306, ssd1309

CURRENT = get_config("screen", "current_screen", fallback="ssd1306", type=str).lower()
TYPE = get_config("screen", "type", fallback="i2c", type=str)

if TYPE.lower() == "spi2c":
    GPIO_DC = get_config("screen", "gpio_dc", fallback=24, type=int)
    GPIO_RST = get_config("screen", "gpio_rst", fallback=25, type=int)
    SERIAL = spi(device=0, port=0, gpio_DC=GPIO_DC, gpio_RST=GPIO_RST)
else:
    # --- I2C serial interface ---
    I2C_ADRESS = get_config("screen", "i2c_address", fallback="0x3C", type=str)
    SERIAL = i2c(port=1, address=I2C_ADRESS)

disp = ssd1306(SERIAL)

# --- Exposed attributes for core_common ---
width = get_config("screen", "width", fallback=128, type=int)
height = get_config("screen", "height", fallback=64, type=int)
DIAG_INCH = get_config("screen", "diag", fallback=0.96, type=float)
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
    """Turn off OLED display (luma.oled)."""
    try:
        disp.command(0xAE)  # DISPLAYOFF
    except Exception as e:
        print(f"Safe poweroff failed: {e}")

def poweron_safe():
    """Turn on OLED display (luma.oled)."""
    try:
        disp.command(0xAF)  # DISPLAYON
    except Exception as e:
        print(f"Safe poweron failed: {e}")
