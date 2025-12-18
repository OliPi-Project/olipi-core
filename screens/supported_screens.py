#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

SCREEN_METADATA = {
    'SSD1306/09/15 I2C       ':  {"resolution": "128x64 ",  "type": "i2c", "id": "SSD1306", "color": "MONO"},
    'SSD1306/09/15 SPI       ':  {"resolution": "128x64 ",  "type": "spi2c", "id": "SSD1306", "color": "MONO"},
    'SSD1351 1.5" SPI        ':  {"resolution": "128x128",  "type": "spi", "id": "SSD1351", "color": "BGR", "fbname": "ssd1351", "speed": "8000000", "txbuflen": "65536"},
    'ST7735 1.77" SPI        ':  {"resolution": "128x160",  "type": "spi", "id": "ST7735R", "color": "RGB", "fbname": "st7735r", "speed": "14000000", "txbuflen": "65536"},
    'ST7789 1.9" SPI         ':  {"resolution": "170x320",  "type": "spi", "id": "ST7789W", "color": "RGB", "fbname": "st7789v", "speed": "64000000", "txbuflen": "262144"},
    'ST7789 2"/2.4"/2.8" SPI ':  {"resolution": "240x320",  "type": "spi", "id": "ST7789V", "color": "RGB", "fbname": "st7789v", "speed": "64000000", "txbuflen": "262144"},
}
