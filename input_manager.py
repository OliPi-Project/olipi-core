#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

import threading
import time
import subprocess
import select
import ctypes
import ctypes.util
import shlex
import locale
import os

try:
    from evdev import InputDevice, list_devices, ecodes
except ImportError:
    InputDevice = None
    list_devices = None
    ecodes = None

try:
    from RPi import GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    GPIO = None

debug = False

repeat_lock = threading.Lock()
repeat_threads = {}
repeat_counts = {}

remote_mapping = {}

keyboard_mapping = {}
keyboard_context = None
keyboard_xkb = None
keyboard_pressed_mapping = {}

# === Shared data ===
press_data = {}

# === External hooks ===
show_message = None
press_callback = None

# --- Common repeat sender ---
def repeat_sender(key: str, check_fn, repeat_interval=0.08, press_timeout=0.10):
    """
    Generic repeat sender.
    - key: logical key name (e.g. "KEY_UP")
    - check_fn: callable returning True while "pressed"
    - repeat_interval: seconds between repeats
    """
    current_thread = threading.current_thread()
    while True:
        time.sleep(repeat_interval)
        with repeat_lock:
            # Check whether this thread is still the one associated with this key.
            if repeat_threads.get(key) is not current_thread:
                break
            if key not in repeat_counts or not check_fn():
                break
            repeat_counts[key] += 1
            count = repeat_counts[key]
        repeat_code = f"{count:02x}"
        process_key(key, repeat_code, press_timeout)
    # Clean up only if the entry still belongs to this thread.
    with repeat_lock:
        if repeat_threads.get(key) is current_thread:
            repeat_threads.pop(key, None)
            repeat_counts.pop(key, None)

# === Key processing + remapping ===
def process_key(key, repeat_code, press_timeout=0.10):
    global press_data
    try:
        rep = int(repeat_code, 16)
    except Exception as e:
        if show_message:
            show_message(f"error process_key: {e}")
        print("error process_key:", e)
        return
    if rep == 0:
        if key not in press_data:
            press_data[key] = {"max_repeat_code": 0, "timer": None}
        else:
            press_data[key]["max_repeat_code"] = 0
        if press_data[key]["timer"] is not None:
            press_data[key]["timer"].cancel()
        t = threading.Timer(press_timeout, lambda: press_callback(key))
        press_data[key]["timer"] = t
        t.start()
        return
    if key not in press_data:
        press_data[key] = {"max_repeat_code": rep, "timer": None}
    else:
        press_data[key]["max_repeat_code"] = max(press_data[key]["max_repeat_code"], rep)
    if press_data[key]["timer"] is not None:
        press_data[key]["timer"].cancel()
    t = threading.Timer(press_timeout, lambda: press_callback(key))
    press_data[key]["timer"] = t
    t.start()

# ============================================================
# Keyboard / evdev
# ============================================================

