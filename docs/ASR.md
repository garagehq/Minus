# ASR (audio-based ad confirmation)

**faster-whisper tiny.en** (CTranslate2 int8) running on 3 CPU threads
in a dedicated multiprocessing worker subprocess (`src/asr_worker.py`).
Fed from a parallel `tee` branch of the existing GStreamer audio
pipeline, used as a **confirmation + veto signal** for VLM-alone ad
blocking. Does not trigger blocking alone; does not affect OCR-driven
blocking.

**Engine history:** initial implementation used whisper.cpp (binary
subprocess invocation), swapped to faster-whisper after the corpus
benchmark in `tests/asr_corpus/bench.py` showed 25% speedup (1.14s vs
1.52s per 5s window) at identical 10/10 corpus accuracy with cleaner
transcripts. The multiprocessing worker pattern restores the
hard-timeout safety we previously got "for free" from whisper.cpp's
binary subprocess invocation.

## Why it exists

VLM sometimes calls a frame an ad when the visual is ambiguous — a
character holding a Coke can during a Netflix show, a brand storefront
in the background, a product placement scene. OCR sees nothing (no
"Sponsored" / "Skip" text on screen) and VLM-alone fires the block on
genuine show content.

ASR provides a **second opinion on the audio channel**. Real ads have a
marketing-language acoustic signature (announcer voice, CTAs like
"available now / call 1-800 / save 50%", price strings with cents,
URLs spoken as "dot com"). Product placements in shows have *actor
dialogue*, no marketing copy. Whisper transcribes the audio, the
keyword module counts marketing markers, the verdict gates VLM-alone.

## Architecture

```
HDMI-RX (hw:4,0)
   │
   ▼
alsasrc (existing) ──► audio/x-raw,48kHz,2ch,S16LE
                                        │
                                        ▼
                              tee (allow-not-linked=true)
                              │                        │
       ┌──────────────────────┘                        └──────────────────────┐
       │ PLAYBACK BRANCH (unchanged, latency-critical)                        │ ASR TAP BRANCH (new)
       ▼                                                                     ▼
syncqueue (300ms threshold)                                       queue leaky=downstream
       │                                                                     │
       ▼                                                                     ▼
audioqueue (jitter buffer)                                        audioconvert + audioresample
       │                                                                     │
       ▼                                                                     ▼
audioconvert                                                      audio/x-raw,16kHz,1ch,S16LE
       │                                                                     │
       ▼                                                                     ▼
volume (mute=true during ads) ◄── ad_blocker mute control          appsink "asr_sink"
       │                                                                     │
       ▼                                                                     ▼ (Python callback)
alsasink (hw:0,0 → HDMI-TX)                                       AudioASRTap ring buffer
       │                                                          (8s ring, 16kHz S16LE)
       ▼                                                                     │
       TV speakers                                                           ▼
                                                                  snapshot_to_wav() every 2s
                                                                             │
                                                                             ▼
                                                                  whisper.cpp tiny.en
                                                                  (subprocess, 3 threads,
                                                                   2.5s hard timeout)
                                                                             │
                                                                             ▼
                                                                  transcript → count_marker_hits()
                                                                             │
                                                                             ▼
                                                                  ASRManager.verdict()
                                                                  ──► confirm / veto / unknown
                                                                             │
                                                                             ▼
                                                                  Minus._update_blocking_state()
                                                                  gates VLM-alone block start
                                                                  + force-stops mid-block on veto
```

**Safety invariant:** the playback branch (`syncqueue → audioqueue →
audioconvert → volume → alsasink`) is byte-identical whether the tap
is attached or not. Same elements, same names, same parameters, same
latency budget (~500ms to match video). Tee fanout is zero-copy ref-
counting; latency added to playback = 0. The tap branch is leaky
(`queue leaky=downstream`) so a slow whisper consumer drops buffers
rather than backpressuring the playback side. Asserted by
`tests/test_asr.py::TestAudioPipelineShape`.

## Decision-engine integration

| OCR | VLM | ASR verdict | Action |
|---|---|---|---|
| ad | * | * | **block** (`source=ocr` or `both`) — OCR is authoritative, ASR has no role |
| no | ad (3+ decisions, 80%+) | confirm | **block** (`source=vlm+asr`) — high confidence |
| no | ad (3+ decisions, 80%+) | unknown | **block** (`source=vlm`) — VLM alone, no ASR signal yet |
| **no** | **ad (3+, 80%+)** | **veto** | **SUPPRESS** — this is the product-placement case |
| (mid-block) | source=`vlm` | veto for ≥4s | **force-stop** — VLM-only block, ASR confirmed show audio |

Notes:

- `verdict='confirm'`: ≥1 marker hit in the rolling 8-second window of
  ASR transcripts.
- `verdict='veto'`: 0 marker hits AND ≥10 alpha-words transcribed across
  the window (i.e. real speech we processed, not silence/music). This
  is the "there was speech, it didn't sound like marketing" signal.
