#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)

import threading
import time
import subprocess
import select

try:
    from RPi import GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
except ImportError:
    GPIO = None

repeat_lock = threading.Lock()

# === Constants ===
DEBOUNCE_DELAY = 0.15
BOUNCETIME_DELAY = 0.05
REPEAT_INTERVAL = 0.1

repeat_threads = {}
repeat_counts = {}

remote_mapping = {}

debug = False

# === Shared data ===
debounce_data = {}

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
    while True:
        time.sleep(REPEAT_INTERVAL)
        with repeat_lock:
            # Check if key still exists and is being pressed
            if key not in repeat_counts or not check_fn():
                break
            repeat_counts[key] += 1
            count = repeat_counts[key]

        repeat_code = f"{count:02x}"
        process_key(key, repeat_code)

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
            process_key(key, "00")  # first press
            # pass a check_fn that reads the GPIO pin
            check_fn = lambda bp=button_pressed: GPIO.input(bp) == GPIO.LOW
            t = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
            repeat_threads[key] = t
            t.start()
    else:
        # release: ensure we stop any repeat
        repeat_counts.pop(key, None)
        repeat_threads.pop(key, None)

# === Key processing with debounce + remapping ===
def process_key(key, repeat_code):
    global debounce_data

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
        if mapped_key not in debounce_data:
            debounce_data[mapped_key] = {"max_code": 0, "timer": None}
        else:
            debounce_data[mapped_key]["max_code"] = 0

        if debounce_data[mapped_key]["timer"] is not None:
            debounce_data[mapped_key]["timer"].cancel()

        t = threading.Timer(DEBOUNCE_DELAY, lambda: press_callback(mapped_key))
        debounce_data[mapped_key]["timer"] = t
        t.start()
        return

    if mapped_key not in debounce_data:
        debounce_data[mapped_key] = {"max_code": rep, "timer": None}
    else:
        debounce_data[mapped_key]["max_code"] = max(debounce_data[mapped_key]["max_code"], rep)

    if debounce_data[mapped_key]["timer"] is not None:
        debounce_data[mapped_key]["timer"].cancel()

    t = threading.Timer(DEBOUNCE_DELAY, lambda: press_callback(mapped_key))
    debounce_data[mapped_key]["timer"] = t
    t.start()

def lirc_listener(process_key, config):
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
                    process_key(key, repeat_code)
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

    # --- Load pad configuration ---
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
                pad_touch_thresholds[pad_index] = tth
                pad_release_thresholds[pad_index] = rth
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
    time.sleep(1.0)
    sensor = MPR121(address)
    if not sensor.begin():
        if show_message:
            show_message("error: MPR121 init failed") if show_message else None
        print("error: MPR121 init failed")
        return

    sensor.set_interrupt_pin(int_pin)

    # global defaults
    global_touch = config.getint("mpr121", "touch_threshold", fallback=20)
    global_release = config.getint("mpr121", "release_threshold", fallback=15)
    sensor.set_touch_threshold(global_touch)
    sensor.set_release_threshold(global_release)

    # per-pad overrides
    for i in range(13):
        tth = pad_touch_thresholds.get(i)
        rth = pad_release_thresholds.get(i)
        if tth is not None:
            sensor.set_touch_threshold_for(i, tth)
        if rth is not None:
            sensor.set_release_threshold_for(i, rth)

    # --- Gesture tracking ---
    gesture_history = []
    gesture_timer = None
    GESTURE_TIMEOUT = 0.3
    DIR_NAMES = {0:"UP",1:"RIGHT",2:"DOWN",3:"LEFT"}
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
                    process_key(key, "00")
                    check_fn = lambda s=sensor, idx=t: s.get_touch_data(idx)
                    t_thread = threading.Thread(target=repeat_sender, args=(key, check_fn), daemon=True)
                    repeat_threads[key] = t_thread
                    t_thread.start()
        gesture_history.clear()

    if debug:
        print(f"[mpr121_listener] started @0x{address:02X}")
        print(f"  global touch/release = {global_touch}/{global_release}")
        print("  per-pad config:")
        time.sleep(1)
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

    last_state = set()
    running = True
    gesture_active = config.getboolean("mpr121", "use_gesture", fallback=False)

    while running:
        try:
            if sensor.touch_status_changed():
                sensor.update_all()
                # range(5) for "joystick" gesture
                touched = {i for i in range(5) if sensor.is_new_touch(i)}
                released = {i for i in range(5) if sensor.is_new_release(i)}

                # --- 1. Handle new touches (gesture / single key detection) ---
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

                # --- 2. Handle releases (independent of touches) ---
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
                    # iterate through pads 0..11 (touch electrodes)
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
                                    process_key(key, "00")

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

            time.sleep(0.01)
        except KeyboardInterrupt:
            running = False
        except Exception as e:
            print("error mpr121 listener:", e)
            if show_message:
                show_message("error mpr121 listener")
            time.sleep(0.1)

