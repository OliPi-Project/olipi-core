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
    """Write a value while preserving comments, section structure, and proper spacing."""
    key = key.strip()
    value = str(value).strip()
    if not preserve_case:
        value = value.lower()

    section_lower = section.lower()
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(f"[{section}]\n{key} = {value}\n", encoding="utf-8")
        config.read(CONFIG_PATH)
        return

    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_section = False
    key_written = False
    section_found = False
    last_nonempty_idx = None  # index of last non-empty line in section

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("[") and stripped.endswith("]"):
            # If we leave a section and key wasn't written yet
            if in_section and not key_written:
                insert_idx = last_nonempty_idx + 1 if last_nonempty_idx is not None else len(new_lines)
                new_lines.insert(insert_idx, f"{key} = {value}")
                key_written = True

            current_section = stripped[1:-1].lower()
            in_section = (current_section == section_lower)
            if in_section:
                section_found = True
                last_nonempty_idx = None
            new_lines.append(line)
            continue

        if in_section:
            if stripped != "":
                last_nonempty_idx = len(new_lines)
            if (stripped.startswith(f"{key}=") or stripped.startswith(f"{key} =")) and not key_written:
                new_lines[last_nonempty_idx] = f"{key} = {value}"
                key_written = True
                continue

        new_lines.append(line)

    # If we were still in section at EOF and key not written
    if in_section and not key_written:
        insert_idx = last_nonempty_idx + 1 if last_nonempty_idx is not None else len(new_lines)
        new_lines.insert(insert_idx, f"{key} = {value}")
        key_written = True

    # Section completely missing
    if not section_found:
        new_lines.append(f"\n[{section}]")
        new_lines.append(f"{key} = {value}")

    CONFIG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    config.read(CONFIG_PATH)

def reload_config():
    config.read(CONFIG_PATH)