class KeyboardXKB:
    """Conversion of evdev events to characters using libxkbcommon."""
    def __init__(self, config_file="/etc/default/keyboard"):
        library = ctypes.util.find_library("xkbcommon")
        if not library:
            raise RuntimeError("libxkbcommon not found")
        self.lib = ctypes.CDLL(library)
        class RuleNames(ctypes.Structure):
            _fields_ = [
                ("rules", ctypes.c_char_p),
                ("model", ctypes.c_char_p),
                ("layout", ctypes.c_char_p),
                ("variant", ctypes.c_char_p),
                ("options", ctypes.c_char_p),
            ]
        self._bind_functions()
        settings = self._read_keyboard_config(config_file)
        names = RuleNames(
            b"evdev",
            settings["model"].encode(),
            settings["layout"].encode(),
            settings["variant"].encode(),
            settings["options"].encode(),
        )
        self.context = self.lib.xkb_context_new(0)
        if not self.context:
            raise RuntimeError("xkb_context_new failed")
        self.keymap = self.lib.xkb_keymap_new_from_names(
            self.context, ctypes.byref(names), 0
        )
        if not self.keymap:
            raise RuntimeError("Unable to create XKB keymap")
        self.state = self.lib.xkb_state_new(self.keymap)
        if not self.state:
            raise RuntimeError("Unable to create XKB state")
        # Compose permet de gérer les accents morts (ex. ^ puis e).
        current_locale = locale.setlocale(locale.LC_CTYPE)
        self.compose_table = self.lib.xkb_compose_table_new_from_locale(
            self.context, current_locale.encode(), 0
        )
        self.compose_state = None
        if self.compose_table:
            self.compose_state = self.lib.xkb_compose_state_new(
                self.compose_table, 0
            )
        print(f"[keyboard] XKB layout={settings['layout']} model={settings['model']} variant={settings['variant'] or '-'}")

    def _bind_functions(self):
        lib = self.lib
        lib.xkb_context_new.argtypes = [ctypes.c_int]
        lib.xkb_context_new.restype = ctypes.c_void_p
        lib.xkb_keymap_new_from_names.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int
        ]
        lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
        lib.xkb_state_new.argtypes = [ctypes.c_void_p]
        lib.xkb_state_new.restype = ctypes.c_void_p
        lib.xkb_state_update_key.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int
        ]
        lib.xkb_state_update_key.restype = ctypes.c_int
        lib.xkb_state_key_get_utf8.argtypes = [
            ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_char_p, ctypes.c_size_t
        ]
        lib.xkb_state_key_get_utf8.restype = ctypes.c_int
        lib.xkb_state_key_get_one_sym.argtypes = [
            ctypes.c_void_p, ctypes.c_uint
        ]
        lib.xkb_state_key_get_one_sym.restype = ctypes.c_uint
        lib.xkb_compose_table_new_from_locale.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int
        ]
        lib.xkb_compose_table_new_from_locale.restype = ctypes.c_void_p
        lib.xkb_compose_state_new.argtypes = [
            ctypes.c_void_p, ctypes.c_int
        ]
        lib.xkb_compose_state_new.restype = ctypes.c_void_p
        lib.xkb_compose_state_feed.argtypes = [
            ctypes.c_void_p, ctypes.c_uint
        ]
        lib.xkb_compose_state_feed.restype = ctypes.c_int
        lib.xkb_compose_state_get_status.argtypes = [
            ctypes.c_void_p
        ]
        lib.xkb_compose_state_get_status.restype = ctypes.c_int
        lib.xkb_compose_state_get_utf8.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t
        ]
        lib.xkb_compose_state_get_utf8.restype = ctypes.c_int
        lib.xkb_compose_state_reset.argtypes = [ctypes.c_void_p]
        lib.xkb_compose_state_reset.restype = None
        lib.xkb_keymap_mod_get_index.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p
        ]
        lib.xkb_keymap_mod_get_index.restype = ctypes.c_uint
        lib.xkb_state_update_mask.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
        ]
        lib.xkb_state_update_mask.restype = ctypes.c_uint

    @staticmethod
    def _read_keyboard_config(path):
        settings = {
            "model": "pc105",
            "layout": "us",
            "variant": "",
            "options": "",
        }
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if key not in ("XKBMODEL", "XKBLAYOUT",
                                   "XKBVARIANT", "XKBOPTIONS"):
                        continue
                    values = shlex.split(value, comments=True)
                    value = values[0] if values else ""
                    settings[key[3:].lower()] = value
        except OSError as e:
            print(f"[keyboard] cannot read {path}: {e}")
        return settings

    def set_numlock(self, enabled):
        """Synchronizes the initial state of NumLock with the kernel."""
        mod_index = self.lib.xkb_keymap_mod_get_index(
            self.keymap, b"Mod2"
        )
        if mod_index == 0xFFFFFFFF:
            print("[keyboard] XKB NumLock modifier not found")
            return
        locked_mods = (1 << mod_index) if enabled else 0
        self.lib.xkb_state_update_mask(
            self.state,
            0,              # depressed modifiers
            0,              # latched modifiers
            locked_mods,    # locked modifiers
            0, 0, 0         # layouts
        )
        print(f"[keyboard] NumLock={'ON' if enabled else 'OFF'}")

    def reset_compose(self):
        """Cancels any composition currently in progress."""
        if self.compose_state:
            self.lib.xkb_compose_state_reset(self.compose_state)

    def handle_event(self, code, value):
        """
        Updates the XKB state.
        Returns a single character only for a PRESS event.
        REPEAT events are ignored.
        """
        if value == 2:
            return None
        if value not in (0, 1):
            return None
        keycode = code + 8
        self.lib.xkb_state_update_key(
            self.state, keycode, 1 if value == 1 else 0
        )
        if value != 1:
            return None
        keysym = self.lib.xkb_state_key_get_one_sym(
            self.state, keycode
        )
        # Managing dead key combinations.
        if self.compose_state and keysym:
            result = self.lib.xkb_compose_state_feed(
                self.compose_state, keysym
            )
            if result == 1:
                status = self.lib.xkb_compose_state_get_status(
                    self.compose_state
                )
                if status == 1:  # COMPOSING
                    return None
                if status == 2:  # COMPOSED
                    buf = ctypes.create_string_buffer(64)
                    size = self.lib.xkb_compose_state_get_utf8(
                        self.compose_state, buf, 64
                    )
                    self.lib.xkb_compose_state_reset(
                        self.compose_state
                    )
                    return buf.value.decode("utf-8") if size > 0 else None
                if status == 3:  # CANCELLED
                    self.lib.xkb_compose_state_reset(
                        self.compose_state
                    )
                    return None
        buf = ctypes.create_string_buffer(64)
        size = self.lib.xkb_state_key_get_utf8(
            self.state, keycode, buf, 64
        )
        return buf.value.decode("utf-8") if size > 0 else None

