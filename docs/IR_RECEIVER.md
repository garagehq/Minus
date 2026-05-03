# IR Receiver — Evaluation Notes

A 3-pin IR receiver module (TSOP38238 / VS1838B class) was wired to the
Rock Pi 5B header to evaluate whether IR *input* would be useful alongside
the existing IR transmitter. This doc captures what worked, the gotchas
we hit, and what a proper `IRReceiver` module would look like if we ever
ship it. **No production code yet** — this is exploratory.

The standalone test script lives at `test_ir_receiver.py` in the repo
root. It uses `gpiomon` (libgpiod 1.6 CLI) to capture edge events and
decodes NEC in pure Python.

---

## Hardware — what works

| Property | Value |
|---|---|
| Header pin (Rock 5B) | **3** |
| GPIO | `GPIO4_B3` (Linux GPIO **139**) |
| libgpiod address | `gpiochip4` line **11** |
| Header line name | `PIN_3` (per `gpioinfo gpiochip4`) |
| Idle level | HIGH (receiver inverts; goes LOW during 38 kHz burst) |
| VCC | 3.3 V (pin 1) or 5 V (pin 2) — check the receiver's spec |
| GND | pin 6 (or any GND) |
| DATA | pin 3 |

GPIO4_B3 has the alternate function `PWM15_IR_M1` but **no overlay is
loaded for it**, so the pad's default mux is GPIO. No `rsetup` step
needed; the libgpiod tools can claim the line directly.

`gpioget gpiochip4 11` reads `1` at idle with a powered receiver — that
is the canonical sanity check before trying to decode anything.

### Why not pin 38 (alongside the transmitter)?

Tried first. `gpiomon gpiochip3 10` *claimed* the line successfully but
saw zero edges. Cause: the `rk3588-pwm3-m1` overlay sets pin 38's
pad-level pinmux to `PWM3_IR_M1` at boot, regardless of whether the PWM
channel is exported. On RK3588, the pad mux gates which IP block sees the
pin — when it's PWM3, the GPIO controller is electrically disconnected
from the pad. Symptom: `gpioget` reads a constant `0` and `gpiomon`
never fires. Two ways out, neither great:

1. Drop the overlay (edit `extlinux.conf`, reboot) — kills the transmitter.
2. Use a different pin — what we did.

Pin 3 / `GPIO4_B3` is unused, has no overlay claiming it, and works out
of the box.

> Note: pin 3 is also the default `I2C8_SDA_M2` pad and the board may
> have hardware pull-ups on it. That's fine for an open-collector IR
> receiver output (it actually helps idle HIGH), but keep it in mind if
> levels look weird.

---

## Decoding — what we observed

Test setup: REI 8K HDMI switch remote → receiver on pin 3. Result:

| Button | Address | Command | Decoded? |
|---|---|---|---|
| `input_1` | `0x80` | `0x07` | ✓ |
| `input_2` | `0x80` | `0x1B` | ✓ |
| `input_3` | `0x80` | `0x08` | ✓ |
| `next`    | `0x80` | `0x1F` | ✓ |
| (held button) | — | — | NEC REPEAT detected |

Address and command both pass the inverted-byte checksum (`addr ^
addr_inv == 0xFF`, ditto command). These are byte-for-byte the codes
captured from a Flipper Zero in `docs/IR_TRANSMITTER.md`, so the
transmitter and receiver agree on the wire.

