#!/usr/bin/env python3
"""
Real3D - Real-time 2D to 3D conversion for HDMI passthrough.

This module provides SBS (Side-by-Side) 3D output from 2D HDMI input,
similar to XReal's Real 3D feature.

Performance: 30+ FPS at 1080p output using:
- Depth Anything V2 on Axera AX650/AX8850 NPU (~40ms inference)
- Frame skipping (depth every N frames) to maintain FPS
- Temporal smoothing for smooth depth transitions
- Optimized DIBR (Depth Image Based Rendering) synthesis

Features:
- Live HDMI input via ustreamer
- Video file input for testing
- Temporal depth smoothing
- Adjustable 3D strength
- Display output via GStreamer
- Video file output for testing

Usage:
    from real3d import Real3DMode

    # Create and start 3D mode
    real3d = Real3DMode(
        connector_id=215,
        plane_id=72,
        ustreamer_port=9090,
        output_width=1920,
        output_height=1080
    )
    real3d.start()

    # Later...
    real3d.stop()
"""

import os
import cv2
import numpy as np
import time
import threading
import queue
import logging
import urllib.request
from typing import Optional, Tuple, Union
from dataclasses import dataclass, field

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

# Try to import axengine
try:
    import axengine as axe
    AXENGINE_AVAILABLE = True
except ImportError:
    AXENGINE_AVAILABLE = False

logger = logging.getLogger(__name__)

# Default model path
DEFAULT_MODEL_PATH = "/home/radxa/axera_models/Depth-Anything-V2/depth_anything_v2_vits_ax650.axmodel"


@dataclass
class Real3DConfig:
    """Configuration for Real3D mode."""
    # Display settings
    connector_id: int = 215
    plane_id: int = 72
    output_width: int = 1920
    output_height: int = 1080

    # Input source settings
    ustreamer_port: int = 9090
    ustreamer_host: str = "localhost"
    video_file: Optional[str] = None  # If set, use video file instead of ustreamer

    # Model settings
    model_path: str = DEFAULT_MODEL_PATH
    depth_input_size: int = 518  # Model expects 518x518

    # Performance tuning
    skip_depth: int = 3  # Compute depth every N frames (3 = ~29fps, 4 = ~34fps)
    dibr_width: int = 640  # DIBR working resolution
    dibr_height: int = 360

    # Temporal smoothing
    temporal_smoothing: bool = True
    smoothing_factor: float = 0.7  # Higher = more smoothing (0.0-0.95)

    # 3D effect settings
    max_disparity: int = 30  # Maximum pixel shift
    strength: float = 1.0  # 3D effect strength (0.5-2.0)

    # Output settings
    output_to_display: bool = True
    output_to_file: Optional[str] = None  # If set, save to video file


