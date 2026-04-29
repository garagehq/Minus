# Status LED Strip — 8× WS2812B via SPI0 MOSI

An 8-LED WS2812B strip driven off header pin 19 (`GPIO1_B2` muxed as
`SPI0_MOSI_M2`). SPI MOSI is used instead of GPIO bit-banging because
the WS2812B 800 kHz protocol needs ~1.25 µs-per-bit timing with sub-µs
precision, which userspace GPIO on Linux can't deliver reliably —
kernel scheduling jitter corrupts the signal. The SPI controller clocks
the line in hardware, so timing is exact.

## Hardware

| Role | Header pin | Notes |
|---|---|---|
| Data | **19** (`GPIO1_B2` / `SPI0_MOSI_M2`) | direct 3.3 V drive; no level shifter, no series resistor |
| 5V power | 2 or 4 | Shared with the SoC and USB; see brightness cap below |
| GND | any GND pin | |

A bare-wire connection works on this build — no inline resistor on the
data line and no bulk capacitor across V+/GND are needed for reliable
operation. We tried both with and without the Adafruit-recommended
470 Ω series resistor and 1000 µF electrolytic; the strip behaves
identically. Keep the data wire short (≤ 10 cm) so the 3.3 V → 5 V
threshold margin stays comfortable. If you push to a longer wire or a
larger strip, both parts are still cheap insurance.

### Historical note: the first-LED problem

Earlier revisions of this driver shipped a "sacrificial first pixel"
workaround: physical LED 0 was always sent zeros and the user-facing
API exposed the remaining seven LEDs. The assumption was that the
3.3 V SPI signal sat just below V<sub>IH(min)</sub> = 0.7 × V<sub>DD</sub>
= 3.5 V, and LED 0 latched garbage on first power-up.

After switching the SPI encoding to the canonical Adafruit
8-bit-per-WS-bit at 6.4 MHz pattern (see *Encoding* below), the first
LED decodes reliably with no further intervention — verified bare-wire
on this board. The workaround is gone; the driver now exposes all 8
LEDs.

## One-time system setup

Run `./install.sh` once — it enables the SPI overlay, installs
`python3-spidev`, and adds your user to the `spi` group. Reboot when
prompted. The script is idempotent so re-running is safe.

If you'd rather do it by hand, the underlying steps are:

```bash
# Enable the SPI0-M2-CS0 spidev overlay
sudo mv /boot/dtbo/rk3588-spi0-m2-cs0-spidev.dtbo.disabled \
        /boot/dtbo/rk3588-spi0-m2-cs0-spidev.dtbo
sudo /usr/sbin/u-boot-update   # regenerates /boot/extlinux/extlinux.conf
sudo apt install -y python3-spidev
sudo usermod -aG spi $USER
sudo reboot
```

Equivalent GUI: `sudo rsetup` → *Overlays* → check
`rk3588-spi0-m2-cs0-spidev` → Save.

After reboot `/dev/spidev0.0` must exist. If it doesn't:
`grep fdtoverlay /boot/extlinux/extlinux.conf` should show the line
`fdtoverlays … /boot/dtbo/rk3588-spi0-m2-cs0-spidev.dtbo`, and
`dmesg | grep spi` should show spidev probing successfully.

The CS0 overlay is fine even though we only use MOSI — CS goes unused.

Don't install `rpi_ws281x`, `Adafruit-Blinka`, or
`adafruit-circuitpython-neopixel` — they depend on Broadcom-specific
PWM+DMA hardware and won't work on RK3588.

## Driver layer (`src/status_leds.py`)

Buffered, blocking-show driver. The framebuffer mutators
(`set_pixel`, `set_all`, `clear`) are cheap and don't touch the wire;
`show()` is what serializes one frame over SPI.

