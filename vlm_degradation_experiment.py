#!/usr/bin/env python3
"""
NPU degradation characterization experiment.

Loads vlm.VLMManager directly (no subprocess), runs inference on a FIXED
input image in a loop, samples Axera NPU telemetry alongside every
inference, writes everything to CSV. Stdout emits only state-transition
events plus a 30s heartbeat (Monitor-friendly).

Goal: characterize the documented "Axera NPU drift to ~15s inferences
after some period of normal operation" and find correlated signals.
"""
import sys
import os
import time
import subprocess
import csv

sys.path.insert(0, '/home/radxa/Minus/src')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')

from vlm import VLMManager

IMAGE_PATH = '/tmp/vlm_test_input.jpg'
LOG_PATH = '/tmp/vlm_experiment.csv'
LOOP_INTERVAL = 1.5      # seconds between inferences (matches detection cadence)
RUN_DURATION = 1800      # 30 minutes max
SLOW_THRESHOLD = 3.0     # latency above which we consider "degraded"
HEARTBEAT_EVERY = 30.0   # seconds between heartbeat prints when state is unchanged


def axcl(args):
    try:
        r = subprocess.run(['axcl-smi', 'info'] + args, capture_output=True, text=True, timeout=2)
        return r.stdout
    except Exception:
        return ''


def get_telemetry():
    out = {'temp_c': -1.0, 'npu_pct': -1.0, 'cmm_kib': -1, 'cmm_remain_kib': -1}
    s = axcl(['--temp'])
    for line in s.splitlines():
        if 'temperature' in line:
            try:
                out['temp_c'] = int(line.split(':')[1].strip()) / 1000.0
            except Exception:
                pass
            break
    s = axcl(['--npu'])
    for line in s.splitlines():
        if 'vnpu-Non' in line or 'vnpu-' in line:
            try:
                v = line.split(':')[1].strip().rstrip('%').rstrip()
                out['npu_pct'] = float(v.split('%')[0])
            except Exception:
                pass
            break
    s = axcl(['--cmm'])
    for line in s.splitlines():
        if 'CMM Used' in line:
            try:
                out['cmm_kib'] = int(line.split(':')[1].strip().split()[0])
            except Exception:
                pass
        elif 'CMM Remain' in line:
            try:
                out['cmm_remain_kib'] = int(line.split(':')[1].strip().split()[0])
            except Exception:
                pass
    return out


def main():
    if not os.path.exists(IMAGE_PATH):
        print(f"FAIL: {IMAGE_PATH} not found", flush=True)
        sys.exit(1)

    print(f"START loading VLM (input={IMAGE_PATH})", flush=True)
    t_load_start = time.time()
    vlm = VLMManager()
    if not vlm.load_model():
        print("FAIL: model load failed", flush=True)
        sys.exit(1)
    print(f"LOADED in {time.time()-t_load_start:.1f}s, running 4 warmup inferences", flush=True)
    for i in range(4):
        is_ad, resp, e, c = vlm.detect_ad(IMAGE_PATH)
        print(f"WARMUP {i+1}/4: lat={e:.2f}s resp=\"{(resp or '')[:40]}\"", flush=True)

    print(f"BEGIN experiment loop ({RUN_DURATION}s max, interval {LOOP_INTERVAL}s, slow_threshold {SLOW_THRESHOLD}s)", flush=True)

    with open(LOG_PATH, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['iter', 't_seconds', 'wall_time', 'latency_s', 'is_ad', 'response',
                    'temp_c', 'npu_pct', 'cmm_used_kib', 'cmm_remain_kib'])
        f.flush()

        t0 = time.time()
        i = 0
        last_state = 'fast'  # 'fast' or 'slow'
        last_heartbeat = 0.0
        slow_run_start = 0.0
        slow_run_max = 0.0
        slow_run_count = 0

        while True:
            elapsed_total = time.time() - t0
            if elapsed_total > RUN_DURATION:
                break

            telem = get_telemetry()
            is_ad, resp, latency, conf = vlm.detect_ad(IMAGE_PATH)
            wall_time = time.strftime('%H:%M:%S', time.localtime())
            resp_short = (resp or '')[:60].replace('\n', ' ').replace(',', ';')

            w.writerow([i, f'{elapsed_total:.1f}', wall_time, f'{latency:.3f}',
                        is_ad, resp_short,
                        telem['temp_c'], telem['npu_pct'],
                        telem['cmm_kib'], telem['cmm_remain_kib']])
            f.flush()

            now_state = 'slow' if latency >= SLOW_THRESHOLD else 'fast'

            # State transition events
            if now_state != last_state:
                if now_state == 'slow':
                    slow_run_start = elapsed_total
                    slow_run_max = latency
                    slow_run_count = 1
                    print(f"DEGRADED at i={i} t={elapsed_total:.1f}s lat={latency:.2f}s "
                          f"temp={telem['temp_c']:.1f}C cmm_used={telem['cmm_kib']}KiB "
                          f"resp=\"{resp_short[:50]}\"", flush=True)
                else:
                    print(f"RECOVERED at i={i} t={elapsed_total:.1f}s lat={latency:.2f}s "
                          f"(slow run was {elapsed_total-slow_run_start:.1f}s, "
                          f"{slow_run_count} samples, max lat {slow_run_max:.2f}s) "
                          f"temp={telem['temp_c']:.1f}C", flush=True)
                last_state = now_state
                last_heartbeat = elapsed_total
            else:
                if now_state == 'slow':
                    slow_run_max = max(slow_run_max, latency)
                    slow_run_count += 1

                if (elapsed_total - last_heartbeat) >= HEARTBEAT_EVERY:
                    if now_state == 'fast':
                        print(f"HEARTBEAT i={i} t={elapsed_total:.1f}s state=fast "
                              f"lat={latency:.2f}s temp={telem['temp_c']:.1f}C "
                              f"cmm_used={telem['cmm_kib']}KiB", flush=True)
                    else:
                        print(f"HEARTBEAT i={i} t={elapsed_total:.1f}s state=SLOW "
                              f"lat={latency:.2f}s max={slow_run_max:.2f}s "
                              f"slow_for={elapsed_total-slow_run_start:.1f}s "
                              f"({slow_run_count} samples) temp={telem['temp_c']:.1f}C", flush=True)
                    last_heartbeat = elapsed_total

            i += 1
            sleep_s = LOOP_INTERVAL - latency
            if sleep_s > 0:
                time.sleep(sleep_s)

    print(f"DONE i={i} elapsed={elapsed_total:.1f}s csv={LOG_PATH}", flush=True)
    vlm.release()


if __name__ == '__main__':
    main()
