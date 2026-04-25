#!/usr/bin/env python3
"""
Tests for src/ir_transmitter.py.

Sysfs writes are mocked so these tests run on any host (no PWM3 needed).
The CLI and a real-hardware send have been verified separately on the
Rock 5B via the API endpoints.

Run with:
    python3 -m pytest tests/test_ir_transmitter.py -v
    python3 tests/test_ir_transmitter.py
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import ir_transmitter as ir
from ir_transmitter import (
    CARRIER_HZ,
    CODES,
    DUTY_NS_ON,
    IRCooldownError,
    IRTransmitter,
    IRTransmitterError,
    PERIOD_NS,
    _nec_pulses,
)


class TestNECEncoding(unittest.TestCase):
    """Pulse list output for NEC frames."""

    def test_pulse_count_is_67(self):
        # Leader (2) + 32 bits × 2 + stop (1) = 67
        for addr, cmd in CODES.values():
            self.assertEqual(len(_nec_pulses(addr, cmd)), 67)

    def test_leader_timing(self):
        pulses = _nec_pulses(0x80, 0x07)
        self.assertEqual(pulses[0], (True, 9000))
        self.assertEqual(pulses[1], (False, 4500))

    def test_ends_on_mark(self):
        pulses = _nec_pulses(0x80, 0x07)
        self.assertEqual(pulses[-1], (True, 562))

    def test_address_lsb_first_byte(self):
        # 0x80 = 10000000 → LSB-first bits: 0,0,0,0,0,0,0,1
        # Pulses 2..17 cover the address byte (8 bits × 2 pulses each)
        pulses = _nec_pulses(0x80, 0x00)
        bit_spaces = [pulses[i + 1][1] for i in range(2, 2 + 16, 2)]
        self.assertEqual(
            bit_spaces,
            [562, 562, 562, 562, 562, 562, 562, 1687],
            "Address 0x80 must encode LSB-first as 0000000-1",
        )

    def test_inverted_address_complement(self):
        # ~0x80 & 0xFF = 0x7F = 01111111 → LSB-first: 1,1,1,1,1,1,1,0
        pulses = _nec_pulses(0x80, 0x00)
        bit_spaces = [pulses[i + 1][1] for i in range(18, 18 + 16, 2)]
        self.assertEqual(
            bit_spaces,
            [1687, 1687, 1687, 1687, 1687, 1687, 1687, 562],
        )

    def test_command_byte(self):
        # 0x07 = 00000111 → LSB-first: 1,1,1,0,0,0,0,0
        pulses = _nec_pulses(0x80, 0x07)
        bit_spaces = [pulses[i + 1][1] for i in range(34, 34 + 16, 2)]
        self.assertEqual(
            bit_spaces,
            [1687, 1687, 1687, 562, 562, 562, 562, 562],
        )

    def test_carrier_constants_match_38khz(self):
        self.assertEqual(CARRIER_HZ, 38000)
        self.assertAlmostEqual(PERIOD_NS, 26316, delta=2)
        self.assertAlmostEqual(DUTY_NS_ON, PERIOD_NS // 2, delta=1)


class TestCodes(unittest.TestCase):
    """The captured-from-Flipper code table."""

    def test_all_buttons_present(self):
        for name in ("input_1", "input_2", "input_3", "power", "next", "auto"):
            self.assertIn(name, CODES, f"missing button {name}")

    def test_addresses_are_0x80(self):
        for name, (addr, _) in CODES.items():
            self.assertEqual(addr, 0x80, f"{name} address differs")


class _FakePwmFs:
    """In-memory stand-in for /sys/class/pwm so the transmitter never touches
    real hardware. Writes are recorded so tests can assert ordering."""

    def __init__(self):
        self.exported = False
        self.values = {
            "enable": "0",
            "duty_cycle": "0",
            "period": "0",
            "polarity": "inversed",
        }
        self.write_log = []  # ordered list of (key, value)
        self.duty_writes_via_fd = []  # writes via os.write(fd, ...)

    def write(self, path, value):
        if path.endswith("/export"):
            self.exported = True
            return
        for key in self.values:
            if path.endswith("/" + key):
                self.values[key] = value
                self.write_log.append((key, value))
                return
        raise OSError(2, f"unexpected path {path}")


def _patch_transmitter_for_test(fs):
    """Returns a list of patch objects that swap PWM-touching primitives."""
    fake_chip = "/sys/class/pwm/pwmchip-fake"
    fake_pwm0 = fake_chip + "/pwm0"

    def fake_find_chip():
        return fake_chip

    def fake_isdir(path):
        return path == fake_pwm0 and fs.exported

    def fake_open(path, flags):
        if path == fake_pwm0 + "/duty_cycle":
            return 9999  # sentinel fd
        raise OSError(2, "no")

    def fake_os_write(fd, data):
        if fd == 9999:
            fs.duty_writes_via_fd.append(data)
            return len(data)
        raise OSError(9, "bad fd")

    def fake_os_close(fd):
        pass

    return [
        patch("ir_transmitter._find_pwm_chip", fake_find_chip),
        patch("ir_transmitter.os.path.isdir", fake_isdir),
        patch("ir_transmitter.os.open", fake_open),
        patch("ir_transmitter.os.write", fake_os_write),
        patch("ir_transmitter.os.close", fake_os_close),
        patch.object(IRTransmitter, "_write",
                     staticmethod(lambda path, value: fs.write(path, value))),
    ]


class TestInitializeSequence(unittest.TestCase):
    """initialize() must satisfy the kernel's PWM ordering rules."""

    def test_polarity_set_before_enable(self):
        fs = _FakePwmFs()
        fs.exported = True  # pretend already exported, like the live host
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            tx.initialize()
            keys = [k for (k, _) in fs.write_log]
            # polarity must appear before the final enable=1
            self.assertIn("polarity", keys)
            self.assertIn("period", keys)
            polarity_idx = keys.index("polarity")
            enable_on_idx = next(
                i for i, (k, v) in enumerate(fs.write_log)
                if k == "enable" and v == "1"
            )
            self.assertLess(polarity_idx, enable_on_idx)
            # period must be set before the final duty_cycle=0
            period_idx = keys.index("period")
            self.assertLess(period_idx, enable_on_idx)
            # final state: enabled + carrier configured
            self.assertEqual(fs.values["enable"], "1")
            self.assertEqual(fs.values["period"], str(PERIOD_NS))
            self.assertEqual(fs.values["polarity"], "normal")
        finally:
            for p in patches:
                p.stop()

    def test_initialize_is_idempotent(self):
        fs = _FakePwmFs()
        fs.exported = True
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            tx.initialize()
            log_len = len(fs.write_log)
            tx.initialize()  # second call should noop
            self.assertEqual(len(fs.write_log), log_len)
        finally:
            for p in patches:
                p.stop()

    def test_unavailable_hardware_raises(self):
        with patch("ir_transmitter._find_pwm_chip", return_value=None):
            tx = IRTransmitter()
            with self.assertRaises(IRTransmitterError):
                tx.initialize()


