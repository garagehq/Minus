"""
iter4 logit-threshold integration parity test.

Drives the production VLMManager.detect_ad() over the frozen 800-image
holdout and checks two things:

  1. PARITY  — our p_yes_norm matches fastvlm-holdout-test/threshold_sweep_raw.json
               (proves the in-app prefill pipeline is byte-faithful to the
               script that calibrated AD_THRESHOLD=0.76).
  2. ACCURACY — confusion matrix at T=0.76 reproduces BENCHMARKS.md
               (iter4: TP=377 TN=381 FP=19 FN=23, F1=94.72).

Usage:
  python3 tests/test_vlm_iter4_parity.py            # smoke: 40 images
  python3 tests/test_vlm_iter4_parity.py --full     # all 800
  python3 tests/test_vlm_iter4_parity.py -n 100
"""
import os
import re
import sys
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np  # noqa: E402

HOLDOUT = '/home/radxa/axera_models/fastvlm-holdout-test'
_P_RE = re.compile(r'p=([0-9.]+)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true', help='all 800 images')
    ap.add_argument('-n', type=int, default=40, help='subset size (default 40)')
    args = ap.parse_args()

    raw = {r['file']: r for r in json.load(open(f'{HOLDOUT}/threshold_sweep_raw.json'))}
    samples = json.load(open(f'{HOLDOUT}/labels.json'))['samples']

    if not args.full:
        # Balanced subset: interleave ads / non-ads, deterministic.
        ads = [s for s in samples if s['label'] == 'ad'][: args.n // 2]
        non = [s for s in samples if s['label'] == 'not_ad'][: args.n // 2]
        samples = [x for pair in zip(ads, non) for x in pair]

    from vlm import VLMManager
    vlm = VLMManager()
    print('Loading iter4 model...', flush=True)
    if not vlm.load_model():
        print('FAIL: model did not load')
        return 1
    print(f'Model ready. T={vlm.AD_THRESHOLD}. Testing {len(samples)} images.\n',
          flush=True)

    diffs, lat = [], []
    tp = tn = fp = fn = 0
    mismatched_class = 0

    for i, s in enumerate(samples):
        path = os.path.join(HOLDOUT, s['file'])
        is_ad, resp, elapsed, conf = vlm.detect_ad(path)

        m = _P_RE.search(resp)
        if not m:
            print(f'  FAIL: unparseable response for {s["file"]}: {resp!r}')
            return 1
        our_norm = float(m.group(1))
        lat.append(elapsed)

        ref = raw.get(s['file'])
        if ref is not None:
            d = abs(our_norm - ref['p_yes_norm'])
            diffs.append(d)
            # A classification flip vs the reference at T=0.76 is the thing
            # that actually matters (tiny score jitter that doesn't cross
            # the threshold is harmless).
            if (our_norm > vlm.AD_THRESHOLD) != (ref['p_yes_norm'] > vlm.AD_THRESHOLD):
                mismatched_class += 1

        truth_ad = s['label'] == 'ad'
        if is_ad and truth_ad:
            tp += 1
        elif not is_ad and not truth_ad:
            tn += 1
        elif is_ad and not truth_ad:
            fp += 1
        else:
            fn += 1

        if (i + 1) % 25 == 0:
            print(f'  [{i+1}/{len(samples)}] '
                  f'mean|Δ|={np.mean(diffs):.4f} '
                  f'avg_lat={np.mean(lat)*1000:.0f}ms', flush=True)

    n = tp + tn + fp + fn
    acc = (tp + tn) / n * 100
    ad_rec = tp / (tp + fn) * 100 if (tp + fn) else 0
    na_rec = tn / (tn + fp) * 100 if (tn + fp) else 0
    prec = tp / (tp + fp) * 100 if (tp + fp) else 0
    f1 = 2 * tp / (2 * tp + fp + fn) * 100 if (2 * tp + fp + fn) else 0

    print('\n' + '=' * 60)
    print(f'PARITY  vs threshold_sweep_raw.json ({len(diffs)} matched)')
    if diffs:
        print(f'  mean|Δ p_yes_norm| = {np.mean(diffs):.5f}')
        print(f'  max |Δ p_yes_norm| = {np.max(diffs):.5f}')
        print(f'  classification flips across T = {mismatched_class}/{len(diffs)}')
    print('-' * 60)
    print(f'ACCURACY @ T={vlm.AD_THRESHOLD}  (n={n})')
    print(f'  TP={tp} TN={tn} FP={fp} FN={fn}')
    print(f'  acc={acc:.2f}%  ad_rec={ad_rec:.2f}%  '
          f'nonad_rec={na_rec:.2f}%  prec={prec:.2f}%  F1={f1:.2f}')
    print(f'  latency: mean={np.mean(lat)*1000:.0f}ms '
          f'p95={np.percentile(lat,95)*1000:.0f}ms')
    print('=' * 60)

    # Pass criteria.
    ok = True
    if diffs and np.mean(diffs) > 0.02:
        print(f'WARN: mean parity drift {np.mean(diffs):.4f} > 0.02')
        ok = False
    if diffs and mismatched_class > max(1, int(0.02 * len(diffs))):
        print(f'WARN: too many classification flips vs reference '
              f'({mismatched_class})')
        ok = False
    if args.full and f1 < 92.0:
        print(f'WARN: F1 {f1:.2f} below 92.0 floor (expected ~94.7)')
        ok = False
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
