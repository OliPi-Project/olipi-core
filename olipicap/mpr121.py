#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2025 OliPi Project (Benoit Toufflet)
#
# mpr121.py

from dataclasses import dataclass
import time
import os
from typing import Optional, List

# Optional SMBus
try:
    from smbus2 import SMBus, i2c_msg
except Exception:
    SMBus = None

# Optional RPi.GPIO for reading interrupt pin
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except Exception:
    GPIO_AVAILABLE = False

# --------------------------- Register constants ---------------------------
# touch and OOR statuses
MPR121_TS1       = 0x00
MPR121_TS2       = 0x01
MPR121_OORS1     = 0x02
MPR121_OORS2     = 0x03

# filtered data
MPR121_E0FDL     = 0x04
MPR121_E0FDH     = 0x05
MPR121_E1FDL     = 0x06
MPR121_E1FDH     = 0x07
MPR121_E2FDL     = 0x08
MPR121_E2FDH     = 0x09
MPR121_E3FDL     = 0x0A
MPR121_E3FDH     = 0x0B
MPR121_E4FDL     = 0x0C
MPR121_E4FDH     = 0x0D
MPR121_E5FDL     = 0x0E
MPR121_E5FDH     = 0x0F
MPR121_E6FDL     = 0x10
MPR121_E6FDH     = 0x11
MPR121_E7FDL     = 0x12
MPR121_E7FDH     = 0x13
MPR121_E8FDL     = 0x14
MPR121_E8FDH     = 0x15
MPR121_E9FDL     = 0x16
MPR121_E9FDH     = 0x17
MPR121_E10FDL    = 0x18
MPR121_E10FDH    = 0x19
MPR121_E11FDL    = 0x1A
MPR121_E11FDH    = 0x1B
MPR121_E12FDL    = 0x1C
MPR121_E12FDH    = 0x1D

# baseline values
MPR121_E0BV      = 0x1E
MPR121_E1BV      = 0x1F
MPR121_E2BV      = 0x20
MPR121_E3BV      = 0x21
MPR121_E4BV      = 0x22
MPR121_E5BV      = 0x23
MPR121_E6BV      = 0x24
MPR121_E7BV      = 0x25
MPR121_E8BV      = 0x26
MPR121_E9BV      = 0x27
MPR121_E10BV     = 0x28
MPR121_E11BV     = 0x29
MPR121_E12BV     = 0x2A

# general electrode touch sense baseline filters (rising)
MPR121_MHDR      = 0x2B
MPR121_NHDR      = 0x2C
MPR121_NCLR      = 0x2D
MPR121_FDLR      = 0x2E

# falling filter
MPR121_MHDF      = 0x2F
MPR121_NHDF      = 0x30
MPR121_NCLF      = 0x31
MPR121_FDLF      = 0x32

# touched filter
MPR121_NHDT      = 0x33
MPR121_NCLT      = 0x34
MPR121_FDLT      = 0x35

# proximity electrode filters (rising)
MPR121_MHDPROXR  = 0x36
MPR121_NHDPROXR  = 0x37
MPR121_NCLPROXR  = 0x38
MPR121_FDLPROXR  = 0x39

# proximity falling
MPR121_MHDPROXF  = 0x3A
MPR121_NHDPROXF  = 0x3B
MPR121_NCLPROXF  = 0x3C
MPR121_FDLPROXF  = 0x3D

# proximity touched
MPR121_NHDPROXT  = 0x3E
MPR121_NCLPROXT  = 0x3F
MPR121_FDLPROXT  = 0x40

# electrode touch and release thresholds
MPR121_E0TTH     = 0x41
MPR121_E0RTH     = 0x42
MPR121_E1TTH     = 0x43
MPR121_E1RTH     = 0x44
MPR121_E2TTH     = 0x45
MPR121_E2RTH     = 0x46
MPR121_E3TTH     = 0x47
MPR121_E3RTH     = 0x48
MPR121_E4TTH     = 0x49
MPR121_E4RTH     = 0x4A
MPR121_E5TTH     = 0x4B
MPR121_E5RTH     = 0x4C
MPR121_E6TTH     = 0x4D
MPR121_E6RTH     = 0x4E
MPR121_E7TTH     = 0x4F
MPR121_E7RTH     = 0x50
MPR121_E8TTH     = 0x51
MPR121_E8RTH     = 0x52
MPR121_E9TTH     = 0x53
MPR121_E9RTH     = 0x54
MPR121_E10TTH    = 0x55
MPR121_E10RTH    = 0x56
MPR121_E11TTH    = 0x57
MPR121_E11RTH    = 0x58
MPR121_E12TTH    = 0x59
MPR121_E12RTH    = 0x5A

