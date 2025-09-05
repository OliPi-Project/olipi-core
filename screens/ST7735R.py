#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/ST7735R.py

import board
import digitalio
import adafruit_rgb_display.st7735 as st7735
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from ..core_config import get_config

# --- SPI pins ---
cs_pin_name = get_config("screen", "cs_pin", fallback="CE0", type=str).upper()
dc_pin_name = get_config("screen", "dc_pin", fallback="D23", type=str).upper()
reset_pin_name = get_config("screen", "reset_pin", fallback="D24", type=str).upper()
#bl_pin_name = get_config("screen", "bl_pin", fallback="D24", type=str).upper()

CS_PIN = digitalio.DigitalInOut(getattr(board, cs_pin_name))
DC_PIN = digitalio.DigitalInOut(getattr(board, dc_pin_name))
RESET_PIN = digitalio.DigitalInOut(getattr(board, reset_pin_name))
#BL_PIN = digitalio.DigitalInOut(getattr(board, bl_pin_name))

BAUDRATE = get_config("screen", "baudrate", fallback=14000000, type=int)
ROTATION = get_config("screen", "rotation", fallback=270, type=int)

spi = board.SPI()

# --- Display init ---
disp = st7735.ST7735R(
    spi,
    rotation=ROTATION,
    cs=CS_PIN,
    dc=DC_PIN,
    rst=RESET_PIN,
    baudrate=BAUDRATE,
)

# Dimensions
if disp.rotation % 180 == 90:
    height = disp.width
    width = disp.height
else:
    width = disp.width
    height = disp.height

diag_inch = 1.77

# --- Image / Draw ---
image = Image.new('RGB', (width, height))
draw = ImageDraw.Draw(image)
Image = Image

DISPLAY_FORMAT = "BGR"

# --- Fonts core_common ---
font_title_menu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
font_item_menu = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
font_message = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)

def refresh(img=None):
    """Display the current buffer or a provided image."""
    disp.image(img if img else image)

def clear_display():
    """Clear the physical display (ignore buffer)."""
    disp.fill(0)
    #disp.image(image)

def poweroff_safe():
    #draw.rectangle((0, 0, width, height), fill=(0, 0, 0))
    #refresh()
    disp.write(st7735._DISPOFF)

def poweron_safe():
    disp.write(st7735._DISPON)

