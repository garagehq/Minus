#!/usr/bin/env python3
"""
Test whether the slow/descriptive response is image-dependent or systemic.
Loads VLM once, runs detect_ad on a variety of images, prints latency + full response.
"""
import sys, os, time
sys.path.insert(0, '/home/radxa/Minus/src')
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')
from vlm import VLMManager

IMAGES = [
    '/tmp/vlm_test_input.jpg',
    '/tmp/loop_check_after2.jpg',
    '/tmp/loop_check_after.jpg',
    '/home/radxa/Minus/screenshots/ads/ad_20260401_204639_406_0001.png',
    '/home/radxa/Minus/screenshots/ads/ad_20260401_204644_585_0002.png',
]

# Synthetic black image
import numpy as np
from PIL import Image
black = '/tmp/vlm_black.jpg'
Image.fromarray(np.zeros((512, 512, 3), dtype=np.uint8)).save(black, quality=80)
IMAGES.append(black)
noise = '/tmp/vlm_noise.jpg'
Image.fromarray(np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8)).save(noise, quality=80)
IMAGES.append(noise)

print("loading model...", flush=True)
t0 = time.time()
vlm = VLMManager()
vlm.load_model()
print(f"loaded in {time.time()-t0:.1f}s\n", flush=True)

for img in IMAGES:
    if not os.path.exists(img):
        print(f"SKIP missing {img}")
        continue
    is_ad, resp, e, c = vlm.detect_ad(img)
    short = (resp or '').replace('\n', ' ')[:100]
    print(f"\n=== {os.path.basename(img)} ===", flush=True)
    print(f"  lat: {e:.2f}s  is_ad: {is_ad}  conf: {c}", flush=True)
    print(f"  resp: \"{short}\"", flush=True)

vlm.release()