# debounce settings
MPR121_DTR       = 0x5B

# configuration registers
MPR121_AFE1      = 0x5C
MPR121_AFE2      = 0x5D
MPR121_ECR       = 0x5E

# GPIO
MPR121_CTL0      = 0x73

# auto-config
MPR121_ACCR0     = 0x7B
MPR121_ACCR1     = 0x7C
MPR121_USL       = 0x7D
MPR121_LSL       = 0x7E
MPR121_TL        = 0x7F

# soft reset
MPR121_SRST      = 0x80


# --------------------------- Helper enums / constants ---------------------
PROX_DISABLED = 0
PROX0_1 = 1
PROX0_3 = 2
PROX0_11 = 3

CAL_LOCK_ENABLED = 0
CAL_LOCK_DISABLED = 1
CAL_LOCK_ENABLED_5_BIT_COPY = 2
CAL_LOCK_ENABLED_10_BIT_COPY = 3

SAMPLE_INTERVAL_1MS = 0x00
SAMPLE_INTERVAL_2MS = 0x01
SAMPLE_INTERVAL_4MS = 0x02
SAMPLE_INTERVAL_8MS = 0x03
SAMPLE_INTERVAL_16MS = 0x04
SAMPLE_INTERVAL_32MS = 0x05
SAMPLE_INTERVAL_64MS = 0x06
SAMPLE_INTERVAL_128MS = 0x07

# Error codes
NO_ERROR = 0
RETURN_TO_SENDER = 1
ADDRESS_UNKNOWN = 2
READBACK_FAIL = 3
OVERCURRENT_FLAG = 4
OUT_OF_RANGE = 5
NOT_INITED = 6

# --------------------------- Settings dataclass ---------------------------
@dataclass
class MPR121Settings:
    """Simple container for the MPR121 configuration registers used by apply_settings()."""
    TTHRESH: int = 40
    RTHRESH: int = 20
    INTERRUPT: int = 0
    MHDR: int = 0x01
    NHDR: int = 0x01
    NCLR: int = 0x10
    FDLR: int = 0x20
    MHDF: int = 0x01
    NHDF: int = 0x01
    NCLF: int = 0x10
    FDLF: int = 0x20
    NHDT: int = 0x01
    NCLT: int = 0x10
    FDLT: int = 0xFF
    MHDPROXR: int = 0x0F
    NHDPROXR: int = 0x0F
    NCLPROXR: int = 0x00
    FDLPROXR: int = 0x00
    MHDPROXF: int = 0x01
    NHDPROXF: int = 0x01
    NCLPROXF: int = 0xFF
    FDLPROXF: int = 0xFF
    NHDPROXT: int = 0x00
    NCLPROXT: int = 0x00
    FDLPROXT: int = 0x00
    DTR: int = 0x11
    AFE1: int = 0xFF
    AFE2: int = 0x30
    ECR: int = 0xCC
    ACCR0: int = 0x00
    ACCR1: int = 0x00
    USL: int = 0x00
    LSL: int = 0x00
    TL: int = 0x00

