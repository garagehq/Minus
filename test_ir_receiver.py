#!/usr/bin/env python3
"""Read an IR receiver wired to pin 38 (GPIO3_B2 / Linux GPIO 106) and print
button presses.

Wiring (typical TSOP38238 / VS1838B / similar 3-pin receiver):
  - VCC  -> pin 1  (3.3V) or pin 2 (5V) — check the receiver's spec
  - GND  -> pin 6  (GND)
  - DATA -> pin 38 (GPIO3_B2, this script reads gpiochip3 line 10)

The receiver demodulates the 38 kHz carrier internally, so its output is a
clean inverted pulse train: HIGH when idle, LOW during an IR burst. We let
gpiomon emit timestamped edge events and decode NEC in Python.

Usage:
  python3 test_ir_receiver.py            # decode mode (default)
  python3 test_ir_receiver.py --raw      # print every pulse with duration
  python3 test_ir_receiver.py --gap-ms 8 # tweak frame-end idle gap

Press buttons on a remote pointed at the receiver. Ctrl+C to stop.
"""

import argparse
import shutil
import signal
import subprocess
import sys
import time

GPIOCHIP = "gpiochip3"
LINE = 10  # PIN_38 / GPIO3_B2

NEC_LEADER_MARK_US = 9000
NEC_LEADER_SPACE_US = 4500
NEC_BIT_MARK_US = 562
NEC_ZERO_SPACE_US = 562
NEC_ONE_SPACE_US = 1687
NEC_REPEAT_SPACE_US = 2250
TOLERANCE = 0.30  # ±30%, cheap remotes drift a lot


def near(value_us: float, target_us: float, tol: float = TOLERANCE) -> bool:
    return abs(value_us - target_us) <= target_us * tol


