"""
Tests for OCR module using PaddleOCR with RKNN NPU.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestOCR(unittest.TestCase):
    """Test cases for PaddleOCR module."""

    @patch('src.ocr.rknn_api')
    @patch('src.ocr.cv2')
    @patch('src.ocr.os')
    def test_ocr_init(self, mock_os, mock_cv2, mock_rknn):
        """Test OCR initialization."""
        from src.ocr import PaddleOCR
        
        mock_os.path.exists.return_value = True
        mock_rknn.RKNN = MagicMock()
        
        ocr = PaddleOCR()
        self.assertIsNotNone(ocr)
        self.assertFalse(ocr.initialized)
        
    @patch('src.ocr.rknn_api')
    @patch('src.ocr.cv2')
    @patch('src.ocr.os')
    def test_load_model(self, mock_os, mock_cv2, mock_rknn):
        """Test model loading."""
        from src.ocr import PaddleOCR
        
        mock_os.path.exists.return_value = True
        mock_rknn.RKNN = MagicMock()
        mock_rknn.RKNN().init.return_value = 0
        
        ocr = PaddleOCR()
        result = ocr.load_model()
        
        self.assertTrue(result)
        self.assertTrue(ocr.initialized)
        
    @patch('src.ocr.rknn_api')
    @patch('src.ocr.cv2')
    @patch('src.ocr.os')
    def test_detect_text(self, mock_os, mock_cv2, mock_rknn):
        """Test text detection."""
        from src.ocr import PaddleOCR
        
        mock_os.path.exists.return_value = True
        mock_rknn.RKNN = MagicMock()
        mock_rknn.RKNN().init.return_value = 0
        
        ocr = PaddleOCR()
        ocr.load_model()
        
        # Mock detection result
        mock_cv2.resize.return_value = MagicMock()
        mock_cv2.cvtColor.return_value = MagicMock()
        
        result = ocr.detect_text(b"test_image_data")
        self.assertIsNotNone(result)
        
    @patch('src.ocr.rknn_api')
    @patch('src.ocr.cv2')
    @patch('src.ocr.os')
    def test_check_ad_keywords(self, mock_os, mock_cv2, mock_rknn):
        """Test ad keyword detection."""
        from src.ocr import PaddleOCR
        
        mock_os.path.exists.return_value = True
        mock_rknn.RKNN = MagicMock()
        mock_rknn.RKNN().init.return_value = 0
        
        ocr = PaddleOCR()
        ocr.load_model()
        
        # Test with ad keywords
        text_with_ads = "Buy now! 50% off! Limited time offer!"
        result = ocr.check_ad_keywords(text_with_ads)
        self.assertTrue(result)
        
        # Test without ad keywords
        text_normal = "This is a regular video content"
        result = ocr.check_ad_keywords(text_normal)
        self.assertFalse(result)
        
    @patch('src.ocr.rknn_api')
    @patch('src.ocr.cv2')
    @patch('src.ocr.os')
    def test_release_resources(self, mock_os, mock_cv2, mock_rknn):
        """Test resource cleanup."""
        from src.ocr import PaddleOCR
        
        mock_os.path.exists.return_value = True
        mock_rknn.RKNN = MagicMock()
        mock_rknn.RKNN().init.return_value = 0
        
        ocr = PaddleOCR()
        ocr.load_model()
        ocr.release_resources()
        
        self.assertFalse(ocr.initialized)
        self.assertIsNone(ocr.det_rknn)
        self.assertIsNone(ocr.rec_rknn)
        self.assertIsNone(ocr.cls_rknn)


if __name__ == '__main__':
    unittest.main()
