"""
Audio Passthrough for Stream Sentry.

Captures audio from HDMI-RX and outputs to HDMI-TX with mute control for ad blocking.

Features:
- Automatic error detection via GStreamer bus messages
- Watchdog thread to detect pipeline stalls
- Auto-restart on failure
- Auto-detection of HDMI capture device

Architecture:
    alsasrc (hw:X,0) -> audioconvert -> volume -> alsasink (hw:Y,0)
                                          ^
                                          | mute=true during ads
"""

import gc
import logging
import os
import subprocess
import threading
import time

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

logger = logging.getLogger(__name__)

# Timeout for GStreamer state changes (in nanoseconds)
GST_STATE_CHANGE_TIMEOUT = 5 * Gst.SECOND  # 5 seconds


def detect_hdmi_capture_device() -> str:
    """
    Auto-detect the HDMI capture device by scanning ALSA cards.

    Looks for 'hdmiin' in the card name which indicates the HDMI-RX audio input.

    Returns:
        ALSA device string (e.g., 'hw:4,0') or 'hw:4,0' as fallback
    """
    try:
        # Read /proc/asound/cards to find hdmiin device
        with open('/proc/asound/cards', 'r') as f:
            cards_output = f.read()

        # Parse lines like: " 4 [rockchiphdmiin ]: rockchip_hdmiin - rockchip,hdmiin"
        for line in cards_output.split('\n'):
            if 'hdmiin' in line.lower():
                # Extract card number from start of line
                parts = line.strip().split()
                if parts and parts[0].isdigit():
                    card_num = parts[0]
                    device = f"hw:{card_num},0"
                    logger.info(f"[AudioPassthrough] Auto-detected HDMI capture device: {device}")
                    return device

        logger.warning("[AudioPassthrough] Could not find hdmiin in /proc/asound/cards, using fallback hw:4,0")
        return "hw:4,0"

    except Exception as e:
        logger.warning(f"[AudioPassthrough] Error detecting HDMI capture device: {e}, using fallback hw:4,0")
        return "hw:4,0"


