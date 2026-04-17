"""
OCR Worker Process - runs OCR in separate process for hard timeout capability.

This allows us to actually KILL stuck OCR inference instead of just timing out.
"""

import os
import sys
import time
import multiprocessing as mp
from multiprocessing import Process, Queue, Event


def _ocr_worker_main(request_queue, response_queue, ready_event, shutdown_event):
    """
    Main function for OCR worker process.

    Loads models once, then processes requests until shutdown.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('OCRWorker')

    try:
        # Import OCR
        sys.path.insert(0, '/home/radxa/Minus/src')
        from ocr import PaddleOCR
        from config import OCR_MODEL_DIR
        from pathlib import Path

        # Find model paths dynamically
        base_path = Path(OCR_MODEL_DIR)
        det_models = list(base_path.glob('ppocrv3_det_*.rknn'))
        rec_models = list(base_path.glob('ppocrv3_rec_*.rknn'))
        dict_file = base_path / 'ppocr_keys_v1.txt'

        if not det_models or not rec_models or not dict_file.exists():
            logger.error(f"[OCRWorker] Models not found in {OCR_MODEL_DIR}")
            return

        det_model = str(det_models[0])
        rec_model = str(rec_models[0])
        dict_path = str(dict_file)

        # Load models
        logger.info("[OCRWorker] Loading models...")
        ocr = PaddleOCR(det_model, rec_model, dict_path)
        if not ocr.load_models():
            logger.error("[OCRWorker] Failed to load models")
            return

        # Warmup inferences to avoid cold-start
        logger.info("[OCRWorker] Running warmup inferences...")
        try:
            import numpy as np
            # Create test images with varying content
            for i in range(2):
                warmup_img = np.random.randint(0, 255, (540, 960, 3), dtype=np.uint8)
                _ = ocr.ocr(warmup_img)
            logger.info("[OCRWorker] Warmup complete (2 inferences)")
        except Exception as e:
            logger.warning(f"[OCRWorker] Warmup failed (non-fatal): {e}")

        logger.info("[OCRWorker] Models loaded, ready for requests")
        ready_event.set()

        # Process requests with keepalive
        last_inference_time = time.time()
        KEEPALIVE_INTERVAL = 20.0  # Run keepalive if idle for 20s

        while not shutdown_event.is_set():
            try:
                # Wait for request with timeout so we can check shutdown and keepalive
                try:
                    request = request_queue.get(timeout=1.0)
                except:
                    # No request - check if we need keepalive
                    if time.time() - last_inference_time > KEEPALIVE_INTERVAL:
                        try:
                            import numpy as np
                            warmup_img = np.random.randint(0, 255, (540, 960, 3), dtype=np.uint8)
                            _ = ocr.ocr(warmup_img)
                            last_inference_time = time.time()
                            logger.debug("[OCRWorker] Keepalive inference completed")
                        except:
                            pass
                    continue

                if request is None:  # Shutdown signal
                    break

                frame_data, request_type = request

                # Convert frame back to numpy array if needed (Queue may serialize as list)
                if isinstance(frame_data, list):
                    frame_rgb = np.array(frame_data, dtype=np.uint8)
                else:
                    frame_rgb = frame_data

                if request_type == 'ocr':
                    result = ocr.ocr(frame_rgb)
                    response_queue.put(('ok', result))
                    last_inference_time = time.time()
                elif request_type == 'check_ad':
                    # OCR + keyword check
                    ocr_results = ocr.ocr(frame_rgb)
                    is_ad, keywords = ocr.check_ad_keywords(ocr_results)
                    response_queue.put(('ok', (is_ad, keywords, ocr_results)))
                    last_inference_time = time.time()
                else:
                    response_queue.put(('error', 'Unknown request type'))

            except Exception as e:
                logger.error(f"[OCRWorker] Error processing request: {e}")
                response_queue.put(('error', str(e)))

        logger.info("[OCRWorker] Shutting down")
        ocr.release()

    except Exception as e:
        import traceback
        print(f"[OCRWorker] Fatal error: {e}")
        traceback.print_exc()


class OCRProcess:
    """
    Manages OCR in a separate process with hard timeout capability.

    If inference takes longer than timeout, the process is KILLED and restarted.
    """

    HARD_TIMEOUT = 1.0  # Kill OCR if it takes longer than this

    def __init__(self):
        self.process = None
        self.request_queue = None
        self.response_queue = None
        self.ready_event = None
        self.shutdown_event = None
        self.is_ready = False
        self._restart_count = 0

    def start(self):
        """Start the OCR worker process."""
        if self.process is not None and self.process.is_alive():
            # Process running - check if ready
            if self.ready_event is not None and self.ready_event.is_set():
                self.is_ready = True
            return self.is_ready

        # Create communication queues
        self.request_queue = Queue()
        self.response_queue = Queue()
        self.ready_event = Event()
        self.shutdown_event = Event()

        # Start worker process
        self.process = Process(
            target=_ocr_worker_main,
            args=(self.request_queue, self.response_queue, self.ready_event, self.shutdown_event),
            daemon=True
        )
        self.process.start()

        # Wait for models to load (up to 30s)
        if self.ready_event.wait(timeout=30.0):
            self.is_ready = True
            return True
        else:
            self.kill()
            return False

    def kill(self):
        """Kill the OCR worker process."""
        if self.process is not None:
            self.shutdown_event.set()
            self.process.terminate()
            self.process.join(timeout=2.0)
            if self.process.is_alive():
                self.process.kill()
            self.process = None
        self.is_ready = False

    def restart(self):
        """Kill and restart the OCR worker."""
        self._restart_count += 1
        self.kill()
        # Clear any stale responses
        if self.response_queue is not None:
            while not self.response_queue.empty():
                try:
                    self.response_queue.get_nowait()
                except:
                    break
        return self.start()

    def ocr(self, frame_rgb):
        """
        Run OCR with hard timeout.

        Returns: OCR results list or empty list on timeout
        """
        if not self.is_ready or self.process is None or not self.process.is_alive():
            if not self.start():
                return []

        start_time = time.time()

        # Send request
        self.request_queue.put((frame_rgb, 'ocr'))

        # Wait for response with hard timeout
        try:
            status, result = self.response_queue.get(timeout=self.HARD_TIMEOUT)
            elapsed = time.time() - start_time

            if status == 'ok':
                return result
            else:
                return []

        except:
            # TIMEOUT - kill the process
            elapsed = time.time() - start_time
            import logging
            logging.getLogger('Minus.OCR').warning(
                f"[OCRProcess] HARD KILL after {elapsed:.1f}s - restarting worker"
            )
            self.restart()
            return []

    def check_ad_keywords(self, frame_rgb):
        """
        Run OCR and check for ad keywords with hard timeout.

        Returns: (is_ad, keywords, ocr_results) or (False, [], []) on timeout
        """
        if not self.is_ready or self.process is None or not self.process.is_alive():
            if not self.start():
                return False, [], []

        start_time = time.time()

        # Send request
        self.request_queue.put((frame_rgb, 'check_ad'))

        # Wait for response with hard timeout
        try:
            status, result = self.response_queue.get(timeout=self.HARD_TIMEOUT)

            if status == 'ok':
                return result
            else:
                return False, [], []

        except:
            # TIMEOUT - kill the process
            elapsed = time.time() - start_time
            import logging
            logging.getLogger('Minus.OCR').warning(
                f"[OCRProcess] HARD KILL after {elapsed:.1f}s - restarting worker"
            )
            self.restart()
            return False, [], []

    def release(self):
        """Release the OCR worker process."""
        self.kill()

    def load_models(self):
        """Compatibility method - starts the worker process."""
        return self.start()

    @property
    def restart_count(self):
        return self._restart_count

    def check_ad_keywords(self, ocr_results):
        """
        Check OCR results for ad-related keywords.
        This runs locally (not in worker) since it's just string matching.

        Returns:
            Tuple of (found_ad, matched_keywords, all_texts, is_terminal)
        """
        import re

        # Ad keyword lists (from PaddleOCR)
        AD_KEYWORDS_EXACT = [
            'skip ad', 'skip ads', 'skip in', 'ad in', 'video will play after ad',
            'shop now', 'learn more', 'sponsored', 'advertisement',
            'download now', 'install now', 'get the app', 'free download',
            'limited time', 'offer ends', 'dont miss', "don't miss",
            'buy now', 'order now', 'sign up', 'subscribe now',
        ]
        AD_KEYWORDS_WORD = [
            'ad', 'ads',
        ]
        AD_EXCLUSIONS = [
            'skip recap', 'skip intro', 'skip credits', 'skip opening',
            'add to', 'add it', 'already added', 'address', 'add new',
            'additionally', 'adaptive', 'advanced', 'advantage',
        ]
        TERMINAL_PATTERNS = [
            r'^\$\s*',
            r'^>\s*',
            r'^#\s*',
            r'def\s+\w+\s*\(',
            r'class\s+\w+',
        ]

        matched = []
        all_texts = []

        for result in ocr_results:
            text = result['text']
            all_texts.append(text)

            text_lower = text.lower()
            text_clean = ''.join(c for c in text_lower if c.isalnum())

            # Check exact phrase keywords
            for keyword in AD_KEYWORDS_EXACT:
                keyword_clean = ''.join(c for c in keyword if c.isalnum())
                if keyword in text_lower or keyword_clean in text_clean:
                    matched.append((keyword, text))
                    break

            # Check word-boundary keywords
            is_excluded = any(excl in text_lower or excl.replace(' ', '') in text_clean
                              for excl in AD_EXCLUSIONS)

            if not is_excluded:
                for keyword in AD_KEYWORDS_WORD:
                    pattern = r'\b' + re.escape(keyword) + r'\b'
                    if re.search(pattern, text_lower):
                        matched.append((keyword, text))
                        break

            # Fuzzy matches for common OCR misreads
            if 'skipad' in text_clean or 'skipads' in text_clean:
                if ('skipad', text) not in matched and ('skipads', text) not in matched:
                    matched.append(('skip ad (fuzzy)', text))

            if 'shopnow' in text_clean or 'shpnow' in text_clean:
                matched.append(('shop now (fuzzy)', text))

            # "Ad 1 of 2" pattern
            if re.search(r'ad\s*\d+\s*of\s*\d+', text_lower) or re.search(r'ad\d+of\d+', text_clean):
                matched.append(('ad X of Y', text))

            # "Ad 10" countdown pattern
            if re.search(r'^ad\s*\d+$', text_lower.strip()):
                matched.append(('ad countdown', text))

            # "Ad | 0:30" timestamp pattern
            if re.search(r'\bad\b', text_lower) and re.search(r'\d:\d{2}', text):
                matched.append(('ad with timestamp', text))

        # Cross-element check
        if not matched and len(all_texts) <= 5:
            combined = ' '.join(all_texts).lower()
            has_ad_word = re.search(r'\bad\b', combined)
            has_timestamp = re.search(r'\d:\d{2}', ' '.join(all_texts))
            if has_ad_word and has_timestamp:
                matched.append(('ad with timestamp (cross-element)', combined[:50]))

        # Check for terminal content
        is_terminal = False
        if all_texts:
            for text in all_texts:
                for pattern in TERMINAL_PATTERNS:
                    if re.match(pattern, text.strip()):
                        is_terminal = True
                        break
                if is_terminal:
                    break

        return len(matched) > 0, matched, all_texts, is_terminal