class TestSendBehavior(unittest.TestCase):

    def test_unknown_button_rejected(self):
        tx = IRTransmitter()
        with self.assertRaises(IRTransmitterError):
            tx.send("doesnotexist")

    def test_send_writes_pulse_pattern(self):
        fs = _FakePwmFs()
        fs.exported = True
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            tx.send("power")
            # 67 edges + a final off write = 68 writes through the fd
            self.assertEqual(len(fs.duty_writes_via_fd), 68)
            self.assertEqual(fs.duty_writes_via_fd[-1], b"0")
        finally:
            for p in patches:
                p.stop()

    def test_cooldown_blocks_back_to_back(self):
        fs = _FakePwmFs()
        fs.exported = True
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            tx.send("power")
            with self.assertRaises(IRCooldownError) as ctx:
                tx.send("input_1")
            self.assertGreater(ctx.exception.remaining_s, 0)
            self.assertLessEqual(ctx.exception.remaining_s, IRTransmitter.COOLDOWN_S)
        finally:
            for p in patches:
                p.stop()

    def test_cooldown_clears_after_window(self):
        fs = _FakePwmFs()
        fs.exported = True
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            # Pretend the cooldown expired by rewinding the timestamp.
            tx.send("power")
            tx._last_send_monotonic = (
                time.monotonic() - IRTransmitter.COOLDOWN_S - 0.05)
            tx.send("input_1")  # should not raise
        finally:
            for p in patches:
                p.stop()


class TestShutdown(unittest.TestCase):

    def test_shutdown_disables_pwm(self):
        fs = _FakePwmFs()
        fs.exported = True
        patches = _patch_transmitter_for_test(fs)
        for p in patches:
            p.start()
        try:
            tx = IRTransmitter()
            tx.initialize()
            self.assertTrue(tx.initialized)
            tx.shutdown()
            self.assertFalse(tx.initialized)
            self.assertEqual(fs.values["enable"], "0")
        finally:
            for p in patches:
                p.stop()

    def test_shutdown_when_not_initialized_is_noop(self):
        tx = IRTransmitter()
        tx.shutdown()  # must not raise


class TestHardwareAvailability(unittest.TestCase):

    def test_reports_available_when_chip_present(self):
        with patch("ir_transmitter._find_pwm_chip",
                   return_value="/sys/class/pwm/pwmchip1"):
            self.assertTrue(IRTransmitter.hardware_available())

    def test_reports_unavailable_when_chip_missing(self):
        with patch("ir_transmitter._find_pwm_chip", return_value=None):
            self.assertFalse(IRTransmitter.hardware_available())


if __name__ == "__main__":
    unittest.main(verbosity=2)
