#!/usr/bin/env python3
"""
Core tests for Minus HDMI passthrough system.
Tests the main minus.py module and core functionality.
"""

import sys
import os
import unittest
from unittest import mock

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


class TestFireTVController(unittest.TestCase):
    """Test Fire TV controller functionality."""
    
    def test_key_codes_exist(self):
        """Test that all expected key codes are defined."""
        from src.fire_tv import KEY_CODES
        expected_keys = ['up', 'down', 'left', 'right', 'select', 'play', 'pause', 'back', 'home']
        for key in expected_keys:
            self.assertIn(key, KEY_CODES, f"Key code '{key}' not found")
    
    def test_is_fire_tv_device(self):
        """Test Fire TV device detection."""
        from src.fire_tv import FireTVController
        # Test Amazon manufacturer
        self.assertTrue(FireTVController._is_fire_tv_device("Amazon", "Fire TV"))
        self.assertTrue(FireTVController._is_fire_tv_device("amazon", "Fire TV Stick"))
        # Test Fire TV model patterns
        self.assertTrue(FireTVController._is_fire_tv_device("Other", "AFTMM"))
        self.assertTrue(FireTVController._is_fire_tv_device("Other", "AFTT"))
        self.assertTrue(FireTVController._is_fire_tv_device("Other", "Fire TV Cube"))
        # Test non-Fire TV
        self.assertFalse(FireTVController._is_fire_tv_device("Samsung", "Smart TV"))
    
    def test_command_mapping(self):
        """Test that command mappings are correct."""
        from src.fire_tv import KEY_CODES
        # Test that key codes have valid ADB commands
        self.assertEqual(KEY_CODES['up'], 'KEYCODE_DPAD_UP')
        self.assertEqual(KEY_CODES['down'], 'KEYCODE_DPAD_DOWN')
        self.assertEqual(KEY_CODES['left'], 'KEYCODE_DPAD_LEFT')
        self.assertEqual(KEY_CODES['right'], 'KEYCODE_DPAD_RIGHT')
        self.assertEqual(KEY_CODES['select'], 'KEYCODE_DPAD_CENTER')
        self.assertEqual(KEY_CODES['back'], 'KEYCODE_BACK')
        self.assertEqual(KEY_CODES['home'], 'KEYCODE_HOME')


class TestOverlay(unittest.TestCase):
    """Test overlay functionality."""
    
    def test_overlay_positions(self):
        """Test overlay position constants."""
        from src.overlay import NotificationOverlay
        # Test position constants
        self.assertEqual(NotificationOverlay.POSITION_TOP_LEFT, 0)
        self.assertEqual(NotificationOverlay.POSITION_TOP_RIGHT, 1)
        self.assertEqual(NotificationOverlay.POSITION_BOTTOM_LEFT, 2)
        self.assertEqual(NotificationOverlay.POSITION_BOTTOM_RIGHT, 3)
        self.assertEqual(NotificationOverlay.POSITION_CENTER, 4)
    
    def test_overlay_position_mapping(self):
        """Test string to integer position mapping."""
        from src.overlay import NotificationOverlay
        pos_map = NotificationOverlay._POS_MAP
        self.assertEqual(pos_map['top-left'], 0)
        self.assertEqual(pos_map['top-right'], 1)
        self.assertEqual(pos_map['bottom-left'], 2)
        self.assertEqual(pos_map['bottom-right'], 3)
        self.assertEqual(pos_map['center'], 4)


class TestAudio(unittest.TestCase):
    """Test audio functionality."""
    
    def test_audio_class_exists(self):
        """Test AudioPassthrough class exists."""
        with mock.patch.dict('sys.modules', {'gi': mock.MagicMock(), 'gi.repository': mock.MagicMock()}):
            from src.audio import AudioPassthrough
            self.assertTrue(hasattr(AudioPassthrough, 'start'))
            self.assertTrue(hasattr(AudioPassthrough, 'stop'))
            self.assertTrue(hasattr(AudioPassthrough, 'mute'))
            self.assertTrue(hasattr(AudioPassthrough, 'unmute'))


class TestHealth(unittest.TestCase):
    """Test health monitoring functionality."""
    
    def test_health_status_fields(self):
        """Test HealthStatus dataclass fields."""
        from src.health import HealthStatus
        status = HealthStatus()
        self.assertTrue(hasattr(status, 'hdmi_signal'))
        self.assertTrue(hasattr(status, 'ustreamer_alive'))
        self.assertTrue(hasattr(status, 'video_pipeline_ok'))
        self.assertTrue(hasattr(status, 'audio_pipeline_ok'))
        self.assertTrue(hasattr(status, 'vlm_ready'))
        self.assertTrue(hasattr(status, 'memory_percent'))
        self.assertTrue(hasattr(status, 'disk_free_mb'))


class TestWebUI(unittest.TestCase):
    """Test web UI functionality."""
    
    def test_webui_class_exists(self):
        """Test WebUI class exists."""
        from src.webui import WebUI
        self.assertTrue(hasattr(WebUI, 'start'))
        self.assertTrue(hasattr(WebUI, 'stop'))


class TestFireTVSetup(unittest.TestCase):
    """Test Fire TV setup functionality."""
    
    def test_setup_class_exists(self):
        """Test FireTVSetupManager class exists."""
        from src.fire_tv_setup import FireTVSetupManager
        self.assertTrue(hasattr(FireTVSetupManager, '__init__'))


class TestMinusMain(unittest.TestCase):
    """Test main minus.py functionality."""
    
    def test_minus_class_exists(self):
        """Test Minus class exists."""
        import minus
        self.assertTrue(hasattr(minus, 'Minus'))
        self.assertTrue(hasattr(minus.Minus, 'run'))
        self.assertTrue(hasattr(minus.Minus, 'stop'))
    
    def test_minus_config_class(self):
        """Test MinusConfig class exists."""
        import minus
        self.assertTrue(hasattr(minus, 'MinusConfig'))


if __name__ == '__main__':
    unittest.main()
