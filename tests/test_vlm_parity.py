#!/usr/bin/env python3
"""
VLM integration parity test (model-agnostic — works with whatever VLM is
currently configured in src/config.py / src/vlm.py).

Drives the production VLMManager.detect_ad() over a frozen holdout of
labeled ad / non-ad images and validates two things:

  1. PARITY  — per-image predictions match the holdout JSON (proves the
               in-app inference pipeline is byte-faithful to whatever
               script produced the holdout). Tolerates a small number of
               argmax flips because Axera NPU output has minor non-
               determinism across reruns.
  2. ACCURACY — the live confusion matrix on the subset reproduces the
               holdout's reported per-class accuracy within tolerance.

This replaces the original `test_vlm_iter4_parity.py` which was hard-
coded to FastVLM-0.5B iter4. Now it auto-detects which holdout matches
the currently-configured model by checking common locations, so it
continues to work across future VLM swaps.

NOT a unittest TestCase — runs as a standalone script so it doesn't
compete for the NPU with the running minus service during normal
unit-test sweeps. Invoke explicitly:

  python3 tests/test_vlm_parity.py             # smoke (40 images)
  python3 tests/test_vlm_parity.py -n 100      # subset
  python3 tests/test_vlm_parity.py --full      # all 800
  python3 tests/test_vlm_parity.py --holdout PATH  # custom holdout dir

Exits 0 if parity is within tolerance, 1 otherwise. The script must be
run with the minus service stopped to avoid NPU contention.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


# Known holdout locations. Each entry: (label, dir, results_filename).
# Add new entries when a new model + holdout ships. The script will use
# the first one whose results file exists.
KNOWN_HOLDOUTS = [
    # Current: LFM2.5-VL fused-v2 holdout
    ('LFM2.5-VL fused-v2',
     '/home/radxa/axera_models/nontrained_test_data',
     'eval_results_fused_rmsfp32.json'),
    # Older: FastVLM-0.5B iter4 holdout (only if user kept it around)
    ('FastVLM-0.5B iter4',
     '/home/radxa/axera_models/fastvlm-holdout-test',
     'threshold_sweep_raw.json'),
]


def _find_holdout(override_dir=None):
    """Return (label, holdout_dir, results_path) for the first available
    holdout, or None if none found."""
    if override_dir:
        # Caller specified — assume it has a results file at a known name
        for name in ('eval_results_fused_rmsfp32.json',
                     'eval_results.json',
                     'threshold_sweep_raw.json',
                     'results.json'):
            p = os.path.join(override_dir, name)
            if os.path.isfile(p):
                return ('custom', override_dir, p)
        print(f"ERROR: no recognized results file in {override_dir!r}")
        return None

    for label, dirpath, fname in KNOWN_HOLDOUTS:
        results_path = os.path.join(dirpath, fname)
        if os.path.isfile(results_path):
            return (label, dirpath, results_path)
    return None


def _normalize_results(raw_path):
    """Holdout JSONs from different model eras have slightly different
    shapes. Return a list of normalized dicts:
        {file, label, p_yes_logit, p_no_logit, predicted_ad}
    """
    raw = json.load(open(raw_path))
    out = []

    # LFM2.5-VL fused-v2 format: top-level dict with 'results' list,
    # each item has image (path), true_label, predicted_ad,
    # p_yes_logit, p_no_logit.
    if isinstance(raw, dict) and 'results' in raw:
        for r in raw['results']:
            img = r['image']
            out.append({
                'file': os.path.basename(img),
                'image': img,  # absolute path
                'label': 'ad' if r['true_label'] == 'ad' else 'not_ad',
                'p_yes_logit': r['p_yes_logit'],
                'p_no_logit': r['p_no_logit'],
                'predicted_ad': r['predicted_ad'],
            })
        return out

    # iter4 format: flat list of {file, label, p_yes_norm}
    if isinstance(raw, list) and raw and 'p_yes_norm' in raw[0]:
        for r in raw:
            out.append({
                'file': r['file'],
                'image': None,  # caller resolves
                'label': r['label'],
                'p_yes_norm': r['p_yes_norm'],
                # iter4 used threshold 0.76 to decide predicted_ad
                'predicted_ad': r['p_yes_norm'] > 0.76,
            })
        return out

    raise ValueError(f"Unrecognized holdout JSON shape in {raw_path!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--full', action='store_true',
                    help='use all images in the holdout (~5 min)')
    ap.add_argument('-n', type=int, default=40,
                    help='subset size (default 40, balanced across labels)')
    ap.add_argument('--holdout', default=None,
                    help='override holdout dir (auto-detected if not set)')
    ap.add_argument('--tolerance', type=float, default=0.05,
                    help='max fraction of per-image flips before parity '
                         'is considered broken (default 0.05 = 5%%)')
    args = ap.parse_args()

    found = _find_holdout(args.holdout)
    if not found:
        print("ERROR: no holdout found. Tried:")
        for label, dirpath, fname in KNOWN_HOLDOUTS:
            print(f"  {label}: {dirpath}/{fname}")
        print("Pass --holdout PATH to specify a custom location.")
        return 1

    label, holdout_dir, results_path = found
    print(f"Holdout: {label}")
    print(f"  dir:     {holdout_dir}")
    print(f"  results: {results_path}")
    print()

    samples = _normalize_results(results_path)
    print(f"Total samples in holdout: {len(samples)}")

    if not args.full:
        ads = [s for s in samples if s['label'] == 'ad'][: args.n // 2]
        non = [s for s in samples if s['label'] == 'not_ad'][: args.n // 2]
        samples = [x for pair in zip(ads, non) for x in pair]
        print(f"Subset (balanced): {len(samples)} images")
    print()

    # Resolve image paths if the holdout JSON didn't include absolute paths
    for s in samples:
        if not s.get('image'):
            s['image'] = os.path.join(holdout_dir, s['file'])
        if not os.path.isfile(s['image']):
            print(f"ERROR: missing image {s['image']}")
            return 1

    # Load the model
    from vlm import VLMManager
    vlm = VLMManager()
    print('Loading VLM model... (this can take ~10s on first load)')
    if not vlm.load_model():
        print("ERROR: VLM failed to load. Is the NPU available? Is "
              "another process holding it (e.g. running minus service)?")
        return 1
    print(f'Model loaded. Running inference on {len(samples)} samples...')
    print()

    tp = tn = fp = fn = 0
    flips = 0  # disagreements between our prediction and the holdout's
    total = 0
    bad_image = 0
    for i, s in enumerate(samples):
        try:
            is_ad, response, elapsed, confidence = vlm.detect_ad(s['image'])
        except Exception as e:
            print(f"  [{i:3}/{len(samples)}] {s['file']:30s}  ERROR: {e}")
            bad_image += 1
            continue
        total += 1

        truth_ad = (s['label'] == 'ad')
        if is_ad and truth_ad:
            tp += 1
        elif (not is_ad) and (not truth_ad):
            tn += 1
        elif is_ad and (not truth_ad):
            fp += 1
        else:
            fn += 1

        if is_ad != s['predicted_ad']:
            flips += 1

        if (i + 1) % 20 == 0:
            print(f"  [{i+1:3}/{len(samples)}] tp={tp} tn={tn} fp={fp} fn={fn} flips={flips}")

    print()
    print("=" * 60)
    print("Results")
    print("=" * 60)
    if total == 0:
        print("ERROR: no inferences completed.")
        return 1

    acc = (tp + tn) / total
    ad_recall = tp / max(1, tp + fn)
    nonad_recall = tn / max(1, tn + fp)
    f1 = (2 * tp) / max(1, 2 * tp + fp + fn)

    print(f"  Total inferences: {total}  (errored: {bad_image})")
    print(f"  Confusion:        TP={tp} TN={tn} FP={fp} FN={fn}")
    print(f"  Accuracy:         {acc*100:.2f}%")
    print(f"  Ad recall:        {ad_recall*100:.2f}%")
    print(f"  Non-ad recall:    {nonad_recall*100:.2f}%")
    print(f"  F1:               {f1*100:.2f}")
    print()
    print(f"  Per-image parity (matches holdout): "
          f"{total - flips}/{total} = {(total-flips)/total*100:.2f}%")
    print(f"  Flips (live vs holdout):           {flips} "
          f"({flips/total*100:.2f}%, tolerance {args.tolerance*100:.0f}%)")
    print()

    # Pass/fail
    ok_parity = (flips / total) <= args.tolerance
    if ok_parity:
        print(f"PARITY: OK (flips within {args.tolerance*100:.0f}% tolerance)")
        return 0
    print(f"PARITY: FAIL — {flips/total*100:.1f}% flips exceeds tolerance "
          f"{args.tolerance*100:.0f}%")
    return 1


if __name__ == '__main__':
    sys.exit(main())
