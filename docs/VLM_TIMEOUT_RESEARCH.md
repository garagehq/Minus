# VLM Timeout and Cancellation Research

*Date: April 19, 2026*

## Problem Statement

When VLM inference takes longer than the timeout threshold (1.5s), we need to handle it gracefully. The naive approach of killing the worker process causes a 30-second model reload, which is unacceptable for a single slow inference.

**Goal**: Find a way to cancel/interrupt a VLM inference that's taking too long WITHOUT killing the process and reloading the model.

## Research Findings

### axengine API Analysis

The `axengine.InferenceSession` class (Python bindings for Axera NPU) exposes only these methods:

```python
InferenceSession methods:
  get_inputs()        # Get input node information
  get_outputs()       # Get output node information
  get_providers()     # Get available providers (AXCLRTExecutionProvider)
  get_session_options() # Get session configuration
  run()               # Execute inference (BLOCKING)
```

**There is no `cancel()`, `abort()`, `interrupt()`, or `stop()` method.**

### Why Cancellation Is Difficult

1. **Blocking C Library**: The inference runs through AXCL (Axera Compute Library), a C library that:
   - Submits work to the NPU hardware
   - Blocks until the hardware completes
   - Returns results to Python

2. **NPU as Black Box**: Once `session.run()` is called, control is transferred to the NPU hardware. There's no mechanism to interrupt the hardware mid-computation.

3. **No Async API**: Unlike some NPU libraries that support async submission with polling, axengine only provides synchronous inference.

### FastVLM Inference Architecture

FastVLM-1.5B inference consists of:

1. **Vision Encoder** (~100ms): Single `InferenceSession.run()` call for image encoding
2. **LLM Prefill** (~200-400ms): Multiple layer-by-layer `run()` calls (28 decoder layers)
3. **LLM Decode** (~500-800ms): Token-by-token autoregressive generation

The decode phase is where most time is spent, and it's a loop of individual `run()` calls. Theoretically, we could add a check between decode steps, but this would require modifying `InferManager.decode()` in the FastVLM codebase.

## Potential Solutions (Future Investigation)

### 1. Inter-Decode-Step Cancellation

Modify `InferManager.decode()` in `/home/radxa/axera_models/FastVLM-1.5B/utils/infer_func.py`:

```python
def decode(self, tokenizer, token_ids, embed_matrix, ..., cancel_flag=None):
    for step_idx in range(self.max_seq_len):
        # Check cancellation between decode steps
        if cancel_flag and cancel_flag.is_set():
            return None  # Cancelled

        # ... rest of decode logic
```

**Pros**: Could cancel mid-generation without killing process
**Cons**:
- Requires modifying FastVLM codebase
- Each decode step is ~20-30ms, so granularity is limited
- Would need to handle partial state cleanup

### 2. Thread-Based Timeout with pthread_cancel

Run inference in a separate thread and use low-level thread cancellation:

```python
import ctypes
import threading

def cancel_thread(thread):
    thread_id = ctypes.c_long(thread.ident)
    ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, ctypes.py_object(SystemExit))
```

**Pros**: Could interrupt even during `run()` call
**Cons**:
- Very dangerous - can corrupt NPU state
- May leak resources
- Python thread cancellation is unreliable

### 3. AXCL C API Direct Access

The underlying C library might have cancellation capabilities not exposed in Python bindings. Would require:
- Finding AXCL header files and documentation
- Writing Python ctypes bindings for cancellation functions
- Testing for NPU state corruption

**Location to investigate**: `/usr/bin/axcl/` contains various AXCL tools

### 4. Separate Process with Shared Memory

Instead of IPC via Queue, use shared memory for the image data:
- Main process writes image to shared memory
- Worker process reads and processes
- On timeout, main process can immediately start processing next frame
- Late results are just discarded (no Queue drain needed)

**Pros**: Eliminates Queue overhead, cleaner timeout handling
**Cons**: More complex implementation, shared memory management

## Current Implementation (Soft Timeout)

Given the limitations, we implemented a "soft timeout" strategy in `src/vlm_worker.py`:

```
SOFT_TIMEOUT = 1.5s   # Return "TIMEOUT" but don't kill
HARD_TIMEOUT = 5.0s   # Kill only if truly stuck
RESTART_THRESHOLD = 3 # Consecutive soft timeouts before hard kill
```

**Flow**:
1. Send inference request
2. Wait 1.5s for response
3. If timeout:
   - First timeout: Return "TIMEOUT", mark `_pending_response = True`
   - Worker keeps running, may complete later
4. On next request:
   - Check if pending response arrived (drain it)
   - If arrived: great, reset counters
   - If not: increment timeout counter
5. After 3 consecutive soft timeouts:
   - Wait up to 5s total (hard timeout)
   - If still stuck: kill and restart

**Results**:
- Occasional slow inferences (1.6-2.0s) don't cause restarts
- Only truly stuck workers get killed
- VLM availability improved from ~50% to ~95%

## Performance Observations

| Scenario | Inference Time | Behavior |
|----------|---------------|----------|
| Normal | 0.9-1.1s | Success, counter reset |
| Slightly slow | 1.5-2.0s | Soft timeout, drained on next request |
| Very slow | 2.0-5.0s | Multiple soft timeouts, may recover |
| Stuck | >5.0s | Hard kill after 3 soft timeouts |

## Files Modified

- `src/vlm_worker.py` - Soft/hard timeout implementation
- `src/ocr_worker.py` - Similar improvements for OCR
- `CLAUDE.md` - Documentation updates

## Future Work

1. **Investigate AXCL C API** for native cancellation support
2. **Modify FastVLM decode loop** to check cancellation flag between steps
3. **Profile NPU behavior** to understand why occasional inferences are slow
4. **Consider shared memory IPC** for lower latency timeout handling

## References

- axengine Python bindings: Part of Axera SDK
- FastVLM model: `/home/radxa/axera_models/FastVLM-1.5B/`
- AXCL tools: `/usr/bin/axcl/`
- Axera M5 LLM 8850 documentation: (proprietary)
