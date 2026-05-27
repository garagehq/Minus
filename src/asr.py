"""
ASR-based ad-content confirmation/veto via whisper.cpp.

Role in the detection stack:
  OCR  → reads text *on the screen*           — authoritative for blocking
  VLM  → classifies the *visual frame*        — primary AD/NO-AD signal
  ASR  → reads marketing-language *in speech* — confirms or vetoes VLM

ASR is intentionally NOT a primary trigger. It only:
  (1) CONFIRMS a VLM-alone block when marketing keywords are heard
      (becomes blocking_source "vlm+asr" — higher confidence label).
  (2) VETOES a VLM-alone block start, OR force-stops an active VLM-only
      block, when the audio is clearly show dialog with no marketing
      language (zero marker hits over the rolling window).
  (3) Returns "unknown" when it has no signal yet (cold start, music-only,
      whisper hallucinations on silence). "unknown" lets VLM fire normally
      — we never let an ASR outage prevent legitimate blocking.

The OCR-driven paths (`blocking_source` "ocr" / "both") are NOT consulted
against ASR. OCR text on the screen is authoritative.

Design (matches OCR/VLM worker patterns):
  - Audio comes from a parallel branch on the existing AudioPassthrough
    GStreamer pipeline (see AudioASRTap in src/audio.py). The tap branch
    has its own leaky queue so a slow ASR can never backpressure the
    passthrough to the TV — the playback latency is unchanged.
  - This module runs a Python *thread* (not subprocess). whisper.cpp's
    inference releases the GIL (it's mostly time in optimized C kernels),
    so a thread is enough — and we still get a hard timeout because we
    invoke `whisper-cli` as a *subprocess* with subprocess.run timeout.
    A hung whisper-cli is killed, the thread continues, no model reload
    needed (the next call reloads the model — ~150ms).
  - Rolling 8-second history of (timestamp, marker_hits, transcript)
    feeds the `verdict()` decision.

Cost on RK3588 (measured): tiny.en transcribes a 5-second window in
~1.1-1.3s on 3 threads (mostly A55 cores via scheduler). Wall-clock
period between inferences is 2s, giving ~70% CPU headroom on the ASR
worker thread. 0% impact on the existing OCR/VLM pipelines (different
cores, different NPUs).

Whisper-tiny mis-transcribes like OCR mis-reads. The keyword set in
`asr_keywords.py` is designed for that constraint: phrase-level
matching with multiple variants per phrase, regex shape-matchers for
prices/URLs/phone numbers, and an exclusion list for show-dialog
mentions of money. If quality is insufficient with tiny.en, swap the
model file (env MINUS_WHISPER_MODEL) — keyword module needs no change.
"""

import logging
import os
import subprocess
import threading
import time
from collections import deque
from typing import Optional

from asr_keywords import count_marker_hits, explain_hits

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Defaults — overridable via env vars matching the existing MINUS_* pattern.
# ---------------------------------------------------------------------------
DEFAULT_WHISPER_BIN = '/home/radxa/whisper.cpp/build/bin/whisper-cli'
DEFAULT_WHISPER_MODEL = '/home/radxa/whisper.cpp/models/ggml-tiny.en.bin'

WHISPER_BIN = os.environ.get('MINUS_WHISPER_BIN', DEFAULT_WHISPER_BIN)
WHISPER_MODEL = os.environ.get('MINUS_WHISPER_MODEL', DEFAULT_WHISPER_MODEL)


def is_asr_available() -> bool:
    """Whether whisper.cpp is installed at the configured paths.
    Used by Minus to decide whether to enable the audio tap branch.
    Returning False keeps the existing audio pipeline byte-identical to
    the pre-ASR shape — important for installs that don't have whisper."""
    return os.path.isfile(WHISPER_BIN) and os.access(WHISPER_BIN, os.X_OK) \
        and os.path.isfile(WHISPER_MODEL)


