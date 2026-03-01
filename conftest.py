#!/usr/bin/env python3
"""
Pytest configuration and fixtures for Minus tests.
"""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, '/home/radxa/Minus')

from src.fire_tv import FireTVController


@pytest.fixture
def ip_address():
    """Provide a default IP address for testing."""
    # Return a test IP - in real usage this would come from config or discovery
    return "192.168.1.100"


@pytest.fixture
def controller():
    """Provide a FireTVController instance for testing."""
    return FireTVController()
