"""
Tests for main Minus module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestMinusMain(unittest.TestCase):
    """Test cases for main Minus module."""

    @patch('minus.gst')
    @patch('minus.cv2')
    @patch('minus.os')
    @patch('minus.sys')
    def test_minus_init(self, mock_sys, mock_os, mock_cv2, mock_gst):
        """Test Minus initialization."""
        from minus import Minus
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        minus = Minus()
        self.assertIsNotNone(minus)
        self.assertFalse(minus.running)
        
    @patch('minus.gst')
    @patch('minus.cv2')
    @patch('minus.os')
    @patch('minus.sys')
    def test_run(self, mock_sys, mock_os, mock_cv2, mock_gst):
        """Test Minus run."""
        from minus import Minus
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        minus = Minus()
        minus.run()
        
        self.assertTrue(minus.running)
        
    @patch('minus.gst')
    @patch('minus.cv2')
    @patch('minus.os')
    @patch('minus.sys')
    def test_stop(self, mock_sys, mock_os, mock_cv2, mock_gst):
        """Test Minus stop."""
        from minus import Minus
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        minus = Minus()
        minus.run()
        minus.stop()
        
        self.assertFalse(minus.running)
        
    @patch('minus.gst')
    @patch('minus.cv2')
    @patch('minus.os')
    @patch('minus.sys')
    def test_setup_pipeline(self, mock_sys, mock_os, mock_cv2, mock_gst):
        """Test pipeline setup."""
        from minus import Minus
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        minus = Minus()
        minus.setup_pipeline()
        
        self.assertIsNotNone(minus.pipeline)
        
    @patch('minus.gst')
    @patch('minus.cv2')
    @patch('minus.os')
    @patch('minus.sys')
    def test_handle_signal(self, mock_sys, mock_os, mock_cv2, mock_gst):
        """Test signal handling."""
        from minus import Minus
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        minus = Minus()
        minus.run()
        minus.handle_signal(None, None)
        
        self.assertFalse(minus.running)


if __name__ == '__main__':
    unittest.main()