class ASRManager:
    """whisper.cpp-driven ad-content confirmation/veto.

    Public API used by Minus:
      start()              → spawn background inference thread
      stop()               → signal shutdown
      verdict()            → 'confirm' / 'veto' / 'unknown'
      get_status()         → dict for /api/status surface
      is_enabled           → bool
      enabled              → settable; False short-circuits verdict to 'unknown'

    Thread safety: `_history`, `last_*` attributes are guarded by `_lock`.
    `verdict()` is safe to call from the OCR/VLM decision loop hot path
    (single lock acquisition, O(window-size) iteration, no I/O).
    """

    # Rolling history window. Chosen to match the VLM sliding-window
    # cadence — 8s is "the last few iterations" so a single noisy hit
    # doesn't carry forever, and a streak of cleanness over 4+ seconds
    # provides enough evidence to veto.
    HISTORY_WINDOW_S = 8.0

    # How often to invoke whisper. 2s = overlapping windows (each 5s
    # snapshot overlaps the previous by 3s), which catches short bursts
    # of marketing copy that a non-overlapping 5s grid might split.
    INFERENCE_INTERVAL_S = 2.0

    # Audio window length per inference. 5s is a good marketing-copy
    # capture: most ad CTAs ("call 1-800, available now at X dot com")
    # fit in 4-5s of speech.
    WINDOW_SECONDS = 5.0

    # Whisper subprocess timeout. Healthy tiny.en p95 is ~1.3s on this
    # box; >2.5s means something's wrong (or model is too large). The
    # timeout is BELOW the inference interval so we can't pile up a
    # backlog of stuck processes.
    WHISPER_TIMEOUT_S = 2.5

    # Number of whisper threads. RK3588 has 4×A76 + 4×A55. 3 threads
    # leaves the rest of the system breathing room. Whisper scales
    # near-linearly up to ~4 threads on this chip; past that the
    # marginal return drops.
    WHISPER_THREADS = 3

    def __init__(self, audio_tap, *, whisper_bin: str = None,
                 model_path: str = None):
        """audio_tap must be an AudioASRTap (see src/audio.py).
        It exposes `snapshot_to_wav(seconds)` returning True on success.
        """
        self._tap = audio_tap
        self._whisper_bin = whisper_bin or WHISPER_BIN
        self._model_path = model_path or WHISPER_MODEL
        self._wav_path = '/dev/shm/minus_asr_window.wav'

        # Runtime state
        self.is_running = False
        self.enabled = True  # When False, verdict() short-circuits to 'unknown'
        self.inference_count = 0
        self.timeout_count = 0
        self.failure_count = 0
        self.last_transcript = ''
        self.last_marker_hits = 0
        self.last_inference_time = 0.0
        self.last_inference_latency = 0.0
        self._recent_latencies = deque(maxlen=20)

        # Rolling history: (timestamp, marker_hits, transcript_len)
        # Transcript length is kept (not full text) for the "veto only
        # when there's enough transcribed speech" rule.
        self._history = deque(maxlen=32)
        self._lock = threading.RLock()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ----- lifecycle -----

    def start(self):
        if self.is_running:
            return
        if not os.path.isfile(self._whisper_bin):
            logger.warning(f"[ASR] whisper-cli not found at {self._whisper_bin} — ASR disabled")
            return
        if not os.path.isfile(self._model_path):
            logger.warning(f"[ASR] model not found at {self._model_path} — ASR disabled")
            return

        self._stop_event.clear()
        self.is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name='ASR')
        self._thread.start()
        logger.info(f"[ASR] started (model={os.path.basename(self._model_path)}, "
                    f"window={self.WINDOW_SECONDS}s, interval={self.INFERENCE_INTERVAL_S}s, "
                    f"threads={self.WHISPER_THREADS})")

    def stop(self):
        if not self.is_running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.is_running = False
        logger.info(f"[ASR] stopped after {self.inference_count} inferences "
                    f"(timeouts={self.timeout_count}, failures={self.failure_count})")

    # ----- main loop -----

    def _loop(self):
        # Give the audio tap a moment to fill the ring buffer with at
        # least one window's worth of data. Without this we'd start
        # producing empty/short transcripts immediately on boot.
        if not self._stop_event.wait(self.WINDOW_SECONDS + 0.5):
            pass

        while not self._stop_event.is_set():
            try:
                # Skip when disabled by user (still keep audio tap running
                # so the buffer stays current — re-enabling resumes
                # without a cold start).
                if not self.enabled:
                    self._stop_event.wait(self.INFERENCE_INTERVAL_S)
                    continue

                # Pull a fresh snapshot from the tap.
                if not self._tap.snapshot_to_wav(self.WINDOW_SECONDS):
                    # Tap not ready (not enough audio yet, or stalled).
                    self._stop_event.wait(self.INFERENCE_INTERVAL_S)
                    continue

                transcript, latency, status = self._run_whisper(self._wav_path)
                self._record_result(transcript, latency, status)
            except Exception as e:
                logger.error(f"[ASR] loop iteration failed: {e}")
                self.failure_count += 1

            self._stop_event.wait(self.INFERENCE_INTERVAL_S)

    def _run_whisper(self, wav_path: str):
        """Returns (transcript, elapsed_seconds, status).
        status ∈ {'ok', 'timeout', 'error'}.
        """
        start = time.time()
        try:
            result = subprocess.run(
                [
                    self._whisper_bin,
                    '-m', self._model_path,
                    '-f', wav_path,
                    '-t', str(self.WHISPER_THREADS),
                    '-np',  # no debug prints
                    '-nt',  # no timestamps in output
                    '-l', 'en',
                ],
                capture_output=True, text=True,
                timeout=self.WHISPER_TIMEOUT_S,
            )
            elapsed = time.time() - start
            if result.returncode != 0:
                logger.warning(f"[ASR] whisper-cli returned {result.returncode}: "
                               f"{result.stderr[:120] if result.stderr else ''}")
                return '', elapsed, 'error'
            text = (result.stdout or '').strip()
            return text, elapsed, 'ok'
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            return '', elapsed, 'timeout'
        except FileNotFoundError as e:
            logger.error(f"[ASR] whisper-cli missing: {e}")
            return '', time.time() - start, 'error'

    def _record_result(self, transcript: str, latency: float, status: str):
        hits = count_marker_hits(transcript) if status == 'ok' else 0
        now = time.time()
        with self._lock:
            self.inference_count += 1
            if status == 'timeout':
                self.timeout_count += 1
            elif status == 'error':
                self.failure_count += 1
            self._recent_latencies.append(latency)
            self.last_inference_time = now
            self.last_inference_latency = latency
            if status == 'ok':
                self.last_transcript = transcript
                self.last_marker_hits = hits
                # Track transcript length (number of alpha words) — used
                # by verdict() to distinguish "no marketing language"
                # from "no transcribed speech at all".
                import re
                alpha_word_count = len(re.findall(r'[a-z]{2,}', transcript.lower()))
                self._history.append((now, hits, alpha_word_count))
                # Trim history to window
                cutoff = now - self.HISTORY_WINDOW_S
                while self._history and self._history[0][0] < cutoff:
                    self._history.popleft()

        # Log only when something useful happened (signal hit OR notable
        # transcript length). Avoids spamming the journal with empty
        # "..." results when the source has been silent.
        if status == 'ok' and (hits > 0 or len(transcript) >= 20):
            preview = transcript[:80].replace('\n', ' ')
            if hits > 0:
                markers = explain_hits(transcript)[:5]
                logger.info(f"[ASR] hits={hits} ({latency:.2f}s) markers={markers} text='{preview}'")
            else:
                logger.debug(f"[ASR] hits=0 ({latency:.2f}s) text='{preview}'")
        elif status != 'ok':
            logger.debug(f"[ASR] inference {status} ({latency:.2f}s)")

    # ----- decision API -----

    def verdict(self) -> str:
        """Three-state output: 'confirm' / 'veto' / 'unknown'.

        Used by Minus._update_blocking_state for the VLM-alone start
        gate and the mid-block force-stop. See the module-level docstring
        for the role contract.

        Decision rule:
          - disabled or not running        → 'unknown' (never blocks VLM)
          - any marker hits in window      → 'confirm' (marketing heard)
          - no hits AND ≥1 inference with
            transcribed speech in window   → 'veto'   (show audio, not ad)
          - otherwise                      → 'unknown' (no useful signal)
        """
        if not self.is_running or not self.enabled:
            return 'unknown'
        now = time.time()
        with self._lock:
            cutoff = now - self.HISTORY_WINDOW_S
            recent = [h for h in self._history if h[0] >= cutoff]
        if not recent:
            return 'unknown'
        total_hits = sum(h[1] for h in recent)
        if total_hits > 0:
            return 'confirm'
        # No hits — only veto if we actually transcribed enough speech.
        # Sum of alpha-word counts across recent windows; 10+ words over
        # the rolling window means "there was real speech we processed."
        total_words = sum(h[2] for h in recent)
        if total_words >= 10:
            return 'veto'
        return 'unknown'

    # ----- status surface -----

    def get_status(self) -> dict:
        with self._lock:
            recent_lat = list(self._recent_latencies)
            history_len = len(self._history)
            recent_hits_sum = sum(h[1] for h in self._history)
        if recent_lat:
            import statistics
            p50 = statistics.median(recent_lat)
            p95 = (sorted(recent_lat)[max(0, int(0.95 * len(recent_lat)) - 1)]
                   if recent_lat else 0.0)
        else:
            p50 = p95 = 0.0
        return {
            'available': is_asr_available(),
            'enabled': self.enabled,
            'running': self.is_running,
            'inference_count': self.inference_count,
            'timeout_count': self.timeout_count,
            'failure_count': self.failure_count,
            'verdict': self.verdict(),
            'history_window_s': self.HISTORY_WINDOW_S,
            'history_entries': history_len,
            'recent_hits_sum': recent_hits_sum,
            'last_transcript': self.last_transcript[:200],
            'last_marker_hits': self.last_marker_hits,
            'last_latency_s': round(self.last_inference_latency, 3),
            'p50_latency_s': round(p50, 3),
            'p95_latency_s': round(p95, 3),
        }
