"""
Tests for WebUI module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestWebUI(unittest.TestCase):
    """Test cases for WebUI."""

    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_webui_init(self, mock_os, mock_requests, mock_flask):
        """Test WebUI initialization."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        
        webui = WebUI()
        self.assertIsNotNone(webui)
        self.assertFalse(webui.server_running)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_start_server(self, mock_os, mock_requests, mock_flask):
        """Test server start."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        
        webui = WebUI()
        webui.start_server()
        
        self.assertTrue(webui.server_running)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_stop_server(self, mock_os, mock_requests, mock_flask):
        """Test server stop."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        
        webui = WebUI()
        webui.start_server()
        webui.stop_server()
        
        self.assertFalse(webui.server_running)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_get_status(self, mock_os, mock_requests, mock_flask):
        """Test status endpoint."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        
        webui = WebUI()
        webui.start_server()
        
        status = webui.get_status()
        self.assertIsNotNone(status)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_proxy_video_feed(self, mock_os, mock_requests, mock_flask):
        """Test video feed proxy."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        mock_requests.get.return_value = MagicMock(content=b"test_video_data")
        
        webui = WebUI()
        webui.start_server()
        
        response = webui.proxy_video_feed()
        self.assertIsNotNone(response)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_get_health_status(self, mock_os, mock_requests, mock_flask):
        """Test health status endpoint."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        
        webui = WebUI()
        webui.start_server()
        
        health = webui.get_health_status()
        self.assertIsNotNone(health)
        
    @patch('src.webui.flask')
    @patch('src.webui.requests')
    @patch('src.webui.os')
    def test_handle_control_request(self, mock_os, mock_requests, mock_flask):
        """Test control request handling."""
        from src.webui import WebUI
        
        mock_os.path.exists.return_value = True
        mock_flask.Flask = MagicMock()
        mock_flask.Flask().route = MagicMock(return_value=lambda f: f)
        
        webui = WebUI()
        webui.start_server()
        
        result = webui.handle_control_request("skip_ad")
        self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main()