class AudioPassthrough:
    """
    Audio passthrough from HDMI-RX to HDMI-TX.

    Uses GStreamer pipeline with volume element for instant mute control.
    Runs as a separate pipeline from video for simplicity and robustness.
    Includes automatic error recovery and watchdog monitoring.
    """

    # HDMI capture device candidates - we try these in order until one works
    # The card number can change depending on boot order
    HDMI_CAPTURE_DEVICES = ["hw:4,0", "hw:2,0", "hw:3,0", "hw:5,0"]

    def __init__(self, capture_device=None, playback_device="hw:0,0"):
        """
        Initialize audio passthrough.

        Args:
            capture_device: ALSA capture device (HDMI-RX) - auto-detected if None or "auto"
            playback_device: ALSA playback device (HDMI-TX)
        """
        # Auto-detect capture device if not specified or set to "auto"
        if capture_device is None or capture_device == "auto":
            capture_device = detect_hdmi_capture_device()

        self.capture_device = capture_device
        self.playback_device = playback_device
        self._capture_device_candidates = self.HDMI_CAPTURE_DEVICES.copy()
        # Move the auto-detected/specified device to front of candidates list
        if capture_device in self._capture_device_candidates:
            self._capture_device_candidates.remove(capture_device)
        self._capture_device_candidates.insert(0, capture_device)
        self.pipeline = None
        self.volume = None
        self.bus = None
        self.is_muted = False
        self.is_running = False
        self._lock = threading.Lock()

        # Watchdog state
        self._watchdog_thread = None
        self._stop_watchdog = threading.Event()
        self._watchdog_paused = False  # Pause watchdog when HDMI is lost
        self._last_buffer_time = 0
        self._restart_count = 0
        self._watchdog_interval = 3.0  # Check every 3 seconds
        self._stall_threshold = 6.0  # Consider stalled if no buffer for 6s

        # Exponential backoff for restarts (no max limit - always try to recover)
        self._base_restart_delay = 1.0  # Start with 1 second delay
        self._max_restart_delay = 60.0  # Cap at 60 seconds
        self._current_restart_delay = self._base_restart_delay
        self._last_restart_time = 0
        self._consecutive_failures = 0

        # Track our PID for ALSA device ownership check
        self._our_pid = os.getpid()

        # Restart coordination - prevent multiple concurrent restarts
        self._restart_in_progress = False
        self._restart_lock = threading.Lock()  # Separate lock for restart coordination

        # A/V sync watchdog - periodic queue flush to prevent drift
        # The sync queue adds fixed delay but clock drift over time could cause issues
        # Flushing every 45 minutes resets the sync queue with minimal audio dropout (~300ms)
        self._sync_interval = 45 * 60  # 45 minutes between sync resets
        self._last_sync_reset = 0

        # Rolling audio level history for the blocking-overlay visualizer.
        # Stores normalized RMS (0.0-1.0) samples of the mixer output. Kept
        # as a bounded deque so memory is O(1) over a 24h run.
        from collections import deque
        self._level_history = deque(maxlen=16)
        self._last_level_sample_time = 0.0
        # Only sample RMS every N seconds — full-rate would thrash the CPU
        # and we only need ~10 Hz updates for the bar visualizer.
        self._level_sample_interval = 0.1
        self._sync_reset_enabled = True

        # Initialize GStreamer (may already be initialized by video pipeline)
        Gst.init(None)

    def _is_alsa_device_running(self) -> bool:
        """Check if our ALSA playback device is actually running with our PID.

        This checks /proc/asound/cardX/pcmYp/sub0/status to see if the device
        is in RUNNING state and owned by our process. This is more reliable
        than GStreamer state queries when PipeWire/WirePlumber is involved.

        Returns:
            True if device is RUNNING and owned by us, False otherwise
        """
        try:
            # Parse playback device from self.playback_device (e.g., "hw:1,0")
            # Format: hw:card,device
            if not self.playback_device.startswith("hw:"):
                return False

            parts = self.playback_device[3:].split(",")
            if len(parts) != 2:
                return False

            card = parts[0]
            device = parts[1]

            # Check status file: /proc/asound/cardX/pcmYp/sub0/status
            # 'p' suffix means playback (vs 'c' for capture)
            status_path = f"/proc/asound/card{card}/pcm{device}p/sub0/status"

            if not os.path.exists(status_path):
                return False

            with open(status_path, 'r') as f:
                status_content = f.read()

            # Parse status - looking for:
            # state: RUNNING
            # owner_pid: <our_pid>
            state_running = False
            owner_is_us = False

            for line in status_content.split('\n'):
                line = line.strip()
                if line.startswith('state:'):
                    state_running = 'RUNNING' in line
                elif line.startswith('owner_pid'):
                    # Format: "owner_pid   : 12345"
                    try:
                        pid_str = line.split(':')[1].strip()
                        owner_pid = int(pid_str)
                        owner_is_us = (owner_pid == self._our_pid)
                    except (IndexError, ValueError):
                        pass

            return state_running and owner_is_us

        except Exception as e:
            logger.debug(f"[AudioPassthrough] Error checking ALSA status: {e}")
            return False

    def _init_pipeline(self):
        """Initialize GStreamer audio pipeline."""
        try:
            # Audio passthrough pipeline with A/V sync delay
            # Video pipeline has ~350-500ms latency (HTTP streaming + decode + queue)
            # Audio needs matching delay to stay in sync
            # Using provide-clock=false to prevent alsasrc from being clock master
            #
            # Latency breakdown:
            #   - alsasrc: 50ms buffer
            #   - syncqueue: 300ms delay (min-threshold-time forces buffering before output)
            #   - audioqueue: up to 100ms for jitter absorption
            #   - alsasink: 50ms buffer
            #   Total: ~500ms to match video latency
            pipeline_str = (
                f"alsasrc device={self.capture_device} buffer-time=50000 latency-time=10000 provide-clock=false ! "
                f"audio/x-raw,rate=48000,channels=2,format=S16LE ! "
                f"queue name=syncqueue min-threshold-time=300000000 max-size-time=500000000 max-size-buffers=0 max-size-bytes=0 ! "
                f"queue max-size-buffers=10 max-size-time=100000000 leaky=downstream name=audioqueue ! "
                f"audioconvert ! "
                f"volume name=vol volume=1.0 mute=false ! "
                f"alsasink device={self.playback_device} buffer-time=50000 latency-time=10000 sync=false"
            )

            logger.debug(f"[AudioPassthrough] Creating pipeline: {pipeline_str}")
            self.pipeline = Gst.parse_launch(pipeline_str)

            # Get volume element for mute control
            self.volume = self.pipeline.get_by_name('vol')

            # Set up bus message handling for error detection
            self.bus = self.pipeline.get_bus()
            self.bus.add_signal_watch()
            self.bus.connect('message::error', self._on_error)
            self.bus.connect('message::eos', self._on_eos)
            self.bus.connect('message::state-changed', self._on_state_changed)

            # Add probe to track buffer flow (for stall detection)
            queue = self.pipeline.get_by_name('audioqueue')
            if queue:
                pad = queue.get_static_pad('src')
                if pad:
                    pad.add_probe(Gst.PadProbeType.BUFFER, self._buffer_probe, None)

            if self.volume:
                logger.info(f"[AudioPassthrough] Pipeline created: {self.capture_device} -> {self.playback_device}")
            else:
                logger.error("[AudioPassthrough] Failed to get volume element")

        except Exception as e:
            logger.error(f"[AudioPassthrough] Failed to create pipeline: {e}")
            import traceback
            traceback.print_exc()
            self.pipeline = None

    def _buffer_probe(self, pad, info, user_data):
        """Probe callback to track buffer flow for stall detection.

        Also samples the buffer's RMS at `_level_sample_interval` so the
        blocking overlay can render an audio-reactive bar visualization.
        Skips the RMS math on most buffers to keep CPU overhead negligible.
        """
        now = time.time()
        self._last_buffer_time = now

        # Sample audio level for the visualizer (throttled)
        if now - self._last_level_sample_time >= self._level_sample_interval:
            self._last_level_sample_time = now
            try:
                buf = info.get_buffer()
                if buf is not None:
                    self._sample_rms(buf)
            except Exception as e:
                logger.debug(f"[AudioPassthrough] RMS sample skipped: {e}")

        # Reset backoff counter after sustained buffer flow (5+ seconds)
        if self._consecutive_failures > 0:
            time_since_restart = now - self._last_restart_time
            if time_since_restart > 5.0:
                self._consecutive_failures = 0
                self._current_restart_delay = self._base_restart_delay
                logger.debug("[AudioPassthrough] Backoff reset - sustained buffer flow")

        return Gst.PadProbeReturn.OK

    def _sample_rms(self, buf):
        """Compute RMS from an S16LE audio buffer, append to history.

        Format is locked to S16LE stereo at 48 kHz elsewhere in the pipeline
        so we can treat the buffer as signed 16-bit little-endian samples.
        """
        success, mapinfo = buf.map(Gst.MapFlags.READ)
        if not success:
            return
        try:
            import struct
            data = bytes(mapinfo.data)
            # Down-sample — we don't need every one of ~1000 samples per 50ms
            # buffer. Stride picks one sample every ~0.5 ms, plenty for bar
            # heights.
            n = len(data) // 2  # S16 = 2 bytes
            if n == 0:
                return
            stride = max(1, n // 64)
            samples = struct.unpack_from(f'<{n}h', data)
            total = 0
            count = 0
            peak = 0
            for i in range(0, n, stride):
                s = samples[i]
                total += s * s
                if abs(s) > peak:
                    peak = abs(s)
                count += 1
            if count == 0:
                return
            import math
            rms = math.sqrt(total / count) / 32767.0
            # Nudge the perceived range — quiet speech is ~0.02 RMS, peaks
            # are ~0.3. A sqrt curve makes the bars feel more responsive.
            visual = min(1.0, math.sqrt(rms))
            self._level_history.append(visual)
        finally:
            buf.unmap(mapinfo)

    def get_level_bars(self, width=16):
        """Render the current audio history as a unicode block bar string.

        Returns a `width`-character string like `.,;ozIMI;,.` that rises and
        falls with audio energy. Designed for the blocking overlay stats
        area (monospace). Returns empty string if no history yet.
        """
        if not self._level_history:
            return ''
        # ASCII-only bar ramp so it renders reliably through the MPP text pass
        # no matter what font the encoder picked.
        ramp = ' .,-;+ox*#@'
        levels = list(self._level_history)[-width:]
        # Pad with zeros on the left if history is shorter than width
        if len(levels) < width:
            levels = [0.0] * (width - len(levels)) + levels
        chars = []
        for lv in levels:
            idx = int(round(lv * (len(ramp) - 1)))
            idx = max(0, min(len(ramp) - 1, idx))
            chars.append(ramp[idx])
        return ''.join(chars)

    def _on_error(self, bus, message):
        """Handle GStreamer error messages."""
        err, debug = message.parse_error()
        logger.error(f"[AudioPassthrough] Pipeline error: {err.message}")
        logger.debug(f"[AudioPassthrough] Debug info: {debug}")

        # Schedule restart on error
        threading.Thread(target=self._restart_pipeline, daemon=True).start()

    def _on_eos(self, bus, message):
        """Handle end-of-stream (shouldn't happen for live source)."""
        logger.warning("[AudioPassthrough] Unexpected EOS received")

        # Restart on EOS
        threading.Thread(target=self._restart_pipeline, daemon=True).start()

    def _on_state_changed(self, bus, message):
        """Handle state changes."""
        if message.src != self.pipeline:
            return

        old, new, pending = message.parse_state_changed()
        if new == Gst.State.PLAYING:
            self._last_buffer_time = time.time()
            logger.debug("[AudioPassthrough] Pipeline now PLAYING")

    def _flush_sync_queue(self):
        """Flush the sync queue to reset A/V sync without full pipeline restart.

        This causes a brief audio dropout (~300ms) while the queue refills,
        but is much faster than a full pipeline restart (~1s).

        Returns:
            True if flush succeeded, False otherwise
        """
        if not self.pipeline:
            return False

        try:
            syncqueue = self.pipeline.get_by_name('syncqueue')
            if not syncqueue:
                logger.warning("[AudioPassthrough] Could not find syncqueue element")
                return False

            # Get the sink pad to send flush events
            sink_pad = syncqueue.get_static_pad('sink')
            if not sink_pad:
                logger.warning("[AudioPassthrough] Could not get syncqueue sink pad")
                return False

            # Send flush-start event (clears queue, puts downstream in flushing mode)
            flush_start = Gst.Event.new_flush_start()
            if not sink_pad.send_event(flush_start):
                logger.warning("[AudioPassthrough] Failed to send flush-start event")
                return False

            # Brief pause to let flush propagate
            time.sleep(0.05)

            # Send flush-stop event (ends flushing, allows data flow to resume)
            # reset_time=True resets the running time
            flush_stop = Gst.Event.new_flush_stop(True)
            if not sink_pad.send_event(flush_stop):
                logger.warning("[AudioPassthrough] Failed to send flush-stop event")
                return False

            self._last_sync_reset = time.time()
            logger.info("[AudioPassthrough] Sync queue flushed - A/V sync reset (~300ms dropout)")
            return True

        except Exception as e:
            logger.error(f"[AudioPassthrough] Error flushing sync queue: {e}")
            return False

    def _restart_pipeline(self):
        """Restart the audio pipeline after an error with exponential backoff.

        This method is resilient to memory pressure and includes:
        - Protection against concurrent restart attempts
        - Timeouts on all GStreamer state changes
        - Explicit garbage collection to help during memory pressure
        - Comprehensive error logging
        """
        # Prevent multiple concurrent restarts using a separate lock
        # Use trylock to avoid blocking the watchdog if restart is in progress
        if not self._restart_lock.acquire(blocking=False):
            logger.debug("[AudioPassthrough] Restart already in progress, skipping")
            return

        try:
            self._restart_in_progress = True

            # Use timeout on main lock to prevent deadlock during memory pressure
            if not self._lock.acquire(timeout=10.0):
                logger.error("[AudioPassthrough] Could not acquire lock for restart (timeout)")
                return

            try:
                self._restart_count += 1
                self._consecutive_failures += 1

                # After 3 consecutive failures, try the next capture device
                if self._consecutive_failures >= 3 and len(self._capture_device_candidates) > 1:
                    old_device = self.capture_device
                    # Rotate to next device
                    self._capture_device_candidates.append(self._capture_device_candidates.pop(0))
                    self.capture_device = self._capture_device_candidates[0]
                    logger.warning(f"[AudioPassthrough] Trying alternate capture device: {old_device} -> {self.capture_device}")
                    self._consecutive_failures = 0  # Reset for new device

                # Calculate backoff delay (cap exponent at 10 to prevent overflow)
                exponent = min(self._consecutive_failures - 1, 10)
                delay = min(
                    self._base_restart_delay * (2 ** exponent),
                    self._max_restart_delay
                )
                self._current_restart_delay = delay

                logger.warning(
                    f"[AudioPassthrough] Restarting pipeline (attempt {self._restart_count}, "
                    f"delay {delay:.1f}s, {self._consecutive_failures} consecutive failures)"
                )

                # Stop current pipeline and clean up resources
                if self.pipeline:
                    try:
                        # CRITICAL: Remove bus signal watch to prevent file descriptor leak
                        if hasattr(self, 'bus') and self.bus:
                            try:
                                self.bus.remove_signal_watch()
                            except Exception as e:
                                logger.debug(f"[AudioPassthrough] Error removing bus watch: {e}")
                            self.bus = None
                        self.pipeline.set_state(Gst.State.NULL)
                        # Wait for NULL state with TIMEOUT - prevents indefinite blocking
                        ret, state, pending = self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                        if ret == Gst.StateChangeReturn.FAILURE:
                            logger.warning("[AudioPassthrough] Failed to set pipeline to NULL state")
                        elif ret != Gst.StateChangeReturn.SUCCESS:
                            logger.warning(f"[AudioPassthrough] Timeout waiting for NULL state (ret={ret})")
                    except Exception as e:
                        logger.warning(f"[AudioPassthrough] Error stopping pipeline: {e}")
                    self.pipeline = None
                    self.volume = None

                    # Force garbage collection to help during memory pressure
                    gc.collect()

                    # Extra delay to ensure ALSA device is fully released
                    time.sleep(0.5)

            finally:
                self._lock.release()

            # Wait with exponential backoff OUTSIDE the lock
            # This allows other operations to proceed during the delay
            time.sleep(delay)

            # Check if we should still be running
            if not self.is_running:
                logger.info("[AudioPassthrough] Restart cancelled - not running")
                return

            # Reacquire lock for pipeline creation
            if not self._lock.acquire(timeout=10.0):
                logger.error("[AudioPassthrough] Could not acquire lock for pipeline creation (timeout)")
                return

            try:
                # Force GC before creating new pipeline
                gc.collect()

                # Recreate and start
                self._init_pipeline()
                if not self.pipeline:
                    logger.error("[AudioPassthrough] Failed to create pipeline during restart")
                    return

                ret = self.pipeline.set_state(Gst.State.PLAYING)
                if ret == Gst.StateChangeReturn.FAILURE:
                    # Get more details about the failure
                    logger.error("[AudioPassthrough] Failed to restart pipeline (set_state returned FAILURE)")
                    # Try to get error from bus
                    if self.bus:
                        msg = self.bus.pop_filtered(Gst.MessageType.ERROR)
                        if msg:
                            err, debug = msg.parse_error()
                            logger.error(f"[AudioPassthrough] GStreamer error: {err.message}")
                            logger.debug(f"[AudioPassthrough] Debug: {debug}")
                elif ret == Gst.StateChangeReturn.ASYNC:
                    # Wait for state change with timeout
                    ret2, state, pending = self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                    if ret2 == Gst.StateChangeReturn.SUCCESS and state == Gst.State.PLAYING:
                        logger.info("[AudioPassthrough] Pipeline restarted successfully (async)")
                        self._last_buffer_time = time.time()
                        self._last_restart_time = time.time()
                        self._last_sync_reset = time.time()  # Reset A/V sync timer
                        if self.is_muted and self.volume:
                            self.volume.set_property('mute', True)
                    else:
                        logger.error(f"[AudioPassthrough] Failed to reach PLAYING state: ret={ret2}, state={state.value_nick if state else 'None'}")
                else:
                    logger.info("[AudioPassthrough] Pipeline restarted successfully")
                    self._last_buffer_time = time.time()
                    self._last_restart_time = time.time()
                    self._last_sync_reset = time.time()  # Reset A/V sync timer
                    # Restore mute state
                    if self.is_muted and self.volume:
                        self.volume.set_property('mute', True)
            finally:
                self._lock.release()

        except Exception as e:
            logger.error(f"[AudioPassthrough] Unexpected error during restart: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._restart_in_progress = False
            self._restart_lock.release()

    def _watchdog_loop(self):
        """Watchdog thread to detect pipeline stalls.

        Enhanced with:
        - Protection against triggering restart if one is already in progress
        - Better logging of pipeline state
        - Detection of completely dead pipelines (no pipeline object)
        """
        logger.debug("[AudioPassthrough] Watchdog started")

        while not self._stop_watchdog.is_set():
            self._stop_watchdog.wait(self._watchdog_interval)

            if self._stop_watchdog.is_set():
                break

            if not self.is_running:
                continue

            # Skip restart attempts if watchdog is paused (e.g., HDMI lost)
            if self._watchdog_paused:
                continue

            # Skip if a restart is already in progress
            if self._restart_in_progress:
                logger.debug("[AudioPassthrough] Watchdog: restart in progress, skipping check")
                continue

            needs_restart = False
            restart_reason = ""

            # A/V Sync reset - periodically flush sync queue to prevent clock drift
            # Uses queue flush instead of full restart for minimal dropout (~300ms vs ~1s)
            if self._sync_reset_enabled and self._last_sync_reset > 0:
                time_since_sync = time.time() - self._last_sync_reset
                if time_since_sync >= self._sync_interval:
                    # Try queue flush first (faster, less disruptive)
                    if self._flush_sync_queue():
                        # Flush succeeded, no restart needed
                        pass
                    else:
                        # Flush failed, fall back to full restart
                        needs_restart = True
                        restart_reason = f"A/V sync reset failed flush (every {self._sync_interval // 60}min)"

            # Check if pipeline exists at all
            if not self.pipeline:
                needs_restart = True
                restart_reason = "pipeline is None"
            # Check if buffers are flowing
            elif self._last_buffer_time > 0:
                time_since_buffer = time.time() - self._last_buffer_time
                if time_since_buffer > self._stall_threshold:
                    # GStreamer says stalled, but check ALSA status first
                    # PipeWire can interfere with GStreamer buffer probes
                    if self._is_alsa_device_running():
                        logger.debug(
                            f"[AudioPassthrough] Buffer probe stale ({time_since_buffer:.1f}s) "
                            f"but ALSA device is RUNNING - updating buffer time"
                        )
                        self._last_buffer_time = time.time()
                    else:
                        needs_restart = True
                        restart_reason = f"stalled ({time_since_buffer:.1f}s since last buffer)"

            # Check pipeline state (only if we have a pipeline and haven't already decided to restart)
            if not needs_restart and self.pipeline:
                try:
                    state_ret, state, pending = self.pipeline.get_state(0)
                    if state != Gst.State.PLAYING and self.is_running:
                        # GStreamer says not PLAYING, but check if audio is ACTUALLY flowing
                        # via ALSA /proc status. This handles PipeWire/WirePlumber interference
                        # where GStreamer state may be incorrect but audio works fine.
                        if self._is_alsa_device_running():
                            logger.debug(
                                f"[AudioPassthrough] GStreamer reports {state.value_nick if state else 'None'} "
                                f"but ALSA device is RUNNING with our PID - skipping restart"
                            )
                            # Update last buffer time since audio is actually flowing
                            self._last_buffer_time = time.time()
                        else:
                            needs_restart = True
                            restart_reason = f"not in PLAYING state ({state.value_nick if state else 'None'})"
                except Exception as e:
                    needs_restart = True
                    restart_reason = f"error checking state: {e}"

            if needs_restart:
                logger.warning(f"[AudioPassthrough] Pipeline issue detected: {restart_reason}")
                # Start restart in a separate thread to not block watchdog
                threading.Thread(
                    target=self._restart_pipeline,
                    daemon=True,
                    name="AudioRestart"
                ).start()

        logger.debug("[AudioPassthrough] Watchdog stopped")

    def start(self):
        """Start audio passthrough.

        Tries all candidate capture devices until one works.
        """
        with self._lock:
            # Try each candidate device until one works
            devices_tried = []
            for candidate in self._capture_device_candidates:
                if candidate in devices_tried:
                    continue
                devices_tried.append(candidate)

                # Update capture device and reinitialize pipeline
                self.capture_device = candidate

                # Clean up any existing pipeline
                if self.pipeline:
                    try:
                        if hasattr(self, 'bus') and self.bus:
                            try:
                                self.bus.remove_signal_watch()
                            except:
                                pass
                            self.bus = None
                        self.pipeline.set_state(Gst.State.NULL)
                        self.pipeline.get_state(Gst.CLOCK_TIME_NONE)
                    except:
                        pass
                    self.pipeline = None
                    self.volume = None
                    time.sleep(0.3)

                # Initialize pipeline with this device
                self._init_pipeline()

                if not self.pipeline:
                    logger.warning(f"[AudioPassthrough] Failed to create pipeline with {candidate}")
                    continue

                try:
                    ret = self.pipeline.set_state(Gst.State.PLAYING)
                    if ret == Gst.StateChangeReturn.FAILURE:
                        logger.warning(f"[AudioPassthrough] Failed to start pipeline with {candidate}")
                        continue

                    # For async state changes, wait for completion
                    if ret == Gst.StateChangeReturn.ASYNC:
                        ret2, state, pending = self.pipeline.get_state(2 * Gst.SECOND)
                        if ret2 != Gst.StateChangeReturn.SUCCESS or state != Gst.State.PLAYING:
                            logger.warning(f"[AudioPassthrough] Pipeline {candidate} failed to reach PLAYING state")
                            continue

                    # Success!
                    self.is_running = True
                    self._last_buffer_time = time.time()
                    self._last_sync_reset = time.time()  # Start A/V sync timer
                    self._restart_count = 0

                    # Reorder candidates so working device is first
                    if candidate in self._capture_device_candidates:
                        self._capture_device_candidates.remove(candidate)
                    self._capture_device_candidates.insert(0, candidate)

                    # Start watchdog thread
                    self._stop_watchdog.clear()
                    self._watchdog_thread = threading.Thread(
                        target=self._watchdog_loop,
                        daemon=True,
                        name="AudioWatchdog"
                    )
                    self._watchdog_thread.start()

                    logger.info(f"[AudioPassthrough] Audio passthrough started with {candidate}")
                    return True

                except Exception as e:
                    logger.warning(f"[AudioPassthrough] Failed to start with {candidate}: {e}")
                    continue

            # All devices failed
            logger.error(f"[AudioPassthrough] All capture devices failed: {devices_tried}")
            return False

    def mute(self):
        """Mute audio (for ad blocking)."""
        with self._lock:
            if self.volume and not self.is_muted:
                self.volume.set_property('mute', True)
                self.is_muted = True
                logger.info("[AudioPassthrough] Audio MUTED")

    def unmute(self):
        """Unmute audio (after ad ends)."""
        with self._lock:
            if self.volume and self.is_muted:
                self.volume.set_property('mute', False)
                self.is_muted = False
                logger.info("[AudioPassthrough] Audio UNMUTED")

    def set_volume(self, level):
        """
        Set volume level.

        Args:
            level: Volume level (0.0 = silent, 1.0 = 100%, 10.0 = 1000%)
        """
        with self._lock:
            if self.volume:
                self.volume.set_property('volume', level)
                logger.info(f"[AudioPassthrough] Volume set to {level}")

    def get_status(self):
        """Get current audio pipeline status."""
        # Use timeout to prevent hanging if lock is held by restart
        if not self._lock.acquire(timeout=2.0):
            return {
                "state": "unknown",
                "muted": self.is_muted,
                "restart_count": self._restart_count,
                "restart_in_progress": self._restart_in_progress,
                "last_buffer_age": time.time() - self._last_buffer_time if self._last_buffer_time > 0 else -1
            }

        try:
            if not self.pipeline:
                return {
                    "state": "stopped",
                    "muted": self.is_muted,
                    "restart_count": self._restart_count,
                    "restart_in_progress": self._restart_in_progress,
                    "last_buffer_age": -1
                }

            try:
                state_ret, state, pending = self.pipeline.get_state(0)
                state_name = state.value_nick if state else "unknown"
            except Exception:
                state_name = "error"

            return {
                "state": state_name,
                "muted": self.is_muted,
                "restart_count": self._restart_count,
                "restart_in_progress": self._restart_in_progress,
                "last_buffer_age": time.time() - self._last_buffer_time if self._last_buffer_time > 0 else -1
            }
        finally:
            self._lock.release()

    def pause_watchdog(self):
        """Pause the watchdog to prevent restart loops (e.g., when HDMI is lost).

        The pipeline will be stopped but the module remains ready to resume.
        """
        # Use timeout on lock to prevent hanging
        if not self._lock.acquire(timeout=10.0):
            logger.error("[AudioPassthrough] Could not acquire lock for pause (timeout)")
            # Still set paused flag even if we can't acquire lock
            self._watchdog_paused = True
            return

        try:
            self._watchdog_paused = True
            logger.info("[AudioPassthrough] Watchdog paused - no auto-restart")

            # Stop current pipeline to save resources
            if self.pipeline:
                try:
                    self.pipeline.set_state(Gst.State.NULL)
                    # Wait with timeout
                    self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                except Exception as e:
                    logger.debug(f"[AudioPassthrough] Error pausing pipeline: {e}")
        finally:
            self._lock.release()

    def resume_watchdog(self):
        """Resume the watchdog and restart the pipeline.

        Call this when HDMI signal is restored.
        """
        # Use timeout on lock to prevent hanging
        if not self._lock.acquire(timeout=10.0):
            logger.error("[AudioPassthrough] Could not acquire lock for resume (timeout)")
            return

        try:
            self._watchdog_paused = False

            # Reset failure counters
            self._consecutive_failures = 0
            self._current_restart_delay = self._base_restart_delay

            # Check if pipeline is already working - don't restart unnecessarily
            if self.pipeline:
                try:
                    state_ret, state, pending = self.pipeline.get_state(0)
                    if state == Gst.State.PLAYING:
                        logger.info("[AudioPassthrough] Watchdog resumed - pipeline already PLAYING, no restart needed")
                        return
                    # Also check ALSA status - if device is running with our PID, audio is working
                    if self._is_alsa_device_running():
                        logger.info("[AudioPassthrough] Watchdog resumed - ALSA device already running, no restart needed")
                        self._last_buffer_time = time.time()
                        return
                except Exception as e:
                    logger.debug(f"[AudioPassthrough] Error checking pipeline state during resume: {e}")

            logger.info("[AudioPassthrough] Watchdog resumed - restarting pipeline")

            # Force GC before restart
            gc.collect()

            # Clean up existing pipeline before creating new one
            if self.pipeline:
                try:
                    if hasattr(self, 'bus') and self.bus:
                        try:
                            self.bus.remove_signal_watch()
                        except:
                            pass
                        self.bus = None
                    self.pipeline.set_state(Gst.State.NULL)
                    self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                except Exception as e:
                    logger.debug(f"[AudioPassthrough] Error cleaning up old pipeline: {e}")
                self.pipeline = None
                self.volume = None
                time.sleep(0.5)  # Give ALSA time to release device

            # Restart pipeline
            if self.is_running:
                self._init_pipeline()
                if self.pipeline:
                    ret = self.pipeline.set_state(Gst.State.PLAYING)
                    if ret == Gst.StateChangeReturn.FAILURE:
                        logger.error("[AudioPassthrough] Failed to resume pipeline (set_state returned FAILURE)")
                    elif ret == Gst.StateChangeReturn.ASYNC:
                        # Wait with timeout
                        ret2, state, pending = self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                        if ret2 == Gst.StateChangeReturn.SUCCESS and state == Gst.State.PLAYING:
                            logger.info("[AudioPassthrough] Pipeline resumed successfully (async)")
                            self._last_buffer_time = time.time()
                            self._last_sync_reset = time.time()  # Reset A/V sync timer
                            if self.is_muted and self.volume:
                                self.volume.set_property('mute', True)
                        else:
                            logger.error(f"[AudioPassthrough] Failed to resume: ret={ret2}, state={state.value_nick if state else 'None'}")
                    else:
                        logger.info("[AudioPassthrough] Pipeline resumed successfully")
                        self._last_buffer_time = time.time()
                        self._last_sync_reset = time.time()  # Reset A/V sync timer
                        if self.is_muted and self.volume:
                            self.volume.set_property('mute', True)
                else:
                    logger.error("[AudioPassthrough] Failed to create pipeline during resume")
        except Exception as e:
            logger.error(f"[AudioPassthrough] Error during resume: {e}")
        finally:
            self._lock.release()

    def stop(self):
        """Stop audio passthrough."""
        # Mark as not running first to signal restart threads to stop
        self.is_running = False

        # Stop watchdog
        self._stop_watchdog.set()
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=2.0)
            self._watchdog_thread = None

        # Wait for any in-progress restart to complete
        if self._restart_in_progress:
            logger.debug("[AudioPassthrough] Waiting for restart to complete before stopping...")
            for _ in range(50):  # Wait up to 5 seconds
                if not self._restart_in_progress:
                    break
                time.sleep(0.1)

        # Use timeout on lock in case restart is stuck
        if not self._lock.acquire(timeout=5.0):
            logger.warning("[AudioPassthrough] Could not acquire lock for stop, forcing cleanup")
            # Force cleanup even without lock
            try:
                if self.pipeline:
                    self.pipeline.set_state(Gst.State.NULL)
            except:
                pass
            self.pipeline = None
            self.volume = None
            self.bus = None
            return

        try:
            # Stop pipeline
            if self.pipeline:
                try:
                    if self.bus:
                        self.bus.remove_signal_watch()
                    self.pipeline.set_state(Gst.State.NULL)
                    # Wait with timeout
                    self.pipeline.get_state(GST_STATE_CHANGE_TIMEOUT)
                    logger.info("[AudioPassthrough] Audio passthrough stopped")
                except Exception as e:
                    logger.error(f"[AudioPassthrough] Error stopping: {e}")

                self.pipeline = None
                self.volume = None
                self.bus = None
        finally:
            self._lock.release()

    def reset_av_sync(self):
        """Manually reset A/V sync by flushing the sync queue.

        This can be called via the web UI when audio/video are out of sync.
        Causes a brief audio dropout (~300ms) while the queue refills.

        Returns:
            dict with success status and message
        """
        if not self.is_running:
            return {'success': False, 'error': 'Audio not running'}

        if not self.pipeline:
            return {'success': False, 'error': 'No audio pipeline'}

        if self._flush_sync_queue():
            return {
                'success': True,
                'message': 'A/V sync reset - audio will resume in ~300ms'
            }
        else:
            # Fall back to full pipeline restart
            logger.info("[AudioPassthrough] Flush failed, doing full restart for A/V sync")
            threading.Thread(target=self._restart_pipeline, daemon=True).start()
            return {
                'success': True,
                'message': 'A/V sync reset via pipeline restart - audio will resume in ~1s'
            }

    def destroy(self):
        """Clean up resources."""
        self.stop()
