"""
WiFi Manager Module for Minus.

Handles WiFi connectivity and captive portal AP mode:
- Detect WiFi connection status
- Scan for available networks
- Connect to networks via NetworkManager
- Create "Minus" hotspot AP when no WiFi is connected
- Auto-restart AP if WiFi drops for 30+ seconds
"""

import subprocess
import logging
import threading
import time
import re
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List, Callable

logger = logging.getLogger(__name__)

# Config file path
WIFI_CONFIG_FILE = Path.home() / '.minus_wifi_config.json'

# AP Configuration
AP_SSID = 'Minus'
AP_IP = '10.42.0.1'
AP_INTERFACE = 'wlP2p33s0'  # Will be auto-detected if this fails

# Timing
WIFI_CHECK_INTERVAL = 5  # seconds
WIFI_DISCONNECT_THRESHOLD = 30  # seconds before starting AP


@dataclass
class WiFiNetwork:
    """Represents a WiFi network."""
    ssid: str
    signal: int  # 0-100
    security: str  # 'Open', 'WPA', 'WPA2', etc.
    in_use: bool = False
    bssid: str = ''


@dataclass
class WiFiStatus:
    """Current WiFi status."""
    connected: bool = False
    ssid: str = ''
    ip_address: str = ''
    signal: int = 0
    ap_mode_active: bool = False
    ap_clients: int = 0


