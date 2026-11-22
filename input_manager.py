#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project

import threading
import time
import subprocess
import select
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

repeat_lock = threading.Lock()

# === Constants ===
PRESS_TIMEOUT = 0.15  # default fallback

repeat_threads = {}
repeat_counts = {}

remote_mapping = {}

debug = False

keyboard_mapping = {}
keyboard_context = None
keyboard_text_callback = None

# === Shared data ===
press_data = {}

# === External hooks ===
show_message = None
press_callback = None

# --- Common repeat sender for GPIO and rotary button ---
def repeat_sender(key: str, check_fn):
    """
    Generic repeat sender.
    - key: logical key name (e.g. "KEY_UP")
    - check_fn: callable returning True while "pressed"
    - REPEAT_INTERVAL: seconds between repeats
    """
    REPEAT_INTERVAL = 0.08

    while True:
        time.sleep(REPEAT_INTERVAL)
        with repeat_lock:
            # Check if key still exists and is being pressed
            if key not in repeat_counts or not check_fn():
                break
            repeat_counts[key] += 1
            count = repeat_counts[key]

        repeat_code = f"{count:02x}"
        process_key(key, repeat_code, 0.1)

    # Cleanup thread-safe
    with repeat_lock:
        repeat_counts.pop(key, None)
        repeat_threads.pop(key, None)

# --- GPIO button event callback ---
def gpio_event(button_pressed, key):
    """
    GPIO callback: start a repeat thread that polls GPIO.input(button_pressed).
    Existing semantics preserved: first press -> process_key(...,"00")
    """
    if GPIO.input(button_pressed) == GPIO.LOW:
        if key not in repeat_threads:
            repeat_counts[key] = 0
            process_key(key, "00", 0.1)  # first press
            # pass a check_fn that reads the GPIO pin
            check_fn = lambda bp=button_pressed: GPIO.input(bp) == GPIO.LOW
            t = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
            repeat_threads[key] = t
            t.start()
    else:
        # release: ensure we stop any repeat
        repeat_counts.pop(key, None)
        repeat_threads.pop(key, None)

# === Key processing + remapping ===
def process_key(key, repeat_code, PRESS_TIMEOUT=PRESS_TIMEOUT):
    global press_data

    # apply remapping if available
    mapped_key = remote_mapping.get(key, key)

    try:
        rep = int(repeat_code, 16)
    except Exception as e:
        if show_message:
            show_message(f"error process_key: {e}")
        print("error process_key:", e)
        return

    if rep == 0:
        if mapped_key not in press_data:
            press_data[mapped_key] = {"max_repeat_code": 0, "timer": None}
        else:
            press_data[mapped_key]["max_repeat_code"] = 0

        if press_data[mapped_key]["timer"] is not None:
            press_data[mapped_key]["timer"].cancel()

        t = threading.Timer(PRESS_TIMEOUT, lambda: press_callback(mapped_key))
        press_data[mapped_key]["timer"] = t
        t.start()
        return

    if mapped_key not in press_data:
        press_data[mapped_key] = {"max_repeat_code": rep, "timer": None}
    else:
        press_data[mapped_key]["max_repeat_code"] = max(press_data[mapped_key]["max_repeat_code"], rep)

    if press_data[mapped_key]["timer"] is not None:
        press_data[mapped_key]["timer"].cancel()

    t = threading.Timer(PRESS_TIMEOUT, lambda: press_callback(mapped_key))
    press_data[mapped_key]["timer"] = t
    t.start()

# ============================================================
# Keyboard / evdev
# ============================================================

KEYBOARD_DEFAULT_MAPPING = {
    "KEY_UP": ["KEY_UP", "KP8"],
    "KEY_DOWN": ["KEY_DOWN", "KP2"],
    "KEY_LEFT": ["KEY_LEFT", "KP4"],
    "KEY_RIGHT": ["KEY_RIGHT", "KP6"],
    "KEY_OK": ["KEY_ENTER", "KPENTER"],
    "KEY_BACK": ["KEY_BACKSPACE"],
    "KEY_CHANNELUP": ["KEY_PAGEUP", "KP9"],
    "KEY_CHANNELDOWN": ["KEY_PAGEDOWN", "KP3"],
    "KEY_PLAY": ["KEY_PLAYPAUSE", "KEY_P"],
    "KEY_INFO": ["KEY_I", "KEY_INFO"],
    "KEY_STOP": ["KEY_ESC", "KEY_S"],
    "KEY_NEXT": ["KEY_NEXTSONG"],
    "KEY_PREVIOUS": ["KEY_PREVIOUSSONG"],
    "KEY_FORWARD": ["KEY_F"],
    "KEY_REWIND": ["KEY_R"],
    "KEY_VOLUMEUP": ["KEY_VOLUMEUP"],
    "KEY_VOLUMEDOWN": ["KEY_VOLUMEDOWN"],
    "KEY_MUTE": ["KEY_MUTE"],
    "KEY_POWER": ["KEY_POWER"],
}


