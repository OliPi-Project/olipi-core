#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

import os
import configparser
from pathlib import Path

env_dir = os.getenv("OLIPI_DIR")
if env_dir:
    OLIPI_DIR = Path(env_dir).expanduser().resolve()
else:
    OLIPI_DIR = Path.cwd()

CONFIG_PATH = OLIPI_DIR / "config.ini"

config = configparser.ConfigParser()
config.read(CONFIG_PATH)

def get_config(section, key, fallback=None, type=str):
    try:
        if type == bool:
            return config.getboolean(section, key, fallback=fallback)
        elif type == int:
            return config.getint(section, key, fallback=fallback)
        elif type == float:
            return config.getfloat(section, key, fallback=fallback)
        else:
            return config.get(section, key, fallback=fallback)
    except Exception:
        return fallback

def save_config(key, value, section="settings", preserve_case=False):
    """Write a value while preserving comments and structure.
    - If key exists → replace it.
    - If missing → add just after the last line of the section.
    - Ensure there is a blank line before the next [section].
    """
    key = key.strip()
    value = str(value).strip()
    if not preserve_case:
        value = value.lower()

    section = section.lower()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(f"[{section}]\n{key} = {value}\n\n", encoding="utf-8")
        config.read(CONFIG_PATH)
        return

    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_section = False
    key_written = False
    section_found = False

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # New section begins
            if in_section and not key_written:
                # Insert key just before leaving the section
                new_lines.append(f"{key} = {value}")
                key_written = True
                # Ensure a blank line before the next section header
                if new_lines and new_lines[-1].strip() != "":
                    new_lines.append("")
            current_section = stripped[1:-1].lower()
            in_section = (current_section == section)
            if in_section:
                section_found = True
            new_lines.append(line)
            continue

        if in_section:
            # Replace existing key
            if (stripped.startswith(f"{key}=") or stripped.startswith(f"{key} =")) and not key_written:
                new_lines.append(f"{key} = {value}")
                key_written = True
                continue
        new_lines.append(line)

    # End of file
    if in_section and not key_written:
        new_lines.append(f"{key} = {value}")
    if not section_found:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append(f"[{section}]")
        new_lines.append(f"{key} = {value}")

    CONFIG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    config.read(CONFIG_PATH)

def reload_config():
    config.read(CONFIG_PATH)
