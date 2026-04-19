# VLM NPU Degradation — Investigation Notes

Living document of findings, hypotheses, and experiments around the
documented "Axera NPU drifts into a degraded state where FastVLM-1.5B
inference jumps from ~0.7s to ~12-18s per query and returns descriptive
responses to short-answer prompts."

## Symptom recap

- Healthy: `vlm.detect_ad(image)` returns in ~0.7s with a short answer like `"Yes."` / `"No."`.
- Degraded: same call returns in ~12–18s with a descriptive paragraph (`"No, this is not an advertisement. It appears to be ..."`).
- Survives `vlm_worker` process restart.
- Survives upstream's "deep restart" (kill + 8s NPU-release backoff + start).

## Confirmed facts (from controlled experiments)

| Fact | Evidence |
|------|----------|
| Degradation persists across **full minus shutdown + fresh `python3` process** | Experiment 1 — first warmup inference after fresh load was already 12.56s. |
| Degradation is **not** thermal | NPU temp 55–57°C while degraded. Docs say healthy is also ~70°C. |
| Degradation is **not** memory pressure | Device memory 79% free; CMM 19% used (1.37 GiB / 7.2 GiB). |
| Degradation is **not** input-dependent | Same fixed JPEG used across 25+ inferences, latency stable at 12.5±0.4s. |
| Degraded inference is **deterministic** in latency *and* output text | Repeated runs of the same image give the same latency to ~0.01s and identical response text. |
| Device-side **load average is high (~5.0)** with CPU mostly idle (96.5%) | Implies many processes blocked in D state — likely waiting on NPU/axengine completions. |

## Key open questions

1. Does `axcl-smi reboot` clear the bad state? (heavier hammer)
2. Does `rmmod` + `modprobe` of the host-side axcl driver clear it? (lighter)
3. Is there a softer in-process reset (axengine API, env var, file under `/proc/ax_proc/`) that clears it?
4. What triggers the transition into the bad state in the first place? (we observed it after ~hours of normal operation, then again after a single fresh load — so it can be present at process start)
5. Once cleared, how quickly does it come back under continuous use?

## Experiment 1 — Baseline characterization (DONE)

**Setup:** minus stopped, `vlm.py` loaded directly, fixed input image (`/tmp/vlm_test_input.jpg` — a recent real frame), inference every 1.5s, axcl-smi telemetry sampled every iteration. Script: `vlm_degradation_experiment.py`.

**Result:** Loaded the model fresh — was *already* in the degraded state from the first inference (warmup `1/4: lat=12.56s`). Stayed locked at 12.3–13.2s for the entire 7+ minute observation window (33 samples). No spontaneous recovery. Telemetry was rock-stable: temp 55–57°C, NPU% ~23%, CMM ~1.37 GiB used. CSV: `/tmp/vlm_experiment.csv`.

**Conclusion:** The NPU's bad state is **persistent**, **deterministic**, and **survives full process restart**. Whatever clears it has to act on the device, not the host process.

---

## Experiment 2 — `axcl-smi reboot` (DONE)

**Setup:** Issued `axcl-smi reboot` (with `y` confirmation). dmesg confirmed `device 1: dead!` then `device 1: alive!`. Loaded a fresh `vlm.py`, ran 5 detect_ad calls on the same image.

**Result:** `state=SLOW n=5 min=12.27s avg=12.42s max=12.48s` — identical to the pre-reboot state. Same descriptive response.

**Conclusion:** Whatever the issue is, it's not in the live device firmware state.

## Experiment 3 — Reload host kernel modules (DONE)

**Setup:** `rmmod axcl_host ax_pcie_msg ax_pcie_mmb ax_pcie_p2p_rc ax_pcie_host_dev` then `modprobe` them back in dependency order. Confirmed device responsive (`axcl-smi info --temp` returned 53.9°C). Ran probe.

**Result:** `state=SLOW n=5 min=12.27s avg=12.39s max=12.49s` — identical to baseline.

**Conclusion:** The state is not in the host-side axcl driver either.

## Experiment 4 — Multi-image variation (DONE) — **THE ANSWER**

**Setup:** With a single VLM session, ran detect_ad on 6 different images: 3 real video frames captured from minus, 1 known-ad screenshot from the training set, and 2 synthetic images (solid black 512×512, random noise 512×512).

**Result:**

| Image | Latency | Response (truncated) |
|-------|---------|----------------------|
| `vlm_test_input.jpg` (Times Square scene, the original "stuck" image) | **12.31s** | "No, this is not an advertisement. It appears to be a candid photograph of a busy urban street scene." |
| `loop_check_after2.jpg` (cherry blossom video frame) | 0.81s | "Yes." |
| `loop_check_after.jpg` (paused video frame) | 0.82s | "Yes." |
| `ad_20260401_204639_406_0001.png` (real TikTok-ad screenshot) | **9.67s** | "Yes, this appears to be an advertisement. The image includes a TikTok logo and a URL, which are typi…" |
| `vlm_black.jpg` (solid black 512×512) | 0.73s | "No." |
| `vlm_noise.jpg` (random noise 512×512) | 0.72s | "No." |

