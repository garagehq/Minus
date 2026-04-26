"""IR transmitter for the REI 8K HDMI switch via PWM3 on GPIO3_B2 (pin 38).

Hardware: IR LED driven from header pin 38 (GPIO3_B2) muxed to PWM3_M1.
Protocol: NEC (8-bit address + 8-bit command + their inverted complements).
Carrier: 38 kHz square wave, 50% duty.

Requires the rk3588-pwm3-m1 device-tree overlay so ``/sys/class/pwm`` exposes
the chip whose ``device`` symlink points at ``fd8b0030.pwm``.

Usage:
    tx = IRTransmitter()
    tx.send("power")      # auto-initializes
    tx.send("input_1")
    tx.shutdown()         # only on process exit / when toggling IR off
"""

import glob
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

CARRIER_HZ = 38000
PERIOD_NS = round(1e9 / CARRIER_HZ)        # 26316 ns
DUTY_NS_ON = PERIOD_NS // 2                # 13158 ns -> 50%
PWM3_DEV_TAG = "fd8b0030.pwm"

NEC_LEADER_MARK_US = 9000
NEC_LEADER_SPACE_US = 4500
NEC_BIT_MARK_US = 562
NEC_ZERO_SPACE_US = 562
NEC_ONE_SPACE_US = 1687
NEC_END_MARK_US = 562

DUTY_ON_BYTES = str(DUTY_NS_ON).encode()
DUTY_OFF_BYTES = b"0"

# Captured from the REI 8K HDMI switch's bundled remote via Flipper Zero.
CODES = {
    "input_1": (0x80, 0x07),
    "input_2": (0x80, 0x1B),
    "input_3": (0x80, 0x08),
    "power":   (0x80, 0x05),
    "next":    (0x80, 0x1F),
    "auto":    (0x80, 0x09),
}


class IRTransmitterError(Exception):
    pass


class IRCooldownError(IRTransmitterError):
    """Raised by send() when called inside the post-send cooldown window."""

    def __init__(self, remaining_s):
        super().__init__(
            f"cooldown active — wait {remaining_s:.2f}s before next send")
        self.remaining_s = remaining_s


def _find_pwm_chip():
    for chip in sorted(glob.glob("/sys/class/pwm/pwmchip*")):
        link = os.path.join(chip, "device")
        if os.path.islink(link) and PWM3_DEV_TAG in os.readlink(link):
            return chip
    return None


def _nec_pulses(address, command):
    pulses = [(True, NEC_LEADER_MARK_US), (False, NEC_LEADER_SPACE_US)]
    payload = (
        address & 0xFF,
        (~address) & 0xFF,
        command & 0xFF,
        (~command) & 0xFF,
    )
    for byte in payload:
        for i in range(8):
            bit = (byte >> i) & 1
            pulses.append((True, NEC_BIT_MARK_US))
            pulses.append((False, NEC_ONE_SPACE_US if bit else NEC_ZERO_SPACE_US))
    pulses.append((True, NEC_END_MARK_US))
    return pulses


class IRTransmitter:
    """Sends NEC IR codes over PWM3. Thread-safe; sends are serialized."""

    # Minimum gap between successful sends. Prevents button-mashing from
    # flooding the receiver and gives the LED a refractory window.
    COOLDOWN_S = 1.5

    def __init__(self):
        self._lock = threading.Lock()
        self._chip_path = None
        self._pwm_path = None
        self._duty_fd = None
        self._last_send_monotonic = 0.0

    @staticmethod
    def hardware_available():
        return _find_pwm_chip() is not None

    @property
    def initialized(self):
        return self._duty_fd is not None

    def initialize(self):
        """Set up PWM3 for IR carrier output. Idempotent."""
        with self._lock:
            if self._duty_fd is not None:
                return
            chip = _find_pwm_chip()
            if chip is None:
                raise IRTransmitterError(
                    f"No pwmchip mapped to {PWM3_DEV_TAG}. "
                    f"Enable rk3588-pwm3-m1 overlay and reboot."
                )
            pwm_path = os.path.join(chip, "pwm0")
            if not os.path.isdir(pwm_path):
                self._write(os.path.join(chip, "export"), "0")
                for _ in range(50):
                    if os.path.isdir(pwm_path):
                        break
                    time.sleep(0.01)
                else:
                    raise IRTransmitterError(
                        f"pwm0 did not appear under {chip}")

            try:
                self._write(os.path.join(pwm_path, "enable"), "0")
            except OSError:
                pass
            try:
                self._write(os.path.join(pwm_path, "duty_cycle"), "0")
            except OSError:
                pass
            # Polarity must be set while disabled. Chip default is "inversed",
            # which would flip mark/space at the LED.
            try:
                self._write(os.path.join(pwm_path, "polarity"), "normal")
            except OSError:
                pass
            self._write(os.path.join(pwm_path, "period"), str(PERIOD_NS))
            self._write(os.path.join(pwm_path, "duty_cycle"), "0")
            self._write(os.path.join(pwm_path, "enable"), "1")

            self._duty_fd = os.open(
                os.path.join(pwm_path, "duty_cycle"), os.O_WRONLY)
            self._chip_path = chip
            self._pwm_path = pwm_path
            logger.info(
                f"[IR] ready on {chip} (pwm0) -> {PWM3_DEV_TAG}, "
                f"carrier {CARRIER_HZ} Hz")

    def shutdown(self):
        with self._lock:
            if self._duty_fd is None:
                return
            try:
                os.write(self._duty_fd, DUTY_OFF_BYTES)
            except OSError:
                pass
            try:
                os.close(self._duty_fd)
            except OSError:
                pass
            try:
                self._write(os.path.join(self._pwm_path, "enable"), "0")
            except OSError:
                pass
            self._duty_fd = None
            self._pwm_path = None
            self._chip_path = None
            logger.info("[IR] shut down")

    def send(self, button):
        if button not in CODES:
            raise IRTransmitterError(f"unknown button '{button}'")
        if self._duty_fd is None:
            self.initialize()
        addr, cmd = CODES[button]
        pulses = _nec_pulses(addr, cmd)
        with self._lock:
            if self._duty_fd is None:
                raise IRTransmitterError("transmitter not initialized")
            elapsed = time.monotonic() - self._last_send_monotonic
            if elapsed < self.COOLDOWN_S:
                raise IRCooldownError(self.COOLDOWN_S - elapsed)
            self._transmit_pulses(pulses)
            self._last_send_monotonic = time.monotonic()
        logger.info(f"[IR] sent '{button}' (addr=0x{addr:02X} cmd=0x{cmd:02X})")

    def _transmit_pulses(self, pulses):
        next_deadline = time.perf_counter_ns()
        fd = self._duty_fd
        for is_mark, dur_us in pulses:
            os.write(fd, DUTY_ON_BYTES if is_mark else DUTY_OFF_BYTES)
            next_deadline += dur_us * 1000
            while time.perf_counter_ns() < next_deadline:
                pass
        os.write(fd, DUTY_OFF_BYTES)

    @staticmethod
    def _write(path, value):
        with open(path, "w") as f:
            f.write(value)


def boost_priority():
    """Best-effort: pin to last CPU + SCHED_FIFO. Reduces busy-wait jitter."""
    try:
        os.sched_setaffinity(0, {os.cpu_count() - 1})
    except (AttributeError, OSError):
        pass
    try:
        os.nice(-20)
    except OSError:
        pass
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(80))
    except (AttributeError, OSError, PermissionError):
        pass
