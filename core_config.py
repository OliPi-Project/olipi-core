#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

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
    """Write a value while preserving comments, structure, and spacing."""
    key = key.strip()
    value = str(value).strip()
    if not preserve_case:
        value = value.lower()

    section = section.lower()
    if not CONFIG_PATH.exists():
        # file doesn't exist → create with the section and key/value
        CONFIG_PATH.write_text(f"[{section}]\n{key} = {value}\n", encoding="utf-8")
        config.read(CONFIG_PATH)
        return

    lines = CONFIG_PATH.read_text(encoding="utf-8").splitlines()
    new_lines = []
    in_section = False
    key_written = False
    section_found = False

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # detect section header
        if stripped.startswith("[") and stripped.endswith("]"):
            # if leaving previous section and key not yet written → insert it
            if in_section and not key_written:
                # insert after last non-empty line in the section
                insert_idx = len(new_lines) - 1
                while insert_idx >= 0 and new_lines[insert_idx].strip() == "":
                    insert_idx -= 1
                new_lines.insert(insert_idx + 1, f"{key} = {value}")
                key_written = True

            current_section = stripped[1:-1].lower()
            in_section = (current_section == section)
            if in_section:
                section_found = True

            new_lines.append(line)
            continue

        if in_section:
            # update existing key if found
            if (stripped.startswith(f"{key}=") or stripped.startswith(f"{key} =")) and not key_written:
                new_lines.append(f"{key} = {value}")
                key_written = True
                continue

        new_lines.append(line)

    # if we ended inside section and key not yet written → insert at end
    if in_section and not key_written:
        insert_idx = len(new_lines) - 1
        while insert_idx >= 0 and new_lines[insert_idx].strip() == "":
            insert_idx -= 1
        new_lines.insert(insert_idx + 1, f"{key} = {value}")
        key_written = True

    # if section never existed → append at the end
    if not section_found:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")  # ensure separation from previous content
        new_lines.append(f"[{section}]")
        new_lines.append(f"{key} = {value}")

    # write back to file
    CONFIG_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    config.read(CONFIG_PATH)

def reload_config():
    config.read(CONFIG_PATH)