class DepthEstimator:
    """Depth estimation on Axera NPU with temporal smoothing."""

    def __init__(self, model_path: str, input_size: int = 518,
                 temporal_smoothing: bool = True, smoothing_factor: float = 0.7):
        self.model_path = model_path
        self.input_size = input_size
        self.session = None
        self._input_buffer = None
        self._loaded = False

        # Temporal smoothing
        self.temporal_smoothing = temporal_smoothing
        self.smoothing_factor = smoothing_factor
        self._prev_depth = None

    def load(self) -> bool:
        """Load the depth model. Returns True on success."""
        if not AXENGINE_AVAILABLE:
            logger.error("axengine not available - cannot load depth model")
            return False

        if not os.path.exists(self.model_path):
            logger.error(f"Depth model not found: {self.model_path}")
            return False

        try:
            logger.info(f"Loading Depth Anything V2 from {self.model_path}")
            t0 = time.time()
            self.session = axe.InferenceSession(self.model_path)
            self._input_buffer = np.zeros((1, self.input_size, self.input_size, 3), dtype=np.uint8)
            self._loaded = True
            logger.info(f"Depth model loaded in {(time.time()-t0)*1000:.0f}ms")
            return True
        except Exception as e:
            logger.error(f"Failed to load depth model: {e}")
            return False

    def estimate(self, frame_rgb: np.ndarray) -> Optional[np.ndarray]:
        """
        Estimate depth from RGB frame with optional temporal smoothing.

        Args:
            frame_rgb: RGB image (H, W, 3) uint8

        Returns:
            Depth map (518, 518) float32 normalized 0-1, or None on error
        """
        if not self._loaded:
            if not self.load():
                return None

        try:
            # Resize to model input
            cv2.resize(frame_rgb, (self.input_size, self.input_size), dst=self._input_buffer[0])

            # Run inference
            depth_out = self.session.run(None, {"input": self._input_buffer})[0]
            depth = depth_out[0, 0].astype(np.float32)  # (518, 518)

            # Normalize to 0-1
            d_min, d_max = depth.min(), depth.max()
            if d_max - d_min > 1e-6:
                depth = (depth - d_min) / (d_max - d_min)
            else:
                depth = np.zeros_like(depth)

            # Apply temporal smoothing
            if self.temporal_smoothing and self._prev_depth is not None:
                depth = self.smoothing_factor * self._prev_depth + (1 - self.smoothing_factor) * depth

            self._prev_depth = depth.copy()
            return depth

        except Exception as e:
            logger.error(f"Depth estimation failed: {e}")
            return None

    def reset_temporal(self):
        """Reset temporal smoothing state."""
        self._prev_depth = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded


class DIBRSynthesizer:
    """DIBR (Depth Image Based Rendering) stereo synthesis."""

    def __init__(self, work_width: int = 640, work_height: int = 360,
                 max_disparity: int = 30, strength: float = 1.0):
        self.work_width = work_width
        self.work_height = work_height
        self.max_disparity = max_disparity
        self.strength = strength

        # Pre-allocate coordinate maps
        self._map_y = np.arange(work_height, dtype=np.float32).reshape(-1, 1)
        self._map_y = np.broadcast_to(self._map_y, (work_height, work_width)).copy()
        self._base_x = np.arange(work_width, dtype=np.float32).reshape(1, -1)
        self._base_x = np.broadcast_to(self._base_x, (work_height, work_width)).copy()

        # Output buffer
        self._sbs_buffer = None

    def synthesize(self, frame_rgb: np.ndarray, depth: np.ndarray,
                   output_width: int, output_height: int) -> np.ndarray:
        """
        Synthesize SBS 3D from frame and depth map.

        Args:
            frame_rgb: RGB image
            depth: Depth map (any resolution, will be resized)
            output_width: Output width (SBS total width)
            output_height: Output height

        Returns:
            SBS 3D image (output_height, output_width, 3)
        """
        # Resize to working resolution
        img_small = cv2.resize(frame_rgb, (self.work_width, self.work_height))
        depth_small = cv2.resize(depth, (self.work_width, self.work_height))

        # Compute disparity
        disparity = depth_small * self.max_disparity * self.strength

        # Warp for left and right views
        map_x_left = np.clip(self._base_x + disparity, 0, self.work_width - 1).astype(np.float32)
        map_x_right = np.clip(self._base_x - disparity, 0, self.work_width - 1).astype(np.float32)

        left = cv2.remap(img_small, map_x_left, self._map_y, cv2.INTER_LINEAR)
        right = cv2.remap(img_small, map_x_right, self._map_y, cv2.INTER_LINEAR)

        # Scale to output resolution
        half_w = output_width // 2
        left_out = cv2.resize(left, (half_w, output_height))
        right_out = cv2.resize(right, (half_w, output_height))

        # Allocate output if needed
        if self._sbs_buffer is None or self._sbs_buffer.shape != (output_height, output_width, 3):
            self._sbs_buffer = np.empty((output_height, output_width, 3), dtype=np.uint8)

        # Concatenate SBS
        self._sbs_buffer[:, :half_w] = left_out
        self._sbs_buffer[:, half_w:] = right_out

        return self._sbs_buffer


