"""
Unit tests for OCR module.
"""

import unittest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestOCRManager(unittest.TestCase):
    """Test OCRManager class."""
    
    def test_init(self):
        """Test OCRManager initialization."""
        from ocr import OCRManager
        
        ocr = OCRManager()
        
        self.assertFalse(ocr.initialized)
        self.assertIsNone(ocr.det_rknn)
        self.assertIsNone(ocr.rec_rknn)
        self.assertIsNone(ocr.cls_rknn)
        self.assertEqual(ocr.keywords, [])
        self.assertEqual(ocr.ad_keywords, [])
        self.assertEqual(ocr.ad_score_threshold, 0.5)
        self.assertEqual(ocr.min_text_length, 20)
    
    def test_load_keywords(self):
        """Test keyword loading."""
        from ocr import OCRManager
        
        ocr = OCRManager()
        
        # Test with custom keywords
        ocr.load_keywords(['buy', 'click', 'subscribe'])
        self.assertEqual(ocr.keywords, ['buy', 'click', 'subscribe'])
        
        # Test with empty keywords
        ocr.load_keywords([])
        self.assertEqual(ocr.keywords, [])
    
    def test_load_ad_keywords(self):
        """Test ad keyword loading."""
        from ocr import OCRManager
        
        ocr = OCRManager()
        
        # Test with custom ad keywords
        ocr.load_ad_keywords(['ad', 'promo', 'sale'])
        self.assertEqual(ocr.ad_keywords, ['ad', 'promo', 'sale'])
        
        # Test with empty keywords
        ocr.load_ad_keywords([])
        self.assertEqual(ocr.ad_keywords, [])


if __name__ == '__main__':
    unittest.main()
