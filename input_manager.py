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

# === Constants ===
DEBOUNCE_DELAY = 0.15
BOUNCETIME_DELAY = 0.05
REPEAT_INTERVAL = 0.08

# === Shared data ===
debounce_data = {}

# === External hooks ===
show_message = None
press_callback = None

# === Repeat threads tracking ===
repeat_threads = {}
repeat_counts = {}

# === Remote mapping ===
remote_mapping = {}

debug = False

# --- Common repeat sender for GPIO and rotary button ---
def repeat_sender(key, channel):
    while key in repeat_counts:
        time.sleep(REPEAT_INTERVAL)
        if GPIO.input(channel) == GPIO.LOW:
            repeat_counts[key] += 1
            code = f"{repeat_counts[key]:02x}"
            process_key(key, code)
        else:
            break
    repeat_counts.pop(key, None)
    repeat_threads.pop(key, None)


# --- GPIO button event callback ---
def gpio_event(channel, key):
    if GPIO.input(channel) == GPIO.LOW:
        if key not in repeat_threads:
            repeat_counts[key] = 0
            process_key(key, "00")  # premier appui
            t = threading.Thread(target=repeat_sender, args=(key, channel), daemon=True)
            repeat_threads[key] = t
            t.start()
    else:
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


# === LIRC listener ===
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

def rotary_listener(pin_a, pin_b, process_key, config=None):
    divider = 2
    invert = False
    min_poll_ms = 1.0

    if config is not None:
        try:
            divider = int(config.get("rotary", "rotary_divider", fallback=divider))
        except Exception:
            pass
        try:
            invert = config.getboolean("rotary", "rotary_invert", fallback=invert)
        except Exception:
            pass
        try:
            min_poll_ms = float(config.get("rotary", "rotary_min_poll_ms", fallback=min_poll_ms))
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
        print("error rotary read initial:", e)
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
    if config.getboolean("input", "use_lirc", fallback=True):
        threading.Thread(target=lirc_listener, args=(process_key, config), daemon=True).start()

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
                        callback=lambda ch, k=key.upper(): gpio_event(ch, k),
                        bouncetime=int(BOUNCETIME_DELAY * 1000),
                    )
                except Exception as e:
                    if show_message:
                        show_message(f"error gpio pin: {e}")
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