KEYBOARD_LETTER_KEYS = {f"KEY_{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

KEYBOARD_DEFAULT_MAPPING = {
    "KEY_UP": ["KEY_UP", "KEY_KP8"],
    "KEY_DOWN": ["KEY_DOWN", "KEY_KP2"],
    "KEY_LEFT": ["KEY_LEFT", "KEY_KP4"],
    "KEY_RIGHT": ["KEY_RIGHT", "KEY_KP6"],
    "KEY_OK": ["KEY_ENTER", "KEY_KPENTER"],
    "KEY_BACK": ["KEY_HOME", "KEY_LEFTMETA", "KEY_TAB"],
    "KEY_CHANNELUP": ["KEY_PAGEUP", "KEY_KP9"],
    "KEY_CHANNELDOWN": ["KEY_PAGEDOWN", "KEY_KP3"],
    "KEY_PLAY": ["KEY_PLAYPAUSE", "KEY_SPACE"],
    "KEY_INFO": ["KEY_INFO", "KEY_I"],
    "KEY_STOP": ["KEY_STOP", "KEY_STOPCD", "KEY_X", "KEY_S"],
    "KEY_NEXT": ["KEY_NEXTSONG", "KEY_N"],
    "KEY_PREVIOUS": ["KEY_PREVIOUSSONG", "KEY_P"],
    "KEY_FORWARD": ["KEY_FORWARD", "KEY_F"],
    "KEY_REWIND": ["KEY_REWIND", "KEY_R"],
    "KEY_VOLUMEUP": ["KEY_VOLUMEUP", "KEY_KPPLUS"],
    "KEY_VOLUMEDOWN": ["KEY_VOLUMEDOWN", "KEY_KPMINUS"],
    "KEY_MUTE": ["KEY_MUTE", "KEY_M"],
    "KEY_POWER": ["KEY_POWER", "KEY_SLEEP", "KEY_END"],
}

KEYBOARD_MODIFIER_KEYS = {
    "KEY_LEFTSHIFT",
    "KEY_RIGHTSHIFT",
    "KEY_LEFTCTRL",
    "KEY_RIGHTCTRL",
    "KEY_LEFTALT",
    "KEY_RIGHTALT",
    "KEY_LEFTMETA",
    "KEY_RIGHTMETA",
    "KEY_CAPSLOCK",
    "KEY_NUMLOCK",
    "KEY_SCROLLLOCK",
}

KEYBOARD_TEXT_KEY_NAMES = {
    "KEY_SPACE",
    "KEY_MINUS",
    "KEY_EQUAL",
    "KEY_LEFTBRACE",
    "KEY_RIGHTBRACE",
    "KEY_BACKSLASH",
    "KEY_SEMICOLON",
    "KEY_APOSTROPHE",
    "KEY_GRAVE",
    "KEY_COMMA",
    "KEY_DOT",
    "KEY_SLASH",
}
def get_keyboard_key_name(code):
    """Returns the evdev name of a key, avoiding sentinel aliases such as KEY_MIN_INTERESTING."""
    names = ecodes.KEY.get(code)
    if not isinstance(names, (tuple, list)):
        names = (names,)
    for name in names:
        if isinstance(name, str) and name.startswith("KEY_"):
            if name != "KEY_MIN_INTERESTING":
                return name
    return str(code)

def load_keyboard_mapping(config):
    """
    Same principle as remote_mapping, but with multiple possible physical keys:
        KEY_UP = KEY_UP, KEY_KP8
        KEY_OK = KEY_ENTER, KEY_KPENTER
    """
    global keyboard_mapping
    keyboard_mapping = {}
    mapping = {action: list(keys) for action, keys in KEYBOARD_DEFAULT_MAPPING.items()}
    if config.has_section("keyboard"):
        for action, value in config.items("keyboard"):
            action = action.strip().upper()
            if not action.startswith("KEY_"):
                continue
            keys = [
                key.strip().upper()
                for key in value.split(",")
                if key.strip()
            ]
            if keys:
                mapping[action] = keys
    for action, physical_keys in mapping.items():
        for physical_key in physical_keys:
            keyboard_mapping[physical_key] = action
    if debug:
        print("[keyboard] mapping:")
        for action, physical_keys in mapping.items():
            print(f"  {action:<18} = {', '.join(physical_keys)}")
    print(f"[keyboard] loaded {len(keyboard_mapping)} key mappings")

def set_keyboard_context(context):
    """
    context=None : Normal keyboard mapping.
    context="text" : Printable characters are sent directly to process_key().
    """
    global keyboard_context
    keyboard_context = context
    if debug:
        print(f"[keyboard] context -> {context}")

def keyboard_handle_event(key, value, code=None):
    """
    Handles an EV_KEY event.
    value :
        0 = release
        1 = press
        2 = repeat
    """
    global keyboard_pressed_mapping
    translated = None
    # XKB continuously monitors the status of keys and modifiers.
    if keyboard_xkb is not None and code is not None:
        translated = keyboard_xkb.handle_event(code, value)

    # --------------------------------------------------------
    # Release: Use the memorized mapping as a guide.
    # --------------------------------------------------------
    if value == 0:
        mapped_key = keyboard_pressed_mapping.pop(code, None)
        if mapped_key:
            with repeat_lock:
                repeat_counts.pop(mapped_key, None)
                repeat_threads.pop(mapped_key, None)
        return
    # Modifiers are tracked by XKB but are not transmitted as commands.
    if key in KEYBOARD_MODIFIER_KEYS:
        return
    # Physical repetitions are ignored.
    if value != 1:
        return
    # Display translated key name (keep physical names for number keys).
    display_key = key
    if key in KEYBOARD_LETTER_KEYS:
        if translated and len(translated) == 1 and translated.isalpha():
            display_key = f"KEY_{translated.upper()}"
    print(f"[keyboard] {display_key}")

    # --------------------------------------------------------
    # Mode text
    # --------------------------------------------------------
    if keyboard_context == "text":
        if key in ("KEY_ESC", "KEY_BACKSPACE", "KEY_DELETE"):
            process_key(key, "00", 0.10)
            return
        if key in ("KEY_ENTER", "KEY_KPENTER"):
            pass  # Continue to keyboard_mapping
        elif translated and translated.isprintable():
            process_key(translated, "00", 0.10)
            return
        elif key in KEYBOARD_TEXT_KEY_NAMES:
            return

    # --------------------------------------------------------
    # Mode normal
    # --------------------------------------------------------
    # Use the AZERTY, QWERTY, etc., keyboard layout for letters
    logical_key = key
    if key in KEYBOARD_LETTER_KEYS:
        if translated and len(translated) == 1 and translated.isalpha():
            logical_key = f"KEY_{translated.upper()}"
    # Use the configured mapping if available; otherwise, pass the logical key directly.
    mapped_key = keyboard_mapping.get(logical_key, logical_key)
    if code is not None:
        keyboard_pressed_mapping[code] = mapped_key
    # First physical contact.
    with repeat_lock:
        if mapped_key in repeat_threads:
            return
        repeat_counts[mapped_key] = 0
    process_key(mapped_key, "00", 0.10)
    check_fn = lambda k=mapped_key: k in repeat_counts
    t = threading.Thread( target=repeat_sender, args=(mapped_key, check_fn, 0.08, 0.10), daemon=True)
    with repeat_lock:
        repeat_threads[mapped_key] = t
    t.start()

def keyboard_listener(config):
    """
    Listen for Linux EV_KEY devices via evdev.
    Detects compatible keyboards and manages their hot-plug connection and disconnection.
    """
    if InputDevice is None:
        print("[keyboard] evdev not available")
        return
    load_keyboard_mapping(config)
    global keyboard_xkb
    try:
        keyboard_xkb = KeyboardXKB()
    except Exception as e:
        keyboard_xkb = None
        print(f"[keyboard] XKB initialization failed: {e}")
    relevant_keys = set(keyboard_mapping.keys())
    relevant_keys.update(KEYBOARD_TEXT_KEY_NAMES)
    relevant_keys.update(KEYBOARD_LETTER_KEYS)
    # Devices to ignore.
    ignored_devices = ("gpio", "vc4-hdmi")
    devices = {}
    keyboard_grabbed = True
    numlock_synced = False
    # Keys held down by device.
    pressed_by_device = {}
    # Number of devices that support each EV_KEY code.
    pressed_counts = {}

    def release_all_pressed():
        """Releases all keys currently held by all devices."""
        for path in list(pressed_by_device):
            dev = devices.get(path)
            if dev is not None:
                release_device(dev)

    def toggle_keyboard_grab():
        nonlocal keyboard_grabbed
        keyboard_grabbed = not keyboard_grabbed
        if not keyboard_grabbed:
            release_all_pressed()
        for dev in devices.values():
            try:
                if keyboard_grabbed:
                    dev.grab()
                else:
                    dev.ungrab()
            except OSError as e:
                if debug:
                    print(f"[keyboard] grab change failed for {dev.path}: {e}")
        if debug:
            print(f"[keyboard] grab -> {'ON' if keyboard_grabbed else 'OFF'}")

    def release_device(dev):
        """Releases any keys still held down by a device."""
        path = dev.path
        for code in pressed_by_device.pop(path, set()):
            count = pressed_counts.get(code, 0) - 1
            if count <= 0:
                pressed_counts.pop(code, None)
                keyboard_handle_event(get_keyboard_key_name(code), 0, code)
            else:
                pressed_counts[code] = count
        # Cancels any composition currently in progress.
        if keyboard_xkb is not None:
            keyboard_xkb.reset_compose()

    try:
        while True:
            # Search for new devices.
            for path in list_devices():
                if path in devices:
                    continue
                try:
                    dev = InputDevice(path)
                    identity = " ".join((
                        dev.name or "",
                        dev.phys or "",
                        dev.path or "",
                    )).lower()
                    if any(name in identity for name in ignored_devices):
                        dev.close()
                        continue
                    capabilities = dev.capabilities()
                    keys = capabilities.get(ecodes.EV_KEY, [])
                    device_keys = {get_keyboard_key_name(code) for code in keys}
                    if not device_keys.intersection(relevant_keys):
                        dev.close()
                        continue
                    devices[path] = dev
                    print(f"[keyboard] device connected: {dev.path}: {dev.name}")
                    if keyboard_grabbed:
                        try:
                            dev.grab()
                        except OSError as e:
                            print(f"[keyboard] cannot grab {dev.path}: {e}")
                    # Initial NumLock synchronization.
                    if (not numlock_synced and "KEY_NUMLOCK" in device_keys):
                        led_caps = capabilities.get(ecodes.EV_LED, [])
                        if ecodes.LED_NUML in led_caps:
                            try:
                                numlock_active = (ecodes.LED_NUML in dev.leds())
                                if keyboard_xkb is not None:
                                    keyboard_xkb.set_numlock(numlock_active)
                                numlock_synced = True
                            except OSError:
                                pass
                except Exception as e:
                    print(f"[keyboard] cannot open {path}: {e}")

            # Waiting for events.
            active_devices = tuple(devices.values())
            try:
                ready, _, _ = select.select(
                    [dev.fd for dev in active_devices],
                    [],
                    [],
                    0.5
                )
            except (OSError, ValueError):
                # A device may have been removed while `select()` was being prepared.
                for dev in active_devices:
                    try:
                        os.fstat(dev.fd)
                    except OSError:
                        print(f"[keyboard] device disconnected: {dev.path}")
                        release_device(dev)
                        devices.pop(dev.path, None)
                        try:
                            dev.close()
                        except OSError:
                            pass
                continue

            for dev in active_devices:
                if dev.fd not in ready:
                    continue
                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue
                        key = get_keyboard_key_name(event.code)
                        if key == "KEY_F12":
                            if event.value == 1:
                                toggle_keyboard_grab()
                            continue
                        if not keyboard_grabbed:
                            continue
                        if debug:
                            state = {
                                0: "RELEASE",
                                1: "PRESS",
                                2: "REPEAT",
                            }.get(event.value, str(event.value))
                            print(f"[keyboard] {dev.name}: {key} {state}")
                        code = event.code
                        pressed = pressed_by_device.setdefault(dev.path, set())
                        if event.value == 1:
                            if code not in pressed:
                                pressed.add(code)
                                count = pressed_counts.get(code, 0) + 1
                                pressed_counts[code] = count
                                # Only one XKB press is recognized, even if multiple keyboards hold down the same key at the same time.
                                if count == 1:
                                    keyboard_handle_event(key, 1, code)
                        elif event.value == 0:
                            if code in pressed:
                                pressed.remove(code)
                                count = pressed_counts.get(code, 0) - 1
                                if count <= 0:
                                    pressed_counts.pop(code, None)
                                    keyboard_handle_event(key, 0, code)
                                else:
                                    pressed_counts[code] = count
                except BlockingIOError:
                    continue
                except OSError:
                    print(f"[keyboard] device disconnected: {dev.path}")
                    release_device(dev)
                    devices.pop(dev.path, None)
                    try:
                        dev.close()
                    except OSError:
                        pass
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[keyboard] listener error: {e}")
    finally:
        for dev in devices.values():
            try:
                release_device(dev)
                try:
                    dev.ungrab()
                except OSError:
                    pass
                dev.close()
            except Exception:
                pass

def lirc_listener(process_key, config):
    lirc_press_timeout = config.getfloat("remote", "lirc_press_timeout_s", fallback=0.20)
    try:
        proc = subprocess.Popen(
            ["irw"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            universal_newlines=True,
        )
        while True:
            rlist, _, _ = select.select([proc.stdout], [], [], 0.1)
            if rlist:
                line = proc.stdout.readline()
                if not line:
                    break
                parts = line.strip().split()
                if len(parts) >= 3:
                    key = parts[2].strip().upper()
                    key = remote_mapping.get(key, key)
                    repeat_code = parts[1].strip()
                    process_key(key, repeat_code, lirc_press_timeout)
    except FileNotFoundError:
        if show_message:
            show_message("error: lirc missing")
        print("error: lirc missing")
    except Exception as e:
        if show_message:
            show_message(f"error lirc listener: {e}")
        print("error lirc listener:", e)

def mpr121_listener(process_key, config):
    from .olipicap.mpr121 import MPR121

    address = int(config.get("mpr121", "i2c_address", fallback="0x5A"), 0)
    int_pin = config.getint("mpr121", "int_pin", fallback=None)
    global_touch = config.getint("mpr121", "touch_threshold", fallback=30)
    global_release = config.getint("mpr121", "release_threshold", fallback=20)

    # --- Pad mapping ---
    PAD_KEY_MAPPING = {}
    pad_touch_thresholds = {}
    pad_release_thresholds = {}
    if config.has_section("mpr121_pads"):
        for key, value in config.items("mpr121_pads"):
            if not key.lower().startswith("pad"):
                continue
            try:
                pad_index = int(key[3:])
                parts = [v.strip() for v in value.split(",")]
                if len(parts) >= 3:
                    action = parts[0].upper()
                    tth = int(parts[1]) if parts[1] not in ["", "-", "none"] else None
                    rth = int(parts[2]) if parts[2] not in ["", "-", "none"] else None
                else:
                    action, tth, rth = parts[0].upper(), None, None
                PAD_KEY_MAPPING[pad_index] = action
                pad_touch_thresholds[pad_index] = (
                    tth if tth is not None else global_touch
                )
                pad_release_thresholds[pad_index] = (
                    rth if rth is not None else global_release
                )
            except Exception as e:
                print(f"error parsing {key}: {e}")
    else:
        # fallback default mapping
        PAD_KEY_MAPPING = {
            0: "KEY_UP",
            1: "KEY_RIGHT",
            2: "KEY_DOWN",
            3: "KEY_LEFT",
            4: "KEY_OK",
            5: "KEY_BACK",
            6: "KEY_CHANNELUP",
            7: "KEY_CHANNELDOWN",
            8: "KEY_PLAY",
            9: "KEY_INFO",
            10: "KEY_STOP",
            11: "KEY_POWER",
            12: "KEY_PROX",
        }

    # --- Init sensor ---
    time.sleep(0.5)
    sensor = MPR121(address)
    if not sensor.begin():
        if show_message:
            show_message("error: MPR121 init failed") if show_message else None
        print("error: MPR121 init failed")
        return

    sensor.set_interrupt_pin(int_pin)
    sensor.set_touch_threshold(global_touch)
    sensor.set_release_threshold(global_release)
    for i in range(13):
        tth = pad_touch_thresholds.get(i, global_touch)
        rth = pad_release_thresholds.get(i, global_release)
        sensor.set_touch_threshold_for(i, tth)
        sensor.set_release_threshold_for(i, rth)

    # --- Gesture tracking ---
    gesture_history = []
    gesture_timer = None
    GESTURE_TIMEOUT = 0.3
    #DIR_NAMES = {0:"UP",1:"RIGHT",2:"DOWN",3:"LEFT"}
    CLOCKWISE = [0,1,2,3]
    COUNTERCLOCKWISE = [0,3,2,1]

    def detect_swipe(seq):
        if 4 not in seq:  # center pad missing
            return None
        idx_c = seq.index(4)
        if idx_c == 0 or idx_c == len(seq)-1:
            return None
        start = seq[idx_c-1]
        end = seq[idx_c+1]
        if start == 3 and end == 1:
            return "swipe_right"
        if start == 1 and end == 3:
            return "swipe_left"
        if start == 0 and end == 2:
            return "swipe_down"
        if start == 2 and end == 0:
            return "swipe_up"
        return None

    def detect_rotation(seq):
        nums = [p for p in seq if p in (0,1,2,3)]
        if len(nums) < 3:
            return None
        for i in range(4):
            cw = CLOCKWISE[i:] + CLOCKWISE[:i]
            ccw = COUNTERCLOCKWISE[i:] + COUNTERCLOCKWISE[:i]
            if all(n in cw for n in nums):
                idx = 0
                for n in nums:
                    while idx < 4 and cw[idx] != n:
                        idx += 1
                    if idx >= 4: break
                else:
                    return "rotate_clockwise"
            if all(n in ccw for n in nums):
                idx = 0
                for n in nums:
                    while idx < 4 and ccw[idx] != n:
                        idx += 1
                    if idx >= 4: break
                else:
                    return "rotate_counterclockwise"
        return None

    def send_simple_keys():
        nonlocal gesture_history, gesture_timer
        gesture_timer = None
        if len(gesture_history) == 1:
            t = gesture_history[0]
            key = PAD_KEY_MAPPING.get(t)
            with repeat_lock:
                if key not in repeat_threads:
                    if debug:
                        print(f"[MPR121][JOYSTICK] Simple Key: {key}")
                    repeat_counts[key] = 0
                    process_key(key, "00", 0.1)
                    check_fn = lambda s=sensor, idx=t: s.get_touch_data(idx)
                    t_thread = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
                    repeat_threads[key] = t_thread
                    t_thread.start()
        gesture_history.clear()

    time.sleep(0.5)
    if debug:
        print(f"[mpr121] started @0x{address:02X}")
        print(f"  global touch/release = {global_touch}/{global_release}")
        print("  per-pad config:")
        sensor.update_all()
        for i in range(13):
            key = PAD_KEY_MAPPING.get(i, f"PAD{i}")
            tth = pad_touch_thresholds.get(i, global_touch)
            rth = pad_release_thresholds.get(i, global_release)
            base = sensor.get_baseline_data(i)
            filt = sensor.get_filtered_data(i)
            diff = filt - base
            print(f"   - pad{i}: {key:<15} touch={tth:3d} rel={rth:3d} base={base:4d} filt={filt:4d} diff={diff:+5d}")
    else:
        print(f"[mpr121] started @0x{address:02X} touch={global_touch} release={global_release}")

    running = True
    gesture_active = config.getboolean("mpr121", "use_gesture", fallback=False)
    swipe = None
    rotation = None

    while running:
        try:
            if sensor.touch_status_changed():
                sensor.update_all()
                touched = {i for i in range(5) if sensor.is_new_touch(i)}
                released = {i for i in range(5) if sensor.is_new_release(i)}


                # --- 1. Handle new touches (gesture / single key detection for the first 5 pads) ---
                if gesture_active and touched:
                    for t in touched:
                        if not gesture_history or gesture_history[-1] != t:
                            gesture_history.append(t)

                    # Cancel timer if new gesture in progress
                    if gesture_timer:
                        gesture_timer.cancel()

                    swipe = detect_swipe(gesture_history)
                    rotation = detect_rotation(gesture_history)

                    if swipe is not None:
                        if debug:
                            print(f"[MPR121][JOYSTICK] Gesture: {swipe}")
                        gesture_history.clear()
                    elif rotation is not None:
                        if debug:
                            print(f"[MPR121][JOYSTICK] Gesture: {rotation}")
                        gesture_history.clear()
                    else:
                        # Start timer if no gesture found yet
                        gesture_timer = threading.Timer(GESTURE_TIMEOUT, send_simple_keys)
                        gesture_timer.start()

                # --- 2. Handle releases (gesture / single key detection for the first 5 pads) ---
                elif gesture_active and released:
                    for t in released:
                        key = PAD_KEY_MAPPING.get(t)
                        with repeat_lock:
                            repeat_counts.pop(key, None)
                            repeat_threads.pop(key, None)
                    if len(gesture_history) == 1 and not (swipe or rotation):
                        if gesture_timer:
                            gesture_timer.cancel()
                        send_simple_keys()

                else:
                    # iterate through pads 0..11 (touch electrodes not used for gestures or disabled)
                    for i in range(12):
                        key = PAD_KEY_MAPPING.get(i, f"PAD{i}")
                        # NEW TOUCH: start repeat thread (if not already running)
                        if sensor.is_new_touch(i):
                            with repeat_lock:
                                if debug:
                                    base = sensor.get_baseline_data(i)
                                    filt = sensor.get_filtered_data(i)
                                    diff = filt - base
                                    print(f"[MPR121] TOUCH pad{i} -> {key:<15} base={base:4d} filt={filt:4d} diff={diff:+5d}")
                                if key not in repeat_threads:
                                    # initialize repeat counter and emit first press ("00")
                                    repeat_counts[key] = 0
                                    process_key(key, "00", 0.1)

                                    # check_fn for this pad: poll sensor.get_touch_data(i)
                                    check_fn = (lambda s=sensor, idx=i: s.get_touch_data(idx))
                                    t = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
                                    repeat_threads[key] = t
                                    t.start()
                        # RELEASE: stop repeat thread by removing entries
                        elif sensor.is_new_release(i):
                            with repeat_lock:
                                if debug:
                                    print(f"[MPR121] TOUCH pad{i} -> {key:<15} was just released")
                                repeat_counts.pop(key, None)
                                repeat_threads.pop(key, None)

            time.sleep(0.1)
        except KeyboardInterrupt:
            running = False
        except Exception as e:
            print("error mpr121 listener:", e)
            if show_message:
                show_message("error mpr121 listener")
            time.sleep(0.1)

def rotary_listener(pin_a, pin_b, process_key, config=None):
    divider = config.getint("rotary", "rotary_divider", fallback=2)
    invert = config.getboolean("rotary", "rotary_invert", fallback=False)
    min_tick_ms = config.getfloat("rotary", "rotary_min_tick_ms", fallback=2)
    try:
        rotary_bouncetime_ms = config.getint("rotary", "rotary_bouncetime_ms", fallback=10)
    except ValueError:
        print("Error: rotary_bouncetime_ms must be an integer. Fallback to 10ms")
        rotary_bouncetime_ms = 10

    if debug:
        print(f"[rotary] start pins A={pin_a} B={pin_b} divider={divider} invert={invert}")

    last_state_a = GPIO.input(pin_a)
    counter = 0
    last_emit = time.time()
    lock = threading.Lock()

    def handle_edge(channel):
        nonlocal last_state_a, counter, last_emit

        a_state = GPIO.input(pin_a)
        b_state = GPIO.input(pin_b)

        if a_state != last_state_a:
            now = time.time()
            if (now - last_emit) * 1000 < min_tick_ms / 2:
                # Ignores very short transitions (bounces)
                return

            direction = +1 if b_state != a_state else -1
            if invert:
                direction = -direction

            with lock:
                counter += direction
                if abs(counter) >= divider and (now - last_emit) * 1000 >= min_tick_ms:
                    key = "KEY_UP" if counter > 0 else "KEY_DOWN"
                    process_key(key, "00", 0.01)
                    counter = 0
                    last_emit = now

        last_state_a = a_state

    GPIO.add_event_detect(pin_a, GPIO.BOTH, callback=handle_edge, bouncetime=rotary_bouncetime_ms)
    GPIO.add_event_detect(pin_b, GPIO.BOTH, callback=handle_edge, bouncetime=rotary_bouncetime_ms)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        GPIO.remove_event_detect(pin_a)
        GPIO.remove_event_detect(pin_b)

# --- GPIO button event callback ---
def gpio_event(button_pressed, key):
    """
    GPIO callback: start a repeat thread that polls GPIO.input(button_pressed).
    """
    if GPIO.input(button_pressed) == GPIO.LOW:
        with repeat_lock:
            if key in repeat_threads:
                return
            repeat_counts[key] = 0
            process_key(key, "00", 0.1)
            check_fn = lambda bp=button_pressed: GPIO.input(bp) == GPIO.LOW
            t = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
            repeat_threads[key] = t
            t.start()
    else:
        with repeat_lock:
            repeat_counts.pop(key, None)
            repeat_threads.pop(key, None)

# === Main entrance ===
def start_inputs(config, process_press, msg_hook=None):
    global show_message, press_callback, remote_mapping, debug
    show_message = msg_hook
    press_callback = process_press
    debug = config.getboolean("settings", "debug", fallback=False)

    # Load key mapping
    remote_mapping = {}
    if config.has_section("remote"):
        for action, remote_key in config.items("remote"):
            if not action.upper().startswith("KEY_"):
                continue
            action = action.strip().upper()
            remote_key = remote_key.strip().upper()
            if not remote_key or remote_key in ["—", "-", "NONE", "YOUR_REMOTE_KEY"]:
                continue
            remote_mapping[remote_key] = action

    if remote_mapping:
        print(f"[Remote] Loaded {len(remote_mapping)} remote key mappings")
    else:
        print("[Remote] No remote mappings found, using default keys")

    # Keyboard / evdev
    if config.getboolean("input", "use_keyboard", fallback=False):
        threading.Thread(target=keyboard_listener, args=(config,), daemon=True).start()

    # LIRC
    if config.getboolean("input", "use_lirc", fallback=False):
        threading.Thread(target=lirc_listener, args=(process_key, config), daemon=True).start()

    # MPR121
    if config.getboolean("input", "use_mpr121", fallback=False):
        threading.Thread(target=mpr121_listener, args=(process_key, config), daemon=True).start()

    # GPIO boutons
    if config.getboolean("input", "use_buttons", fallback=False):
        try:
            buttons_bouncetime_ms = config.getint("buttons", "buttons_bouncetime_ms", fallback=10)
        except ValueError:
            print("Error: buttons_bouncetime_ms must be an integer. Fallback to 10ms")
            buttons_bouncetime_ms = 10
        if GPIO is None:
            print("error: gpio missing")
            if show_message:
                show_message("error: gpio missing")
        elif config.has_section("buttons"):
            for key, pin in config.items("buttons"):
                if not key.upper().startswith("KEY_"):
                    continue
                try:
                    pin = int(pin)
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                    GPIO.add_event_detect(
                        pin,
                        GPIO.BOTH,
                        callback=lambda ch, k=key.upper(), p=pin: gpio_event(p, k),
                        bouncetime=buttons_bouncetime_ms,
                    )
                except Exception as e:
                    if show_message:
                        show_message(f"error gpio pin")
                    print("error gpio pin:", e)

    # Rotary encoder
    if config.getboolean("input", "use_rotary", fallback=False) and config.has_section("rotary") and GPIO:
        try:
            pin_a = config.getint("rotary", "pin_a")
            pin_b = config.getint("rotary", "pin_b")
            GPIO.setup(pin_a, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(pin_b, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            threading.Thread(target=rotary_listener, args=(pin_a, pin_b, process_key, config), daemon=True).start()
        except Exception as e:
            if show_message:
                show_message(f"error rotary: {e}")
            print("error rotary:", e)
