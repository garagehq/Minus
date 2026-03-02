"""
Tests for Fire TV Controller module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestFireTVController(unittest.TestCase):
    """Test cases for Fire TV Controller."""

    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_controller_init(self, mock_socket, mock_subprocess):
        """Test controller initialization."""
        from src.fire_tv import FireTVController
        
        controller = FireTVController("192.168.1.100")
        self.assertIsNotNone(controller)
        self.assertEqual(controller.ip_address, "192.168.1.100")
        self.assertFalse(controller.connected)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_connect(self, mock_socket, mock_subprocess):
        """Test connection to Fire TV."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        result = controller.connect()
        
        self.assertTrue(result)
        self.assertTrue(controller.connected)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_disconnect(self, mock_socket, mock_subprocess):
        """Test disconnection."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        controller.disconnect()
        
        self.assertFalse(controller.connected)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_send_adb_command(self, mock_socket, mock_subprocess):
        """Test ADB command execution."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        
        result = controller.send_adb_command("input keyevent 82")
        self.assertIsNotNone(result)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_skip_ad(self, mock_socket, mock_subprocess):
        """Test ad skipping."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        
        result = controller.skip_ad()
        self.assertIsNotNone(result)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_pause_playback(self, mock_socket, mock_subprocess):
        """Test playback control."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        
        result = controller.pause_playback()
        self.assertIsNotNone(result)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_resume_playback(self, mock_socket, mock_subprocess):
        """Test playback resume."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        
        result = controller.resume_playback()
        self.assertIsNotNone(result)
        
    @patch('src.fire_tv.subprocess')
    @patch('src.fire_tv.socket')
    def test_get_device_info(self, mock_socket, mock_subprocess):
        """Test device info retrieval."""
        from src.fire_tv import FireTVController
        
        mock_socket.socket.return_value.connect.return_value = None
        mock_socket.socket.return_value.recv.return_value = b"OK"
        
        controller = FireTVController("192.168.1.100")
        controller.connect()
        
        result = controller.get_device_info()
        self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main()
