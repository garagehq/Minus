#!/usr/bin/env python3
"""
Demo/test mode for Minus detection pipeline.

Runs OCR and VLM detection on existing screenshots without needing HDMI input.
Useful for:
- Testing detection accuracy
- Verifying OCR/VLM are working
- Training data validation
- Debugging false positives/negatives

Usage:
    python3 demo_detection.py                    # Test with random samples
    python3 demo_detection.py --all              # Test all screenshots
    python3 demo_detection.py --ads-only         # Only test ad screenshots
    python3 demo_detection.py --non-ads-only     # Only test non-ad screenshots
    python3 demo_detection.py --image path.jpg   # Test specific image
    python3 demo_detection.py --summary          # Just show accuracy summary
"""

import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

SCREENSHOT_DIR = Path(__file__).parent / 'screenshots'
ADS_DIR = SCREENSHOT_DIR / 'ads'
NON_ADS_DIR = SCREENSHOT_DIR / 'non_ads'


def get_screenshots(ads_only=False, non_ads_only=False, max_count=None, shuffle=True):
    """Get list of screenshot paths with their expected labels."""
    screenshots = []

    if not non_ads_only and ADS_DIR.exists():
        for f in ADS_DIR.glob('*.png'):
            screenshots.append((str(f), True))  # True = is_ad
        for f in ADS_DIR.glob('*.jpg'):
            screenshots.append((str(f), True))

    if not ads_only and NON_ADS_DIR.exists():
        for f in NON_ADS_DIR.glob('*.png'):
            screenshots.append((str(f), False))  # False = not_ad
        for f in NON_ADS_DIR.glob('*.jpg'):
            screenshots.append((str(f), False))

    if shuffle:
        random.shuffle(screenshots)

    if max_count:
        screenshots = screenshots[:max_count]

    return screenshots


def find_ocr_model_paths():
    """Find OCR model paths (copied from minus.py logic)."""
    from config import OCR_MODEL_DIR
    import os

    model_dir = OCR_MODEL_DIR
    if not os.path.exists(model_dir):
        return None, None, None

    det_model = None
    rec_model = None
    dict_path = None

    for f in os.listdir(model_dir):
        if 'det' in f.lower() and f.endswith('.rknn'):
            det_model = os.path.join(model_dir, f)
        elif 'rec' in f.lower() and f.endswith('.rknn'):
            rec_model = os.path.join(model_dir, f)
        elif f.endswith('_dict.txt') or f == 'ppocr_keys_v1.txt':
            dict_path = os.path.join(model_dir, f)

    return det_model, rec_model, dict_path


def test_ocr(image_path):
    """Run OCR on an image and return results."""
    try:
        from ocr import PaddleOCR

        # Initialize OCR if not already done
        if not hasattr(test_ocr, '_ocr'):
            logger.info("Loading OCR models...")
            det_model, rec_model, dict_path = find_ocr_model_paths()
            if not det_model:
                logger.error("OCR models not found")
                return {'is_ad': False, 'error': 'Models not found'}
            test_ocr._ocr = PaddleOCR(det_model, rec_model, dict_path)
            test_ocr._ocr.load_models()
            logger.info("OCR models loaded")

        import cv2

        ocr = test_ocr._ocr
        # Load and process image
        img = cv2.imread(image_path)
        if img is None:
            return {'is_ad': False, 'error': f'Could not load image: {image_path}'}

        # Convert BGR to RGB
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Run OCR
        ocr_results = ocr.ocr(img_rgb)

        # Check for ad keywords
        is_ad, matched, all_texts, is_terminal = ocr.check_ad_keywords(ocr_results)

        return {
            'is_ad': is_ad,
            'matched_keywords': matched,
            'all_texts': all_texts[:5] if all_texts else [],  # First 5 texts
            'is_terminal': is_terminal,
            'latency_ms': 0  # Would need timing wrapper
        }
    except Exception as e:
        logger.error(f"OCR error: {e}")
        return {'is_ad': False, 'error': str(e)}


def test_vlm(image_path):
    """Run VLM on an image and return results."""
    try:
        from vlm import VLMManager

        # Initialize VLM if not already done
        if not hasattr(test_vlm, '_vlm'):
            logger.info("Loading VLM model (this takes ~13 seconds)...")
            test_vlm._vlm = VLMManager()
            if not test_vlm._vlm.load_model():
                logger.error("Failed to load VLM model")
                return {'is_ad': False, 'error': 'Failed to load model'}
            logger.info("VLM model loaded")

        vlm = test_vlm._vlm
        start = time.time()
        is_ad, response, tokens, confidence = vlm.detect_ad(image_path)
        latency = (time.time() - start) * 1000

        return {
            'is_ad': is_ad,
            'response': response,
            'tokens': tokens,
            'confidence': confidence,
            'latency_ms': latency
        }
    except Exception as e:
        logger.error(f"VLM error: {e}")
        return {'is_ad': False, 'error': str(e)}


