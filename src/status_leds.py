"""
WS2812B status strip driver for Rock Pi 5B+.

Hardware
--------
- 8 × WS2812B in a chain (also sold as "NeoPixel")
- Data line  → header pin 19 (GPIO1_B2 muxed as SPI0_MOSI_M2)
- 5V power   → header pin 2 or 4
- GND        → any header GND pin
- Keep the data wire under ~10 cm — we drive the 3.3V signal directly
  into the first WS2812B without a level shifter.

Why SPI MOSI and not GPIO bit-banging / rpi_ws281x
--------------------------------------------------
WS2812B uses a tight 800 kHz protocol (~1.25 µs per bit, with sub-µs
high/low timing per 0/1). Userspace GPIO toggling on Linux cannot hit
this reliably — kernel scheduling jitter corrupts the signal. The
rpi_ws281x / Adafruit_NeoPixel / board+neopixel libraries rely on
Broadcom-specific PWM+DMA hardware; they do NOT work on RK3588.

The correct approach here: clock SPI MOSI at 6.4 MHz and encode each
WS2812B bit as 8 SPI bits — `0b11110000` for a WS "1", `0b11000000` for
a WS "0". This matches the canonical Adafruit
``Adafruit_CircuitPython_NeoPixel_SPI`` pattern. The SPI controller
handles the timing in hardware, so it's jitter-free.

The 8-bit-per-WS-bit scheme is a load-bearing choice: it leaves ~3×
more skew tolerance per WS bit than the 3-bit-per-WS-bit alternative,
which matters because the spi-rockchip driver inserts measurable
inter-byte gaps when its FIFO refills mid-transfer (PIO mode below the
DMA threshold). The 3-bit scheme is too tight to absorb those gaps and
produces visible decode errors — the symptom is that a steady frame
(say, solid green) decodes as a cycling sequence of unrelated colours.
The 8-bit scheme tolerates this happily.

Required setup (one-time)
-------------------------
1. Enable the SPI0-M2 overlay so /dev/spidev0.0 exists:

       sudo mv /boot/dtbo/rk3588-spi0-m2-cs0-spidev.dtbo.disabled \\
               /boot/dtbo/rk3588-spi0-m2-cs0-spidev.dtbo
       sudo /usr/sbin/u-boot-update
       sudo reboot

   Equivalent: `sudo rsetup` → Overlays → tick
   `rk3588-spi0-m2-cs0-spidev` → Save → Reboot.

2. Install the Python bindings:

       sudo apt install -y python3-spidev

3. Add your user to the `spi` group if you want to use this module
   without sudo:

       sudo usermod -aG spi $USER   # then log out / in

Brightness cap (load-bearing — do not remove)
---------------------------------------------
The 40-pin header's 5V rail is shared with the SoC and USB peripherals.
Each WS2812B can pull ~60 mA at full white, so 8 LEDs at peak would
draw ~480 mA through the header. That inrush dips the 5V rail enough
to reset the board or cause USB devices to disconnect.

A 10% software cap keeps peak draw at ~42 mA across 7 active LEDs,
far inside safe header limits. The lower cap (vs. the WS2812B spec's
many-amp ceiling) also keeps current swings during animation small
enough that the marginal 3.3V → 5V data signaling stays decode-clean
even without a level shifter. The cap is applied inside `set_pixel()`
before storage, so every caller (including `set_all()`, animations,
etc.) gets it automatically. There is intentionally no way to bypass
it from the application layer.

Sacrificial first pixel
-----------------------
Without a proper 3.3→5V level shifter, the first WS2812B in the chain
often mis-latches the marginal signal and gets stuck on a single colour
while the rest of the chain behaves normally. The fix is a "sacrificial"
pixel: always send zeros to physical LED 0 so it sits dark and acts as
a level-buffering re-transmitter for the rest of the chain (WS2812Bs
retime and re-emit at their own supply rail, so every downstream LED
sees clean 5V logic). Callers see N-1 usable LEDs — indices 0..N-2 map
to physical LEDs 1..N-1. Toggle `SACRIFICIAL_FIRST_PIXEL` to False
after adding a real level shifter.
"""

