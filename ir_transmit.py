#!/usr/bin/env python3
"""IR transmitter CLI for the REI 8K HDMI switch.

The actual logic lives in src/ir_transmitter.py so the Minus webui can import
the same code path. This CLI is for standalone testing.

Examples:
    sudo python3 ir_transmit.py input_1
    sudo python3 ir_transmit.py power
    sudo python3 ir_transmit.py next
    sudo python3 ir_transmit.py auto
    sudo python3 ir_transmit.py --list
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from src.ir_transmitter import (  # noqa: E402
    CODES, IRTransmitter, IRTransmitterError, boost_priority,
)


def main():
    parser = argparse.ArgumentParser(
        description="Send a single NEC IR command to the REI HDMI switch.")
    parser.add_argument(
        "button",
        nargs="?",
        choices=list(CODES.keys()),
        help="Which button to press.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List available buttons and their codes, then exit.",
    )
    args = parser.parse_args()

    if args.list:
        for name, (addr, cmd) in CODES.items():
            print(f"{name:8s} addr=0x{addr:02X} cmd=0x{cmd:02X}")
        return

    if args.button is None:
        parser.error("button is required (or use --list)")

    if os.geteuid() != 0:
        print(
            "WARNING: not root; PWM sysfs writes will likely fail.",
            file=sys.stderr,
        )

    boost_priority()
    tx = IRTransmitter()
    try:
        tx.send(args.button)
        print(f"OK: sent '{args.button}'")
    except IRTransmitterError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    finally:
        tx.shutdown()


if __name__ == "__main__":
    main()