- `verdict='unknown'`: cold start, music-only audio, silence, ASR
  disabled, or whisper hung. Falls through to existing VLM behaviour —
  we NEVER let an ASR outage prevent legitimate VLM blocking.
- The 4-second mid-block force-stop floor exists so the rolling window
  has time to fill with show audio after the block starts. VLM-only
  blocks that ASR has been listening to for ≥4s with zero markers are
  almost certainly false positives on visual brand content.

## Install

```bash
pip3 install --break-system-packages --user faster-whisper
```

Model files auto-download from HuggingFace to `~/.cache/huggingface/`
on first use (~75 MB for tiny.en). Subsequent loads are local.

Override the model via `MINUS_ASR_MODEL` env var. Built-in sizes:
`tiny.en` (default), `base.en`, `small.en`, `medium.en`, `large`.
Can also be a path to a local model directory.

CTranslate2 (the inference engine under faster-whisper) auto-detects
ARM NEON kernels on RK3588 — no manual flags needed.

**whisper.cpp (legacy):** the original implementation lives at
`/home/radxa/whisper.cpp`. Kept on disk for reference + the
`tests/asr_corpus/bench.py` baseline comparison. No longer
loaded at runtime.

## Cost on RK3588

Bench: `tests/asr_corpus/bench.py` against 10-sample synthesized corpus.
**Measured on RK3588 with `minus` service stopped** so each engine got
all 8 cores to itself (no contention with OCR/VLM workers). 3 threads
each for direct comparison. Re-run from the repo root:

```
python3 tests/asr_corpus/bench.py
```

| Engine | Pass | Total | Avg / 5 s window | Notes |
|---|---|---|---|---|
| **faster-whisper tiny.en** (CTranslate2 int8) | **10/10** | 11.45 s | **1.14 s** | Fastest at 10/10. Best transcripts. |
| moonshine tiny (ONNX) | 8/10 | 11.25 s | 1.13 s | Tied on speed; missed 2 subtle ads (`narcissism`-style hallucinations dropped one marker each). |
| **whisper.cpp tiny.en** *(current)* | 10/10 | 15.15 s | 1.52 s | Production baseline. |
| moonshine small-streaming (ONNX) | 9/10 | 19.55 s | 1.95 s | Cleaner transcripts than tiny; one ad-pharma miss. |
| moonshine medium-streaming (ONNX) | 10/10 | 26.31 s | 2.63 s | Best transcription quality of any tested model. |

**Findings:**

1. **faster-whisper tiny.en is the winner**: 25% faster than whisper.cpp
   at identical pass rate (10/10), and slightly better transcript quality
   (correct punctuation, retains `$` in phone numbers like `$15`,
   captures `1-800-555-1234` shape). CTranslate2 int8 quantization
   does heavy lifting.
2. **Moonshine tiny (ONNX) is competitive with faster-whisper on speed**,
   but loses 2 subtle-ad cases in this corpus. The streaming variants
   exist primarily for *streaming* use (live audio chunks); we're using
   them as non-streaming transcribers which probably understates their
   real strength.
3. **Moonshine medium-streaming** has the cleanest transcripts of any
   model tested — "Now only 999. Free shipping on orders over $25.
   Order yours today" is basically perfect. 10/10 pass, but 2.3×
   slower than faster-whisper.

**The first install attempt did NOT use the right Moonshine package.**
We initially installed `useful-moonshine` from PyPI which is the
deprecated Keras+Torch implementation — that gave us ~9 s/sample,
orders of magnitude slower than the published Pi 5 benchmarks. The
correct package is `moonshine-voice` which ships ONNX models and the
optimized C++/ONNX runtime. The numbers above are from `moonshine-voice
0.1.0`.

**Trade-off vs whisper.cpp (the architectural angle):**
- whisper.cpp invokes a separate binary subprocess per inference.
  Hard timeout is straightforward (subprocess.run with `timeout=`).
  If whisper.cpp hangs, the OS reaps the child. Zero risk of Python-
  memory leak through repeated runs.
- faster-whisper runs in-process. Hard timeout requires either
  threading (with kill via `_thread.interrupt_main()` — messy) or
  subprocess-wrapping the Python invocation. We'd need to match the
  OCR/VLM worker pattern (multiprocessing.Process + Queue) for
  parity with the existing safety story.
- Moonshine `Transcriber` is a Python-wrapped C++ library; in-process
  with native code under the hood. Same Python-side timeout issue as
  faster-whisper, plus a less battle-tested project (younger than
  whisper.cpp).

Sample transcripts (ad_cta_strong.wav, real text: "Call now! 1-800-555-1234. Save up to 50 percent..."):
- whisper.cpp tiny: `"Call now 85551234. Same up to 50%. Available now on our website..."`
- faster-whisper tiny: `"Call now, 1-800-555-1234  Same up to 50%  Available now at our website..."` ← clean toll-free
- moonshine tiny: `"Cold power. 1800 555 1234 Same up to 50%..."` ← "Cold power" hallucination from "Call now"
- moonshine small-streaming: `"Call now. 1800-555-1234. Save up to 50%  Limited time only."`
- moonshine medium-streaming: `"Call now. 18551234 Save up to 50 percent Available now at our website..."` ← best

