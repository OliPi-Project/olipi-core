#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project
#
# test_prox.py
#
# Press Ctrl+C to exit.

import time
import os
from mpr121 import MPR121

# ------------------------------------------------------------
# Initialize MPR121 sensor
# ------------------------------------------------------------
sensor = MPR121(0x5A)
if not sensor.begin():
    raise RuntimeError("MPR121 initialization failed")

# Enable the 13th (virtual) electrode for proximity sensing
# Mode 0 = PROX_DISABLED = Disable the 13th virtual proximity electrode
# Mode 1 = PROX0_1 = use ELE0..ELE1 summed into 13th virtual proximity electrode
# Mode 2 = PROX0_3 = use ELE0..ELE3 summed into 13th virtual proximity electrode
# Mode 3 = PROX0_11 = use ELE0..ELE11 summed into 13th virtual proximity electrode
sensor.set_prox_mode(2)

# Set touch and release thresholds
# Touch threshold: higher = less sensitive
# Release threshold: should be slightly lower
touch_threshold = 20
release_threshold = 15
sensor.set_touch_threshold(touch_threshold)
sensor.set_release_threshold(release_threshold)

# Configure visualization settings
electrodes_range = range(13)  # 0–11 = touch electrodes, 12 = virtual proximity
max_bar = 40  # visualization bar width

# ANSI color codes for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

def clear_console():
    """Clear terminal for live updating."""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_color(diff):
    """Return color depending on touch strength."""
    if diff < touch_threshold / 2:
        return GREEN
    elif diff < touch_threshold:
        return YELLOW
    else:
        return RED

print("Starting MPR121 proximity/touch test. Press Ctrl+C to exit.")
time.sleep(2)

try:
    while True:
        # --------------------------------------------------------
        # Update all data from sensor (touch, baseline, filtered)
        # Can use update_all() instead
        # --------------------------------------------------------
        sensor.update_touch_data()
        sensor.update_baseline_data()
        sensor.update_filtered_data()

        clear_console()
        print("Elec | Touch | Diff | Visualization")
        print("-" * 60)

        for i in electrodes_range:
            # Read sensor data
            touch = int(sensor.get_touch_data(i))
            filtered = sensor.get_filtered_data(i)
            baseline = sensor.get_baseline_data(i)
            diff = baseline - filtered

            # Create a simple bar graph of the difference
            bar_len = int(max(0, min(max_bar, diff / 2)))
            bar = '#' * bar_len

            # Label the proximity electrode distinctly
            label = f"{i:2d}" + ("*" if i == 12 else " ")

            # Select color depending on difference
            color = get_color(diff)
            # Keep proximity (13th electrode) green when weak
            if i == 12 and diff < touch_threshold / 2:
                color = GREEN

            # Print one line per electrode
            print(f"{label:4} |  {color}{touch:2d}{RESET}   | {color}{diff:4d}{RESET} | {color}{bar}{RESET}")

        time.sleep(0.1)

except KeyboardInterrupt:
    print("\nExiting MPR121 proximity/touch test.")