import spidev

# Physical LEDs wired on the SPI MOSI chain (including the sacrificial one,
# if SACRIFICIAL_FIRST_PIXEL is True — see below).
NUM_LEDS = 8

SPI_BUS = 0
SPI_DEVICE = 0
# 8 SPI bits × 6.4 MHz = 51.2 Mbit/s = 1.25 µs / WS bit. Matches the
# Adafruit-CircuitPython-NeoPixel-SPI canonical timing. We previously used
# 3 SPI bits @ 2.4 MHz, which gave the smallest possible spec margin (each
# SPI bit = 417 ns, single-bit timing skew shifts the whole stream off
# spec). On this RK3588 the spi-rockchip driver uses PIO below ~64 byte
# transfers and refills its FIFO mid-transfer with measurable inter-byte
# gaps; even a 250 ns gap is enough to corrupt the 3-bit-per-WS-bit scheme,
# producing the symptom "solid green decodes as cycling red/blue/white".
# 8-bit-per-WS-bit gives ~6× more skew tolerance per WS bit and is what
# every well-regarded Linux WS2812B library uses.
SPI_SPEED_HZ = 6_400_000

# See module docstring: capped at 10% to keep peak current on the 40-pin
# header's shared 5V rail well under safe limits across the 7 active LEDs
# (≈7 × 60 mA × 0.10 ≈ 42 mA peak — sacrificial pixel always dark).
# 10% is also conservative enough that current swings during animation
# don't induce decode errors on the marginal 3.3V → 5V data line, even
# at low frame rates. Applied in set_pixel() before storage so every
# caller inherits it. Do not expose a way to override from the
# application layer.
BRIGHTNESS = 0.10

# When driving the WS2812B data line directly from SPI MOSI at 3.3V
# (no level shifter), the first LED frequently mis-latches its frame —
# classic symptom: LED 0 stays stuck on one colour while the rest of the
# chain behaves correctly. The fix is a "sacrificial" pixel: always send
# zeros to physical LED 0 so it acts purely as a level-buffering
# re-transmitter for the rest of the chain (WS2812Bs retime/re-emit at
# their own 5V supply, so every downstream LED sees clean logic). Set to
# False if you add a proper 3.3→5V level shifter on the data line.
SACRIFICIAL_FIRST_PIXEL = True

# Per-WS-bit encoding at 6.4 MHz SPI (each SPI bit = 156.25 ns, each WS
# bit = 8 SPI bits = 1.25 µs):
#   WS "1" → 0b11110000 → high ~625 ns, low ~625 ns   (T1H=700±150, T1L=600±150)
#   WS "0" → 0b11000000 → high ~313 ns, low ~937 ns   (T0H=350±150, T0L=800±150)
# Both fall comfortably inside the ±150 ns WS2812B tolerance windows, with
# ~3× more margin than the old 3-bit-per-WS-bit scheme. This is the
# Adafruit_CircuitPython_NeoPixel_SPI canonical pattern.
_BIT_1_ENC = 0b11110000
_BIT_0_ENC = 0b11000000

# ≥80 µs of idle-low both BEFORE and AFTER the data latches the chain. The
# leading reset is what most people skip, but it's load-bearing here:
# without a clean low at the start of every frame, residual high pulses
# from the previous frame's tail (or from a FIFO refill gap) shift the
# decoder by a fraction of a bit and corrupt every pixel that follows.
# 64 zero bytes at 6.4 MHz = exactly 80 µs.
_RESET_BYTES = bytes(64)


class StatusLEDsError(Exception):
    pass