class FrameSource:
    """Abstract frame source interface."""

    def get_frame(self) -> Optional[np.ndarray]:
        """Get next frame as RGB numpy array."""
        raise NotImplementedError

    def start(self):
        pass

    def stop(self):
        pass


class UstreamerSource(FrameSource):
    """Frame source from ustreamer's /snapshot API."""

    def __init__(self, host: str = "localhost", port: int = 9090):
        self.url = f"http://{host}:{port}/snapshot"

    def get_frame(self) -> Optional[np.ndarray]:
        try:
            with urllib.request.urlopen(self.url, timeout=2) as response:
                jpeg_data = response.read()

            img_array = np.frombuffer(jpeg_data, dtype=np.uint8)
            frame_bgr = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

            if frame_bgr is not None:
                return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        except Exception as e:
            logger.warning(f"Frame capture failed: {e}")

        return None


class VideoFileSource(FrameSource):
    """Frame source from video file with looping."""

    def __init__(self, video_path: str, target_fps: float = 30.0):
        self.video_path = video_path
        self.target_fps = target_fps
        self.cap = None
        self._frame = None
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread = None

    def start(self):
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(f"Video source: {self.width}x{self.height}")

        self._running = True
        self._thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self.cap:
            self.cap.release()

    def _playback_loop(self):
        frame_interval = 1.0 / self.target_fps
        last_time = time.time()

        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            with self._frame_lock:
                self._frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            elapsed = time.time() - last_time
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            last_time = time.time()

    def get_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return self._frame.copy() if self._frame is not None else None


