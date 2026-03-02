"""
Tests for VLM (Vision Language Model) module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestVLM(unittest.TestCase):
    """Test cases for VLM module."""

    @patch('src.vlm.axera_llm')
    @patch('src.vlm.cv2')
    @patch('src.vlm.os')
    def test_vlm_init(self, mock_os, mock_cv2, mock_axera):
        """Test VLM initialization."""
        from src.vlm import VLM
        
        mock_os.path.exists.return_value = True
        mock_axera.AxeraLLM = MagicMock()
        
        vlm = VLM()
        self.assertIsNotNone(vlm)
        self.assertFalse(vlm.initialized)
        
    @patch('src.vlm.axera_llm')
    @patch('src.vlm.cv2')
    @patch('src.vlm.os')
    def test_load_model(self, mock_os, mock_cv2, mock_axera):
        """Test model loading."""
        from src.vlm import VLM
        
        mock_os.path.exists.return_value = True
        mock_axera.AxeraLLM = MagicMock()
        mock_axera.AxeraLLM().init.return_value = 0
        
        vlm = VLM()
        result = vlm.load_model()
        
        self.assertTrue(result)
        self.assertTrue(vlm.initialized)
        
    @patch('src.vlm.axera_llm')
    @patch('src.vlm.cv2')
    @patch('src.vlm.os')
    def test_inference(self, mock_os, mock_cv2, mock_axera):
        """Test model inference."""
        from src.vlm import VLM
        
        mock_os.path.exists.return_value = True
        mock_axera.AxeraLLM = MagicMock()
        mock_axera.AxeraLLM().init.return_value = 0
        
        vlm = VLM()
        vlm.load_model()
        
        # Mock inference result
        mock_cv2.resize.return_value = MagicMock()
        mock_cv2.cvtColor.return_value = MagicMock()
        
        result = vlm.inference(b"test_image_data", "What is in this image?")
        self.assertIsNotNone(result)
        
    @patch('src.vlm.axera_llm')
    @patch('src.vlm.cv2')
    @patch('src.vlm.os')
    def test_check_ad_content(self, mock_os, mock_cv2, mock_axera):
        """Test ad content detection."""
        from src.vlm import VLM
        
        mock_os.path.exists.return_value = True
        mock_axera.AxeraLLM = MagicMock()
        mock_axera.AxeraLLM().init.return_value = 0
        
        vlm = VLM()
        vlm.load_model()
        
        # Mock inference that returns ad-related content
        vlm.inference = MagicMock(return_value="This is an advertisement for products")
        
        result = vlm.check_ad_content(b"test_image_data")
        self.assertTrue(result)
        
    @patch('src.vlm.axera_llm')
    @patch('src.vlm.cv2')
    @patch('src.vlm.os')
    def test_release_resources(self, mock_os, mock_cv2, mock_axera):
        """Test resource cleanup."""
        from src.vlm import VLM
        
        mock_os.path.exists.return_value = True
        mock_axera.AxeraLLM = MagicMock()
        mock_axera.AxeraLLM().init.return_value = 0
        
        vlm = VLM()
        vlm.load_model()
        vlm.release_resources()
        
        self.assertFalse(vlm.initialized)
        self.assertIsNone(vlm.model)
        self.assertIsNone(vlm.tokenizer)


if __name__ == '__main__':
    unittest.main()