Memory: tiny.en model + ring buffer + ONNX/CT2 runtime ≈ 200-300 MB
depending on engine. Plenty of headroom (~12 GB free).

3× real-time on 3 threads (current whisper.cpp) → 2-second inference
cadence has 50%+ idle margin. faster-whisper at 1.14s/5s-window would
push that to ~75% idle. Either way, no audio backpressure concern.

**Recommendation**: faster-whisper tiny.en is a credible upgrade path
(25% faster, slightly better quality, same accuracy on this corpus)
but the swap requires migrating to a Python-subprocess worker pattern
to preserve the hard-timeout safety guarantee. Defer the engine swap
until we've validated real-world TV audio for ~24h on the current
whisper.cpp build. The keyword module is engine-agnostic, so the
future swap is a localized change in `src/asr.py` only.

## Keyword set design (`src/asr_keywords.py`)

Whisper-tiny mistranscribes much like OCR mis-reads — drops syllables,
mangles uncommon words, hallucinates short phrases on silence. The
keyword set accommodates this:

- **Multiple variants per phrase**: `available now` also matches
  `vailable now`, `a vailable now`. Tiny.en regularly drops unstressed
  syllables.
- **Phrase-level matching** (not substring): `now` does not match
  everywhere; `available now` is a full phrase.
- **Regex shape matchers** for prices, URLs, phone numbers: structurally
  stable across transcription noise.
- **Exclusion list**: show-content phrasings that incidentally use
  keywords (`available on netflix this friday`, `subscribe to my
  channel`, `previously on`). These take priority and produce 0 hits
  regardless of any markers also present.
- **Tightened price regex**: `$X` alone is NOT a marker (show characters
  mention bare dollar amounts; whisper renders "fifty dollars" as
  "$15"). Only `$X.XX` with cents, `only $X`, `save $X`, `starting at
  $X`, "X dollars and Y cents" — contextual prices.
- **Minimum-content gate**: transcripts with <3 alpha words score 0
  (filters whisper hallucinations on silence like "you" / "thank you").

If tiny.en quality proves insufficient, swap the model via
`MINUS_WHISPER_MODEL=ggml-base.en.bin` — the keyword module is
backend-agnostic, no code change needed. See task #22 for the
faster-whisper / Moonshine evaluation.

## Control corpus

`tests/asr_corpus/` — 10 espeak-ng synthesized samples spanning ad copy
(pharma, strong CTA, subtle, price-focused, streaming promo) and
negatives (show dialog, money-mention, Netflix promo, YouTube creator,
silence). Each sample has an `expected_min_hits` ground-truth value;
`bench.py` validates the keyword module + transcription engine against
those expectations and writes `BENCH_RESULTS.json` for the architecture
log.

Run:
```
python3 tests/asr_corpus/bench.py
```

## Testing

`tests/test_asr.py` — 44 tests covering:

- **Keyword module**: ad-copy scores, mistranscription resilience,
  exclusion list overrides, whisper-hallucination filtering.
- **ASRManager state machine**: verdict() three-state output, rolling
  window aging, graceful degradation when ASR is disabled/missing.
- **AudioASRTap ring buffer**: write correctness, wraparound, snapshot
  atomicity, concurrent write+snapshot.
- **Pipeline shape**: playback branch byte-identical with/without tap;
  tee + appsink only present with tap; tap branch is leaky; tap
  resamples to 16kHz mono.
- **Audio recovery survival**: `_init_pipeline` re-attaches the tap on
  pipeline restart (HDMI-RX sleep/wake survives); watchdog still finds
  `audioqueue`; mute element `vol` still present; ALSA zombie detection
  intact.
- **Decision-engine integration**: ASR veto suppresses VLM-alone start;
  ASR unknown lets VLM fire alone; ASR confirm upgrades source label to
  `vlm+asr`; OCR-driven blocks unaffected.

End-to-end live test runs as part of `tests/asr_corpus/bench.py` which
invokes the real whisper.cpp binary on synthesized audio.

## Known limitations

- **Music-heavy ads** with no spoken copy (pure jingle): no transcript
  markers → ASR returns `unknown`, VLM fires alone (current behaviour
  preserved).
- **Foreign-language content**: tiny.en is English-only. Spanish ads
  produce 0-marker transcripts → ASR `unknown` or `veto` (false veto).
  Spanish support is deferred — see task #22.
- **Multi-speaker scenes** with overlapping dialogue: whisper-tiny
  transcript quality degrades, marker precision drops. Keyword set is
  designed to err on the side of `unknown` (not falsely confirm).
- **Whisper warm-up**: the FIRST inference after a model-load takes
  ~1.5s longer than subsequent calls. The ASR thread sleeps 5s after
  start before the first snapshot, so this only delays the first
  verdict — never blocks the audio pipeline.