**Decode rate:** ~22 of 25 frames in a typical 25 s session. The 3
"undecodable" frames are session-boundary partial captures — leader
timings looked perfect (`9020/4548 µs`, `8987/4495 µs`), but pulse counts
were off (67 with one bit slightly outside ±30 % tolerance, or 58 because
a previous frame's tail bled in). 100 % decode rate on actual
mid-session button presses.

### NEC protocol summary (for reference)

| Element | Mark (LOW) | Space (HIGH) |
|---|---|---|
| Leader | 9000 µs | 4500 µs |
| `0` bit | 562 µs | 562 µs |
| `1` bit | 562 µs | 1687 µs |
| Trailing mark | 562 µs | (frame ends) |
| Repeat code | 9000 µs leader, 2250 µs space, 562 µs mark, then idle |

Standard NEC frame = leader + 32 bits (addr, ~addr, cmd, ~cmd) + final
mark = 67 alternating mark/space intervals. Bytes are LSB-first.

The receiver demodulates the 38 kHz carrier internally, so the pin sees
a clean pulse train. We do **not** sample at 38 kHz — we capture edge
events with kernel timestamps and look at the gaps.

---

## How the test script works

```
gpiomon gpiochip4 11  →  edge events  →  Python  →  pulse train  →  NEC decoder
                       (rising/falling                (alternating
                        + ns timestamps)               mark/space µs)
```

Implementation details, in order from least to most important:

1. **`subprocess.Popen(["gpiomon", "--format=%e %s.%n", ...])`** —
   `--format=%e %s.%n` gives `<event_type> <secs>.<ns>` per line.
   `%e` is `0`=falling, `1`=rising.
2. **Polarity reasoning (the one we got wrong first):** `last_event` is
   the edge that occurred at `last_edge_ns`. After a *falling* edge, the
   line was LOW until now — that interval is a MARK. After a *rising*
   edge it was HIGH — a SPACE. Flipping this is a silent bug: every
   frame appears to start with a `~4500/~600 µs` "leader" because the
   real 9 ms leader mark is being filtered out by the empty-buffer guard.
3. **Frame boundary:** an idle gap on the HIGH line ≥ `gap_ms` (default
   15 ms) flushes the current pulse buffer to the decoder. Real NEC
   inter-frame spacing is ~40 ms, so 15 ms is plenty.
4. **Empty-buffer guard:** the first pulse of a frame must be a MARK
   (the leader). If the script starts mid-frame on a SPACE we skip until
   we see a MARK.
5. **Decoder:** classifies pulses by ±30 % tolerance windows. Cheap
   remotes drift a lot; tighter tolerances cause spurious decode failures.

### Gotchas worth not re-discovering

- **`gpiomon -B both` is wrong.** In libgpiod 1.6, `-B` is *bias*
  (pull-up/down/disable), not edge select. The valid edge flags are
  `--rising-edge` / `--falling-edge`; default = both. Passing `-B both`
  fails fast with `invalid bias: both` and gpiomon exits — the calling
  Python script sees an empty stdout and silently reports zero frames.
- **Stdout buffering kills `timeout`-based testing.** When `timeout`
  sends SIGTERM (its default) to a Python subprocess, stdout is never
  flushed. Use `python3 -u`, register a SIGTERM handler, or use
  `timeout --signal=INT`. Otherwise a working decoder looks broken
  because nothing reaches the terminal.
- **Pad mux trumps GPIO claim.** `gpiomon` will *claim* a line that's
  pad-muxed away from the GPIO controller. It just never fires. Always
  sanity-check with `gpioget` first — should read `1` with the receiver
  idling. A constant `0` means the GPIO controller can't see the pad.

---

## Status: works on the bench, not in the app

What we have right now:

- ✓ Hardware path verified: pin 3 / `gpiochip4 11`
- ✓ NEC decoding works for both standard (8-bit address) and would
  cover extended (16-bit address) variants — the decoder branches on
  whether `addr ^ addr_inv == 0xFF`.
- ✓ NEC repeat codes recognized.
- ✗ Not wired into Minus. Test script only.

---

## Future work — sketch for an `IRReceiver` module

If/when this becomes worth building, the shape that fits the existing
codebase:

### Module layout

| Piece | File | Purpose |
|---|---|---|
| Core class | `src/ir_receiver.py` | `gpiomon` subprocess + decoder, runs in a background thread, dispatches to a callback |
| Standalone CLI | `test_ir_receiver.py` (already exists) | rename/promote, or keep as a debug tool |
| Web API | `src/webui.py` (`/api/ir_rx/*`) | status + last-seen frame, optional learn-mode endpoints |
| Web UI | `src/templates/index.html` | live "last button received" indicator, learn-mode button mapping |
| Wiring | `minus.py` | instantiate `IRReceiver`, register callbacks for whatever app actions we want |

The test script's decoder logic is mostly transplantable as-is.

### Threading model

One background thread per receiver instance. It owns the `gpiomon`
subprocess, parses edge events, runs the NEC state machine, and pushes
decoded frames to a `queue.Queue` and/or invokes a user-supplied
callback. `start()` / `stop()` lifecycle mirrors `IRTransmitter`. The
gpiomon process is the natural cancellation point — `terminate()` it on
shutdown and the reader thread exits when stdout closes.

### Protocol coverage

NEC covers the REI remote and most cheap household remotes. If we ever
need broader support, sensible additions in priority order:

1. **NEC-extended** — already handled by the decoder (16-bit address
   when the inverted-byte check fails on the address half).
2. **SIRC (Sony)** — 12, 15, or 20 bits, different leader timing.
3. **RC-5 / RC-6 (Philips)** — Manchester-encoded, fundamentally
   different decoder topology.
4. **Raw mode** — emit pulse trains unchanged, let the caller match them
   against a learned database. This is what `--raw` already does in the
   test script and is the right abstraction for a general "remote
   learning" feature.

### Integration ideas (the actual reason to build this)

In rough order of how much they'd change the app:

1. **Closed-loop verification of the transmitter.** Point the receiver
   at the IR LED, fire `tx.send("input_1")`, assert the receiver decoded
   `0x80 / 0x07` within ~50 ms. Catches polarity / timing regressions
   automatically. Could even run as part of `tests/`.
2. **External hardware trigger.** Spare remote → receiver → action
   ("block now", "skip ad", "pause autonomous mode", "cycle HDMI input").
   Useful when the web UI isn't reachable or when the user wants a
   physical button. Maps cleanly to existing `/api/*` endpoints.
3. **Remote learning.** UI mode: "press the button you want to use for
   X". Receiver captures the (protocol, address, command, raw_pulses)
   tuple, stores it. Lets the app work with whatever remote the user
   actually owns — including remotes for HDMI switches we don't have
   captured codes for. Pairs nicely with the transmitter: capture →
   replay.
4. **Confirm what got transmitted.** When the autonomous-mode scheduler
   eventually does `tx.send("next")` to rotate HDMI input, a co-located
   receiver could confirm the device actually saw the burst before
   advancing state. Low value but cheap to add once (1) exists.

### API surface (rough)

```python
from ir_receiver import IRReceiver, IRFrame

def on_button(frame: IRFrame) -> None:
    # frame.protocol = "NEC" | "NEC_REPEAT" | "RAW"
    # frame.address, frame.command, frame.raw_pulses_us
    print(f"got {frame.protocol} {frame.address:#x}/{frame.command:#x}")

rx = IRReceiver(chip="gpiochip4", line=11, on_frame=on_button)
rx.start()    # spawns gpiomon + reader thread
...
rx.stop()     # terminates subprocess, joins thread
```

A `learn_one(timeout=10.0)` blocking helper would be useful for the UI
"press the button now" flow:

```python
frame = rx.learn_one(timeout=10.0)  # returns None on timeout
if frame:
    config["block_now"] = (frame.address, frame.command)
```

### Shared protocol layer with `IRTransmitter`?

Tempting but probably not worth it yet. The encoder in `IRTransmitter`
turns `(address, command)` into PWM duty toggles; the decoder turns
edge timings into `(address, command)`. They share *nothing* at the
runtime level — different OS interfaces, different constants matter
(period vs. tolerance), different threading concerns. A shared `nec.py`
module with constants (`LEADER_MARK_US`, `BIT_MARK_US`, etc.) and the
inverted-byte checksum is the most that's worth lifting; both sides
already agree on these numbers, they're just duplicated.

---

## Quick reference

```bash
# Sanity check (powered receiver should idle HIGH)
gpioget gpiochip4 11

# Decode mode
python3 -u test_ir_receiver.py --chip gpiochip4 --line 11

# Raw mode — every pulse with µs duration, useful for non-NEC remotes
python3 -u test_ir_receiver.py --chip gpiochip4 --line 11 --raw

# Tweak frame-end idle gap (default 15 ms)
python3 -u test_ir_receiver.py --chip gpiochip4 --line 11 --gap-ms 8
```