class Real3DMode:
    """
    Real-time 2D to 3D conversion mode.

    Captures frames from ustreamer or video file, converts to SBS 3D,
    outputs to display and/or video file.
    """

    def __init__(self, config: Optional[Real3DConfig] = None, **kwargs):
        """
        Initialize Real3D mode.

        Args:
            config: Real3DConfig object, or pass individual params as kwargs
        """
        if config:
            self.config = config
        else:
            self.config = Real3DConfig(**kwargs)

        # Components
        self.depth_estimator = DepthEstimator(
            self.config.model_path,
            self.config.depth_input_size,
            temporal_smoothing=self.config.temporal_smoothing,
            smoothing_factor=self.config.smoothing_factor
        )
        self.dibr = DIBRSynthesizer(
            work_width=self.config.dibr_width,
            work_height=self.config.dibr_height,
            max_disparity=self.config.max_disparity,
            strength=self.config.strength
        )

        # Frame source
        self.frame_source: Optional[FrameSource] = None

        # State
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()

        # Depth caching for frame skipping
        self._cached_depth = None
        self._frame_counter = 0

        # GStreamer display output
        self._pipeline = None
        self._appsrc = None

        # Video file output
        self._video_writer = None

        # Stats
        self._fps = 0.0
        self._frame_count = 0
        self._start_time = 0
        self._stats_lock = threading.Lock()
        self._depth_computed_count = 0

    def _init_frame_source(self) -> bool:
        """Initialize the frame source."""
        if self.config.video_file:
            logger.info(f"Using video file source: {self.config.video_file}")
            self.frame_source = VideoFileSource(self.config.video_file, target_fps=30.0)
        else:
            logger.info(f"Using ustreamer source: {self.config.ustreamer_host}:{self.config.ustreamer_port}")
            self.frame_source = UstreamerSource(
                self.config.ustreamer_host,
                self.config.ustreamer_port
            )
        return True

    def _init_gstreamer(self) -> bool:
        """Initialize GStreamer output pipeline."""
        if not self.config.output_to_display:
            return True

        try:
            Gst.init(None)

            pipeline_str = (
                f"appsrc name=src format=time is-live=true do-timestamp=true "
                f"caps=video/x-raw,format=RGB,width={self.config.output_width},"
                f"height={self.config.output_height},framerate=30/1 ! "
                f"videoconvert ! "
                f"kmssink plane-id={self.config.plane_id} "
                f"connector-id={self.config.connector_id} sync=false"
            )

            logger.debug(f"GStreamer pipeline: {pipeline_str}")
            self._pipeline = Gst.parse_launch(pipeline_str)
            self._appsrc = self._pipeline.get_by_name("src")

            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                logger.error("Failed to start GStreamer pipeline")
                return False

            logger.info("GStreamer output pipeline started")
            return True

        except Exception as e:
            logger.error(f"GStreamer init failed: {e}")
            return False

    def _init_video_output(self) -> bool:
        """Initialize video file output."""
        if not self.config.output_to_file:
            return True

        try:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self._video_writer = cv2.VideoWriter(
                self.config.output_to_file,
                fourcc,
                30.0,
                (self.config.output_width, self.config.output_height)
            )
            logger.info(f"Video output: {self.config.output_to_file}")
            return True
        except Exception as e:
            logger.error(f"Video output init failed: {e}")
            return False

    def _process_frame(self, frame_rgb: np.ndarray) -> Optional[np.ndarray]:
        """Process a single frame to SBS 3D."""
        # Decide if we need new depth
        compute_depth = (
            self._frame_counter % self.config.skip_depth == 0 or
            self._cached_depth is None
        )
        self._frame_counter += 1

        if compute_depth:
            depth = self.depth_estimator.estimate(frame_rgb)
            if depth is not None:
                self._cached_depth = depth
                self._depth_computed_count += 1
            elif self._cached_depth is None:
                return None  # No depth available at all

        # DIBR synthesis
        sbs = self.dibr.synthesize(
            frame_rgb,
            self._cached_depth,
            self.config.output_width,
            self.config.output_height
        )

        return sbs

    def _push_to_display(self, sbs: np.ndarray) -> bool:
        """Push SBS frame to GStreamer display."""
        if self._appsrc is None:
            return True  # Display disabled

        try:
            data = sbs.tobytes()
            buf = Gst.Buffer.new_allocate(None, len(data), None)
            buf.fill(0, data)

            ret = self._appsrc.emit("push-buffer", buf)
            return ret == Gst.FlowReturn.OK

        except Exception as e:
            logger.warning(f"Display push failed: {e}")
            return False

    def _write_to_file(self, sbs: np.ndarray):
        """Write SBS frame to video file."""
        if self._video_writer is None:
            return

        try:
            # Convert RGB to BGR for OpenCV
            sbs_bgr = cv2.cvtColor(sbs, cv2.COLOR_RGB2BGR)
            self._video_writer.write(sbs_bgr)
        except Exception as e:
            logger.warning(f"Video write failed: {e}")

    def _main_loop(self):
        """Main processing loop."""
        logger.info("Real3D main loop started")

        self._frame_count = 0
        self._depth_computed_count = 0
        self._start_time = time.time()
        last_log_time = time.time()

        while not self._stop_event.is_set():
            # Capture frame
            frame = self.frame_source.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            # Process to 3D
            sbs = self._process_frame(frame)
            if sbs is None:
                continue

            # Output
            self._push_to_display(sbs)
            self._write_to_file(sbs)

            # Update stats
            with self._stats_lock:
                self._frame_count += 1
                elapsed = time.time() - self._start_time
                self._fps = self._frame_count / elapsed if elapsed > 0 else 0

            # Log periodically
            if time.time() - last_log_time > 5.0:
                depth_ratio = self._depth_computed_count / self._frame_count if self._frame_count > 0 else 0
                logger.info(f"Real3D: {self._fps:.1f} FPS, {self._frame_count} frames, "
                           f"depth computed {self._depth_computed_count}x ({depth_ratio*100:.0f}%)")
                last_log_time = time.time()

        logger.info("Real3D main loop stopped")

    def start(self) -> bool:
        """Start Real3D mode."""
        if self._running:
            logger.warning("Real3D already running")
            return True

        logger.info("Starting Real3D mode...")
        logger.info(f"  skip_depth={self.config.skip_depth}, smoothing={self.config.temporal_smoothing}")
        logger.info(f"  output: {self.config.output_width}x{self.config.output_height}")

        # Load depth model
        if not self.depth_estimator.load():
            logger.error("Failed to load depth model")
            return False

        # Initialize frame source
        if not self._init_frame_source():
            logger.error("Failed to initialize frame source")
            return False

        # Initialize outputs
        if not self._init_gstreamer():
            logger.error("Failed to initialize display")
            return False

        if not self._init_video_output():
            logger.error("Failed to initialize video output")
            return False

        # Start frame source
        self.frame_source.start()

        # Start main loop
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._main_loop, daemon=True)
        self._thread.start()
        self._running = True

        logger.info("Real3D mode started successfully")
        return True

    def stop(self):
        """Stop Real3D mode."""
        if not self._running:
            return

        logger.info("Stopping Real3D mode...")

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

        if self.frame_source:
            self.frame_source.stop()

        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
            self._appsrc = None

        if self._video_writer:
            self._video_writer.release()
            self._video_writer = None

        self._running = False

        # Final stats
        elapsed = time.time() - self._start_time if self._start_time > 0 else 0
        logger.info(f"Real3D stopped. Total: {self._frame_count} frames in {elapsed:.1f}s, {self._fps:.1f} FPS avg")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def fps(self) -> float:
        with self._stats_lock:
            return self._fps

    def set_strength(self, strength: float):
        """Set 3D effect strength (0.5-2.0)."""
        self.config.strength = max(0.5, min(2.0, strength))
        self.dibr.strength = self.config.strength
        logger.info(f"3D strength set to {self.config.strength}")

    def set_skip_depth(self, skip: int):
        """Set depth skip factor (1-4). Higher = faster but less temporal accuracy."""
        self.config.skip_depth = max(1, min(4, skip))
        logger.info(f"Depth skip set to {self.config.skip_depth}")

    def set_smoothing(self, factor: float):
        """Set temporal smoothing factor (0.0-0.95). Higher = more smoothing."""
        self.config.smoothing_factor = max(0.0, min(0.95, factor))
        self.depth_estimator.smoothing_factor = self.config.smoothing_factor
        logger.info(f"Smoothing factor set to {self.config.smoothing_factor}")


