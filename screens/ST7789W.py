#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# screens/ST7789W.py

import board
import digitalio
import adafruit_rgb_display.st7789 as st7789
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from ..core_config import get_config

# --- SPI pins ---
cs_gpio = get_config("screen", "cs_pin", fallback="8", type=int)
dc_gpio = get_config("screen", "dc_pin", fallback="23", type=int)
reset_gpio = get_config("screen", "reset_pin", fallback="24", type=int)
#bl_gpio = get_config("screen", "bl_pin", fallback="", type=int)

def gpio_to_board_pin(gpio: int):
    return getattr(board, f"D{gpio}")

CS_PIN = digitalio.DigitalInOut(gpio_to_board_pin(cs_gpio))
DC_PIN = digitalio.DigitalInOut(gpio_to_board_pin(dc_gpio))
RESET_PIN = digitalio.DigitalInOut(gpio_to_board_pin(reset_gpio))
#BL_PIN = digitalio.DigitalInOut(gpio_to_board_pin(bl_gpio))

BAUDRATE = get_config("screen", "baudrate", fallback=64000000, type=int)
ROTATION = get_config("screen", "rotation", fallback=90, type=int)

spi = board.SPI()

# --- Display init ---
disp = st7789.ST7789(
    spi,
    rotation=ROTATION,
    width=170,
    height=320,
    x_offset=35,
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

diag_inch = 1.9

# --- Image / Draw ---
image = Image.new('RGB', (width, height))
draw = ImageDraw.Draw(image)
Image = Image

DISPLAY_FORMAT = "RGB"

def refresh(img=None):
    """Display the current buffer or a provided image."""
    disp.image(img if img else image)

def clear_display():
    """Clear the physical display (ignore buffer)."""
    disp.fill(0)

def poweroff_safe():
    disp.write(st7789._DISPOFF)

def poweron_safe():
    disp.write(st7789._DISPON)