**Conclusion — this changes everything:**

There is **no NPU degradation**. The model's per-token decode rate is essentially constant (~0.23s/token in both regimes). What we were calling "slow inference" is the model **choosing to generate a long descriptive answer** for certain images instead of the requested short "Yes."/"No.". The NPU is fine. The driver is fine. The firmware is fine.

For some images (more visually complex / ambiguous?), the model ignores the system prompt's "concisely" instruction and the AD_PROMPT's "Answer Yes or No." instruction, producing a 30–60-token descriptive paragraph that takes 9–12 seconds at the model's normal ~0.23 s/tok rate.

This invalidates the prior reasoning behind several pieces of upstream code:
- The latency-based auto-recovery (P95 > 3s → restart). Restarting the worker doesn't help — the next inference on a similar image is just as long. The "recovery" we saw was the input changing to a simpler frame.
- The DEEP restart with 8 s NPU-release. The NPU doesn't need releasing.
- The `RESPONSE_TIMEOUT` rejection logic that returns confidence 0.2 — at least this one is correct (a slow response *is* an unreliable response, just for the wrong reason).
- My `RESTART_THRESHOLD` bump from 3 → 6 — addressed the wrong cause.

## Real fix — cap `max_new_tokens`

If we never let the model generate more than ~5 tokens, both behaviors collapse:
- "Yes." → still works (1 token + EOS).
- "No, this is not an advertisement..." → truncated to "No, this is" (5 tokens), parsed as "No" by the existing `_is_ad_response` regex (which already keys on the first word).

This caps inference at ~5 × 0.23 s ≈ 1.15 s end-to-end, comfortably under SOFT_TIMEOUT (1.5 s). Eliminates the entire "restart cycle" without touching the NPU.

Status: implementing now in `src/vlm.py`.

## Experiment 5 — `max_new_tokens` cap (DONE)

**Setup:**
- Patched `/home/radxa/axera_models/FastVLM-1.5B/utils/infer_func.py`'s `decode()` to accept a `max_new_tokens` argument that breaks the loop early. (Annotated `# MINUS PATCH:` so the diff is searchable; needs re-applying after a model reinstall.)
- Patched `src/vlm.py` to pass `max_new_tokens=5` from `detect_ad` and `max_new_tokens=8` from `query_image`.
- Changed `detect_ad`'s `RESPONSE_TIMEOUT` handling: instead of short-circuiting to `(False, conf=0.2)` when slow, parse the (now-truncated) response and halve confidence if it ran over `RESPONSE_TIMEOUT`. Slow with the cap means "model wanted to go descriptive but we cut it off" — the parsed verdict is still meaningful, just less certain.
- Re-ran the multi-image variation test.

**Result:**

| Image | Before (lat / verdict / conf) | After (lat / verdict / conf) | Notes |
|-------|--------------------------------|-------------------------------|-------|
| Times Square scene | 12.31s / False / 0.2 | **1.34s** / False / 0.375 | 9× faster; verdict consistent |
| Cherry blossom frame | 0.81s / True / 0.75 | 0.81s / True / 0.75 | unchanged (was already short) |
| Paused video frame | 0.82s / True / 0.75 | 0.84s / True / 0.75 | unchanged |
| TikTok ad screenshot | 9.67s / **False** / 0.2 | **1.33s** / **True** / 0.25 | 7× faster AND **fixes a misclassification** — the parser now sees "Yes," and correctly returns True |
| Solid black 512×512 | 0.73s / False / 0.75 | 0.72s / False / 0.75 | unchanged |
| Random noise 512×512 | 0.72s / False / 0.75 | 0.73s / False / 0.75 | unchanged |

Worst-case latency dropped from 12.3 s to 1.34 s. All cases comfortably under the 1.5 s `SOFT_TIMEOUT`. Hard kills, deep restarts, latency auto-recovery, and the lock fix all become unnecessary in practice for this failure mode (they remain as defense-in-depth for genuine NPU/process pathologies).

**Bonus:** the prior `RESPONSE_TIMEOUT` short-circuit was *masking* a parser bug — every "Yes, this appears to..." answer was being returned as `is_ad=False`. With the cap, we parse the truncated answer correctly.

## Files changed

- `/home/radxa/axera_models/FastVLM-1.5B/utils/infer_func.py` — added `max_new_tokens` parameter and break condition. **External; not under git.** Marked with `# MINUS PATCH:` comments. Re-apply after a model reinstall.
- `src/vlm.py` — pass `max_new_tokens=5` from `detect_ad`, `max_new_tokens=8` from `query_image`; turn `RESPONSE_TIMEOUT` short-circuit into a confidence halver.