# Touches de contrôle qui restent disponibles en mode texte.
# Elles ne passent PAS par keyboard_mapping.
KEYBOARD_TEXT_CONTROL_KEYS = {
    "KEY_LEFT": "KEY_LEFT",
    "KEY_RIGHT": "KEY_RIGHT",
    "KEY_UP": "KEY_UP",
    "KEY_DOWN": "KEY_DOWN",
    "KEY_ENTER": "KEY_ENTER",
    "KPENTER": "KEY_ENTER",
    "KEY_ESC": "KEY_ESC",
}


# Correspondance minimale pour la saisie texte.
# Les touches alphanumériques sont complétées automatiquement.
KEYBOARD_TEXT_KEYS = {
    "KEY_SPACE": " ",
    "KEY_TAB": "\t",
    "KEY_MINUS": "-",
    "KEY_EQUAL": "=",
    "KEY_LEFTBRACE": "[",
    "KEY_RIGHTBRACE": "]",
    "KEY_BACKSLASH": "\\",
    "KEY_SEMICOLON": ";",
    "KEY_APOSTROPHE": "'",
    "KEY_GRAVE": "`",
    "KEY_COMMA": ",",
    "KEY_DOT": ".",
    "KEY_SLASH": "/",
}


def get_keyboard_key_name(code):
    """
    Retourne le nom evdev d'une touche en évitant les alias
    sentinelles comme KEY_MIN_INTERESTING.
    """
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
    Charge le mapping clavier.

    La configuration utilise le même principe que remote_mapping,
    mais avec plusieurs touches physiques possibles :

        KEY_UP = KEY_UP, KP8
        KEY_OK = KEY_ENTER, KPENTER

    Le dictionnaire interne est inversé :

        KEY_UP  -> KEY_UP
        KP8     -> KEY_UP
    """
    global keyboard_mapping

    keyboard_mapping = {}

    mapping = {
        action: list(keys)
        for action, keys in KEYBOARD_DEFAULT_MAPPING.items()
    }

    if config.has_section("keyboard_mapping"):
        for action, value in config.items("keyboard_mapping"):
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


def set_keyboard_context(context, text_callback=None):
    """
    Change le contexte de traitement du clavier.

    context=None :
        fonctionnement normal avec keyboard_mapping.

    context="text" :
        aucune conversion via keyboard_mapping et aucun raccourci
        n'est utilisé. Les caractères sont envoyés à text_callback.

    text_callback reçoit :
        - un caractère pour une touche texte
        - "BACKSPACE" pour Backspace
        - "ENTER" pour Enter
        - "ESC" pour Escape
        - KEY_LEFT / KEY_RIGHT / KEY_UP / KEY_DOWN pour les directions
    """
    global keyboard_context, keyboard_text_callback

    keyboard_context = context
    keyboard_text_callback = text_callback

    if debug:
        print(f"[keyboard] context -> {context}")


def keyboard_send_text(value):
    """
    Envoie une valeur au callback texte courant.
    """
    if keyboard_text_callback is not None:
        try:
            keyboard_text_callback(value)
        except Exception as e:
            print(f"[keyboard] text callback error: {e}")


def keyboard_translate_text_key(key):
    """
    Convertit un nom de touche evdev en caractère ou contrôle texte.

    Cette première version couvre les caractères courants.
    La gestion de Shift/CapsLock est traitée séparément dans le listener.
    """
    if key in KEYBOARD_TEXT_KEYS:
        return KEYBOARD_TEXT_KEYS[key]

    # Lettres
    if key.startswith("KEY_") and len(key) == 5:
        letter = key[-1]
        if "A" <= letter <= "Z":
            return letter.lower()

    # Chiffres du clavier principal
    if key.startswith("KEY_") and len(key) == 5:
        digit = key[-1]
        if digit in "0123456789":
            return digit

    # Pavé numérique
    keypad_digits = {
        "KP0": "0",
        "KP1": "1",
        "KP2": "2",
        "KP3": "3",
        "KP4": "4",
        "KP5": "5",
        "KP6": "6",
        "KP7": "7",
        "KP8": "8",
        "KP9": "9",
    }

    if key in keypad_digits:
        return keypad_digits[key]

    if key == "KEY_BACKSPACE":
        return "BACKSPACE"

    if key == "KEY_ENTER" or key == "KPENTER":
        return "ENTER"

    if key == "KEY_ESC":
        return "ESC"

    return None


def keyboard_handle_event(key, value):
    """
    Traite un événement EV_KEY.

    value :
        0 = release
        1 = press
        2 = repeat
    """
    # --------------------------------------------------------
    # Mode texte
    # --------------------------------------------------------
    if keyboard_context == "text":
        # Les répétitions peuvent être ignorées pour le moment.
        # On pourra les gérer ensuite si nécessaire.
        if value != 1:
            return

        # Contrôles de navigation : ils restent des contrôles,
        # mais ne sont PAS transformés via keyboard_mapping.
        if key in KEYBOARD_TEXT_CONTROL_KEYS:
            keyboard_send_text(KEYBOARD_TEXT_CONTROL_KEYS[key])
            return

        text = keyboard_translate_text_key(key)

        if text is not None:
            keyboard_send_text(text)

        return


    # --------------------------------------------------------
    # Mode normal
    # --------------------------------------------------------

    mapped_key = keyboard_mapping.get(key)

    if not mapped_key:
        return

    if value == 1:
        # Premier appui physique
        with repeat_lock:
            if mapped_key in repeat_threads:
                return

            repeat_counts[mapped_key] = 0

        # Premier code : 00
        process_key(mapped_key, "00", 0.1)

        # Répétition générée par repeat_sender
        check_fn = lambda k=mapped_key: k in repeat_counts

        t = threading.Thread(
            target=repeat_sender,
            args=(mapped_key, check_fn),
            daemon=True
        )

        with repeat_lock:
            repeat_threads[mapped_key] = t

        t.start()

    elif value == 0:
        # Relâchement physique : arrêt de la répétition
        with repeat_lock:
            repeat_counts.pop(mapped_key, None)
            repeat_threads.pop(mapped_key, None)

    # value == 2 ignoré :
    # la répétition est entièrement gérée par repeat_sender.

def keyboard_listener(config):
    """
    Écoute les périphériques Linux EV_KEY via evdev.

    Seuls les périphériques exposant au moins une touche connue
    du mapping clavier ou une touche texte sont retenus.
    """
    if InputDevice is None:
        print("[keyboard] evdev not available")
        return

    load_keyboard_mapping(config)

    devices = []

    # Touches susceptibles d'intéresser le clavier en mode normal.
    relevant_keys = set(keyboard_mapping.keys())

    # Touches nécessaires au mode texte.
    relevant_keys.update(KEYBOARD_TEXT_KEYS.keys())
    relevant_keys.update(KEYBOARD_TEXT_CONTROL_KEYS.keys())
    relevant_keys.update({
        "KEY_BACKSPACE",
        "KEY_ENTER",
        "KPENTER",
        "KEY_SPACE",
    })

    try:
        for path in list_devices():
            try:
                dev = InputDevice(path)

                capabilities = dev.capabilities()
                keys = capabilities.get(ecodes.EV_KEY, [])

                device_keys = {
                    get_keyboard_key_name(code)
                    for code in keys
                }

                if not device_keys.intersection(relevant_keys):
                    dev.close()
                    continue

                devices.append(dev)

            except Exception as e:
                print(f"[keyboard] cannot open {path}: {e}")

        if not devices:
            print("[keyboard] no compatible input device found")
            return

        print("[keyboard] listening on:")
        for dev in devices:
            print(f"  {dev.path}: {dev.name}")

        while True:
            ready, _, _ = select.select(
                [dev.fd for dev in devices],
                [],
                [],
                0.5
            )

            for dev in devices:
                if dev.fd not in ready:
                    continue

                try:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue

                        key = get_keyboard_key_name(event.code)

                        if debug:
                            state = {
                                0: "RELEASE",
                                1: "PRESS",
                                2: "REPEAT",
                            }.get(event.value, str(event.value))
                            print(
                                f"[keyboard] {dev.name}: "
                                f"{key} {state}"
                            )

                        keyboard_handle_event(key, event.value)

                except OSError:
                    # Périphérique débranché.
                    print(f"[keyboard] device disconnected: {dev.path}")

    except KeyboardInterrupt:
        pass

    except Exception as e:
        print(f"[keyboard] listener error: {e}")

    finally:
        for dev in devices:
            try:
                dev.close()
            except Exception:
                pass

def lirc_listener(process_key, config):
    lirc_bouncetime = config.getfloat("lirc", "lirc_bouncetime_s", fallback=0.20)
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
                    repeat_code = parts[1].strip()
                    process_key(key, repeat_code, lirc_bouncetime)
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
        print(f"[mpr121_listener] started @0x{address:02X}")
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
        print(f"[mpr121_listener] started @0x{address:02X} touch={global_touch} release={global_release}")

    running = True
    gesture_active = config.getboolean("mpr121", "use_gesture", fallback=False)

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
        print(f"[rotary_listener] start pins A={pin_a} B={pin_b} divider={divider} invert={invert}")

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
                # Ignore très courtes transitions (rebonds)
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

# === Main entrance ===
def start_inputs(config, process_press, msg_hook=None):
    global show_message, press_callback, remote_mapping, debug
    show_message = msg_hook
    press_callback = process_press
    debug = config.getboolean("settings", "debug", fallback=False)

    # Load key mapping
    remote_mapping = {}
    if config.has_section("remote_mapping"):
        for action, remote_key in config.items("remote_mapping"):
            action = action.strip().upper()
            remote_key = remote_key.strip().upper()
            if not remote_key or remote_key in ["—", "-", "NONE", "YOUR_REMOTE_KEY"]:
                continue
            remote_mapping[remote_key] = action

    if remote_mapping:
        print(f"Loaded {len(remote_mapping)} remote key mappings")
    else:
        print("No valid remote mappings found, using raw keys")

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
