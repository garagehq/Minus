#!/usr/bin/env python3
"""Drive the production ASRProcess + ASRManager pipeline end-to-end
against the corpus. Validates that the multiprocessing worker spawn,
queue plumbing, and timeout machinery all work — which the in-process
bench.py doesn't exercise."""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / 'src'))

from asr_worker import ASRProcess
from asr_keywords import count_marker_hits


def main():
    corpus = json.load(open(HERE / 'CORPUS.json'))
    proc = ASRProcess(model_name='tiny.en', cpu_threads=3)
    if not proc.start():
        print('Worker failed to start')
        return 1
    print(f'Worker started (PID {proc.process.pid})\n')

    pass_count = fail_count = 0
    total_t = 0.0
    for sample in corpus:
        wav = str(HERE / sample['file'])
        status, text, lat = proc.transcribe(wav)
        hits = count_marker_hits(text) if status == 'ok' else 0
        expected = sample['expected_min_hits']
        ok = (hits >= expected) if expected > 0 else (hits == 0)
        pass_count += ok
        fail_count += (not ok)
        total_t += lat
        status_str = 'PASS' if ok else 'FAIL'
        print(f'  [{status_str}] {sample["file"]:30s} '
              f'status={status:7s} hits={hits} need>={expected} '
              f'{lat:.2f}s | "{(text or "")[:60]}"')

    print()
    print(f'summary: {pass_count}/{pass_count + fail_count} pass, '
          f'total {total_t:.2f}s, avg {total_t / len(corpus):.2f}s')
    print(f'latency stats: {proc.get_latency_stats()}')

    proc.stop()
    print('Worker stopped cleanly')
    return 0


if __name__ == '__main__':
    sys.exit(main())
