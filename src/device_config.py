"""
Device Configuration Module for Minus.

Handles streaming device type selection and configuration.
Supports: Fire TV, Roku, Apple TV, Google TV, and generic devices.

Each device type has its own:
- Remote control key mappings
- Discovery/connection methods
- Setup flow requirements
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Config file path
CONFIG_FILE = Path.home() / '.minus_device_config.json'


class DeviceType(Enum):
    """Supported streaming device types."""
    FIRE_TV = 'fire_tv'
    ROKU = 'roku'
    APPLE_TV = 'apple_tv'
    GOOGLE_TV = 'google_tv'
    GENERIC = 'generic'
    NONE = 'none'


@dataclass
class DeviceConfig:
    """Configuration for a streaming device."""
    device_type: str = 'none'
    device_name: str = ''
    device_ip: str = ''
    setup_complete: bool = False

    # Device-specific settings
    custom_settings: Dict[str, Any] = None

    def __post_init__(self):
        if self.custom_settings is None:
            self.custom_settings = {}


# Key code mappings for different device types
# Fire TV uses Android KeyEvent codes via ADB
FIRE_TV_KEY_CODES = {
    'up': 'KEYCODE_DPAD_UP',
    'down': 'KEYCODE_DPAD_DOWN',
    'left': 'KEYCODE_DPAD_LEFT',
    'right': 'KEYCODE_DPAD_RIGHT',
    'select': 'KEYCODE_DPAD_CENTER',
    'back': 'KEYCODE_BACK',
    'home': 'KEYCODE_HOME',
    'menu': 'KEYCODE_MENU',
    'play': 'KEYCODE_MEDIA_PLAY',
    'pause': 'KEYCODE_MEDIA_PAUSE',
    'play_pause': 'KEYCODE_MEDIA_PLAY_PAUSE',
    'fast_forward': 'KEYCODE_MEDIA_FAST_FORWARD',
    'rewind': 'KEYCODE_MEDIA_REWIND',
    'volume_up': 'KEYCODE_VOLUME_UP',
    'volume_down': 'KEYCODE_VOLUME_DOWN',
    'mute': 'KEYCODE_VOLUME_MUTE',
    'power': 'KEYCODE_POWER',
}

# Roku uses ECP (External Control Protocol) commands
ROKU_KEY_CODES = {
    'up': 'Up',
    'down': 'Down',
    'left': 'Left',
    'right': 'Right',
    'select': 'Select',
    'back': 'Back',
    'home': 'Home',
    'info': 'Info',
    'play': 'Play',
    'pause': 'Pause',
    'play_pause': 'Play',  # Roku toggle
    'fast_forward': 'Fwd',
    'rewind': 'Rev',
    'volume_up': 'VolumeUp',
    'volume_down': 'VolumeDown',
    'mute': 'VolumeMute',
    'power': 'Power',
    'instant_replay': 'InstantReplay',
    'search': 'Search',
}

# Apple TV uses pyatv with different command style
APPLE_TV_KEY_CODES = {
    'up': 'up',
    'down': 'down',
    'left': 'left',
    'right': 'right',
    'select': 'select',
    'back': 'menu',
    'home': 'home',
    'menu': 'menu',
    'play': 'play',
    'pause': 'pause',
    'play_pause': 'play_pause',
    'fast_forward': 'skip_forward',
    'rewind': 'skip_backward',
    'volume_up': 'volume_up',
    'volume_down': 'volume_down',
    # Note: Apple TV volume control requires CEC or TV control
}

# Google TV / Android TV uses ADB (similar to Fire TV)
GOOGLE_TV_KEY_CODES = {
    'up': 'KEYCODE_DPAD_UP',
    'down': 'KEYCODE_DPAD_DOWN',
    'left': 'KEYCODE_DPAD_LEFT',
    'right': 'KEYCODE_DPAD_RIGHT',
    'select': 'KEYCODE_DPAD_CENTER',
    'back': 'KEYCODE_BACK',
    'home': 'KEYCODE_HOME',
    'menu': 'KEYCODE_MENU',
    'play': 'KEYCODE_MEDIA_PLAY',
    'pause': 'KEYCODE_MEDIA_PAUSE',
    'play_pause': 'KEYCODE_MEDIA_PLAY_PAUSE',
    'fast_forward': 'KEYCODE_MEDIA_FAST_FORWARD',
    'rewind': 'KEYCODE_MEDIA_REWIND',
    'volume_up': 'KEYCODE_VOLUME_UP',
    'volume_down': 'KEYCODE_VOLUME_DOWN',
    'mute': 'KEYCODE_VOLUME_MUTE',
    'power': 'KEYCODE_POWER',
    'assistant': 'KEYCODE_ASSIST',
}

# Device info for UI display
DEVICE_INFO = {
    DeviceType.FIRE_TV.value: {
        'name': 'Fire TV',
        'icon': '🔥',
        'protocol': 'ADB over WiFi',
        'setup_steps': [
            'Enable Developer Options (Settings > My Fire TV > About > click device name 7 times)',
            'Enable ADB Debugging (Settings > My Fire TV > Developer Options > ADB Debugging)',
            'Note the IP address (Settings > My Fire TV > About > Network)',
            'Approve the connection on your TV when prompted',
        ],
        'requirements': ['ADB debugging enabled', 'Same WiFi network'],
    },
    DeviceType.ROKU.value: {
        'name': 'Roku',
        'icon': '📺',
        'protocol': 'ECP (External Control Protocol)',
        'setup_steps': [
            'Enable Device Connect (Settings > System > Advanced system settings > Control by mobile apps)',
            'Set to "Default" or "Permissive"',
            'Note the IP address (Settings > Network > About)',
        ],
        'requirements': ['Device Connect enabled', 'Same WiFi network'],
    },
    DeviceType.APPLE_TV.value: {
        'name': 'Apple TV',
        'icon': '🍎',
        'protocol': 'MRP/AirPlay',
        'setup_steps': [
            'Allow AirPlay devices to connect (Settings > AirPlay and HomeKit)',
            'Note the IP address (Settings > Network)',
            'When prompted, enter the PIN shown on your TV',
        ],
        'requirements': ['AirPlay enabled', 'Same WiFi network', 'pyatv library'],
    },
    DeviceType.GOOGLE_TV.value: {
        'name': 'Google TV / Android TV',
        'icon': '📱',
        'protocol': 'ADB over WiFi',
        'setup_steps': [
            'Enable Developer Options (Settings > About > click Build number 7 times)',
            'Enable USB/Network Debugging (Settings > System > Developer options)',
            'Note the IP address (Settings > Network & Internet)',
            'Approve the connection on your TV when prompted',
        ],
        'requirements': ['ADB debugging enabled', 'Same WiFi network'],
    },
    DeviceType.GENERIC.value: {
        'name': 'Generic / Manual',
        'icon': '⚙️',
        'protocol': 'None',
        'setup_steps': [
            'Manual setup - no automatic remote control',
            'Blocking and detection will still work',
        ],
        'requirements': [],
    },
    DeviceType.NONE.value: {
        'name': 'No Device Selected',
        'icon': '❓',
        'protocol': 'None',
        'setup_steps': ['Select a device type to get started'],
        'requirements': [],
    },
}


def get_key_codes(device_type: str) -> Dict[str, str]:
    """Get key code mappings for a device type."""
    mappings = {
        DeviceType.FIRE_TV.value: FIRE_TV_KEY_CODES,
        DeviceType.ROKU.value: ROKU_KEY_CODES,
        DeviceType.APPLE_TV.value: APPLE_TV_KEY_CODES,
        DeviceType.GOOGLE_TV.value: GOOGLE_TV_KEY_CODES,
    }
    return mappings.get(device_type, {})


def get_device_info(device_type: str) -> Dict[str, Any]:
    """Get device info for a device type."""
    return DEVICE_INFO.get(device_type, DEVICE_INFO[DeviceType.NONE.value])


class DeviceConfigManager:
    """Manager for device configuration persistence and operations."""

    def __init__(self):
        self.config = DeviceConfig()
        self._load()

    def _load(self):
        """Load configuration from disk."""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                self.config = DeviceConfig(
                    device_type=data.get('device_type', 'none'),
                    device_name=data.get('device_name', ''),
                    device_ip=data.get('device_ip', ''),
                    setup_complete=data.get('setup_complete', False),
                    custom_settings=data.get('custom_settings', {}),
                )
                logger.info(f"[DeviceConfig] Loaded config: type={self.config.device_type}, ip={self.config.device_ip}")
        except Exception as e:
            logger.warning(f"[DeviceConfig] Failed to load config: {e}")
            self.config = DeviceConfig()

    def _save(self):
        """Save configuration to disk."""
        try:
            data = {
                'device_type': self.config.device_type,
                'device_name': self.config.device_name,
                'device_ip': self.config.device_ip,
                'setup_complete': self.config.setup_complete,
                'custom_settings': self.config.custom_settings,
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info(f"[DeviceConfig] Saved config: type={self.config.device_type}")
        except Exception as e:
            logger.error(f"[DeviceConfig] Failed to save config: {e}")

    def get_config(self) -> Dict[str, Any]:
        """Get current configuration as dict."""
        info = get_device_info(self.config.device_type)
        return {
            'device_type': self.config.device_type,
            'device_name': self.config.device_name or info['name'],
            'device_ip': self.config.device_ip,
            'setup_complete': self.config.setup_complete,
            'custom_settings': self.config.custom_settings,
            'info': info,
        }

    def set_device_type(self, device_type: str) -> Dict[str, Any]:
        """Set the device type."""
        # Validate device type
        valid_types = [dt.value for dt in DeviceType]
        if device_type not in valid_types:
            return {'success': False, 'error': f'Invalid device type. Valid: {valid_types}'}

        # If changing device type, reset setup
        if device_type != self.config.device_type:
            self.config.device_type = device_type
            self.config.device_ip = ''
            self.config.device_name = ''
            self.config.setup_complete = False
            self.config.custom_settings = {}
            self._save()

        return {'success': True, 'config': self.get_config()}

    def set_device_ip(self, ip: str) -> Dict[str, Any]:
        """Set the device IP address."""
        self.config.device_ip = ip
        self._save()
        return {'success': True, 'config': self.get_config()}

    def set_device_name(self, name: str) -> Dict[str, Any]:
        """Set a custom device name."""
        self.config.device_name = name
        self._save()
        return {'success': True, 'config': self.get_config()}

    def set_setup_complete(self, complete: bool) -> Dict[str, Any]:
        """Mark setup as complete or incomplete."""
        self.config.setup_complete = complete
        self._save()
        return {'success': True, 'config': self.get_config()}

    def update_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update custom settings."""
        self.config.custom_settings.update(settings)
        self._save()
        return {'success': True, 'config': self.get_config()}

    def reset(self) -> Dict[str, Any]:
        """Reset configuration to defaults."""
        self.config = DeviceConfig()
        self._save()
        return {'success': True, 'config': self.get_config()}

    def get_available_devices(self) -> list:
        """Get list of available device types with info."""
        devices = []
        for dt in DeviceType:
            if dt == DeviceType.NONE:
                continue
            info = get_device_info(dt.value)
            devices.append({
                'type': dt.value,
                'name': info['name'],
                'icon': info['icon'],
                'protocol': info['protocol'],
            })
        return devices


# Singleton instance
_device_config_manager: Optional[DeviceConfigManager] = None


def get_device_config_manager() -> DeviceConfigManager:
    """Get the singleton DeviceConfigManager instance."""
    global _device_config_manager
    if _device_config_manager is None:
        _device_config_manager = DeviceConfigManager()
    return _device_config_manager
