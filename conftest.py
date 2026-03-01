#!/usr/bin/env python3
"""
Pytest configuration and fixtures for Minus tests.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, '')

from src.fire_tv import FireTVController


@pytest.fixture
def ip_address():
    """Fixture providing a test IP address."""
    return "127.0.0.1"


@pytest.fixture
def controller(ip_address):
    """Fixture providing a mocked FireTVController."""
    with patch('src.fire_tv.FireTVController') as mock_controller:
        instance = mock_controller.return_value
        instance.connect.return_value = True
        instance.disconnect.return_value = None
        yield instance
