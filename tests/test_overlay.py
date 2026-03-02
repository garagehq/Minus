"""
Tests for Notification Overlay module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestNotificationOverlay(unittest.TestCase):
    """Test cases for Notification Overlay."""

    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_overlay_init(self, mock_os, mock_time, mock_ustreamer):
        """Test overlay initialization."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        
        overlay = NotificationOverlay()
        self.assertIsNotNone(overlay)
        self.assertFalse(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_show_notification(self, mock_os, mock_time, mock_ustreamer):
        """Test notification display."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_notification("Test notification")
        
        self.assertTrue(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_show_ad_detected(self, mock_os, mock_time, mock_ustreamer):
        """Test ad detected notification."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_ad_detected()
        
        self.assertTrue(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_show_ad_blocked(self, mock_os, mock_time, mock_ustreamer):
        """Test ad blocked notification."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_ad_blocked()
        
        self.assertTrue(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_show_skipped(self, mock_os, mock_time, mock_ustreamer):
        """Test setup skipped notification."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_skipped()
        
        self.assertTrue(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_hide_notification(self, mock_os, mock_time, mock_ustreamer):
        """Test notification hide."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_notification("Test")
        overlay.hide_notification()
        
        self.assertFalse(overlay.is_active)
        
    @patch('src.overlay.ustreamer')
    @patch('src.overlay.time')
    @patch('src.overlay.os')
    def test_destroy(self, mock_os, mock_time, mock_ustreamer):
        """Test resource cleanup."""
        from src.overlay import NotificationOverlay
        
        mock_os.path.exists.return_value = True
        mock_ustreamer.UStreamer = MagicMock()
        mock_ustreamer.UStreamer().overlay_text.return_value = True
        
        overlay = NotificationOverlay()
        overlay.show_notification("Test")
        overlay.destroy()
        
        self.assertFalse(overlay.is_active)
        self.assertIsNone(overlay.ustreamer)


if __name__ == '__main__':
    unittest.main()
