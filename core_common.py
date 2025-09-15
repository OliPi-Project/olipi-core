#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

import os
import time
import yaml
import threading
from pathlib import Path
from .core_config import config, get_config, save_config, reload_config
from importlib import import_module
from olipi_core import screens

env_dir = os.getenv("OLIPI_DIR")
if env_dir:
    OLIPI_DIR = Path(env_dir).expanduser().resolve()
else:
    OLIPI_DIR = Path.cwd()

THEME_PATH = OLIPI_DIR / "theme_colors.yaml"

OLIPICORE_DIR = Path(__file__).resolve().parent
MASK_PATH = OLIPICORE_DIR / "mask.png"

SCREEN_TYPE = get_config("screen", "current_screen", fallback="SSD1306", type=str).upper()
screen = import_module(f"olipi_core.screens.{SCREEN_TYPE}")

# --- Wrappers / Shortcuts ---
#disp = screen.disp
image = screen.image
draw = screen.draw
Image = screen.Image
width  = screen.width
height = screen.height
diag_inch = screen.DIAG_INCH

refresh = screen.refresh
clear_display = screen.clear_display
poweroff_safe = screen.poweroff_safe
poweron_safe = screen.poweron_safe

display_format = getattr(screen, "DISPLAY_FORMAT", "MONO")

clear_display()

DEBUG = get_config("settings", "debug", fallback=False, type=bool)
LANGUAGE = get_config("settings", "language", fallback="en", type=str)
SCREEN_TIMEOUT = get_config("settings", "screen_timeout", fallback=0, type=int)

ppi = (width**2 + height**2)**0.5 / diag_inch
BASE_PPI = 150
def get_font(path, base_size):
    # petits écrans → garder taille originale
    if ppi <= BASE_PPI:
        return screen.ImageFont.truetype(str(path), base_size)

    # sinon → scale proportionnel au PPI
    scale = min((ppi / BASE_PPI) * 1.2, 1.6)
    size = max(8, int(base_size * scale))
    return screen.ImageFont.truetype(str(path), size)


font_title_menu = get_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
font_item_menu = get_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)
font_message = get_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 11)

def get_rpi_model():
    model_path = Path("/proc/device-tree/model")
    try:
        with model_path.open("r") as f:
            return f.read().strip("\x00\n ")
    except Exception:
        return "Unknown"

def detect_refresh_interval():
    if config.has_option("screen", "refresh_interval"):
        return get_config("screen", "refresh_interval", type=float)
    model = get_rpi_model()
    if "Zero 2" in model:
        return 0.03 if ppi >= BASE_PPI else 0.05
    elif "Raspberry Pi 3" in model:
        return 0.03 if ppi >= BASE_PPI else 0.05
    elif "Raspberry Pi 4" in model:
        return 0.1
    elif "Raspberry Pi 5" in model:
        return 0.1
    else:
        return 0.03
REFRESH_INTERVAL = detect_refresh_interval()

THEME_NAME = get_config("settings", "color_theme", fallback="default", type=str)
if display_format.upper() == "MONO":
    THEME_NAME = "default"