# --------------------------- Main class ------------------------------
class MPR121:

    def __init__(self, address: int = 0x5A, busnum: int = 1, bus: Optional[SMBus] = None):
        self.address = address
        self.busnum = busnum
        self._bus = bus
        self.default_settings = MPR121Settings()
        self.ECR_backup = 0x00
        self._error = 1 << 0  # NOT_INITED
        self.running = False
        self.interrupt_pin: Optional[int] = None
        self.filtered_data: List[int] = [0]*13
        self.baseline_data: List[int] = [0]*13
        self.touch_data = 0
        self.last_touch_data = 0
        self.auto_touch_status_flag = False

    # -------------------- I2C helpers ---------------------------
    def _ensure_bus(self):
        """Open SMBus lazily (only when needed)."""
        if self._bus is None:
            if SMBus is None:
                print("smbus2 not installed")
                raise RuntimeError("smbus2 not available; install smbus2")
            self._bus = SMBus(self.busnum)

    def close(self):
        """Close the SMBus if we opened it."""
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
            self._bus = None

    def _read_byte(self, reg: int) -> int:
        """Read a single byte from register 'reg' using repeated start."""
        self._ensure_bus()
        write = i2c_msg.write(self.address, [reg])
        read = i2c_msg.read(self.address, 1)
        self._bus.i2c_rdwr(write, read)
        return list(read)[0]

    def _write_byte(self, reg: int, val: int) -> None:
        """Write a single byte (val & 0xFF) to register 'reg'."""
        self._ensure_bus()
        self._bus.write_byte_data(self.address, reg, val & 0xFF)

    def _read_word_le(self, reg: int) -> int:
        """Read two bytes LSB/MSB at reg using repeated start, return signed 16-bit value."""
        self._ensure_bus()
        write = i2c_msg.write(self.address, [reg])
        read = i2c_msg.read(self.address, 2)
        self._bus.i2c_rdwr(write, read)
        lo, hi = list(read)
        val = (hi << 8) | lo
        if val & 0x8000:
            val -= 0x10000
        return val

    # -------------------- High level -------------------------
    def begin(self, address: Optional[int] = None) -> bool:
        """
        Initialize the chip: optionally change I2C address then reset/apply defaults.

        Returns True on success.
        """
        if address is not None:
            if address < 0x5A or address > 0x5D:
                print(f"Invalid I2C address {address}")
                self._error |= (1 << 1)
                return False
            self.address = address

        try:
            self._ensure_bus()
        except Exception:
            print("SMBus open failed")
            self._error |= (1 << 1)
            return False

        self._error &= ~(1 << 0)  # clear NOT_INITED

        if self.reset():
            # apply defaults (this will also set thresholds)
            self.apply_settings(self.default_settings)
            print("MPR121 initialized successfully")
            return True
        print("MPR121 initialization failed")
        return False

    def reset(self) -> bool:
        """Soft reset the chip and check a few registers to detect errors."""
        try:
            self.set_register(MPR121_SRST, 0x63)
        except Exception:
            self._error |= (1 << 2)
            return False

        try:
            afe2 = self.get_register(MPR121_AFE2)
            if afe2 != 0x24:
                # non fatal but mark readback bit
                self._error |= (1 << 2)
            else:
                self._error &= ~(1 << 2)

            ts2 = self.get_register(MPR121_TS2)
            if (ts2 & 0x80) != 0:
                self._error |= (1 << 3)
            else:
                self._error &= ~(1 << 3)
        except Exception:
            self._error |= (1 << 2)

        if self.get_error() in (NOT_INITED, NO_ERROR):
            return True
        return False

    def apply_settings(self, settings: MPR121Settings) -> None:
        """
        Apply a MPR121Settings instance to the chip. This writes a set of
        baseline/filter/AFE registers, then thresholds.

        The method stops the chip if required, and restores run state.
        """
        was_running = self.running
        if was_running:
            self.stop()

        # Write core filter/AFE registers (order like C++ original)
        # NOTE: ensure constants exist in module (we kept same names)
        self.set_register(MPR121_MHDR, settings.MHDR)
        self.set_register(MPR121_NHDR, settings.NHDR)
        self.set_register(MPR121_NCLR, settings.NCLR)
        self.set_register(MPR121_FDLR, settings.FDLR)
        self.set_register(MPR121_MHDF, settings.MHDF)
        self.set_register(MPR121_NHDF, settings.NHDF)
        self.set_register(MPR121_NCLF, settings.NCLF)
        self.set_register(MPR121_FDLF, settings.FDLF)
        self.set_register(MPR121_NHDT, settings.NHDT)
        self.set_register(MPR121_NCLT, settings.NCLT)
        self.set_register(MPR121_FDLT, settings.FDLT)
        self.set_register(MPR121_MHDPROXR, settings.MHDPROXR)
        self.set_register(MPR121_NHDPROXR, settings.NHDPROXR)
        self.set_register(MPR121_NCLPROXR, settings.NCLPROXR)
        self.set_register(MPR121_FDLPROXR, settings.FDLPROXR)
        self.set_register(MPR121_MHDPROXF, settings.MHDPROXF)
        self.set_register(MPR121_NHDPROXF, settings.NHDPROXF)
        self.set_register(MPR121_NCLPROXF, settings.NCLPROXF)
        self.set_register(MPR121_FDLPROXF, settings.FDLPROXF)
        self.set_register(MPR121_NHDPROXT, settings.NHDPROXT)
        self.set_register(MPR121_NCLPROXT, settings.NCLPROXT)
        self.set_register(MPR121_FDLPROXT, settings.FDLPROXT)
        self.set_register(MPR121_DTR, settings.DTR)
        self.set_register(MPR121_AFE1, settings.AFE1)
        self.set_register(MPR121_AFE2, settings.AFE2)
        self.set_register(MPR121_ACCR0, settings.ACCR0)
        self.set_register(MPR121_ACCR1, settings.ACCR1)
        self.set_register(MPR121_USL, settings.USL)
        self.set_register(MPR121_LSL, settings.LSL)
        self.set_register(MPR121_TL, settings.TL)

        # Set ECR last (affects running state)
        self.set_register(MPR121_ECR, settings.ECR)

        self._error &= ~(1 << 0)  # clear NOT_INITED

        # thresholds and interrupt pin
        self.set_touch_threshold(settings.TTHRESH)
        self.set_release_threshold(settings.RTHRESH)
        try:
            self.set_interrupt_pin(settings.INTERRUPT)
        except Exception:
            # optional: ignore if RPi.GPIO not present
            print("set_interrupt_pin not configured (GPIO missing?)")

        if was_running:
            self.run()

    def get_error(self) -> int:
        """Return a single error code integer similar to the C++ API."""
        # Read OOR regs first (some chips clear IRQ on read)
        try:
            self.get_register(MPR121_OORS1)
            self.get_register(MPR121_OORS2)
        except Exception:
            pass

        if not self.is_inited():
            print("MPR121 not initialized")
            return NOT_INITED
        if (self._error & (1 << 1)) != 0:
            print("MPR121 I2C address unknown")
            return ADDRESS_UNKNOWN
        if (self._error & (1 << 2)) != 0:
            print("MPR121 register readback failed")
            return READBACK_FAIL
        if (self._error & (1 << 3)) != 0:
            print("MPR121 overcurrent flag set")
            return OVERCURRENT_FLAG
        if (self._error & (1 << 4)) != 0:
            print("MPR121 out of range error")
            return OUT_OF_RANGE

        return NO_ERROR

    def clear_error(self) -> None:
        self._error = 0

    def is_running(self) -> bool:
        return self.running

    def is_inited(self) -> bool:
        return (self._error & (1 << 0)) == 0

    # -------------------- Register access with state handling ----------
    def set_register(self, reg: int, value: int) -> None:
        """
        Write register and preserve running state when appropriate.
        For most registers the chip must be stopped before write.
        """
        was_running = False
        if reg == MPR121_ECR:
            # ECR directly affects running
            if value & 0x3F:
                self.running = True
            else:
                self.running = False
        elif reg < MPR121_CTL0:
            was_running = self.running
            if was_running:
                self.stop()

        self._write_byte(reg, value)

        if was_running:
            self.run()

    def get_register(self, reg: int) -> int:
        """Read a register and update auto errors flags from special regs."""
        val = self._read_byte(reg)
        if reg == MPR121_TS2 and ((val & 0x80) != 0):
            self._error |= (1 << 3)  # overcurrent
        else:
            self._error &= ~(1 << 3)

        if (reg == MPR121_OORS1 or reg == MPR121_OORS2) and (val != 0):
            self._error |= (1 << 4)  # out of range
        else:
            self._error &= ~(1 << 4)

        return val

    # -------------------- run / stop ------------------------------------
    def run(self) -> None:
        if not self.is_inited():
            return
        self.set_register(MPR121_ECR, self.ECR_backup)

    def stop(self) -> None:
        if not self.is_inited():
            return
        self.ECR_backup = self.get_register(MPR121_ECR)
        self.set_register(MPR121_ECR, self.ECR_backup & 0xC0)

    # -------------------- touch / baseline / filtered updates ------------
    def update_touch_data(self) -> None:
        """Read TS1/TS2 and update touch_data / last_touch_data."""
        if not self.is_inited():
            return
        self.auto_touch_status_flag = False
        self.last_touch_data = self.touch_data
        ts1 = self.get_register(MPR121_TS1)
        ts2 = self.get_register(MPR121_TS2)
        self.touch_data = ts1 | (ts2 << 8)

    def get_touch_data(self, electrode: int) -> bool:
        if electrode > 12 or not self.is_inited():
            return False
        return ((self.touch_data >> electrode) & 1) == 1

    def get_num_touches(self) -> int:
        if not self.is_inited():
            return 0xFF
        return sum(1 for i in range(13) if self.get_touch_data(i))

    def get_last_touch_data(self, electrode: int) -> bool:
        if electrode > 12 or not self.is_inited():
            return False
        return ((self.last_touch_data >> electrode) & 1) == 1

    def update_filtered_data(self) -> bool:
        """Read filtered values for all electrodes into self.filtered_data."""
        if not self.is_inited():
            return False
        if self.touch_status_changed():
            self.auto_touch_status_flag = True
        for i in range(13):
            self.filtered_data[i] = self._read_word_le(MPR121_E0FDL + (i * 2))
        return True

    def get_filtered_data(self, electrode: int) -> int:
        if electrode > 12 or not self.is_inited():
            return 0xFFFF
        return self.filtered_data[electrode]

    def update_baseline_data(self) -> bool:
        """Read baseline values (8-bit registers shifted left by 2 like original driver)."""
        if not self.is_inited():
            return False
        if self.touch_status_changed():
            self.auto_touch_status_flag = True
        for i in range(13):
            self.baseline_data[i] = (self.get_register(MPR121_E0BV + i) << 2)
        return True

    def get_baseline_data(self, electrode: int) -> int:
        if electrode > 12 or not self.is_inited():
            return 0xFFFF
        return self.baseline_data[electrode]

    def is_new_touch(self, electrode: int) -> bool:
        if electrode > 12 or not self.is_inited():
            return False
        return (self.get_last_touch_data(electrode) == False) and (self.get_touch_data(electrode) == True)

    def is_new_release(self, electrode: int) -> bool:
        if electrode > 12 or not self.is_inited():
            return False
        return (self.get_last_touch_data(electrode) == True) and (self.get_touch_data(electrode) == False)

    def update_all(self) -> None:
        """Convenience: update touch, baseline and filtered in one call."""
        self.update_touch_data()
        self.update_baseline_data()
        self.update_filtered_data()

    # -------------------- thresholds helpers -----------------------------
    def set_touch_threshold(self, val: int) -> None:
        """Set same touch threshold for all electrodes (0..255)."""
        if not self.is_inited():
            return
        was_running = self.running
        if was_running:
            self.stop()
        for i in range(13):
            self.set_touch_threshold_for(i, val)
        if was_running:
            self.run()

    def set_touch_threshold_for(self, electrode: int, val: int) -> None:
        """Set touch threshold for specified electrodes (0..255)."""
        if electrode > 12 or not self.is_inited():
            return
        self.set_register(MPR121_E0TTH + (electrode << 1), val)

    def set_release_threshold(self, val: int) -> None:
        """Set same release threshold for all electrodes."""
        if not self.is_inited():
            return
        was_running = self.running
        if was_running:
            self.stop()
        for i in range(13):
            self.set_release_threshold_for(i, val)
        if was_running:
            self.run()

    def set_release_threshold_for(self, electrode: int, val: int) -> None:
        """Set release threshold for specified electrodes."""
        if electrode > 12 or not self.is_inited():
            return
        self.set_register(MPR121_E0RTH + (electrode << 1), val)

    def get_touch_threshold(self, electrode: int) -> int:
        if electrode > 12 or not self.is_inited():
            return 0xFF
        return self.get_register(MPR121_E0TTH + (electrode << 1))

    def get_release_threshold(self, electrode: int) -> int:
        if electrode > 12 or not self.is_inited():
            return 0xFF
        return self.get_register(MPR121_E0RTH + (electrode << 1))

    # -------------------- interrupt / status -----------------------
    def set_interrupt_pin(self, pin: int) -> None:
        """
        Configure an INT pin number for the Pi (BCM numbering). If RPi.GPIO is
        not available we still store the pin number (useful in higher layers).
        """
        if not self.is_inited():
            return
        self.interrupt_pin = pin
        if not GPIO_AVAILABLE:
            print("RPi.GPIO not available; stored interrupt_pin but not configured")
            return
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        #print(f"Configured interrupt pin {pin}")

    def touch_status_changed(self) -> bool:
        """
        Return True if last-touch auto flag set or if INT pin is asserted.
        Note: if no INT pin configured this returns False (use polling).
        """
        if self.auto_touch_status_flag:
            return True
        if self.interrupt_pin is None:
            return False
        if GPIO_AVAILABLE:
            return not GPIO.input(self.interrupt_pin)
        return False

    # -------------------- proximity / calibration -----------------
    def set_prox_mode(self, mode: int) -> None:
        """Configure proximity sensing mode (none / 1 / 4 / 12 electrodes)."""
        if not self.is_inited():
            return
        was_running = self.running
        if was_running:
            self.stop()
        if mode == PROX_DISABLED:           # 0
            self.ECR_backup &= ~(3 << 4)
        elif mode == PROX0_1:               # 1
            self.ECR_backup |= (1 << 4)
            self.ECR_backup &= ~(1 << 5)
        elif mode == PROX0_3:               # 2
            self.ECR_backup &= ~(1 << 4)
            self.ECR_backup |= (1 << 5)
        elif mode == PROX0_11:              # 3
            self.ECR_backup |= (3 << 4)
        print(f"Proximity mode set to {mode}")
        if was_running:
            self.run()

    def set_calibration_lock(self, lock: int) -> None:
        """Lock or unlock calibration registers with optional bit-copy modes."""
        if not self.is_inited():
            return
        was_running = self.running
        if was_running:
            self.stop()
        if lock == CAL_LOCK_ENABLED:
            self.ECR_backup &= ~(3 << 6)
        elif lock == CAL_LOCK_DISABLED:
            self.ECR_backup |= (1 << 6)
            self.ECR_backup &= ~(1 << 7)
        elif lock == CAL_LOCK_ENABLED_5_BIT_COPY:
            self.ECR_backup &= ~(1 << 6)
            self.ECR_backup |= (1 << 7)
        elif lock == CAL_LOCK_ENABLED_10_BIT_COPY:
            self.ECR_backup |= (3 << 4)
        print(f"Calibration lock set to {lock}")
        if was_running:
            self.run()

    def set_num_enabled_electrodes(self, numElectrodes: int) -> None:
        """Set the number of touch electrodes (0-12) to enable."""
        if not self.is_inited():
            return
        if numElectrodes > 12:
            numElectrodes = 12
        was_running = self.running
        if was_running:
            self.stop()
        self.ECR_backup = (0x0F & numElectrodes) | (self.ECR_backup & 0xF0)
        print(f"Num enabled electrodes={numElectrodes}")
        if was_running:
            self.run()

    # -------------------- sample period -----------------
    def set_sample_period(self, period: int) -> None:
        """Set the touch sampling interval (must be power of 2)."""
        scratch = self.get_register(MPR121_AFE2)
        self.set_register(MPR121_AFE2, (scratch & 0xF8) | (period & 0x07))

    # -------------------- utility/read helpers ---------------------------
    def read_registers(self, start: int, count: int) -> List[int]:
        """Read a sequence of bytes starting at 'start' (simple helper)."""
        return [self._read_byte(start + i) for i in range(count)]

# Single global instance for convenience (like original C++/py wrapper)
mpr121 = MPR121()