def rotary_listener(pin_a, pin_b, process_key, config=None):
    divider = 2
    invert = False
    min_poll_ms = 1.0

    if config is not None:
        try:
            divider = config.getint("rotary", "rotary_divider", fallback=divider)
        except Exception:
            pass
        try:
            invert = config.getboolean("rotary", "rotary_invert", fallback=invert)
        except Exception:
            pass
        try:
            min_poll_ms = config.getfloat("rotary", "rotary_min_poll_ms", fallback=min_poll_ms)
        except Exception:
            pass

    state_map = {
        (0, 0): 0,
        (0, 1): 1,
        (1, 1): 2,
        (1, 0): 3,
    }

    try:
        a = GPIO.input(pin_a)
        b = GPIO.input(pin_b)
    except Exception as e:
        if show_message:
            show_message(f"error rotary initial read")
        print("error rotary initial read:", e)
        return

    last_val = state_map.get((a, b), 2)
    accum = 0
    poll_delay = max(0.001, min_poll_ms / 1000.0)

    if debug:
        print(f"[rotary_listener] start pins A={pin_a} B={pin_b} divider={divider} invert={invert} poll_ms={min_poll_ms}")

    while True:
        try:
            a = GPIO.input(pin_a)
            b = GPIO.input(pin_b)
            cur = state_map.get((a, b), None)
            if cur is None:
                if debug:
                    print(f"[rotary_listener] unknown state: {(a,b)}")
                time.sleep(poll_delay)
                continue

            if cur != last_val:
                delta = (cur - last_val) % 4
                if delta == 1:
                    step = 1
                elif delta == 3:
                    step = -1
                else:
                    # delta == 2 (invalid / bounce) => ignore
                    step = 0
                    if debug:
                        print(f"[rotary_listener] ignored delta==2 (bounce?) last={last_val} cur={cur}")

                if invert:
                    step = -step

                if step != 0:
                    accum += step
                    if debug:
                        print(f"[rotary_listener] raw_transition last={last_val} cur={cur} step={step} accum={accum}")

                    if abs(accum) >= max(1, divider):
                        if accum > 0:
                            if debug:
                                print("[rotary_listener] EMIT KEY_UP")
                            process_key("KEY_UP", "00")
                        else:
                            if debug:
                                print("[rotary_listener] EMIT KEY_DOWN")
                            process_key("KEY_DOWN", "00")
                        accum = 0

                last_val = cur

            time.sleep(poll_delay)
        except Exception as e:
            if show_message:
                show_message(f"error rotary listener")
            print("error rotary listener:", e)
            time.sleep(0.05)

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

    # LIRC
    if config.getboolean("input", "use_lirc", fallback=False):
        threading.Thread(target=lirc_listener, args=(process_key, config), daemon=True).start()

    # MPR121
    if config.getboolean("input", "use_mpr121", fallback=False):
        threading.Thread(target=mpr121_listener, args=(process_key, config), daemon=True).start()

    # GPIO boutons
    if config.getboolean("input", "use_buttons", fallback=False):
        if GPIO is None:
            print("error: gpio missing")
            if show_message:
                show_message("error: gpio missing")
        elif config.has_section("buttons"):
            for key, pin in config.items("buttons"):
                try:
                    pin = int(pin)
                    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                    GPIO.add_event_detect(
                        pin,
                        GPIO.BOTH,
                        callback=lambda ch, k=key.upper(), p=pin: gpio_event(p, k),
                        bouncetime=int(BOUNCETIME_DELAY * 1000),
                    )
                except Exception as e:
                    if show_message:
                        show_message(f"error gpio pin")
                    print("error gpio pin:", e)

    # Rotary encoder + bouton rotary
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
