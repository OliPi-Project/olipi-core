#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

# supported_screens.py

SCREEN_METADATA = {
    # key: canonical screen identifier used in config.ini
    # values: resolution, type ('i2c' or 'spi'), suggested driver filename and color format
    'SSD1306 0.96"':  {"resolution": "128x64 ",  "type": "i2c", "id": "SSD1306", "color": "MONO"},
    'SSD1315 0.96"':  {"resolution": "128x64 ",  "type": "i2c", "id": "SSD1306", "color": "MONO"},
    'SSD1309 2.49"':  {"resolution": "128x64 ",  "type": "i2c", "id": "SSD1306", "color": "MONO"},
    'SSD1351 1.5" ':  {"resolution": "128x128",  "type": "spi", "id": "SSD1351", "color": "RGB", "speed": "8000000", "txbuflen": "65536"},
    'ST7735 1.77" ':  {"resolution": "128x160",  "type": "spi", "id": "ST7735R", "color": "RGB", "speed": "14000000", "txbuflen": "65536"},
    'ST7789 1.9"  ':  {"resolution": "170x320",  "type": "spi", "id": "ST7789W", "color": "RGB", "speed": "64000000", "txbuflen": "262144"},
    'ST7789 2"    ':  {"resolution": "240x320",  "type": "spi", "id": "ST7789V", "color": "RGB", "speed": "64000000", "txbuflen": "262144"},
}
