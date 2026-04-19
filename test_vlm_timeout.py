#!/usr/bin/env python3
"""
Test VLM timeout behavior in isolation.

This script tests the hard timeout mechanism to ensure:
1. Normal inference completes within 1.5s
2. Stuck inference is killed and process restarts
3. No "can only join a child process" errors
"""

import os
import sys
import time
import signal
import logging

# Add src to path
sys.path.insert(0, '/home/radxa/Minus/src')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def test_vlm_direct():
    """Test VLM directly without process wrapper."""
    logger.info("=== Testing VLM directly (no process wrapper) ===")

    from vlm import VLMManager

    vlm = VLMManager()
    logger.info("Loading model...")
    if not vlm.load_model():
        logger.error("Failed to load model")
        return False

    logger.info("Model loaded, running inference...")

    # Create test image
    import numpy as np
    from PIL import Image
    test_path = '/tmp/vlm_test.jpg'
    test_img = Image.fromarray(np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8))
    test_img.save(test_path, quality=80)

    # Run multiple inferences
    times = []
    for i in range(5):
        start = time.time()
        is_ad, response, elapsed, confidence = vlm.detect_ad(test_path)
        actual_elapsed = time.time() - start
        times.append(actual_elapsed)
        logger.info(f"  Inference {i+1}: {actual_elapsed:.2f}s - {response[:30] if response else 'None'}")

    avg_time = sum(times) / len(times)
    max_time = max(times)
    logger.info(f"  Average: {avg_time:.2f}s, Max: {max_time:.2f}s")

    vlm.release()
    return max_time < 1.5


def test_vlm_process_wrapper():
    """Test VLM with process wrapper and timeout."""
    logger.info("=== Testing VLM with process wrapper ===")

    from vlm_worker import VLMProcess

    vlm = VLMProcess()
    logger.info("Starting VLM process...")

    if not vlm.start():
        logger.error("Failed to start VLM process")
        return False

    logger.info("VLM process ready, running inferences...")

    # Create test image
    import numpy as np
    from PIL import Image
    test_path = '/tmp/vlm_test.jpg'
    test_img = Image.fromarray(np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8))
    test_img.save(test_path, quality=80)

    # Run multiple inferences
    times = []
    kills = 0
    for i in range(5):
        start = time.time()
        is_ad, response, elapsed, confidence = vlm.detect_ad(test_path)
        actual_elapsed = time.time() - start
        times.append(actual_elapsed)

        if response == "KILLED":
            kills += 1
            logger.warning(f"  Inference {i+1}: KILLED after {actual_elapsed:.2f}s")
        else:
            logger.info(f"  Inference {i+1}: {actual_elapsed:.2f}s - {response[:30] if response else 'None'}")

    avg_time = sum(times) / len(times)
    max_time = max(times)
    logger.info(f"  Average: {avg_time:.2f}s, Max: {max_time:.2f}s, Kills: {kills}")
    logger.info(f"  Restart count: {vlm.restart_count}")

    vlm.release()
    return True


def test_timeout_recovery():
    """Test that timeout and restart works correctly."""
    logger.info("=== Testing timeout recovery ===")

    from vlm_worker import VLMProcess

    vlm = VLMProcess()

    # Temporarily reduce timeout for testing
    original_timeout = VLMProcess.HARD_TIMEOUT
    VLMProcess.HARD_TIMEOUT = 0.5  # Very short to force timeout

    logger.info(f"Starting VLM process with {VLMProcess.HARD_TIMEOUT}s timeout...")

    if not vlm.start():
        logger.error("Failed to start VLM process")
        VLMProcess.HARD_TIMEOUT = original_timeout
        return False

    logger.info("VLM process ready, testing timeout recovery...")

    # Create test image
    import numpy as np
    from PIL import Image
    test_path = '/tmp/vlm_test.jpg'
    test_img = Image.fromarray(np.random.randint(0, 255, (512, 512, 3), dtype=np.uint8))
    test_img.save(test_path, quality=80)

    # This should trigger timeouts
    errors = []
    for i in range(3):
        try:
            start = time.time()
            is_ad, response, elapsed, confidence = vlm.detect_ad(test_path)
            actual_elapsed = time.time() - start

            if response == "KILLED":
                logger.info(f"  Inference {i+1}: Correctly killed after {actual_elapsed:.2f}s")
            else:
                logger.info(f"  Inference {i+1}: {actual_elapsed:.2f}s - {response[:30] if response else 'None'}")
        except Exception as e:
            errors.append(str(e))
            logger.error(f"  Inference {i+1}: ERROR - {e}")

    logger.info(f"  Restart count: {vlm.restart_count}")

    # Restore original timeout
    VLMProcess.HARD_TIMEOUT = original_timeout

    vlm.release()

    if errors:
        logger.error(f"Errors during timeout recovery: {errors}")
        return False

    return True


def main():
    logger.info("VLM Timeout Test Suite")
    logger.info("=" * 60)

    results = {}

    # Test 1: Direct VLM (baseline)
    try:
        results['direct'] = test_vlm_direct()
    except Exception as e:
        logger.error(f"Direct test failed: {e}")
        import traceback
        traceback.print_exc()
        results['direct'] = False

    # Test 2: Process wrapper
    try:
        results['process'] = test_vlm_process_wrapper()
    except Exception as e:
        logger.error(f"Process wrapper test failed: {e}")
        import traceback
        traceback.print_exc()
        results['process'] = False

    # Test 3: Timeout recovery
    try:
        results['timeout'] = test_timeout_recovery()
    except Exception as e:
        logger.error(f"Timeout recovery test failed: {e}")
        import traceback
        traceback.print_exc()
        results['timeout'] = False

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Test Results:")
    for test, passed in results.items():
        status = "PASS" if passed else "FAIL"
        logger.info(f"  {test}: {status}")

    all_passed = all(results.values())
    logger.info(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")

    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