```python
from status_leds import StatusLEDs

with StatusLEDs() as leds:
    leds.set_pixel(0, 255, 0, 0)    # user LED 0 (= physical LED 1) red
    leds.set_all(0, 0, 128)         # everyone dim blue
    leds.clear()
    leds.show()
```

### Encoding

SPI is clocked at **6.4 MHz**. Each WS2812B bit is sent as a full SPI
byte (8 SPI bits = 1.25 µs, exactly one WS bit cell):

| WS2812B bit | SPI byte | High time | Low time |
|---|---|---|---|
| `1` | `0b11110000` | ~625 ns | ~625 ns |
| `0` | `0b11000000` | ~313 ns | ~937 ns |

Both fall inside the WS2812B datasheet's T0H/T0L/T1H/T1L tolerance
windows (350/800 and 700/600 ns, each ±150 ns).

This is the canonical pattern used by Adafruit's
``Adafruit_CircuitPython_NeoPixel_SPI`` and most well-regarded Linux
WS2812B libraries. We previously used a 3-bit-per-WS-bit scheme at
2.4 MHz and saw decode errors on a steady frame ("solid green decoded
as cycling red/blue/white"); the 8-bit scheme has roughly 3× more
skew tolerance per WS bit and absorbs the inter-byte gaps the
``spi-rockchip`` driver inserts when its FIFO refills mid-transfer.

Colours are reordered to **GRB** before encoding — that's the wire-
protocol order WS2812B expects. **Both ends** of the frame carry an
80 µs zero-byte reset (64 bytes × 8 SPI bits ÷ 6.4 MHz). The leading
reset is load-bearing: without it, residual high pulses from the
previous frame's tail (or from a FIFO refill gap) shift the decoder
by a fraction of a bit and corrupt every pixel that follows.

Bytes are written via ``writebytes2(bytes)`` — directly from a
``bytes`` object, no per-element list conversion. ``xfer2`` works too
but allocates a Python ``int`` per byte and is more likely to underrun
the SPI FIFO mid-transfer.

### Brightness cap (load-bearing — do not remove)

`BRIGHTNESS = 0.10` is applied inside `set_pixel()` before the value is
stored. Every other setter funnels through `set_pixel()`, so the cap is
inherited everywhere — no call site can bypass it, by design.

Reason: each WS2812B draws ~60 mA at full white. Seven at peak =
~480 mA through the 40-pin header's 5V rail, which is shared with the
SoC and USB. That inrush dips the rail enough to brown out the board
or drop USB devices. 10% caps peak draw at ~48 mA across all 8 LEDs —
well within safe header limits, plenty bright for status indicators,
and small enough to keep the marginal 3.3V → 5V data line decoding
cleanly even without a level shifter.

If you ever need more brightness, add external 5 V power to the strip
(common ground with the Pi); only then is it safe to raise the cap.

## Controller layer (`src/status_led_controller.py`)

`StatusLEDController` wraps the raw driver in a state machine driven
by a background animation thread. It's what the rest of Minus uses —
`minus.py` instantiates one and the ad blocker / health monitor push
state changes into it.

### State catalogue

| State | Visual | When it's used |
|---|---|---|
| `off` | all LEDs dark | strip disabled / quiescent |
| `initializing` | white pulse ~floor → 10% → ~floor (1 step per 500 ms; 14 s/breath) | boot, HDMI restored, anything still loading |
| `idle` | solid green | system healthy, no ad active |
| `blocking` | bouncing red Cylon eye with 2-pixel decaying tail (~150 ms/step) | ad block in progress |
| `paused` | slow yellow breathing (3 s period) | user paused detection from the web UI |
| `no_signal` | slow amber breathing (4 s period) | HDMI signal lost |
| `autonomous` | slow blue breathing (4 s period) | autonomous mode driving the streaming device |
| `wifi_setup` | cyan alternating sweep (~250 ms swap) | captive portal / AP mode active |
| `error` | fast red blink (250 ms on / 250 ms off) | subsystem failure |

Adding a new state is one line in `_RENDERERS`. Each renderer takes
the LED handle and the current frame number and self-paces the effect
from the global 50 ms (20 fps) tick.

### Persistence

The user-facing on/off toggle is persisted to
`~/.minus_status_leds.json` (the systemd service runs as root so the
file lives at `/root/.minus_status_leds.json` in production). The
chosen state itself is runtime-only — the system re-asserts it on
every relevant event (boot → `initializing`, ad block → `blocking`,
etc.).

The `leds_require_display` toggle (see *Display gating* below) is
persisted to `~/.minus_system_settings.json` alongside the rest of the
system flags.

### Display gating

By default the strip stays dark while the **HDMI-TX display is
disconnected or powered off** so a dark room stays dark. The state
machine still ticks underneath — animations resume seamlessly when
the display comes back on, no service restart needed.

Mechanics: the controller takes an optional `drive_predicate` callable.
`Minus` sets one that calls `health_monitor._check_hdmi_output_connected()`
(reads `/sys/class/drm/card0-HDMI-A-*/status`) once per tick. When the
predicate returns False, the worker renders an all-zero frame for the
strip while leaving `state` and `frame` untouched. Sub-200 ms latency
on plug/unplug because that's the tick interval.

Toggle off the gate from the WebUI to keep the strip lit regardless of
display state — useful for headless boxes or initial bring-up.

## HTTP API

| Method + Path | Purpose | Status codes |
|---|---|---|
| `GET /api/leds/status` | Returns `{available, enabled, running, state, states, last_error, gated}` | 200, 503 if module not loaded |
| `POST /api/leds/enable` | Turn the feature on; persists; starts the thread; defaults to `idle` | 200, 503 if hardware missing |
| `POST /api/leds/disable` | Turn the feature off; persists; stops the thread; blanks the strip | 200, 503 if module not loaded |
| `POST /api/leds/state` | Body `{"state": "<name>"}` switches state | 200, 400 unknown state, 403 disabled, 503 module not loaded |
| `GET /api/leds/require_display` | Returns `{leds_require_display, display_connected}` (live HDMI-TX read) | 200, 500 |
| `POST /api/leds/require_display` | Body `{"enabled": true|false}` toggles the display gate | 200, 500 |

Examples:

```bash
curl http://localhost/api/leds/status                 # includes "gated"
curl http://localhost/api/leds/require_display
curl -X POST -H 'Content-Type: application/json' \
     -d '{"enabled":false}' http://localhost/api/leds/require_display
curl -X POST http://localhost/api/leds/enable
curl -X POST -H 'Content-Type: application/json' \
     -d '{"state":"blocking"}' http://localhost/api/leds/state
curl -X POST http://localhost/api/leds/disable
```

## Web UI

A toggle and a 7-button state palette live in the **Autonomous Mode**
section of the Settings tab, right beside the IR Remote panel. The
panel is hidden until the toggle is on. The active state button is
outlined in green and updates whenever something else (ad blocker,
health monitor, API) pushes a state change.

Inside the panel: a secondary "Only when display is on" toggle
controls the display-gate behavior described above. When gated the
status line shows `state: <name> (gated — display off, strip dark)`
so it's obvious why the LEDs aren't visible.

Hardware-not-detected (the SPI overlay isn't loaded) disables the
toggle and replaces the help text with the overlay-enable instructions.

## Internal hooks

The following points push state automatically:

| Trigger | State |
|---|---|
| `Minus.run()` start, if persisted enabled | `initializing` |
| `ad_blocker.start()` (live pipeline up) | `idle` |
| `ad_blocker.show(...)` | `blocking` |
| `ad_blocker.hide(...)` | baseline (idle / autonomous / paused) |
| `ad_blocker.start_no_signal_mode()` | `no_signal` |
| Health monitor `_on_hdmi_lost` | `no_signal` |
| Health monitor `_on_hdmi_restored` (during recovery) | `initializing` |
| Health monitor recovery complete | `idle` |
| `Minus.pause_blocking(...)` | `paused` |
| `Minus.resume_blocking()` | baseline (idle / autonomous) |
| `WiFiManager` AP started callback | `wifi_setup` |
| `WiFiManager` AP stopped callback | `idle` |
| `AutonomousMode` activate (status callback) | `autonomous` (unless blocking) |
| `AutonomousMode` deactivate (status callback) | baseline (idle / paused) |

`baseline` is computed by `Minus._baseline_led_state()`: `paused` if the
user-pause is still in effect, `autonomous` if autonomous mode is
active, otherwise `idle`. This way a blocking event can fire and clear
during an autonomous session without losing the autonomous indicator.

Manual overrides via the API or the UI palette are last-write-wins;
the next automatic event will reassert.

## Failure handling

The strip never crashes the rest of Minus. Two layers protect the service:

1. **Hardware not present at start.** If `/dev/spidev0.0` can't be opened
   (overlay not enabled, missing python3-spidev), `start()` swallows the
   exception, records the message in `last_error`, and stays in a no-op
   state. The toggle in the UI keeps the user's intent. Re-toggling
   off → on after fixing the system retries.
2. **Hardware fails mid-run** (cable pulled, EM noise, etc.). Each
   `show()` runs inside a try/except in the animation loop. After three
   consecutive failures the loop exits, sets `last_error`, and stops
   driving the strip. The user's enabled-toggle preference isn't
   touched — they see `running=false, enabled=true, last_error=…` in
   the API and a yellow warning under the toggle in the UI. Toggling
   off → on retries.

The `/api/leds/status` payload includes `last_error` (string or null)
so any consumer (UI, monitoring) can show it.

## Walk/cycle test

`test_status_leds.py` at repo root walks one LED at a time 0→7 and
then flashes all 8 for each of red, green, blue, white. Useful for
verifying wiring after install.

```bash
python3 test_status_leds.py      # needs spi group membership
sudo python3 test_status_leds.py # otherwise
```

`tests/test_status_led_states.py` walks every controller state across
all 8 LEDs at five seconds each — useful for revalidating animation
timing and decode stability after a wiring or overlay change.

Expected failure patterns:

| Symptom | Likely cause |
|---|---|
| Steady state mis-decodes as cycling colours | Encoding too tight for the SPI driver's inter-byte gaps — should not happen with the current 8-bit-per-WS-bit scheme; suspect a modified copy |
| All LEDs show wrong colours | GRB ↔ RGB reordering (driver handles this; suspect a modified copy) |
| First LED stuck on a single colour | Marginal 3.3V data signalling — keep the data wire short (≤ 10 cm); add a 470 Ω inline resistor and/or 1000 µF V+/GND cap if it persists |
| `/dev/spidev0.0` missing | overlay didn't load; see system-setup section |
| `PermissionError` opening device | user not in `spi` group, and not root |

## Files

- `src/status_leds.py` — raw SPI driver
- `src/status_led_controller.py` — state machine + animation thread
- `test_status_leds.py` — walk/flash hardware test (R/G/B/W cycle)
- `tests/test_status_led_states.py` — hardware walk through every controller state across all 8 LEDs
- `tests/test_status_led_controller.py` — unit tests (mocked hardware, 31 tests)
- `tests/test_status_leds_ui.py` — Playwright UI tests
- `docs/STATUS_LEDS.md` — this document
- `install.sh` — overlay enabler / dep installer

## Future work

- More fine-grained per-LED meanings (OCR / VLM / audio / HDMI / wifi /
  autonomous occupy individual LEDs instead of one global state).
- Brief flash effects on detection events (one-shot pulse on top of
  the steady state).
- Tie autonomous mode entry/exit to `autonomous` state automatically
  (currently only manual via the API).
