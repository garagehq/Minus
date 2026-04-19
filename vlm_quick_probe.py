#!/usr/bin/env python3
"""
Quick latency probe: load VLM, run N inferences on a fixed image, print
summary. ~30s end-to-end (model load dominates).

Use for fast before/after comparisons of recovery techniques.
"""
import sys, os, time
sys.path.insert(0, '/home/radxa/Minus/src')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
from vlm import VLMManager

IMAGE = '/tmp/vlm_test_input.jpg'
N = 5

def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'probe'
    t0 = time.time()
    print(f"[{label}] loading model...", flush=True)
    vlm = VLMManager()
    if not vlm.load_model():
        print(f"[{label}] FAIL load")
        sys.exit(1)
    print(f"[{label}] model loaded in {time.time()-t0:.1f}s", flush=True)

    lats = []
    last_resp = ''
    for i in range(N):
        is_ad, resp, e, c = vlm.detect_ad(IMAGE)
        lats.append(e)
        last_resp = (resp or '')[:50].replace('\n', ' ')
        print(f"[{label}] i={i} lat={e:.2f}s resp=\"{last_resp}\"", flush=True)

    avg = sum(lats) / len(lats)
    mx = max(lats)
    mn = min(lats)
    state = 'SLOW' if avg > 3.0 else 'FAST'
    print(f"[{label}] SUMMARY state={state} n={N} min={mn:.2f}s avg={avg:.2f}s max={mx:.2f}s last_resp=\"{last_resp}\"", flush=True)
    vlm.release()

if __name__ == '__main__':
    main()
