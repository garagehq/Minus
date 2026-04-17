"""
VLM Worker Process - runs VLM in separate process for hard timeout capability.

This allows us to actually KILL stuck VLM inference instead of just timing out.
"""

import os
import sys
import time
import multiprocessing as mp
from multiprocessing import Process, Queue, Event

# Set environment before any imports
os.environ['PYTORCH_MATCHER_LOGLEVEL'] = 'WARNING'
os.environ['TORCH_LOGS'] = '-all'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'


def _vlm_worker_main(request_queue, response_queue, ready_event, shutdown_event):
    """
    Main function for VLM worker process.

    Loads model once, then processes requests until shutdown.
    """
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    logger = logging.getLogger('VLMWorker')

    try:
        # Import VLM manager
        sys.path.insert(0, '/home/radxa/Minus/src')
        from vlm import VLMManager

        # Load model
        logger.info("[VLMWorker] Loading model...")
        vlm = VLMManager()
        if not vlm.load_model():
            logger.error("[VLMWorker] Failed to load model")
            return

        logger.info("[VLMWorker] Model loaded, ready for requests")
        ready_event.set()

        # Process requests
        while not shutdown_event.is_set():
            try:
                # Wait for request with timeout so we can check shutdown
                try:
                    request = request_queue.get(timeout=1.0)
                except:
                    continue

                if request is None:  # Shutdown signal
                    break

                image_path, request_type = request

                if request_type == 'detect_ad':
                    result = vlm.detect_ad(image_path)
                    response_queue.put(('ok', result))
                elif request_type == 'query':
                    # For query_image, request is (image_path, prompt, 'query')
                    pass
                else:
                    response_queue.put(('error', 'Unknown request type'))

            except Exception as e:
                logger.error(f"[VLMWorker] Error processing request: {e}")
                response_queue.put(('error', str(e)))

        logger.info("[VLMWorker] Shutting down")
        vlm.release()

    except Exception as e:
        import traceback
        print(f"[VLMWorker] Fatal error: {e}")
        traceback.print_exc()


class VLMProcess:
    """
    Manages VLM in a separate process with hard timeout capability.

    If inference takes longer than timeout, the process is KILLED and restarted.
    """

    HARD_TIMEOUT = 2.0  # Kill VLM if it takes longer than this

    def __init__(self):
        self.process = None
        self.request_queue = None
        self.response_queue = None
        self.ready_event = None
        self.shutdown_event = None
        self.is_ready = False
        self._restart_count = 0

    def start(self):
        """Start the VLM worker process."""
        if self.process is not None and self.process.is_alive():
            return True

        # Create communication queues
        self.request_queue = Queue()
        self.response_queue = Queue()
        self.ready_event = Event()
        self.shutdown_event = Event()

        # Start worker process
        self.process = Process(
            target=_vlm_worker_main,
            args=(self.request_queue, self.response_queue, self.ready_event, self.shutdown_event),
            daemon=True
        )
        self.process.start()

        # Wait for model to load (up to 30s)
        if self.ready_event.wait(timeout=30.0):
            self.is_ready = True
            return True
        else:
            self.kill()
            return False

    def kill(self):
        """Kill the VLM worker process."""
        if self.process is not None:
            self.shutdown_event.set()
            self.process.terminate()
            self.process.join(timeout=2.0)
            if self.process.is_alive():
                self.process.kill()
            self.process = None
        self.is_ready = False

    def restart(self):
        """Kill and restart the VLM worker."""
        self._restart_count += 1
        self.kill()
        return self.start()

    def detect_ad(self, image_path):
        """
        Run ad detection with hard timeout.

        Returns: (is_ad, response, elapsed, confidence)
        If timeout: returns (False, "KILLED", timeout, 0.0)
        """
        if not self.is_ready or self.process is None or not self.process.is_alive():
            if not self.start():
                return False, "VLM not ready", 0, 0.0

        start_time = time.time()

        # Send request
        self.request_queue.put((image_path, 'detect_ad'))

        # Wait for response with hard timeout
        try:
            status, result = self.response_queue.get(timeout=self.HARD_TIMEOUT)
            elapsed = time.time() - start_time

            if status == 'ok':
                return result
            else:
                return False, f"Error: {result}", elapsed, 0.0

        except:
            # TIMEOUT - kill the process
            elapsed = time.time() - start_time
            import logging
            logging.getLogger('Minus.VLM').warning(
                f"[VLMProcess] HARD KILL after {elapsed:.1f}s - restarting worker"
            )
            self.restart()
            return False, "KILLED", elapsed, 0.0

    def release(self):
        """Release the VLM worker process."""
        self.kill()

    def load_model(self):
        """Compatibility method - starts the worker process."""
        return self.start()

    @property
    def restart_count(self):
        return self._restart_count
