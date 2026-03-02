"""
Tests for Audio Passthrough module.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestAudioPassthrough(unittest.TestCase):
    """Test cases for Audio Passthrough."""

    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_audio_init(self, mock_os, mock_gst):
        """Test audio passthrough initialization."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        audio = AudioPassthrough()
        self.assertIsNotNone(audio)
        self.assertFalse(audio.is_active)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_start_pipeline(self, mock_os, mock_gst):
        """Test audio pipeline start."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        
        self.assertTrue(audio.is_active)
        self.assertIsNotNone(audio.pipeline)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_stop_pipeline(self, mock_os, mock_gst):
        """Test audio pipeline stop."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        audio.stop_pipeline()
        
        self.assertFalse(audio.is_active)
        self.assertIsNone(audio.pipeline)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_mute_audio(self, mock_os, mock_gst):
        """Test audio mute."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        audio.mute_audio()
        
        self.assertIsNotNone(audio.volume)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_unmute_audio(self, mock_os, mock_gst):
        """Test audio unmute."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        audio.mute_audio()
        audio.unmute_audio()
        
        self.assertIsNotNone(audio.volume)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_handle_bus_message(self, mock_os, mock_gst):
        """Test bus message handling."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value.set_state.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        
        # Mock bus message
        mock_message = MagicMock()
        mock_message.type = mock_gst.MessageType.ERROR
        mock_message.parse_error.return_value = (Exception("Test error"), "Details")
        
        audio.handle_bus_message(mock_message)
        
        self.assertIsNone(audio.pipeline)
        
    @patch('src.audio.gst')
    @patch('src.audio.os')
    def test_destroy(self, mock_os, mock_gst):
        """Test resource cleanup."""
        from src.audio import AudioPassthrough
        
        mock_os.path.exists.return_value = True
        mock_gst.ElementFactoryMake.return_value = MagicMock()
        mock_gst.Pipeline.new.return_value = MagicMock()
        
        audio = AudioPassthrough()
        audio.start_pipeline()
        audio.destroy()
        
        self.assertIsNone(audio.pipeline)
        self.assertIsNone(audio.volume)
        self.assertIsNone(audio.bus)


if __name__ == '__main__':
    unittest.main()
