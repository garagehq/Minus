"""
Tests for Ad Blocker module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestAdBlocker(unittest.TestCase):
    """Test cases for DRMAdBlocker."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_gst = MagicMock()
        self.mock_cv2 = MagicMock()
        self.mock_os = MagicMock()
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_ad_blocker_init(self, mock_os, mock_cv2, mock_gst):
        """Test AdBlocker initialization."""
        from src.ad_blocker import DRMAdBlocker
        
        # Setup mocks
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        self.assertIsNotNone(blocker)
        self.assertFalse(blocker.is_visible)
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_start_pipeline(self, mock_os, mock_cv2, mock_gst):
        """Test pipeline start."""
        from src.ad_blocker import DRMAdBlocker
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        blocker.start_pipeline()
        
        self.assertIsNotNone(blocker.pipeline)
        self.assertIsNotNone(blocker.selector)
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_stop_pipeline(self, mock_os, mock_cv2, mock_gst):
        """Test pipeline stop."""
        from src.ad_blocker import DRMAdBlocker
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        blocker.start_pipeline()
        blocker.stop_pipeline()
        
        self.assertIsNone(blocker.pipeline)
        self.assertIsNone(blocker.selector)
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_show_overlay(self, mock_os, mock_cv2, mock_gst):
        """Test overlay display."""
        from src.ad_blocker import DRMAdBlocker
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        blocker.start_pipeline()
        blocker.show_overlay("Test overlay")
        
        self.assertTrue(blocker.is_visible)
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_hide_overlay(self, mock_os, mock_cv2, mock_gst):
        """Test overlay hide."""
        from src.ad_blocker import DRMAdBlocker
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        blocker.start_pipeline()
        blocker.show_overlay("Test")
        blocker.hide_overlay()
        
        self.assertFalse(blocker.is_visible)
        
    @patch('src.ad_blocker.gst')
    @patch('src.ad_blocker.cv2')
    @patch('src.ad_blocker.os')
    def test_destroy(self, mock_os, mock_cv2, mock_gst):
        """Test resource cleanup."""
        from src.ad_blocker import DRMAdBlocker
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        blocker = DRMAdBlocker()
        blocker.start_pipeline()
        blocker.destroy()
        
        self.assertIsNone(blocker.pipeline)
        self.assertIsNone(blocker.selector)
        self.assertIsNone(blocker.bus)
        self.assertIsNone(blocker.volume)


if __name__ == '__main__':
    unittest.main()
