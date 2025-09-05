#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/ssd1306.py

from board import SCL, SDA
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# --- I2C pins ---
i2c = busio.I2C(SCL, SDA)

# --- Display init ---
disp = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)

# Dimensions
width, height = disp.width, disp.height
diag_inch = 0.96

# --- Image / Draw ---
image = Image.new("1", (width, height))
draw = ImageDraw.Draw(image)
Image = Image

DISPLAY_FORMAT = "MONO"

# --- Fonts core_common ---
font_title_menu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
font_item_menu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
font_message = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)

def refresh(img=None):
    """Display the current buffer or a provided image."""
    disp.image(img if img else image)
    disp.show()

def clear_display():
    """Clear the physical display (ignore buffer)."""
    disp.fill(0)
    disp.show()

def poweroff_safe():
    if hasattr(disp, "poweroff"):
        disp.poweroff()

def poweron_safe():
    if hasattr(disp, "poweron"):
        disp.poweron()