def load_theme_file():
    if not THEME_PATH.exists():
        print("Theme file missing")
        return {}
    with open(THEME_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

# --- Color handling ---
def load_theme(theme_name="default"):
    themes = load_theme_file()
    theme = themes.get(theme_name, themes.get("default", {}))

    colors = theme.get("colors", {})
    for key, val in colors.items():
        globals()["COLOR_" + key.upper()] = get_color(tuple(val))

def get_color(color):
    """Return color adapted to the screen's pixel format (RGB, BGR, MONO)."""
    # Monochrome screen
    if display_format.upper() == "MONO":
        if isinstance(color, int):
            return color  # Already 0..255
        elif isinstance(color, tuple) and len(color) == 3:
            r, g, b = color
            # Convert to grayscale luminance
            return int(0.299*r + 0.587*g + 0.114*b)
        else:
            return 255  # fallback = white
    # RGB screen
    if display_format.upper() == "RGB":
        return color
    # BGR screen
    if display_format.upper() == "BGR":
        if isinstance(color, tuple) and len(color) == 3:
            r, g, b = color
            return (b, g, r)
        else:
            return color
    # Unknown case, return as is
    return color

load_theme(THEME_NAME)

message_text = None
message_start_time = 0
message_permanent = False
scroll_offset_message = 0
scroll_speed_message = 1
last_scroll_time = 0
scroll_delay = 0.05

SCROLL_SPEED_MENU = 0.1
SCROLL_SPEED_LINEAR = 0.05
SCROLL_TITLE_PADDING_END = 20

scroll_state = {
    "menu_title": {"offset": 0, "last_update": time.time()},
    "menu_item": {"offset": 0, "last_update": time.time(), "phase": "pause_start", "pause_start_time": time.time()},
    "message": {"offset": 0, "direction": 1, "last_update": time.time(), "total_lines": 0, "max_visible_lines": 0}
}

def reset_scroll(*keys):
    now = time.time()
    for key in keys:
        state = scroll_state.get(key)
        if state:
            state["offset"] = 0
            state["direction"] = 1
            state["pause"] = False
            state["pause_start_time"] = now
            state["phase"] = "pause_start"

translations = {}
def load_translations(script_name="script"):
    global translations
    translations.clear()

    lang_dir = OLIPI_DIR / "language"
    selected_file = lang_dir / f"{script_name}_{LANGUAGE}.yaml"
    fallback_file = lang_dir / f"{script_name}_en.yaml"

    if selected_file.exists():
        with open(selected_file, "r", encoding="utf-8") as f:
            translations.update(yaml.safe_load(f) or {})
    elif fallback_file.exists():
        print(f"Translation file not found: {selected_file.name}, using fallback: {fallback_file.name}")
        with open(fallback_file, "r", encoding="utf-8") as f:
            translations.update(yaml.safe_load(f) or {})
    else:
        print(f"No translation file found for script: {script_name}")

def t(key, **kwargs):
    template = translations.get(key, key)
    try:
        return template.format(**kwargs)
    except KeyError as e:
        if DEBUG:
            print(f"Missing placeholder {e} in key '{key}'")
        return template

def draw_custom_menu(options, selection, title="Menu", multi=None, checkmark="✓ "):
    """Full-width menu, spacing/scroll dynamic, fixed line height, selection rectangle aligned to text."""
    global scroll_state
    now = time.time()

    # --- Panel geometry (full screen) ---
    menu_width = width
    border = 1
    padding_x = max(1, int(menu_width * 0.02))
    padding_y = max(1, int(height * 0.01))

    # --- Title & linear scroll ---
    state_t = scroll_state["menu_title"]
    title_w = draw.textlength(title, font=font_title_menu)
    bbox_title = font_title_menu.getbbox("Ay")
    title_h = bbox_title[3] - bbox_title[1]

    inner_width_guess = menu_width - 2 * (border + padding_x)
    if title_w > inner_width_guess and now - state_t.get("last_update", 0) > SCROLL_SPEED_LINEAR:
        scroll_w = title_w + SCROLL_TITLE_PADDING_END
        state_t["offset"] = (state_t.get("offset", 0) + 1) % scroll_w
        state_t["last_update"] = now
    else:
        state_t.setdefault("offset", 0)

    # --- Title → items spacing based on screen height ---
    if height <= 64:
        spacing_title_items = 5
        padding_item = 1
    elif height < 128:
        spacing_title_items = 5
        padding_item = 2
    else:
        spacing_title_items = 6
        padding_item = 2

    # --- Fixed line metrics ("Ay") ---
    item_bbox = font_item_menu.getbbox("Ay")
    item_h = item_bbox[3] - item_bbox[1]
    line_height = item_h + padding_item

    # --- Number of visible lines (include borders + paddings) ---
    avail_height_for_items = height - (border + padding_y + title_h + spacing_title_items + padding_y + border)
    max_lines_fit = max(1, avail_height_for_items // line_height)
    visible_lines = min(len(options), max_lines_fit)

    # --- Panel dimensions & vertical centering ---
    menu_inner_height = title_h + spacing_title_items + visible_lines * line_height + 2 * padding_y
    MENU_HEIGHT = menu_inner_height + 2 * border
    y0 = max(0, (height - MENU_HEIGHT) // 2)
    x0 = 0

    # --- Draw panel ---
    draw.rectangle((0, 0, width, height), fill=COLOR_BG)
    draw.rectangle((x0, y0, x0 + menu_width - 1, y0 + MENU_HEIGHT - 1),
                   outline=COLOR_MENU_OUTLINE, fill=COLOR_MENU_BG)

    inner_x = x0 + border + padding_x
    inner_y = y0 + border + padding_y
    inner_width = menu_width - (border + padding_x + border)

    # --- Draw title (centered / scroll) ---
    title_y = inner_y
    if title_w <= inner_width:
        x_title = inner_x + (inner_width - title_w) // 2
        draw.text((x_title, title_y), title, font=font_title_menu, fill=COLOR_MENU_TITLE)
    else:
        off = state_t["offset"]
        draw.text((inner_x - off, title_y), title, font=font_title_menu, fill=COLOR_MENU_TITLE)
        draw.text((inner_x - off + title_w + SCROLL_TITLE_PADDING_END, title_y),
                  title, font=font_title_menu, fill=COLOR_MENU_TITLE)

    # --- Compute visible window of items (center selection) ---
    start_idx = max(0, selection - visible_lines // 2)
    if start_idx + visible_lines > len(options):
        start_idx = max(0, len(options) - visible_lines)

    list_y0 = inner_y + title_h + spacing_title_items

    for i in range(visible_lines):
        idx = start_idx + i
        if idx >= len(options):
            break

        entry = options[idx]
        label = entry[0] if isinstance(entry, tuple) else entry
        prefix = checkmark if (multi and label in multi) else ""
        full_txt = prefix + label

        y_item = list_y0 + i * line_height
        text_y = y_item + (line_height - item_h) // 2 - item_bbox[1]
        x_text_base = inner_x

        if idx == selection:
            # --- Smooth adaptive scroll (pause → scroll → pause) ---
            state_i = scroll_state["menu_item"]
            text_w = draw.textlength(full_txt, font=font_item_menu)
            avail = inner_width - padding_x

            if text_w > avail:
                # Adaptive scroll speed
                BASE_INTERVAL = SCROLL_SPEED_MENU
                MIN_INTERVAL = 0.05
                MAX_INTERVAL = 0.12
                PAUSE_DURATION = 0.6
                BLANK_DURATION = 0.2
                ratio = text_w / float(avail)
                interval = BASE_INTERVAL / max(0.001, ratio)
                scroll_speed = max(MIN_INTERVAL, min(MAX_INTERVAL, interval))

                phase = state_i.get("phase", "pause_start")
                if phase == "pause_start":
                    state_i["offset"] = 0
                    if now - state_i.get("pause_start_time", 0) > PAUSE_DURATION:
                        state_i["phase"] = "scrolling"
                        state_i["last_update"] = now

                elif phase == "scrolling":
                    if now - state_i.get("last_update", 0) > scroll_speed:
                        state_i["offset"] += 1
                        state_i["last_update"] = now
                        if state_i["offset"] >= (text_w - avail):
                            # enter pause_end and mark its start
                            state_i["phase"] = "pause_end"
                            state_i["pause_start_time"] = now

                elif phase == "pause_end":
                    # compute elapsed in pause_end
                    elapsed = now - state_i.get("pause_start_time", 0)
                    # if pause_end completed, reset to pause_start
                    if elapsed >= PAUSE_DURATION:
                        state_i["offset"] = 0
                        state_i["phase"] = "pause_start"
                        state_i["pause_start_time"] = now
                    # else: keep offset at end (no change) and show text normally
            else:
                # text fits; reset
                state_i["offset"] = 0
                state_i["phase"] = "pause_start"
                state_i["pause_start_time"] = now

            # compute x_text once
            off = state_i.get("offset", 0)
            x_text = x_text_base - off if text_w > avail else x_text_base

            # selection rectangle (always shown)
            sel_top = text_y + item_bbox[1] - 3
            sel_bot = text_y + item_bbox[3]
            sel_x0 = x0 + border - 1
            sel_x1 = x0 + menu_width - border
            draw.rectangle((sel_x0, sel_top, sel_x1, sel_bot),
                        outline=COLOR_MENU_OUTLINE, fill=COLOR_MENU_SELECTED_BG)

            # determine whether to draw text:
            draw_text = True
            if state_i.get("phase") == "pause_end":
                elapsed = now - state_i.get("pause_start_time", 0)
                # hide text only during the short BLANK_DURATION at the end of the pause
                if elapsed >= (PAUSE_DURATION - BLANK_DURATION) and elapsed < PAUSE_DURATION:
                    draw_text = False

            if draw_text:
                draw.text((x_text, text_y), full_txt, font=font_item_menu, fill=COLOR_MENU_SELECTED_TEXT)
            # else: skip drawing text -> creates the brief disappearance just before reset
        else:
            draw.text((x_text_base, text_y), full_txt, font=font_item_menu, fill=COLOR_MENU_TEXT)

def compute_message_layout(text):
    # dynamic paddings / margins based on screen
    margin = max(1, int(width * 0.02))
    padding_x = max(2, int(width * 0.04))
    padding_y = max(2, int(height * 0.02))

    # maximum box width inside screen margins
    max_box_w = max(80, width - 2 * margin)

    # measure full text width (single-line)
    test_w = draw.textlength(text, font=font_message)

    # choose box width: either snug to text or clamp to max_box_w
    if test_w + 2 * padding_x <= max_box_w:
        box_w = test_w + 2 * padding_x
    else:
        box_w = max_box_w

    # wrap words to lines using the available inner width
    inner_w = box_w - 2 * padding_x
    words = text.strip().split()
    lines = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w) if cur else w
        # measure candidate width using font getbbox
        w_box = font_message.getbbox(candidate)
        w_len = w_box[2] - w_box[0]
        if w_len <= inner_w:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    # line height metric (stable baseline using "Ay")
    line_h = font_message.getbbox("Ay")[3] - font_message.getbbox("Ay")[1] + 2
    total_text_height = len(lines) * line_h
    # single line -> more padding, multi-line -> normal
    if len(lines) == 1:
        padding_y = max(padding_y, line_h)

    # --- compute message box height (adapt to text, but clamp) ---
    # desired height: text height + vertical paddings
    desired_h = total_text_height + 2 * padding_y

    # min/max height
    min_box_h = line_h + 2 * padding_y
    max_box_h = height - 2 * margin

    MESS_HEIGHT = max(min_box_h, min(desired_h, max_box_h))

    return {
        "width": box_w,
        "padding_x": padding_x,
        "padding_y": padding_y,
        "lines": lines,
        "line_height": line_h,
        "total_text_height": total_text_height,
        "MESS_HEIGHT": MESS_HEIGHT,
    }

def show_message(text, permanent=False):
    """Prepare message to display (timed or permanent)."""
    global message_text, message_start_time, message_permanent
    message_permanent = permanent
    message_text = text

    if permanent:
        message_start_time = float('inf')
        return

    # compute layout so we know number of lines and duration
    layout = compute_message_layout(text)
    lines = layout["lines"]

    per_line = 2.0
    duration = min(max(len(lines) * per_line, 2.0), 30.0)
    message_start_time = time.time() + duration

def draw_message():
    """Draw currently active message centered on screen with adaptive box sizing."""
    global scroll_offset_message, last_scroll_time

    if not message_text:
        return

    # compute layout (must match show_message)
    layout = compute_message_layout(message_text)
    MESS_WIDTH = layout["width"]
    MESS_HEIGHT = layout["MESS_HEIGHT"]
    MESS_PADDING_X = layout["padding_x"]
    MESS_PADDING_Y = layout["padding_y"]
    lines = layout["lines"]
    line_h = layout["line_height"]
    total_text_height = layout["total_text_height"]

    # compute box origin (centered horizontally). Center vertically for nicer look.
    x0 = (width - MESS_WIDTH) // 2
    y0 = max(2, (height - MESS_HEIGHT) // 2)  # change to y0 = 2 if you prefer top-aligned box

    # handle vertical auto-scroll if text too tall for the box inner height
    inner_box_h = MESS_HEIGHT - 2 * MESS_PADDING_Y
    now = time.time()
    if total_text_height > inner_box_h:
        # initialize last_scroll_time if unset
        if last_scroll_time == 0:
            last_scroll_time = now
        if now - last_scroll_time >= scroll_delay:
            scroll_offset_message = (scroll_offset_message + scroll_speed_message) % (total_text_height + MESS_PADDING_Y)
            last_scroll_time = now
        y_start = y0 + MESS_PADDING_Y - scroll_offset_message
    else:
        # center text vertically inside the box
        scroll_offset_message = 0
        y_start = y0 + (MESS_HEIGHT - total_text_height) // 2

    # draw background under message box
    if display_format.upper() == "MONO":
        draw.rectangle((0, 0, width, height), fill=COLOR_BG)
    else:
        mask_overlay()
    # draw box and then lines that fall inside visible area
    draw.rectangle((x0, y0, x0 + MESS_WIDTH, y0 + MESS_HEIGHT), outline=COLOR_MESSAGE_OUTLINE, fill=COLOR_MESSAGE_BG)

    for i, ln in enumerate(lines):
        y = y_start + i * line_h
        # only draw lines that fit inside the inner area
        if y >= y0 + MESS_PADDING_Y and y + line_h <= y0 + MESS_HEIGHT - MESS_PADDING_Y:
            w_box = font_message.getbbox(ln)
            text_w = w_box[2] - w_box[0]
            x_text = x0 + (MESS_WIDTH - text_w) // 2
            draw.text((x_text, y), ln, font=font_message, fill=COLOR_MESSAGE_TEXT)

def message_updater():
    global message_text, message_start_time, scroll_offset_message, message_permanent
    while True:
        if message_text and not message_permanent and time.time() >= message_start_time:
            message_text = None
            scroll_offset_message = 0
        time.sleep(1)

def start_message_updater():
    threading.Thread(target=message_updater, daemon=True).start()

def mask_overlay():
    overlay = Image.open(MASK_PATH).convert("RGBA")
    overlay = overlay.resize((width, height), Image.Resampling.LANCZOS)
    base = image.copy()
    composite = Image.alpha_composite(base.convert("RGBA"), overlay)
    image.paste(composite)
