"""
ASR Worker Process — runs faster-whisper in a separate Python process so
we can hard-kill stuck inferences instead of just timing out.

Mirrors the OCR/VLM worker pattern (see src/vlm_worker.py for the
template that defines our hard-timeout safety story):
  - 'spawn' start method (no inherited fds / state from the parent)
  - load model once at startup, then process WAV file paths from a
    multiprocessing.Queue
  - parent uses a soft timeout (returns 'timeout' to caller but keeps
    the worker running, hoping it finishes) and a hard timeout (kill +
    restart). Three consecutive soft timeouts → hard kill.

Why this exists (history): the previous implementation in src/asr.py
shelled out to whisper.cpp's `whisper-cli` binary per inference. That
gave us hard-timeout for free (subprocess.run with timeout=). When we
swapped to faster-whisper for the speed/accuracy win documented in
docs/ASR.md, faster-whisper became an in-process Python lib — losing
that safety story. This worker restores it: faster-whisper runs in
a child process; if it hangs we kill the process; the parent thread
that requested the inference returns 'killed' and the next snapshot
goes through normally after the worker comes back up.

The keyword module (src/asr_keywords.py) is engine-agnostic, so the
swap from whisper.cpp to faster-whisper required no keyword changes.
"""

import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from collections import deque
from multiprocessing import Process, Queue, Event

# 'spawn' so we don't inherit fds/state from the parent. Critical when
# the parent process uses multiprocessing internally (axengine for VLM)
# — 'fork' there causes "can only join a child process" errors.
try:
    mp.set_start_method('spawn', force=True)
except RuntimeError:
    pass  # Already set by another worker import (VLM/OCR)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker process main loop
# ---------------------------------------------------------------------------

def _asr_worker_main(request_queue, response_queue, ready_event, shutdown_event,
                     model_name, cpu_threads):
    """Worker process entrypoint.

    Args:
        request_queue:  multiprocessing.Queue carrying WAV file paths
                        (or None as a shutdown sentinel)
        response_queue: multiprocessing.Queue receiving
                        (status, transcript, elapsed_seconds) tuples
        ready_event:    set once the model is loaded and warmup is done
        shutdown_event: set by parent to request graceful shutdown
        model_name:     faster-whisper model identifier (e.g. 'tiny.en')
                        or a path to a pre-downloaded model directory
        cpu_threads:    threads for CTranslate2 inference
    """
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO,
                         format='%(asctime)s [%(levelname)s] %(message)s')
    log = _logging.getLogger('ASRWorker')

    try:
        load_start = time.time()
        log.info(f"[ASRWorker] Loading faster-whisper {model_name!r} "
                 f"(cpu_threads={cpu_threads}, compute_type=int8)...")

        # Import inside the worker so the parent doesn't carry the
        # faster-whisper / CTranslate2 dependency footprint.
        from faster_whisper import WhisperModel

        model = WhisperModel(
            model_name,
            device='cpu',
            compute_type='int8',
            cpu_threads=cpu_threads,
            # The model auto-downloads to ~/.cache/huggingface on first
            # use. Subsequent loads are local and fast (~1s for tiny.en).
        )

        # Tiny warmup: a single empty/silence inference primes the
        # CTranslate2 kernels so the first real call doesn't pay
        # one-time overhead.
        try:
            import numpy as np
            warmup_audio = np.zeros(16000, dtype=np.float32)  # 1s of silence
            list(model.transcribe(warmup_audio, beam_size=1, language='en')[0])
        except Exception as e:
            log.warning(f"[ASRWorker] Warmup skipped: {e}")

        log.info(f"[ASRWorker] Model loaded in {time.time() - load_start:.1f}s "
                 f"(ready)")
        ready_event.set()

        # Main request loop. `get(timeout=1.0)` returns control to check
        # shutdown_event between requests, so kill signals propagate
        # within ~1s even when no audio is arriving.
        while not shutdown_event.is_set():
            try:
                request = request_queue.get(timeout=1.0)
            except Exception:
                continue  # queue.Empty — loop back and re-check shutdown

            if request is None:
                # Sentinel: parent signaling shutdown via the queue.
                break

            wav_path = request
            start = time.time()
            try:
                segments, _info = model.transcribe(
                    wav_path,
                    beam_size=1,        # greedy decoding — fastest
                    language='en',
                    condition_on_previous_text=False,
                    vad_filter=False,
                )
                text = ' '.join(s.text for s in segments).strip()
                response_queue.put(('ok', text, time.time() - start))
            except FileNotFoundError as e:
                response_queue.put(('error', f'wav not found: {e}', time.time() - start))
            except Exception as e:
                response_queue.put(('error', f'inference failed: {e}',
                                    time.time() - start))

        log.info("[ASRWorker] Shutdown signaled, exiting cleanly")
    except Exception as e:
        log.error(f"[ASRWorker] Fatal during startup/loop: {e}", exc_info=True)
    finally:
        # Best-effort signal so the parent's start() wait returns even
        # on load failure (so it can retry/give up rather than block 60s).
        try:
            ready_event.set()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Parent-side controller — hard-timeout via process kill
