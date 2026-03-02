"""
Tests for Health Monitor module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestHealthMonitor(unittest.TestCase):
    """Test cases for Health Monitor."""

    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_health_monitor_init(self, mock_socket, mock_subprocess):
        """Test health monitor initialization."""
        from src.health import HealthMonitor
        
        monitor = HealthMonitor()
        self.assertIsNotNone(monitor)
        self.assertFalse(monitor.running)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_check_ustreamer_health(self, mock_socket, mock_subprocess):
        """Test ustreamer health check."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"running")
        
        monitor = HealthMonitor()
        result = monitor.check_ustreamer_health()
        
        self.assertTrue(result)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_check_hdmi_signal(self, mock_socket, mock_subprocess):
        """Test HDMI signal check."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"signal present")
        
        monitor = HealthMonitor()
        result = monitor.check_hdmi_signal()
        
        self.assertTrue(result)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_check_npu_health(self, mock_socket, mock_subprocess):
        """Test NPU health check."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"NPU operational")
        
        monitor = HealthMonitor()
        result = monitor.check_npu_health()
        
        self.assertTrue(result)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_check_memory_usage(self, mock_socket, mock_subprocess):
        """Test memory usage check."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"memory: 50%")
        
        monitor = HealthMonitor()
        result = monitor.check_memory_usage()
        
        self.assertTrue(result)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_trigger_recovery(self, mock_socket, mock_subprocess):
        """Test recovery trigger."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0)
        
        monitor = HealthMonitor()
        result = monitor.trigger_recovery("ustreamer")
        
        self.assertTrue(result)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_start_monitoring(self, mock_socket, mock_subprocess):
        """Test monitoring start."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"ok")
        
        monitor = HealthMonitor()
        monitor.start_monitoring()
        
        self.assertTrue(monitor.running)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_stop_monitoring(self, mock_socket, mock_subprocess):
        """Test monitoring stop."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"ok")
        
        monitor = HealthMonitor()
        monitor.start_monitoring()
        monitor.stop_monitoring()
        
        self.assertFalse(monitor.running)
        
    @patch('src.health.subprocess')
    @patch('src.health.socket')
    def test_register_callbacks(self, mock_socket, mock_subprocess):
        """Test callback registration."""
        from src.health import HealthMonitor
        
        mock_subprocess.run.return_value = MagicMock(returncode=0, stdout=b"ok")
        
        monitor = HealthMonitor()
        
        def on_failure():
            pass
        
        monitor.on_ad_blocker_failure(on_failure)
        monitor.on_ustreamer_failure(on_failure)
        monitor.on_npu_failure(on_failure)
        monitor.on_hdmi_failure(on_failure)
        monitor.on_memory_critical(on_failure)
        
        self.assertIsNotNone(monitor._on_ad_blocker_failure)
        self.assertIsNotNone(monitor._on_ustreamer_failure)
        self.assertIsNotNone(monitor._on_npu_failure)
        self.assertIsNotNone(monitor._on_hdmi_failure)
        self.assertIsNotNone(monitor._on_memory_critical)


if __name__ == '__main__':
    unittest.main()
