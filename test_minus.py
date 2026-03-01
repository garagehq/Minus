#!/usr/bin/env python3
"""
Test suite for Minus - HDMI passthrough with ML-based ad detection.
Tests core logic and utilities in isolation from hardware dependencies.
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
import logging

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))


class TestConfig:
    """Tests for configuration handling."""
    
    def test_config_defaults(self):
        """Test that MinusConfig has proper defaults."""
        # Import after path is set
        from minus import MinusConfig
        
        config = MinusConfig(device='/dev/video0')
        
        assert config.device == '/dev/video0'
        assert config.screenshot_dir == 'screenshots'
        assert config.ocr_timeout == 1.5
        assert config.max_screenshots == 50
        assert config.drm_connector_id is None
        assert config.drm_plane_id is None
        assert config.webui_port == 8080


class TestLogging:
    """Tests for logging configuration."""
    
    def test_logger_setup(self):
        """Test that logger is properly configured."""
        # Import to trigger logger setup
        import minus
        
        # Check that root logger has handlers
        assert len(logging.getLogger().handlers) > 0
        
        # Check that Minus logger exists
        minus_logger = logging.getLogger('Minus')
        assert minus_logger is not None


class TestProbeDRM:
    """Tests for DRM output probing functionality."""
    
    def test_probe_drm_output_fallback(self):
        """Test that probe_drm_output returns fallback values when modetest fails."""
        from minus import probe_drm_output
        
        with patch('subprocess.run') as mock_run:
            # Simulate modetest failure
            mock_run.returncode = 1
            mock_run.return_value = Mock(returncode=1, stderr='error', stdout='')
            
            result = probe_drm_output()
            
            assert result['connector_id'] is None
            assert result['connector_name'] is None
            assert result['width'] == 1920  # fallback
            assert result['height'] == 1080  # fallback
            assert result['plane_id'] == 72  # fallback
            assert result['crtc_id'] is None
            assert result['audio_device'] == 'hw:0,0'  # fallback


class TestAdBlocker:
    """Tests for ad blocking functionality."""
    
    def test_ad_blocker_creation(self):
        """Test that AdBlocker can be instantiated."""
        try:
            from src.ad_blocker import AdBlocker
            
            # Mock the necessary dependencies
            mock_config = Mock()
            mock_config.drm_connector_id = 215
            mock_config.drm_plane_id = 72
            
            with patch('cv2.VideoCapture'):  # Mock video capture
                with patch('cv2.imshow'):  # Mock window display
                    with patch('cv2.waitKey', return_value=-1):  # Mock key wait
                        blocker = AdBlocker(config=mock_config)
                        assert blocker is not None
        except ImportError:
            pytest.skip("AdBlocker module not available")


class TestOCR:
    """Tests for OCR functionality."""
    
    def test_ocr_creation(self):
        """Test that OCR can be instantiated."""
        try:
            from src.ocr import PaddleOCR
            
            with patch('paddleocr.PaddleOCR') as mock_paddle:
                ocr = PaddleOCR()
                assert ocr is not None
        except ImportError:
            pytest.skip("OCR module not available")


class TestVLM:
    """Tests for VLM (Visual Language Model) functionality."""
    
    def test_vlm_creation(self):
        """Test that VLMManager can be instantiated."""
        try:
            from src.vlm import VLMManager
            
            mock_config = Mock()
            mock_config.vlm_prompt = "Detect ads"
            
            with patch('transformers.AutoProcessor'):  # Mock transformers
                with patch('transformers.AutoModelForCausalLM'):  # Mock model
                    vlm = VLMManager(config=mock_config)
                    assert vlm is not None
        except ImportError:
            pytest.skip("VLM module not available")


class TestAudio:
    """Tests for audio passthrough functionality."""
    
    def test_audio_creation(self):
        """Test that AudioPassthrough can be instantiated."""
        try:
            from src.audio import AudioPassthrough
            
            mock_config = Mock()
            mock_config.audio_device = 'hw:0,0'
            
            audio = AudioPassthrough(config=mock_config)
            assert audio is not None
        except ImportError:
            pytest.skip("Audio module not available")


class TestHealthMonitor:
    """Tests for health monitoring functionality."""
    
    def test_health_monitor_creation(self):
        """Test that HealthMonitor can be instantiated."""
        try:
            from src.health import HealthMonitor
            
            mock_minus = Mock()
            mock_minus.config = Mock()
            mock_minus.config.drm_connector_id = 215
            mock_minus.config.drm_plane_id = 72
            
            with patch('subprocess.run'):  # Mock gstreamer process check
                monitor = HealthMonitor(minus=mock_minus)
                assert monitor is not None
        except ImportError:
            pytest.skip("HealthMonitor module not available")


class TestWebUI:
    """Tests for web UI functionality."""
    
    def test_webui_creation(self):
        """Test that WebUI can be instantiated."""
        try:
            from src.webui import WebUI
            
            mock_minus = Mock()
            mock_minus.config = Mock()
            mock_minus.config.webui_port = 8080
            
            with patch('flask.Flask'):  # Mock Flask
                with patch('threading.Thread'):  # Mock threading
                    webui = WebUI(minus_instance=mock_minus, port=8080)
                    assert webui is not None
        except ImportError:
            pytest.skip("WebUI module not available")


class TestFireTVSetup:
    """Tests for Fire TV setup functionality."""
    
    def test_fire_tv_setup_creation(self):
        """Test that FireTVSetupManager can be instantiated."""
        try:
            from src.fire_tv_setup import FireTVSetupManager
            
            with patch('subprocess.run'):  # Mock ADB commands
                setup = FireTVSetupManager()
                assert setup is not None
        except ImportError:
            pytest.skip("FireTVSetupManager module not available")


class TestFireTVController:
    """Tests for Fire TV controller functionality."""
    
    def test_key_codes_exist(self):
        """Test that KEY_CODES dictionary exists and has expected keys."""
        try:
            from src.fire_tv import KEY_CODES
            
            # Check for common navigation keys
            expected_keys = ['up', 'down', 'left', 'right', 'select', 'back', 'home']
            for key in expected_keys:
                assert key in KEY_CODES, f"Missing key: {key}"
        except ImportError:
            pytest.skip("FireTV module not available")


class TestMainFunctions:
    """Tests for main application functions."""
    
    def test_main_argparse(self):
        """Test that main() can parse arguments."""
        from minus import main
        
        # Mock sys.argv and test argument parsing
        with patch('sys.argv', ['minus.py', '--device', '/dev/video1']):
            with patch('minus.Minus') as MockMinus:
                MockMinus.return_value.run.return_value = True
                
                try:
                    main()
                except SystemExit:
                    pass  # Expected when argparse parses --help or exits


class TestHelperFunctions:
    """Tests for helper functions."""
    
    def test_get_ad_duration(self):
        """Test ad duration calculation."""
        try:
            from minus import get_ad_duration
            
            # Test with valid duration
            result = get_ad_duration(15, 30)
            assert result == 15
            
            # Test with negative duration
            result = get_ad_duration(-5, 30)
            assert result == 30  # fallback
            
        except ImportError:
            pytest.skip("get_ad_duration not available")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
