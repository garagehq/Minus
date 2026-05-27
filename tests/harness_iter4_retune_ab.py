"""
A/B wrapper around block_latency_harness.py to validate the iter4
decision-engine retune.

iter4 has near-perfect per-frame separation on real video (clean
content p_yes≈0.05, ad text p_yes≈0.85; holdout non-ad recall 95.25%,
ad recall 94.25%) and ~0.33s deterministic latency. The anti-waffle
sliding window (vlm_min_decisions=4, vlm_start_agreement=0.90,
VLM_INTERVAL modelled at 2.0s) was sized for the 1.5B's ~36% home-screen
false-positive rate and ~1s latency. This runs round5 (VLM state machine,
injected verdicts — measures pure window dynamics), round7 (real VLM on
clean content — false-positive safety) and round6 (phantom re-block
regression) under a relaxed param set so we only adopt changes the rig
proves safe.

Usage:
  python3 tests/harness_iter4_retune_ab.py CURRENT   # baseline params
  python3 tests/harness_iter4_retune_ab.py NEW        # relaxed params
"""
import sys
import time
import threading

sys.path.insert(0, 'src')
import block_latency_harness as H  # noqa: E402

# Relaxed set — only params the harness BlockEngine actually models, so
# every change here is empirically validated by this rig. (vlm_min_state_
# duration / cooldown is NOT modelled by the harness, so it is deliberately
# left at the production default — changing an un-testable param would
# violate the project's test-before-push rule.)
# VLM_INTERVAL_S is modelled at iter4's real cadence (~0.33s infer + 0.5s
# loop sleep ≈ 0.85s; 1.0 is the conservative round number).
NEW = {
    'VLM_INTERVAL_S': 1.0,        # was 2.0 — iter4 real cadence
    'vlm_min_decisions': 3,       # was 4  — per-frame signal is decisive now
    'vlm_start_agreement': 0.80,  # was 0.90 — 0.90 was a 1.5B-FP band-aid
}


def main():
    variant = (sys.argv[1] if len(sys.argv) > 1 else 'CURRENT').upper()
    if variant == 'NEW':
        H.PARAMS.update(NEW)
    print(f"=== iter4 retune A/B — variant={variant} ===")
    _show = ('VLM_INTERVAL_S', 'vlm_min_decisions', 'vlm_start_agreement',
             'VLM_STOP_THRESHOLD', 'vlm_stop_agreement',
             'vlm_hysteresis_boost', 'vlm_history_window')
    print("PARAMS:", {k: H.PARAMS[k] for k in _show if k in H.PARAMS})

    harness = H.Harness(H.PARAMS)
    harness.start()
    runner = threading.Thread(target=harness.run, daemon=True)
    runner.start()
    time.sleep(2)
    try:
        H.run_round5(harness)
        H.run_round7(harness)
        H.run_round6(harness, params_label=variant)
    finally:
        harness.stop()
        print("\n=== A/B RUN COMPLETE ===")


if __name__ == '__main__':
    main()