class WiFiManager:
    """Manager for WiFi connectivity and captive portal AP mode."""

    def __init__(self, on_ap_started: Callable = None, on_ap_stopped: Callable = None):
        self._interface = self._detect_wifi_interface()
        self._ap_mode_active = False
        self._ap_connection_name = 'Hotspot'  # nmcli hotspot always uses this name
        self._last_wifi_connected_time = time.time()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_running = False
        self._on_ap_started = on_ap_started
        self._on_ap_stopped = on_ap_stopped
        self._connecting = False
        self._last_connection_error = ''

        logger.info(f"[WiFi] Initialized with interface: {self._interface}")

    def _detect_wifi_interface(self) -> str:
        """Detect the WiFi interface name."""
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'DEVICE,TYPE', 'device'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                if ':wifi' in line:
                    interface = line.split(':')[0]
                    logger.info(f"[WiFi] Detected interface: {interface}")
                    return interface
        except Exception as e:
            logger.warning(f"[WiFi] Failed to detect interface: {e}")
        return AP_INTERFACE  # Fallback

    def _run_nmcli(self, args: List[str], timeout: int = 30) -> tuple:
        """Run nmcli command and return (success, output)."""
        try:
            cmd = ['nmcli'] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"[WiFi] nmcli timeout: {args}")
            return False, 'Command timed out'
        except Exception as e:
            logger.error(f"[WiFi] nmcli error: {e}")
            return False, str(e)

    def is_wifi_connected(self) -> bool:
        """Check if connected to any WiFi network (not AP mode)."""
        if self._ap_mode_active:
            return False

        # Check the actual connection name - if it's our AP, we're not "connected"
        success, output = self._run_nmcli([
            '-t', '-f', 'NAME,TYPE,DEVICE',
            'connection', 'show', '--active'
        ])

        if success:
            for line in output.split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    name, conn_type, device = parts[0], parts[1], parts[2]
                    # Skip our AP connection
                    if name == self._ap_connection_name:
                        continue
                    # Found a WiFi connection that's not our AP
                    if conn_type == '802-11-wireless' and device == self._interface:
                        return True

        return False

    def get_status(self) -> WiFiStatus:
        """Get current WiFi status."""
        status = WiFiStatus()

        # Check if we're in AP mode by looking at active connections
        success, output = self._run_nmcli([
            '-t', '-f', 'NAME,TYPE,DEVICE',
            'connection', 'show', '--active'
        ])

        if success:
            for line in output.split('\n'):
                parts = line.split(':')
                if len(parts) >= 3:
                    name, conn_type, device = parts[0], parts[1], parts[2]
                    if device == self._interface and conn_type == '802-11-wireless':
                        if name == self._ap_connection_name:
                            # We're in AP mode
                            status.ap_mode_active = True
                            self._ap_mode_active = True  # Sync the flag
                            status.ap_clients = self._count_ap_clients()
                            return status
                        else:
                            # We're connected to a WiFi network
                            status.connected = True
                            status.ssid = name
                            self._ap_mode_active = False  # Sync the flag
                            break

        # Sync AP mode flag based on actual state
        if not status.connected and not status.ap_mode_active:
            self._ap_mode_active = False

        if status.connected:
            # Get IP address
            status.ip_address = self._get_ip_address()
            # Get signal strength
            status.signal = self._get_signal_strength(status.ssid)

        return status

    def _get_ip_address(self) -> str:
        """Get the current WiFi IP address."""
        try:
            result = subprocess.run(
                ['ip', '-4', '-o', 'addr', 'show', self._interface],
                capture_output=True, text=True, timeout=5
            )
            # Parse: "2: wlP2p33s0 inet 192.168.1.15/24 ..."
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
        except Exception as e:
            logger.warning(f"[WiFi] Failed to get IP: {e}")
        return ''

    def _get_signal_strength(self, ssid: str) -> int:
        """Get signal strength for connected network."""
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'SIGNAL,SSID', 'device', 'wifi', 'list'],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.split(':')
                if len(parts) >= 2 and parts[1] == ssid:
                    return int(parts[0])
        except Exception:
            pass
        return 0

    def _count_ap_clients(self) -> int:
        """Count devices connected to our AP."""
        try:
            # Check ARP table for devices on AP subnet
            result = subprocess.run(
                ['ip', 'neigh', 'show', 'dev', self._interface],
                capture_output=True, text=True, timeout=5
            )
            # Count reachable neighbors
            count = len([l for l in result.stdout.strip().split('\n') if l and 'REACHABLE' in l])
            return count
        except Exception:
            pass
        return 0

    def scan_networks(self) -> List[WiFiNetwork]:
        """Scan for available WiFi networks."""
        networks = []

        # Trigger rescan
        self._run_nmcli(['device', 'wifi', 'rescan'])
        time.sleep(1)  # Wait for scan

        # Get network list - use different format to avoid BSSID colon escaping issues
        success, output = self._run_nmcli([
            '-t', '-f', 'SSID,SIGNAL,SECURITY,IN-USE',
            'device', 'wifi', 'list'
        ])

        if not success:
            logger.warning("[WiFi] Failed to scan networks")
            return networks

        seen_ssids = set()
        for line in output.split('\n'):
            if not line:
                continue

            # Format: SSID:SIGNAL:SECURITY:IN-USE
            # Split from the right to handle SSIDs that might contain colons
            parts = line.rsplit(':', 3)
            if len(parts) >= 4:
                ssid = parts[0].replace('\\:', ':')  # Unescape any colons in SSID
                try:
                    signal = int(parts[1])
                except ValueError:
                    signal = 0
                security = parts[2] if parts[2] else 'Open'
                in_use = parts[3] == '*'

                # Skip empty SSIDs and duplicates
                if not ssid or ssid in seen_ssids:
                    continue
                seen_ssids.add(ssid)

                networks.append(WiFiNetwork(
                    ssid=ssid,
                    signal=signal,
                    security=security,
                    in_use=in_use,
                    bssid=''  # Not fetching BSSID to avoid parsing issues
                ))

        # Sort by signal strength
        networks.sort(key=lambda n: n.signal, reverse=True)
        return networks

    def get_saved_networks(self) -> List[Dict[str, Any]]:
        """Get list of saved WiFi connections."""
        networks = []

        success, output = self._run_nmcli([
            '-t', '-f', 'NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY',
            'connection', 'show'
        ])

        if not success:
            return networks

        for line in output.split('\n'):
            parts = line.split(':')
            if len(parts) >= 4 and parts[1] == '802-11-wireless':
                name = parts[0]
                # Skip our AP connection
                if name == self._ap_connection_name:
                    continue
                networks.append({
                    'name': name,
                    'autoconnect': parts[2] == 'yes',
                    'priority': int(parts[3]) if parts[3].lstrip('-').isdigit() else 0
                })

        return networks

    def connect_to_network(self, ssid: str, password: str = '') -> Dict[str, Any]:
        """Connect to a WiFi network."""
        self._connecting = True
        self._last_connection_error = ''

        try:
            # Stop AP mode if active
            if self._ap_mode_active:
                self.stop_ap_mode()
                time.sleep(2)  # Wait for interface to be ready

            # Check if connection already exists
            existing = self._get_connection_by_ssid(ssid)

            if existing:
                # Modify password if provided
                if password:
                    self._run_nmcli([
                        'connection', 'modify', existing,
                        '802-11-wireless-security.psk', password
                    ])
                # Activate existing connection
                success, output = self._run_nmcli([
                    'connection', 'up', existing
                ], timeout=45)
            else:
                # Create new connection
                if password:
                    success, output = self._run_nmcli([
                        'device', 'wifi', 'connect', ssid,
                        'password', password,
                        'ifname', self._interface
                    ], timeout=45)
                else:
                    # Open network
                    success, output = self._run_nmcli([
                        'device', 'wifi', 'connect', ssid,
                        'ifname', self._interface
                    ], timeout=45)

            if success:
                # Verify connection
                time.sleep(2)
                if self.is_wifi_connected():
                    self._last_wifi_connected_time = time.time()
                    logger.info(f"[WiFi] Connected to {ssid}")
                    return {'success': True, 'ssid': ssid}
                else:
                    self._last_connection_error = 'Connection established but verification failed'
            else:
                # Parse error message
                if 'Secrets were required' in output or 'No secrets' in output:
                    self._last_connection_error = 'Incorrect password'
                elif 'not found' in output.lower():
                    self._last_connection_error = 'Network not found'
                elif 'timeout' in output.lower():
                    self._last_connection_error = 'Connection timed out'
                else:
                    self._last_connection_error = output or 'Connection failed'

            logger.warning(f"[WiFi] Failed to connect to {ssid}: {self._last_connection_error}")
            return {'success': False, 'error': self._last_connection_error}

        except Exception as e:
            self._last_connection_error = str(e)
            logger.error(f"[WiFi] Connection error: {e}")
            return {'success': False, 'error': str(e)}
        finally:
            self._connecting = False

    def _get_connection_by_ssid(self, ssid: str) -> Optional[str]:
        """Get connection name for an SSID if it exists."""
        success, output = self._run_nmcli([
            '-t', '-f', 'NAME,TYPE,802-11-wireless.ssid',
            'connection', 'show'
        ])

        if success:
            for line in output.split('\n'):
                parts = line.split(':')
                if len(parts) >= 3 and parts[1] == '802-11-wireless':
                    # SSID might be in parts[2] or later
                    if ssid in line:
                        return parts[0]
        return None

    def disconnect_network(self) -> Dict[str, Any]:
        """Disconnect from current WiFi network."""
        success, output = self._run_nmcli([
            'device', 'disconnect', self._interface
        ])

        if success:
            logger.info("[WiFi] Disconnected from network")
            return {'success': True}
        else:
            return {'success': False, 'error': output}

    def forget_network(self, name: str) -> Dict[str, Any]:
        """Delete a saved network connection."""
        success, output = self._run_nmcli([
            'connection', 'delete', name
        ])

        if success:
            logger.info(f"[WiFi] Deleted connection: {name}")
            return {'success': True}
        else:
            return {'success': False, 'error': output}

    def start_ap_mode(self) -> Dict[str, Any]:
        """Start the Minus WiFi access point."""
        if self._ap_mode_active:
            return {'success': True, 'message': 'AP already active'}

        logger.info("[WiFi] Starting AP mode...")

        try:
            # Stop any existing WiFi connection first
            self._run_nmcli(['device', 'disconnect', self._interface])
            time.sleep(1)

            # Delete any existing AP connection to ensure clean state
            self._run_nmcli(['connection', 'delete', self._ap_connection_name])
            time.sleep(0.5)

            # Create hotspot using NetworkManager
            # Note: This creates a WPA2-secured hotspot by default
            # We use a simple password since open networks are harder with NM
            success, output = self._run_nmcli([
                'device', 'wifi', 'hotspot',
                'ifname', self._interface,
                'con-name', self._ap_connection_name,
                'ssid', AP_SSID,
                'band', 'bg',
                'password', 'minus123'  # Simple 8-char password for setup
            ], timeout=30)

            if success:
                self._ap_mode_active = True
                logger.info(f"[WiFi] AP mode started: SSID={AP_SSID}")

                # Get AP IP for captive portal
                time.sleep(2)
                ap_ip = self._get_ip_address()

                if self._on_ap_started:
                    self._on_ap_started()

                return {
                    'success': True,
                    'ssid': AP_SSID,
                    'password': 'minus123',
                    'ip': ap_ip or AP_IP
                }
            else:
                logger.error(f"[WiFi] Failed to start AP: {output}")
                return {'success': False, 'error': output}

        except Exception as e:
            logger.error(f"[WiFi] AP start error: {e}")
            return {'success': False, 'error': str(e)}

    def stop_ap_mode(self) -> Dict[str, Any]:
        """Stop the Minus WiFi access point."""
        if not self._ap_mode_active:
            return {'success': True, 'message': 'AP not active'}

        logger.info("[WiFi] Stopping AP mode...")

        try:
            # Set flag first to prevent monitor from restarting
            self._ap_mode_active = False

            # Bring down the hotspot connection
            self._run_nmcli(['connection', 'down', self._ap_connection_name])
            time.sleep(1)

            # Delete the hotspot connection
            self._run_nmcli(['connection', 'delete', self._ap_connection_name])
            time.sleep(1)

            # Verify interface is available for client mode
            for _ in range(5):
                result = subprocess.run(
                    ['nmcli', '-t', '-f', 'DEVICE,STATE', 'device'],
                    capture_output=True, text=True, timeout=5
                )
                for line in result.stdout.split('\n'):
                    if self._interface in line and 'disconnected' in line:
                        logger.info("[WiFi] Interface ready for client mode")
                        break
                else:
                    time.sleep(1)
                    continue
                break

            if self._on_ap_stopped:
                self._on_ap_stopped()

            logger.info("[WiFi] AP mode stopped")
            return {'success': True}

        except Exception as e:
            logger.error(f"[WiFi] AP stop error: {e}")
            self._ap_mode_active = False  # Ensure flag is reset even on error
            return {'success': False, 'error': str(e)}

    def get_ap_status(self) -> Dict[str, Any]:
        """Get AP mode status."""
        return {
            'active': self._ap_mode_active,
            'ssid': AP_SSID if self._ap_mode_active else None,
            'password': 'minus123' if self._ap_mode_active else None,
            'ip': self._get_ip_address() if self._ap_mode_active else None,
            'clients': self._count_ap_clients() if self._ap_mode_active else 0
        }

    def start_monitor(self):
        """Start the background WiFi monitor thread."""
        if self._monitor_running:
            return

        self._monitor_running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[WiFi] Monitor thread started")

    def stop_monitor(self):
        """Stop the background WiFi monitor thread."""
        self._monitor_running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
        logger.info("[WiFi] Monitor thread stopped")

    def _monitor_loop(self):
        """Background thread that monitors WiFi and auto-starts AP if needed."""
        disconnect_time = None

        while self._monitor_running:
            try:
                if self._connecting:
                    # Don't interfere while connecting
                    time.sleep(WIFI_CHECK_INTERVAL)
                    continue

                is_connected = self.is_wifi_connected()

                if is_connected:
                    # Connected - reset disconnect timer
                    disconnect_time = None
                    self._last_wifi_connected_time = time.time()

                    # If AP was active, stop it
                    if self._ap_mode_active:
                        logger.info("[WiFi] WiFi connected, stopping AP")
                        self.stop_ap_mode()
                else:
                    # Not connected
                    if not self._ap_mode_active:
                        if disconnect_time is None:
                            disconnect_time = time.time()
                            logger.info("[WiFi] WiFi disconnected, starting timer")
                        elif time.time() - disconnect_time >= WIFI_DISCONNECT_THRESHOLD:
                            logger.info(f"[WiFi] No WiFi for {WIFI_DISCONNECT_THRESHOLD}s, starting AP")
                            self.start_ap_mode()
                            disconnect_time = None

            except Exception as e:
                logger.error(f"[WiFi] Monitor error: {e}")

            time.sleep(WIFI_CHECK_INTERVAL)

    def get_last_error(self) -> str:
        """Get the last connection error message."""
        return self._last_connection_error


# Singleton instance
_wifi_manager: Optional[WiFiManager] = None


def get_wifi_manager() -> WiFiManager:
    """Get the singleton WiFiManager instance."""
    global _wifi_manager
    if _wifi_manager is None:
        _wifi_manager = WiFiManager()
    return _wifi_manager
