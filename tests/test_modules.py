#!/usr/bin/env python3
"""
Unit tests for Minus modules.

These tests verify the basic functionality of each module
without requiring hardware dependencies.
"""

import sys
import os
import unittest
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))


class TestAdBlocker(unittest.TestCase):
    """Test AdBlocker module."""

    def test_ad_blocker_class_exists(self):
        """Verify AdBlocker class is importable."""
        try:
            from ad_blocker import AdBlocker
            self.assertIsNotNone(AdBlocker)
        except ImportError as e:
            self.skipTest(f"AdBlocker module not available: {e}")


class TestOCR(unittest.TestCase):
    """Test OCR module."""

    def test_ocr_class_exists(self):
        """Verify PaddleOCR class is importable."""
        try:
            from ocr import PaddleOCR
            self.assertIsNotNone(PaddleOCR)
        except ImportError as e:
            self.skipTest(f"OCR module not available: {e}")

    def test_ocr_keyword_lists_exist(self):
        """Verify OCR has expected keyword lists."""
        try:
            from ocr import PaddleOCR
            self.assertTrue(hasattr(PaddleOCR, 'AD_KEYWORDS_EXACT'))
            self.assertTrue(hasattr(PaddleOCR, 'AD_KEYWORDS_WORD'))
            self.assertIsInstance(PaddleOCR.AD_KEYWORDS_EXACT, list)
            self.assertIsInstance(PaddleOCR.AD_KEYWORDS_WORD, list)
        except ImportError:
            self.skipTest("OCR module not available")


class TestVLM(unittest.TestCase):
    """Test VLM module."""

    def test_vlm_class_exists(self):
        """Verify VLMManager class is importable."""
        try:
            from vlm import VLMManager
            self.assertIsNotNone(VLMManager)
        except ImportError as e:
            self.skipTest(f"VLM module not available: {e}")

    def test_vlm_ad_prompt_exists(self):
        """Verify VLM has expected AD_PROMPT."""
        try:
            from vlm import VLMManager
            self.assertTrue(hasattr(VLMManager, 'AD_PROMPT'))
            self.assertIsInstance(VLMManager.AD_PROMPT, str)
        except ImportError:
            self.skipTest("VLM module not available")


class TestOverlay(unittest.TestCase):
    """Test Overlay module."""

    def test_notification_overlay_class_exists(self):
        """Verify NotificationOverlay class is importable."""
        try:
            from overlay import NotificationOverlay
            self.assertIsNotNone(NotificationOverlay)
        except ImportError as e:
            self.skipTest(f"Overlay module not available: {e}")

    def test_fire_tv_notification_class_exists(self):
        """Verify FireTVNotification class is importable."""
        try:
            from overlay import FireTVNotification
            self.assertIsNotNone(FireTVNotification)
        except ImportError:
            self.skipTest("Overlay module not available")

    def test_overlay_positions_defined(self):
        """Verify overlay has expected position constants."""
        try:
            from overlay import NotificationOverlay
            self.assertTrue(hasattr(NotificationOverlay, 'POS_TOP_RIGHT'))
            self.assertTrue(hasattr(NotificationOverlay, 'POS_TOP_LEFT'))
            self.assertTrue(hasattr(NotificationOverlay, 'POS_BOTTOM_RIGHT'))
            self.assertTrue(hasattr(NotificationOverlay, 'POS_BOTTOM_LEFT'))
            self.assertTrue(hasattr(NotificationOverlay, 'POS_CENTER'))
        except ImportError:
            self.skipTest("Overlay module not available")


class TestAudio(unittest.TestCase):
    """Test Audio module."""

    def test_audio_passthrough_class_exists(self):
        """Verify AudioPassthrough class is importable."""
        try:
            from audio import AudioPassthrough
            self.assertIsNotNone(AudioPassthrough)
        except ImportError as e:
            self.skipTest(f"Audio module not available: {e}")


class TestHealth(unittest.TestCase):
    """Test Health module."""

    def test_health_monitor_class_exists(self):
        """Verify HealthMonitor class is importable."""
        try:
            from health import HealthMonitor
            self.assertIsNotNone(HealthMonitor)
        except ImportError as e:
            self.skipTest(f"Health module not available: {e}")


class TestWebUI(unittest.TestCase):
    """Test WebUI module."""

    def test_webui_class_exists(self):
        """Verify WebUI class is importable."""
        try:
            from webui import WebUI
            self.assertIsNotNone(WebUI)
        except ImportError as e:
            self.skipTest(f"WebUI module not available: {e}")


class TestFireTV(unittest.TestCase):
    """Test Fire TV module."""

    def test_fire_tv_controller_class_exists(self):
        """Verify FireTVController class is importable."""
        try:
            from fire_tv import FireTVController
            self.assertIsNotNone(FireTVController)
        except ImportError as e:
            self.skipTest(f"Fire TV module not available: {e}")

    def test_fire_tv_setup_class_exists(self):
        """Verify FireTVSetupManager class is importable."""
        try:
            from fire_tv_setup import FireTVSetupManager
            self.assertIsNotNone(FireTVSetupManager)
        except ImportError:
            self.skipTest("Fire TV module not available")


class TestMinusMain(unittest.TestCase):
    """Test main Minus module."""

    def test_minus_config_class_exists(self):
        """Verify MinusConfig class is importable."""
        try:
            from minus import MinusConfig
            self.assertIsNotNone(MinusConfig)
        except ImportError as e:
            self.skipTest(f"Minus module not available: {e}")

    def test_minus_class_exists(self):
        """Verify Minus class is importable."""
        try:
            from minus import Minus
            self.assertIsNotNone(Minus)
        except ImportError:
            self.skipTest("Minus module not available")


if __name__ == '__main__':
    unittest.main(verbosity=2)
