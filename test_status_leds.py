#!/usr/bin/env python3
"""
Walk/cycle test for the WS2812B status strip.

Verifies wiring: runs a "walk" (one LED lit at a time, 0→7) then a
"flash all" for each of red, green, blue, white. If a particular LED
stays dark on every colour its chain is broken at that point; if colours
come out wrong the GRB reorder is off.

Run:
    sudo python3 test_status_leds.py
    # or, after adding yourself to the spi group:
    python3 test_status_leds.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from status_leds import StatusLEDs, StatusLEDsError


COLOURS = (
    ("red",   (255,   0,   0)),
    ("green", (  0, 255,   0)),
    ("blue",  (  0,   0, 255)),
    ("white", (255, 255, 255)),
)


def main():
    try:
        leds = StatusLEDs()
    except StatusLEDsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    with leds:
        for name, rgb in COLOURS:
            print(f"-> walk {name}")
            for i in range(leds.num_leds):
                leds.clear()
                leds.set_pixel(i, *rgb)
                leds.show()
                time.sleep(0.08)
            print(f"-> flash {name}")
            leds.set_all(*rgb)
            leds.show()
            time.sleep(0.6)
        print("done.")


if __name__ == "__main__":
    main()
