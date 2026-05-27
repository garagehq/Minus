# ASR (audio-based ad confirmation)

whisper.cpp tiny.en running on 3 CPU threads, fed from a parallel
`tee` branch of the existing GStreamer audio pipeline, used as a
**confirmation + veto signal** for VLM-alone ad blocking. Does not
trigger blocking alone; does not affect OCR-driven blocking.

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

## Whisper.cpp build

```bash
git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git /home/radxa/whisper.cpp
cd /home/radxa/whisper.cpp
bash ./models/download-ggml-model.sh tiny.en  # ~75 MB; pulls from huggingface.co/ggerganov/whisper.cpp
cmake -B build -DGGML_NATIVE=ON -DBUILD_SHARED_LIBS=OFF
cmake --build build -j4 --config Release
```

The CMake auto-detection picks up `-mcpu=cortex-a76.cortex-a55+crypto+dotprod`
on RK3588, so we get NEON + dotprod kernels without manual flags.

Override paths via env: `MINUS_WHISPER_BIN`, `MINUS_WHISPER_MODEL`.

## Cost on RK3588

Bench: `tests/asr_corpus/bench.py` against 10-sample synthesized corpus.

| Engine | Pass rate | Avg latency / 5s window | Threads |
|---|---|---|---|
| whisper.cpp tiny.en | 10/10 | **1.67 s** | 3 (mixed A76/A55) |
| faster-whisper tiny.en | (not yet installed) | TBD | 3 |
| moonshine tiny | (not yet installed) | TBD | 3 |

3× real-time on 3 threads → 2-second inference cadence has 50%+ idle
margin. Negligible impact on OCR (RK3588 NPU) and VLM (Axera NPU),
which use different compute resources. Memory: tiny.en model ~75 MB +
ring buffer ~256 KB.

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