class StatusLEDs:
    """Simple driver for an 8-LED WS2812B status strip.

    Buffered — `set_pixel` / `set_all` / `clear` only mutate an internal
    framebuffer. Call `show()` to push the frame out over SPI.

    Works as a context manager so SPI is always closed and the strip is
    blanked on exit:

        with StatusLEDs() as leds:
            leds.set_pixel(0, 255, 0, 0)
            leds.show()
    """

    def __init__(self, num_leds=NUM_LEDS, bus=SPI_BUS, device=SPI_DEVICE,
                 sacrificial_first=SACRIFICIAL_FIRST_PIXEL):
        self._physical_count = num_leds
        self._offset = 1 if sacrificial_first else 0
        self._user_count = num_leds - self._offset
        if self._user_count < 1:
            raise StatusLEDsError(
                f"need at least {self._offset + 1} physical LED(s) with "
                f"sacrificial_first={sacrificial_first}")
        # Internal buffer mirrors the wire: sacrificial pixel (if any) sits
        # at index 0 and is never exposed to callers — it stays (0,0,0)
        # so that first LED is always dark and acts as a level buffer.
        self._pixels = [(0, 0, 0)] * num_leds
        self._spi = spidev.SpiDev()
        try:
            self._spi.open(bus, device)
        except (FileNotFoundError, PermissionError) as e:
            raise StatusLEDsError(
                f"could not open /dev/spidev{bus}.{device}: {e}. "
                f"Is the rk3588-spi0-m2-cs0-spidev overlay enabled and "
                f"is the user in the 'spi' group (or run as root)?"
            ) from e
        self._spi.max_speed_hz = SPI_SPEED_HZ
        self._spi.mode = 0
        self._spi.bits_per_word = 8

    @property
    def num_leds(self):
        """User-addressable LED count (excludes sacrificial pixel if used)."""
        return self._user_count

    def set_pixel(self, index, r, g, b):
        if not 0 <= index < self._user_count:
            raise IndexError(
                f"pixel {index} out of range (0..{self._user_count - 1})")
        # Clamp then scale. Brightness cap applied here so every caller
        # inherits it — see module docstring for rationale.
        r = max(0, min(255, int(r)))
        g = max(0, min(255, int(g)))
        b = max(0, min(255, int(b)))
        r = int(round(r * BRIGHTNESS))
        g = int(round(g * BRIGHTNESS))
        b = int(round(b * BRIGHTNESS))
        self._pixels[index + self._offset] = (r, g, b)

    def set_all(self, r, g, b):
        for i in range(self._user_count):
            self.set_pixel(i, r, g, b)

    def clear(self):
        # Blanks every pixel including the sacrificial one (which was
        # already zero, but keeps state consistent after reuse).
        self._pixels = [(0, 0, 0)] * self._physical_count

    def show(self):
        """Push the framebuffer to the strip over SPI.

        Frame layout: leading 80 µs reset + per-LED GRB encoded bytes +
        trailing 80 µs reset. Sent via ``writebytes2`` rather than
        ``xfer2`` so we pass a ``bytes`` object directly (no per-element
        Python int conversion) — that's both faster and reduces the
        chance of a FIFO underrun mid-transfer.
        """
        buf = bytearray()
        buf.extend(_RESET_BYTES)
        for (r, g, b) in self._pixels:
            # WS2812B expects GRB byte order.
            for byte in (g, r, b):
                buf.extend(_encode_byte(byte))
        buf.extend(_RESET_BYTES)
        # writebytes2 accepts bytes/bytearray directly, doesn't allocate a
        # per-element list, and is the call Adafruit's reference SPI
        # NeoPixel driver uses on Linux.
        self._spi.writebytes2(bytes(buf))

    def close(self):
        # Blank the strip so it doesn't hold the last frame after exit.
        try:
            self.clear()
            self.show()
        except Exception:
            pass
        try:
            self._spi.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _encode_byte(byte):
    """Encode one 8-bit colour channel as 8 SPI bytes, MSB first.

    Each WS2812B bit becomes one full SPI byte at 6.4 MHz, so 8 input
    bits produce exactly 8 output bytes (1 byte per WS bit). Byte
    duration = 8 SPI bits ÷ 6.4 MHz = 1.25 µs, matching the WS2812B
    bit cell.
    """
    return bytes(
        _BIT_1_ENC if byte & (1 << (7 - bit)) else _BIT_0_ENC
        for bit in range(8)
    )
