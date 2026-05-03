# IR Transmitter — REI 8K HDMI Switch Control

Minus can drive an IR LED connected to Rock Pi 5B pin 38 to remote-control a
REI 8K 3-port HDMI switch. This lets autonomous mode cycle between streaming
devices (Roku / Fire TV / Google TV) to collect training data from a variety
of home-screen layouts.

The integration is split so the IR code is reusable from multiple callers:

| Piece | File | Purpose |
|---|---|---|
| Core class | `src/ir_transmitter.py` | NEC encoder + PWM driver + 1.5 s cooldown |
| Standalone CLI | `ir_transmit.py` | `sudo python3 ir_transmit.py <button>` for testing |
| Web API | `src/webui.py` (`/api/ir/*`) | HTTP endpoints used by the web UI |
| Web UI | `src/templates/index.html` | Toggle + remote panel in the Autonomous Mode section |
| Wiring | `minus.py` | Instantiates `IRTransmitter`, exposes `ir_enabled` setting |

---

## Hardware

| Property | Value |
|---|---|
| Header pin (Rock 5B) | **38** |
| GPIO | `GPIO3_B2` (Linux GPIO number **106**) |
| Pin function | `PWM3_IR_M1` — one of the PWM3 channel mux options |
| Carrier | 38 kHz, 50 % duty |
| Protocol | NEC (8-bit address + 8-bit command + their inverted complements) |
| PWM chip | `/sys/class/pwm/pwmchipN` whose `device` symlink points to `fd8b0030.pwm` |

The IR LED is powered from 3V3 and GND on the 40-pin header and gated by
pin 38. No external transistor is strictly required at close range; add one
(plus a current-limiting resistor) for longer throw.

### Captured codes

All captured from the REI switch's bundled remote using a Flipper Zero.
Address `0x80` is constant across every button.

| Button | Address | Command |
|---|---|---|
| `input_1` | `0x80` | `0x07` |
| `input_2` | `0x80` | `0x1B` |
| `input_3` | `0x80` | `0x08` |
| `power`   | `0x80` | `0x05` |
| `next`    | `0x80` | `0x1F` — cycles 1→2→3→1 |
| `auto`    | `0x80` | `0x09` — auto-select input |

`next` wraps from input 3 back to input 1.

---

## Device-tree overlay

RK3588 exposes PWM3 via mux option `M1` on GPIO3_B2. The overlay ships
disabled by default. Enable once, then reboot:

```bash
sudo mv /boot/dtbo/rk3588-pwm3-m1.dtbo.disabled /boot/dtbo/rk3588-pwm3-m1.dtbo
sudo /usr/sbin/u-boot-update   # regenerates /boot/extlinux/extlinux.conf
sudo reboot
```

Equivalent GUI path: `sudo rsetup` → *Overlays* → *Manage overlays* →
check `rk3588-pwm3-m1` → Save.

After reboot a second `pwmchipN` appears under `/sys/class/pwm/` whose
`device` symlink resolves to `fd8b0030.pwm`. The transmitter auto-detects
by that address, so the exact `N` value does not matter.

---

## Python module (`src/ir_transmitter.py`)

```python
from ir_transmitter import IRTransmitter, IRCooldownError, IRTransmitterError, CODES

tx = IRTransmitter()                        # cheap, does not touch hardware
IRTransmitter.hardware_available()          # True iff overlay is loaded

tx.send("power")                            # auto-initializes on first call
try:
    tx.send("input_1")
except IRCooldownError as e:                # sent < 1.5 s after last send
    wait = e.remaining_s                    # float seconds remaining

tx.shutdown()                               # release PWM; optional
```

### What `initialize()` does (and why it matters)

PWM sysfs is picky. `initialize()` applies the only sequence that actually
works on this chip:

1. `enable = 0` (best-effort)
2. `duty_cycle = 0` (best-effort — fails silently on a fresh export where `period == 0`)
3. `polarity = normal` — the chip's default is `inversed`, which would flip mark/space at the LED
4. `period = 26316` — 38 kHz carrier
5. `duty_cycle = 0` — carrier off
6. `enable = 1` — carrier is running at 0 % duty, so the LED is dark

After that, `send()` toggles `duty_cycle` between `0` and `13158` (50 %) via
an already-open file descriptor, using `time.perf_counter_ns()` busy-wait
for each mark/space edge. `SCHED_FIFO` is attempted (ignored silently if the
process lacks `CAP_SYS_NICE`) to reduce jitter.

### Cooldown

`IRTransmitter.COOLDOWN_S = 1.5`. `send()` raises `IRCooldownError` when
called within that window of a previous successful send. The check runs
under the instance lock, so it is safe across threads. The cooldown is
per-`IRTransmitter` instance — standalone CLI invocations do not share it.

### Thread safety

A `threading.Lock` serializes `send()` calls. The webui uses a singleton
(`minus.ir_transmitter`) so concurrent HTTP requests cannot interleave
mid-frame.

---

## HTTP API

Base: `http://<minus-host>/`.

