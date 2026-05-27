#!/usr/bin/env python3
"""Run the ASR corpus through each available engine and report results.

Engines tested (when available):
  - whisper.cpp tiny.en   (always available — bundled in Minus)
  - faster-whisper tiny.en (if pip-installed)
  - moonshine tiny         (if pip-installed; experimental)

For each (engine, sample) pair we record:
  - transcript (truncated)
  - marker hits (using src/asr_keywords.count_marker_hits)
  - inference time (wall clock)
  - peak RSS (rough; via /proc/self/status)

Then we cross-check against CORPUS.json's expected_min_hits to print a
pass/fail summary.

This is the per-engine quality + speed benchmark referenced in the
architecture log. Re-run after any keyword-set change or model swap.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / 'src'))

from asr_keywords import count_marker_hits, explain_hits

WHISPER_BIN = '/home/radxa/whisper.cpp/build/bin/whisper-cli'
WHISPER_MODEL = '/home/radxa/whisper.cpp/models/ggml-tiny.en.bin'

ENGINES = {}


def _engine_whisper_cpp(wav_path):
    """Run whisper.cpp tiny.en with 3 threads (matches production config)."""
    start = time.time()
    res = subprocess.run(
        [WHISPER_BIN, '-m', WHISPER_MODEL, '-f', wav_path, '-t', '3', '-np', '-nt', '-l', 'en'],
        capture_output=True, text=True, timeout=10,
    )
    return (res.stdout or '').strip(), time.time() - start


if os.path.isfile(WHISPER_BIN) and os.path.isfile(WHISPER_MODEL):
    ENGINES['whisper.cpp tiny.en'] = _engine_whisper_cpp


def _engine_faster_whisper(wav_path):
    """faster-whisper tiny.en (CTranslate2-based). Loaded lazily."""
    global _fw_model
    try:
        _fw_model
    except NameError:
        from faster_whisper import WhisperModel
        _fw_model = WhisperModel('tiny.en', device='cpu', compute_type='int8', cpu_threads=3)
    start = time.time()
    segments, _info = _fw_model.transcribe(wav_path, beam_size=1, language='en')
    text = ' '.join(s.text for s in segments).strip()
    return text, time.time() - start


try:
    import faster_whisper  # noqa: F401
    ENGINES['faster-whisper tiny.en'] = _engine_faster_whisper
except ImportError:
    pass


def _engine_moonshine(wav_path):
    """Moonshine tiny. Loaded lazily."""
    global _moonshine_model
    try:
        _moonshine_model
    except NameError:
        import moonshine
        _moonshine_model = moonshine.load_model('moonshine/tiny')
    import wave
    import numpy as np
    with wave.open(wav_path, 'rb') as wf:
        n = wf.getnframes()
        data = wf.readframes(n)
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    start = time.time()
    result = _moonshine_model(audio)
    return str(result).strip(), time.time() - start


try:
    import moonshine  # noqa: F401
    ENGINES['moonshine tiny'] = _engine_moonshine
except ImportError:
    pass


def _peak_rss_kib():
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmHWM:'):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def main():
    corpus = json.load(open(HERE / 'CORPUS.json'))
    print(f"\nEngines available: {list(ENGINES.keys()) or '(none)'}\n")
    if not ENGINES:
        print("No engines available — install whisper.cpp/faster-whisper/moonshine to bench.")
        return 1

    per_engine = {name: {'pass': 0, 'fail': 0, 'total_time': 0.0, 'rows': []} for name in ENGINES}

    for name, fn in ENGINES.items():
        print(f"=== {name} ===")
        for sample in corpus:
            wav = HERE / sample['file']
            if not wav.exists():
                continue
            try:
                transcript, elapsed = fn(str(wav))
            except subprocess.TimeoutExpired:
                transcript, elapsed = '<TIMEOUT>', 10.0
            except Exception as e:
                transcript, elapsed = f'<ERROR: {e}>', 0.0

            hits = count_marker_hits(transcript)
            expected_min = sample['expected_min_hits']
            ok = (hits >= expected_min) if expected_min > 0 else (hits == 0)
            per_engine[name]['pass' if ok else 'fail'] += 1
            per_engine[name]['total_time'] += elapsed
            per_engine[name]['rows'].append({
                'file': sample['file'],
                'expected_min': expected_min,
                'transcript': transcript[:80],
                'hits': hits,
                'time_s': round(elapsed, 3),
                'ok': ok,
            })
            status = 'PASS' if ok else 'FAIL'
            print(f"  [{status}] {sample['file']:30s} hits={hits:2d} (need >={expected_min}) "
                  f"{elapsed:5.2f}s  | '{transcript[:70]}'")
        print()

    print("=== summary ===")
    for name, info in per_engine.items():
        total = info['pass'] + info['fail']
        print(f"  {name:30s}  {info['pass']}/{total} pass  "
              f"total={info['total_time']:.2f}s  "
              f"avg={info['total_time']/max(total,1):.2f}s/sample")

    # Save detailed results for the architecture log
    with open(HERE / 'BENCH_RESULTS.json', 'w') as f:
        json.dump(per_engine, f, indent=2)
    print(f"\nDetails written to {HERE / 'BENCH_RESULTS.json'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