# ---------------------------------------------------------------------------


class ASRProcess:
    """Parent-side handle to the ASR worker. Provides transcribe() with
    soft + hard timeouts; kills + restarts the worker on hangs.

    Threading: all public methods are thread-safe via `_call_lock`.
    transcribe() can be called from the ASRManager's loop thread without
    additional locking on the caller side.
    """

    # Healthy faster-whisper tiny.en (CT2 int8) on 3 threads, measured
    # from tests/asr_corpus/bench.py against the 10-sample corpus:
    #   p50 ~1.10 s, max ~1.40 s per 5-second window.
    # Soft timeout 2.5s gives ~2.2× headroom over observed max; hard
    # timeout 3.0s reaps a genuinely hung worker before the next 2-second
    # snapshot cycle can pile up a second request.
    SOFT_TIMEOUT = 2.5
    HARD_TIMEOUT = 3.0
    RESTART_THRESHOLD = 3  # Hard kill after this many consecutive soft timeouts
    WORKER_LOAD_TIMEOUT = 30.0  # tiny.en loads ~1s; allow plenty for first-time HF download

    def __init__(self, model_name='tiny.en', cpu_threads=3):
        self.model_name = model_name
        self.cpu_threads = cpu_threads

        # Worker process state
        self.process = None
        self.request_queue = None
        self.response_queue = None
        self.ready_event = None
        self.shutdown_event = None
        self.is_ready = False

        # Bookkeeping for restart / timeout management
        self._restart_count = 0
        self._consecutive_timeouts = 0
        self._pending_response = False  # True if previous call timed out and worker may still answer
        self._call_lock = threading.Lock()
        self._recent_latencies = deque(maxlen=20)

    # ----- lifecycle -----

    def start(self) -> bool:
        """Spawn the worker process and wait up to WORKER_LOAD_TIMEOUT
        seconds for the model to load. Returns True on success."""
        with self._call_lock:
            if self.process is not None and self.process.is_alive():
                if self.ready_event is not None and self.ready_event.is_set():
                    self.is_ready = True
                return self.is_ready

            self.request_queue = Queue()
            self.response_queue = Queue()
            self.ready_event = Event()
            self.shutdown_event = Event()

            self.process = Process(
                target=_asr_worker_main,
                args=(self.request_queue, self.response_queue,
                      self.ready_event, self.shutdown_event,
                      self.model_name, self.cpu_threads),
                daemon=True,
                name=f'ASRWorker-{self.model_name}'
            )
            self.process.start()

        start = time.time()
        logger.info(f"[ASRProcess] Waiting for worker to load "
                    f"(PID {self.process.pid}, model={self.model_name})...")

        ok = self.ready_event.wait(timeout=self.WORKER_LOAD_TIMEOUT)
        if ok and self.process.is_alive():
            elapsed = time.time() - start
            self.is_ready = True
            logger.info(f"[ASRProcess] Worker ready in {elapsed:.1f}s")
            return True

        # Either timeout or worker died during load. Tear it down so
        # the next start() attempt gets a clean slate.
        logger.error(f"[ASRProcess] Worker failed to become ready "
                     f"after {self.WORKER_LOAD_TIMEOUT}s — killing")
        self._kill_process_locked()
        return False

    def stop(self):
        """Gracefully shut down the worker. Best-effort — falls through
        to terminate/kill if the worker is unresponsive."""
        with self._call_lock:
            if self.process is None:
                return

            if self.shutdown_event is not None:
                self.shutdown_event.set()
            # Queue a sentinel so a blocked `get(timeout=1)` loop wakes up
            try:
                self.request_queue.put_nowait(None)
            except Exception:
                pass

            if self.process.is_alive():
                self.process.join(timeout=3.0)
            if self.process.is_alive():
                logger.warning("[ASRProcess] Worker did not exit cleanly; terminating")
                self.process.terminate()
                self.process.join(timeout=2.0)
            if self.process.is_alive():
                logger.warning("[ASRProcess] Worker still alive after terminate; killing")
                self.process.kill()
                self.process.join(timeout=1.0)

            self.process = None
            self.is_ready = False

    def restart(self):
        """Kill + respawn the worker. Used on hard-timeout escalation."""
        logger.warning(f"[ASRProcess] Restarting worker "
                       f"(restart #{self._restart_count + 1})")
        self._restart_count += 1
        self.stop()
        return self.start()

    def _kill_process_locked(self):
        """Internal — must be called with `_call_lock` held."""
        if self.process is None:
            return
        try:
            self.process.kill()
            self.process.join(timeout=1.0)
        except Exception:
            pass
        self.process = None
        self.is_ready = False

    # ----- public inference API -----

    def transcribe(self, wav_path: str):
        """Synchronously transcribe a WAV file.

        Returns (status, transcript, elapsed_seconds) where:
          status == 'ok'      → inference completed
                 == 'timeout' → soft timeout fired; worker may still finish
                                later (we'll drain on next call). Returned
                                so the caller can keep going.
                 == 'killed'  → hard timeout fired; worker has been killed
                                and is restarting in the background. Caller
                                should not block on the next call.
                 == 'error'   → worker reported an inference exception OR
                                the worker isn't running. transcript holds
                                the error text for logging.

        Thread-safe via `_call_lock`. The lock also serializes the
        per-call bookkeeping (_pending_response, _consecutive_timeouts).
        """
        with self._call_lock:
            if not self.is_ready or self.process is None or not self.process.is_alive():
                return 'error', 'worker not running', 0.0

            # Drain any late response from a previous soft-timeout call.
            # If we don't, that response would be picked up as the answer
            # to the NEW request below — classic queue desync.
            self._drain_stale_responses_locked()

            if self._pending_response:
                # Worker is still busy with a previous inference. Don't
                # queue another; tell caller we're still waiting.
                if self._consecutive_timeouts >= self.RESTART_THRESHOLD:
                    logger.warning(
                        f"[ASRProcess] {self._consecutive_timeouts} consecutive "
                        f"soft timeouts — killing stuck worker")
                    self.restart()
                    self._pending_response = False
                    self._consecutive_timeouts = 0
                    return 'killed', '', 0.0
                return 'timeout', '', 0.0

            self.request_queue.put(wav_path)
            start = time.time()

            try:
                result = self.response_queue.get(timeout=self.SOFT_TIMEOUT)
            except Exception:
                # Soft timeout. Worker may still finish — leave
                # _pending_response True so we drain on next call.
                self._pending_response = True
                self._consecutive_timeouts += 1
                elapsed = time.time() - start

                # If we're past hard timeout, kill+restart immediately.
                if elapsed >= self.HARD_TIMEOUT or \
                        self._consecutive_timeouts >= self.RESTART_THRESHOLD:
                    logger.warning(
                        f"[ASRProcess] Hard timeout / restart threshold "
                        f"hit ({elapsed:.1f}s) — killing worker")
                    self.restart()
                    self._pending_response = False
                    self._consecutive_timeouts = 0
                    return 'killed', '', elapsed

                return 'timeout', '', elapsed

            # Got a response — reset timeout counter
            self._consecutive_timeouts = 0
            self._pending_response = False

            status, payload, latency = result
            if status == 'ok':
                self._recent_latencies.append(latency)
            return status, payload, latency

    # Hard cap on drain iterations. The drain loop SHOULD exit naturally
    # via queue.Empty after at most ~RESTART_THRESHOLD entries (one per
    # backlogged soft-timeout). But if the queue object misbehaves (a
    # tests-with-MagicMock surprise that killed the box once, or a real
    # multiprocessing.Queue corruption case), we never want an infinite
    # loop here — it'd OOM the parent + take down the whole service.
    _MAX_DRAIN_ITERATIONS = 32

    def _drain_stale_responses_locked(self):
        """Pull any leftover responses from a previous soft-timeout call.
        Returns immediately if the queue is empty. Hard-capped at
        _MAX_DRAIN_ITERATIONS to prevent infinite-loop OOM if the queue
        object somehow returns truthy non-empty results indefinitely."""
        drained = 0
        for _ in range(self._MAX_DRAIN_ITERATIONS):
            try:
                self.response_queue.get_nowait()
                drained += 1
            except Exception:
                break
        else:
            # Hit the cap without seeing Empty. Real-world this should
            # never happen — log loud so it's visible if it does.
            logger.warning(
                f"[ASRProcess] drain capped at {self._MAX_DRAIN_ITERATIONS} "
                f"iterations — queue may be misbehaving")
        if drained:
            logger.debug(f"[ASRProcess] Drained {drained} stale responses")
            # If we drained something, the previous pending_response is now resolved
            self._pending_response = False

    # ----- introspection -----

    def get_latency_stats(self) -> dict:
        latencies = list(self._recent_latencies)
        if not latencies:
            return {'samples': 0, 'p50_s': 0.0, 'p95_s': 0.0, 'max_s': 0.0}
        import statistics
        srt = sorted(latencies)
        p95_idx = max(0, int(0.95 * len(srt)) - 1)
        return {
            'samples': len(latencies),
            'p50_s': round(statistics.median(latencies), 3),
            'p95_s': round(srt[p95_idx], 3),
            'max_s': round(max(latencies), 3),
        }