| Method | Path | Body | Response |
|---|---|---|---|
| `GET`  | `/api/ir/status` | — | `{enabled, available, initialized, codes}` |
| `POST` | `/api/ir/enable` | — | `{success, ir_enabled}` (or `503` if hardware missing) |
| `POST` | `/api/ir/disable` | — | `{success, ir_enabled}` |
| `POST` | `/api/ir/command` | `{"button": "<name>"}` | `{success, button}` |

`/api/ir/command` status codes:

| Code | Cause |
|---|---|
| `200` | sent successfully |
| `400` | unknown button name (response includes valid `codes`) |
| `403` | `ir_enabled` is `false` — toggle it on first |
| `429` | inside the 1.5 s cooldown; response includes `retry_after` seconds |
| `503` | hardware missing or `IRTransmitterError` raised |

Persisted state: the `ir_enabled` flag lives in
`~/.minus_system_settings.json`. Disabling also calls `shutdown()` on the
transmitter so the PWM is released.

---

## Web UI

Settings tab → **Autonomous Mode** section:

1. A toggle labelled *IR Remote (HDMI Switch)*. Disabled and greyed-out if
   `available=false` (overlay not loaded).
2. When on, a 6-button remote appears below (Input 1/2/3 on the top row,
   Power/Next/Auto on the bottom row).
3. Clicking a button posts to `/api/ir/command`. All buttons disable for
   1.5 s after a successful press (matching the server-side cooldown) and a
   status line reports `sent power` or `cooldown — wait 0.74s`.

The state survives page reloads — `loadIRStatus()` runs on every page load
and hydrates both the toggle and the panel visibility.

---

## Standalone CLI

```bash
sudo python3 ir_transmit.py --list
# input_1  addr=0x80 cmd=0x07
# ...

sudo python3 ir_transmit.py power
sudo python3 ir_transmit.py input_1
```

One invocation = one button. Root is required for both sysfs writes and
`SCHED_FIFO` priority. The CLI imports the same `IRTransmitter` class as
the webui — this is the one source of truth.

---

## Troubleshooting

**`ERROR: no pwmchip mapped to fd8b0030.pwm`**
The overlay isn't loaded. See *Device-tree overlay* above; check
`grep fdtoverlay /boot/extlinux/extlinux.conf` for the line
`fdtoverlays /boot/dtbo/rk3588-pwm3-m1.dtbo`.

**`OSError: [Errno 22] Invalid argument` on first run**
Writing `duty_cycle` while `period` is still `0` is rejected by the kernel.
The class handles this now, but if you're writing sysfs directly, set
`period` first.

**LED is on all the time, or inverted brightness**
Polarity defaults to `inversed` after a fresh export on this chip. The class
sets it to `normal` before enabling. If you bypass the class, write
`polarity=normal` while the PWM is disabled (polarity is read-only once the
PWM is enabled on most kernels).

**IR receiver doesn't respond**
Most commonly a timing-jitter issue. This is the expected failure mode of
userspace sysfs PWM; receivers typically tolerate ~10 % deviation. If you
hit it, the kernel-side alternative is `pwm-ir-tx` bound to PWM3 via a
custom overlay — that surfaces as `/dev/lirc0` and is driven by `ir-ctl`
with hardware-exact timing.

**Cooldown seems too aggressive**
Change `IRTransmitter.COOLDOWN_S` in `src/ir_transmitter.py`. The web UI
reads the remaining window from the server (`retry_after`) and mirrors it,
so they stay in sync automatically.

---

## Tests

| File | Kind | Requires |
|---|---|---|
| `tests/test_ir_transmitter.py` | unit, sysfs mocked | nothing hardware-y |
| `tests/test_ir_ui.py` | Playwright, live service | `minus.service` running at `:80` |

```bash
python3 tests/test_ir_transmitter.py           # 20 unit tests
python3 tests/test_ir_ui.py                    # Playwright — live API + DOM
```

Unit tests cover: NEC pulse counts and bit ordering, carrier constants,
initialize ordering (polarity before enable, period before final duty),
idempotent init/shutdown, hardware-availability detection, cooldown raise
and clear, unknown-button rejection, pulse-pattern write count.

Playwright tests cover: toggle presence in the Autonomous Mode section,
panel hidden-by-default, toggle-on reveals panel, toggle-off hides panel,
persistence across page reload, `/api/ir/command` actually fires from a
click, cooldown disables all six buttons during the window and re-enables
them after, `403` when calling the endpoint while disabled.

The Playwright suite seeds the service to `ir_enabled=false` in
`setUpClass` and resets it again in `tearDownClass`, so running the tests
leaves the system in a clean state.

---

## Future work

The user's target integration is autonomous mode: rotate the HDMI input on
a schedule (every 12 h or 24 h) to vary training data across streaming
devices. The current code is deliberately feature-complete at the
*boilerplate* level — settings flag, endpoints, UI, cooldown — so that
logic can be added in `src/autonomous_mode.py` without changing the IR
layer. `minus.ir_transmitter.send("next")` from a scheduler thread is the
one-liner that ties it together.
