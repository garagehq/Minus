#!/usr/bin/env python3
"""
Unit tests for Fire TV Controller.
"""

import sys
import os

# Add src to path
sys.path.insert(0, '')

import unittest
from unittest.mock import MagicMock, patch, mock_open

from src.fire_tv import FireTVController, KEY_CODES


class TestFireTVController(unittest.TestCase):
    """Test FireTVController class."""

    def test_key_codes_exists(self):
        """Test that KEY_CODES dictionary exists and has expected keys."""
        self.assertIsInstance(KEY_CODES, dict)
        self.assertGreater(len(KEY_CODES), 0)
        # Check for some expected key codes
        expected_keys = ['up', 'down', 'left', 'right', 'select', 'back', 'home']
        for key in expected_keys:
            self.assertIn(key, KEY_CODES)

    def test_controller_initialization(self):
        """Test FireTVController initialization."""
        controller = FireTVController()
        self.assertIsNotNone(controller)
        self.assertEqual(controller._ip_address, None)
        self.assertEqual(controller.adbkey_path, os.path.expanduser("~/.android/adbkey"))
        self.assertFalse(controller._connected)
        self.assertIsNone(controller._device)

    def test_is_connected_no_connection(self):
        """Test is_connected when not connected."""
        controller = FireTVController()
        self.assertFalse(controller.is_connected())

    def test_discover_devices(self):
        """Test device discovery."""
        # This test just verifies the method exists and returns a list
        devices = FireTVController.discover_devices(timeout=1.0)
        self.assertIsInstance(devices, list)

    def test_key_code_values(self):
        """Test that key codes have valid values."""
        # Check that key codes are strings (keycode names)
        for key, value in KEY_CODES.items():
            self.assertIsInstance(value, str)
            self.assertTrue(len(value) > 0)

    def test_controller_properties(self):
        """Test controller properties."""
        controller = FireTVController()
        
        # Test that properties exist and have correct defaults
        self.assertTrue(hasattr(controller, '_ip_address'))
        self.assertTrue(hasattr(controller, '_connected'))
        self.assertTrue(hasattr(controller, '_device'))
        self.assertTrue(hasattr(controller, 'adbkey_path'))
        self.assertTrue(hasattr(controller, '_auto_reconnect'))

    def test_set_connection_callback(self):
        """Test setting connection callback."""
        controller = FireTVController()
        
        def mock_callback(connected):
            pass
        
        controller.set_connection_callback(mock_callback)
        self.assertEqual(controller._on_connection_change, mock_callback)

    def test_notify_connection_change(self):
        """Test notification of connection change."""
        controller = FireTVController()
        callback_called = []
        
        def mock_callback(connected):
            callback_called.append(connected)
        
        controller.set_connection_callback(mock_callback)
        controller._notify_connection_change(True)
        
        self.assertEqual(len(callback_called), 1)
        self.assertTrue(callback_called[0])

    def test_notify_connection_change_no_callback(self):
        """Test notification without callback set."""
        controller = FireTVController()
        # Should not raise any exception
        controller._notify_connection_change(True)


if __name__ == '__main__':
    unittest.main()