def run_demo(args):
    """Run the demo detection on screenshots."""
    # Get screenshots to test
    if args.image:
        if not os.path.exists(args.image):
            logger.error(f"Image not found: {args.image}")
            return 1
        screenshots = [(args.image, None)]  # Unknown label
    else:
        screenshots = get_screenshots(
            ads_only=args.ads_only,
            non_ads_only=args.non_ads_only,
            max_count=args.count if not args.all else None
        )

    if not screenshots:
        logger.error("No screenshots found to test")
        return 1

    logger.info(f"Testing {len(screenshots)} screenshots...")
    logger.info(f"  OCR: {'enabled' if not args.no_ocr else 'disabled'}")
    logger.info(f"  VLM: {'enabled' if not args.no_vlm else 'disabled'}")
    print()

    # Track results
    results = {
        'total': len(screenshots),
        'ocr_correct': 0,
        'ocr_wrong': 0,
        'vlm_correct': 0,
        'vlm_wrong': 0,
        'ocr_latency': [],
        'vlm_latency': [],
    }

    for i, (path, expected_is_ad) in enumerate(screenshots, 1):
        filename = os.path.basename(path)
        label = "AD" if expected_is_ad else "NON-AD" if expected_is_ad is not None else "UNKNOWN"

        if not args.summary:
            print(f"[{i}/{len(screenshots)}] {filename} (expected: {label})")

        # Run OCR
        if not args.no_ocr:
            start = time.time()
            ocr_result = test_ocr(path)
            ocr_latency = (time.time() - start) * 1000
            results['ocr_latency'].append(ocr_latency)

            ocr_correct = None
            if expected_is_ad is not None:
                ocr_correct = ocr_result.get('is_ad') == expected_is_ad
                if ocr_correct:
                    results['ocr_correct'] += 1
                else:
                    results['ocr_wrong'] += 1

            if not args.summary:
                status = "✓" if ocr_correct else "✗" if ocr_correct is False else "?"
                matched = ocr_result.get('matched_keywords', [])
                print(f"  OCR: {status} is_ad={ocr_result.get('is_ad')} ({ocr_latency:.0f}ms)")
                if matched:
                    print(f"       keywords: {matched[:3]}")

        # Run VLM
        if not args.no_vlm:
            vlm_result = test_vlm(path)
            if 'latency_ms' in vlm_result:
                results['vlm_latency'].append(vlm_result['latency_ms'])

            vlm_correct = None
            if expected_is_ad is not None:
                vlm_correct = vlm_result.get('is_ad') == expected_is_ad
                if vlm_correct:
                    results['vlm_correct'] += 1
                else:
                    results['vlm_wrong'] += 1

            if not args.summary:
                status = "✓" if vlm_correct else "✗" if vlm_correct is False else "?"
                print(f"  VLM: {status} is_ad={vlm_result.get('is_ad')} conf={vlm_result.get('confidence', 0):.2f} ({vlm_result.get('latency_ms', 0):.0f}ms)")
                if vlm_result.get('response'):
                    print(f"       response: {vlm_result['response'][:60]}...")

        if not args.summary:
            print()

    # Print summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total screenshots tested: {results['total']}")

    if not args.no_ocr:
        total_ocr = results['ocr_correct'] + results['ocr_wrong']
        if total_ocr > 0:
            accuracy = results['ocr_correct'] / total_ocr * 100
            avg_latency = sum(results['ocr_latency']) / len(results['ocr_latency']) if results['ocr_latency'] else 0
            print(f"\nOCR Results:")
            print(f"  Accuracy: {results['ocr_correct']}/{total_ocr} ({accuracy:.1f}%)")
            print(f"  Avg latency: {avg_latency:.0f}ms")

    if not args.no_vlm:
        total_vlm = results['vlm_correct'] + results['vlm_wrong']
        if total_vlm > 0:
            accuracy = results['vlm_correct'] / total_vlm * 100
            avg_latency = sum(results['vlm_latency']) / len(results['vlm_latency']) if results['vlm_latency'] else 0
            print(f"\nVLM Results:")
            print(f"  Accuracy: {results['vlm_correct']}/{total_vlm} ({accuracy:.1f}%)")
            print(f"  Avg latency: {avg_latency:.0f}ms")

    print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Test Minus detection pipeline on existing screenshots'
    )
    parser.add_argument(
        '--all', action='store_true',
        help='Test all screenshots (default: random sample of 10)'
    )
    parser.add_argument(
        '--count', type=int, default=10,
        help='Number of screenshots to test (default: 10)'
    )
    parser.add_argument(
        '--ads-only', action='store_true',
        help='Only test screenshots from ads/ directory'
    )
    parser.add_argument(
        '--non-ads-only', action='store_true',
        help='Only test screenshots from non_ads/ directory'
    )
    parser.add_argument(
        '--image', type=str,
        help='Test a specific image file'
    )
    parser.add_argument(
        '--no-ocr', action='store_true',
        help='Skip OCR detection'
    )
    parser.add_argument(
        '--no-vlm', action='store_true',
        help='Skip VLM detection'
    )
    parser.add_argument(
        '--summary', action='store_true',
        help='Only show summary (no per-image output)'
    )

    args = parser.parse_args()

    if args.no_ocr and args.no_vlm:
        logger.error("Cannot disable both OCR and VLM")
        return 1

    return run_demo(args)


if __name__ == '__main__':
    sys.exit(main())