# Convenience function for standalone testing
def main():
    """Standalone test of Real3D mode."""
    import argparse
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description='Real3D - 2D to 3D conversion')
    parser.add_argument('--connector-id', type=int, default=215)
    parser.add_argument('--plane-id', type=int, default=72)
    parser.add_argument('--ustreamer-port', type=int, default=9090)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--strength', type=float, default=1.0)
    parser.add_argument('--skip-depth', type=int, default=3)
    parser.add_argument('--smoothing', type=float, default=0.7)
    parser.add_argument('--video-file', type=str, default=None,
                        help='Use video file instead of ustreamer')
    parser.add_argument('--output-file', type=str, default=None,
                        help='Save output to video file')
    parser.add_argument('--no-display', action='store_true',
                        help='Disable display output')
    parser.add_argument('--max-frames', type=int, default=0,
                        help='Maximum frames to process (0=unlimited)')
    args = parser.parse_args()

    config = Real3DConfig(
        connector_id=args.connector_id,
        plane_id=args.plane_id,
        ustreamer_port=args.ustreamer_port,
        output_width=args.width,
        output_height=args.height,
        strength=args.strength,
        skip_depth=args.skip_depth,
        smoothing_factor=args.smoothing,
        temporal_smoothing=True,
        video_file=args.video_file,
        output_to_file=args.output_file,
        output_to_display=not args.no_display
    )

    real3d = Real3DMode(config)

    # Handle signals
    def signal_handler(sig, frame):
        logger.info("Received signal, stopping...")
        real3d.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start
    if not real3d.start():
        logger.error("Failed to start Real3D mode")
        return 1

    # Run until stopped or max frames reached
    try:
        while real3d.is_running:
            time.sleep(0.5)
            if args.max_frames > 0 and real3d._frame_count >= args.max_frames:
                logger.info(f"Reached max frames ({args.max_frames})")
                break
    except KeyboardInterrupt:
        pass

    real3d.stop()
    return 0


if __name__ == "__main__":
    exit(main())
