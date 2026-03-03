"""
Unit tests for HealthMonitor module.
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestHealthStatus(unittest.TestCase):
    """Test HealthStatus dataclass."""
    
    def test_default_values(self):
        """Test that HealthStatus has sensible defaults."""
        from health import HealthStatus
        status = HealthStatus()
        
        self.assertFalse(status.hdmi_signal)
        self.assertEqual(status.hdmi_resolution, "")
        self.assertFalse(status.ustreamer_alive)
        self.assertFalse(status.ustreamer_responding)
        self.assertEqual(status.last_frame_age, -1)
        self.assertFalse(status.video_pipeline_ok)
        self.assertFalse(status.audio_pipeline_ok)
        self.assertFalse(status.vlm_ready)
        self.assertEqual(status.vlm_consecutive_timeouts, 0)
        self.assertFalse(status.ocr_ready)
        self.assertEqual(status.memory_percent, 0)
        self.assertEqual(status.disk_free_mb, 0)
        self.assertEqual(status.uptime_seconds, 0)
        self.assertEqual(status.output_fps, 0.0)


class TestHealthMonitor(unittest.TestCase):
    """Test HealthMonitor class."""
    
    def test_init(self):
        """Test HealthMonitor initialization."""
        from health import HealthMonitor
        
        # Create a mock Minus instance
        class MockMinus:
            ad_blocker = None
            audio = None
            vlm = None
            ocr = None
        
        mock_minus = MockMinus()
        monitor = HealthMonitor(mock_minus, check_interval=1.0)
        
        self.assertEqual(monitor.check_interval, 1.0)
        self.assertIsNone(monitor._monitor_thread)
        self.assertFalse(monitor._stop_event.is_set())
    
    def test_start_stop(self):
        """Test HealthMonitor start and stop."""
        from health import HealthMonitor
        
        class MockMinus:
            ad_blocker = None
            audio = None
            vlm = None
            ocr = None
        
        mock_minus = MockMinus()
        monitor = HealthMonitor(mock_minus, check_interval=0.1)
        
        # Start should create a thread
        monitor.start()
        self.assertIsNotNone(monitor._monitor_thread)
        self.assertTrue(monitor._monitor_thread.is_alive())
        
        # Stop should terminate the thread
        monitor.stop()
        # Thread may be set to None after stop
        self.assertIsNone(monitor._monitor_thread)


if __name__ == '__main__':
    unittest.main()