def decode_nec(pulses):
    """pulses = alternating [mark_us, space_us, mark_us, space_us, ...].
    A 'mark' is a LOW burst (receiver pulls low while seeing 38kHz).
    A 'space' is HIGH idle between bursts.
    Returns (address, command, is_extended, valid_inverted) or None.
    """
    # Repeat code: 9ms mark, 2.25ms space, 562us mark
    if len(pulses) >= 3 and near(pulses[0], NEC_LEADER_MARK_US) \
            and near(pulses[1], NEC_REPEAT_SPACE_US) \
            and near(pulses[2], NEC_BIT_MARK_US):
        return ("REPEAT", None, False, True)

    # Full frame: leader + 32 data bits (each = mark + space) + final mark
    # = 1 + 1 + 64 + 1 = 67 edges
    if len(pulses) < 67:
        return None
    if not near(pulses[0], NEC_LEADER_MARK_US):
        return None
    if not near(pulses[1], NEC_LEADER_SPACE_US):
        return None

    bits = []
    for i in range(32):
        mark = pulses[2 + i * 2]
        space = pulses[3 + i * 2]
        if not near(mark, NEC_BIT_MARK_US):
            return None
        if near(space, NEC_ZERO_SPACE_US):
            bits.append(0)
        elif near(space, NEC_ONE_SPACE_US):
            bits.append(1)
        else:
            return None

    # NEC sends LSB-first per byte
    def bits_to_byte(b):
        v = 0
        for i, bit in enumerate(b):
            v |= bit << i
        return v

    addr = bits_to_byte(bits[0:8])
    addr_inv = bits_to_byte(bits[8:16])
    cmd = bits_to_byte(bits[16:24])
    cmd_inv = bits_to_byte(bits[24:32])

    addr_ok = (addr ^ addr_inv) == 0xFF
    cmd_ok = (cmd ^ cmd_inv) == 0xFF
    extended = not addr_ok  # NEC-extended uses a 16-bit address (no inversion)

    if extended:
        full_addr = (addr_inv << 8) | addr
        return (full_addr, cmd, True, cmd_ok)
    return (addr, cmd, False, addr_ok and cmd_ok)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", action="store_true",
                    help="Print every edge / pulse, don't try to decode")
    ap.add_argument("--gap-ms", type=float, default=15.0,
                    help="Idle gap (ms) that ends a frame (default: 15)")
    ap.add_argument("--chip", default=GPIOCHIP)
    ap.add_argument("--line", type=int, default=LINE)
    args = ap.parse_args()

    if not shutil.which("gpiomon"):
        sys.exit("gpiomon not found — install libgpiod (apt install gpiod)")

    cmd = ["gpiomon", "--format=%e %s.%n", args.chip, str(args.line)]
    print(f"Listening on {args.chip} line {args.line}...")
    print(f"Mode: {'RAW' if args.raw else 'NEC DECODE'} | frame gap: {args.gap_ms} ms")
    print("Press buttons on the remote. Ctrl+C to stop.\n")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    signal.signal(signal.SIGINT, lambda *a: (proc.terminate(), sys.exit(0)))

    last_edge_ns = None
    last_event = None  # 0=falling, 1=rising
    pulses_us = []  # alternating mark/space starting with leader mark
    frame_count = 0
    gap_us = args.gap_ms * 1000.0

    def flush_frame():
        nonlocal pulses_us, frame_count
        if not pulses_us:
            return
        frame_count += 1
        if args.raw:
            print(f"[frame {frame_count}] {len(pulses_us)} pulses:")
            for i, p in enumerate(pulses_us):
                tag = "MARK" if i % 2 == 0 else "SPACE"
                print(f"  {i:3d} {tag:5s} {p:7.0f} us")
        else:
            result = decode_nec(pulses_us)
            ts = time.strftime("%H:%M:%S")
            if result is None:
                print(f"[{ts}] frame {frame_count}: undecodable "
                      f"({len(pulses_us)} pulses, leader="
                      f"{pulses_us[0]:.0f}/{pulses_us[1] if len(pulses_us) > 1 else 0:.0f} us)"
                      "  — try --raw to inspect")
            elif result[0] == "REPEAT":
                print(f"[{ts}] frame {frame_count}: NEC REPEAT")
            else:
                addr, cmd, extended, valid = result
                kind = "NEC-ext" if extended else "NEC"
                check = "ok" if valid else "INVERTED-CHECK-FAIL"
                if extended:
                    print(f"[{ts}] frame {frame_count}: {kind}  "
                          f"addr=0x{addr:04X}  cmd=0x{cmd:02X}  [{check}]")
                else:
                    print(f"[{ts}] frame {frame_count}: {kind}      "
                          f"addr=0x{addr:02X}    cmd=0x{cmd:02X}  [{check}]")
        pulses_us = []

    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev_str, ts_str = line.split(" ", 1)
                ev = int(ev_str)
                sec_str, ns_str = ts_str.split(".")
                ts_ns = int(sec_str) * 1_000_000_000 + int(ns_str)
            except ValueError:
                continue

            if last_edge_ns is None:
                last_edge_ns = ts_ns
                last_event = ev
                continue

            delta_us = (ts_ns - last_edge_ns) / 1000.0

            # If we've been idle longer than gap_us at HIGH, the previous frame ended.
            # last_event tells us the level since last_edge_ns: after a rising edge
            # the line was HIGH (idle), after a falling edge it was LOW (mark).
            if last_event == 1 and delta_us >= gap_us and pulses_us:
                flush_frame()
                last_edge_ns = ts_ns
                last_event = ev
                continue

            # Append the just-completed interval.
            # last_event was the edge AT last_edge_ns. After a falling edge the
            # line was LOW until now (a MARK). After a rising edge it was HIGH
            # (a SPACE).
            interval_was_mark = (last_event == 0)

            if not pulses_us:
                # First pulse of a frame must be a MARK (leader). If we're
                # starting on a space, ignore it.
                if interval_was_mark:
                    pulses_us.append(delta_us)
            else:
                pulses_us.append(delta_us)

            last_edge_ns = ts_ns
            last_event = ev

    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait(timeout=1)
        if pulses_us:
            flush_frame()
        print(f"\n{frame_count} frame(s) captured.")


if __name__ == "__main__":
    main()
