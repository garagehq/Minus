#!/usr/bin/env python3
"""Hardware walk test: every controller state across all 8 LEDs.

Drives every state in :mod:`status_led_controller` (off, initializing,
idle, blocking, paused, no_signal, autonomous, wifi_setup, error) for
five seconds each. Useful for verifying:

- the SPI encoding is healthy on this board (steady frames render as
  steady colours, not as cycling decode artifacts);
- every state's animation timing looks right (breath periods, blink
  rates, bounce speed, etc.).

Requires the :mod:`status_leds` driver and a real WS2812B strip on
``/dev/spidev0.0``. Run as root or with the ``spi`` group, and **only
when the Minus service has the LED feature disabled** (otherwise the
service holds the SPI handle and this script will fail to open it):

    sudo systemctl is-active minus    # may still be running, that's fine
    curl -X POST http://localhost/api/leds/disable   # release SPI
    sudo python3 tests/test_status_led_states.py
"""

import sys
import time
from pathlib import Path

# Make `src/` importable so the script can be run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from status_leds import StatusLEDs
from status_led_controller import _RENDERERS, TICK_S


SECONDS_PER_STATE = 5.0
ORDER = (
    "off",
    "initializing",
    "idle",
    "blocking",
    "paused",
    "no_signal",
    "autonomous",
    "wifi_setup",
    "error",
)


def main():
    leds = StatusLEDs()
    print(f"strip num_leds = {leds.num_leds}")
    try:
        for name in ORDER:
            renderer = _RENDERERS[name]
            print(f"  {name:14s} for {SECONDS_PER_STATE}s …", end="", flush=True)
            ticks = int(SECONDS_PER_STATE / TICK_S)
            for f in range(ticks):
                renderer(leds, f)
                leds.show()
                time.sleep(TICK_S)
            print(" done")
    finally:
        leds.clear()
        leds.show()
        leds.close()
    print("strip dark — done.")


if __name__ == "__main__":
    main()
