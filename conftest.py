#!/usr/bin/env python3
"""
Pytest configuration and fixtures for Fire TV tests.
"""

import sys
import os

# Add src to path
sys.path.insert(0, '')

import pytest
from unittest.mock import MagicMock, patch

from src.fire_tv import FireTVController


@pytest.fixture
def ip_address():
    """Fixture for IP address."""
    return "192.168.1.100"


@pytest.fixture
def controller():
    """Fixture for FireTVController."""
    with patch('src.fire_tv.FireTVController') as mock_controller:
        mock_controller.return_value = MagicMock(spec=FireTVController)
        yield mock_controller.return_value
