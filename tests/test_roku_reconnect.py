#!/usr/bin/env python3
"""
Tests for RokuController auto-reconnect robustness.

Covers the sticky-disconnect bug (2026-07): a transient outage (Roku's
nightly update reboot, WiFi blip) cleared `_connected`, the immediate
reconnect attempt failed while the device was still booting, and once the
Roku came back the old health-check-only loop never called connect()
again — the controller stayed "disconnected" for good until the user
reconnected via the web UI.

Run with: python3 tests/test_roku_reconnect.py
Or:       python3 -m pytest tests/test_roku_reconnect.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from roku import RokuController


def _make_controller(ip='192.168.1.50', connected=True, serial='X001'):
    c = RokuController()
    c._ip_address = ip
    c._connected = connected
    c._last_serial = serial
    return c


class TestReconnectTick(unittest.TestCase):
    """Tests for the per-cycle reconnect logic."""

    def test_noop_when_healthy(self):
        c = _make_controller(connected=True)
        c._check_connection = MagicMock(return_value=True)
        c.connect = MagicMock()
        c._reconnect_tick()
        c.connect.assert_not_called()
        self.assertTrue(c._connected)
        self.assertEqual(c._consecutive_failures, 0)

    def test_reconnects_after_dropped_flag(self):
        """REGRESSION (24h drop): `_connected` was cleared by a failed
        keypress / mid-reboot check, the device is reachable again — the
        tick must call connect() even though the health check would pass."""
        c = _make_controller(connected=False)
        c._check_connection = MagicMock(return_value=True)
        c.connect = MagicMock(return_value=True)
        c._reconnect_tick()
        c.connect.assert_called_once_with('192.168.1.50')

    def test_reconnects_when_device_stops_responding(self):
        c = _make_controller(connected=True)
        c._check_connection = MagicMock(return_value=False)
        c.connect = MagicMock(return_value=True)
        notified = []
        c.set_connection_callback(lambda connected: notified.append(connected))
        c._reconnect_tick()
        self.assertEqual(notified, [False])
        c.connect.assert_called_once_with('192.168.1.50')

    def test_rediscovers_after_three_failures(self):
        """DHCP change: the saved IP keeps failing — every 3rd consecutive
        failure the tick must fall back to network rediscovery."""
        c = _make_controller(connected=False)
        c._check_connection = MagicMock(return_value=False)
        c.connect = MagicMock(return_value=False)
        c._rediscover_and_connect = MagicMock(return_value=False)

        c._reconnect_tick()
        c._reconnect_tick()
        c._rediscover_and_connect.assert_not_called()
        c._reconnect_tick()
        c._rediscover_and_connect.assert_called_once()

    def test_no_direct_connect_without_ip_still_rediscovers(self):
        c = _make_controller(ip=None, connected=False)
        c._check_connection = MagicMock(return_value=False)
        c.connect = MagicMock()
        c._rediscover_and_connect = MagicMock(return_value=False)
        for _ in range(3):
            c._reconnect_tick()
        c.connect.assert_not_called()
        c._rediscover_and_connect.assert_called_once()

    def test_stopped_tick_does_not_reconnect(self):
        c = _make_controller(connected=False)
        c._stop_reconnect.set()
        c._check_connection = MagicMock(return_value=False)
        c.connect = MagicMock()
        c._reconnect_tick()
        c.connect.assert_not_called()


class TestRediscovery(unittest.TestCase):
    """Tests for SSDP rediscovery after an IP change."""

    def test_follows_device_to_new_ip_and_fires_callback(self):
        c = _make_controller(connected=False, serial='X001')
        new_ips = []
        c.set_ip_change_callback(lambda ip: new_ips.append(ip))
        c.connect = MagicMock(return_value=True)
        with patch.object(RokuController, 'discover_devices',
                          return_value=[{'ip': '192.168.1.99', 'serial': 'X001',
                                         'name': 'Roku', 'model': 'Ultra'}]):
            self.assertTrue(c._rediscover_and_connect())
        c.connect.assert_called_once_with('192.168.1.99')
        self.assertEqual(new_ips, ['192.168.1.99'])

    def test_skips_different_roku(self):
        """A neighbor's second Roku (different serial) must not be hijacked."""
        c = _make_controller(connected=False, serial='X001')
        c.connect = MagicMock(return_value=True)
        with patch.object(RokuController, 'discover_devices',
                          return_value=[{'ip': '192.168.1.77', 'serial': 'OTHER',
                                         'name': 'Roku', 'model': 'Express'}]):
            self.assertFalse(c._rediscover_and_connect())
        c.connect.assert_not_called()

    def test_prefers_serial_match(self):
        c = _make_controller(connected=False, serial='X001')
        c.connect = MagicMock(return_value=True)
        devices = [
            {'ip': '192.168.1.60', 'serial': '', 'name': 'Roku', 'model': '?'},
            {'ip': '192.168.1.99', 'serial': 'X001', 'name': 'Roku', 'model': 'Ultra'},
        ]
        with patch.object(RokuController, 'discover_devices', return_value=devices):
            self.assertTrue(c._rediscover_and_connect())
        c.connect.assert_called_once_with('192.168.1.99')

    def test_same_ip_reconnect_does_not_fire_ip_callback(self):
        c = _make_controller(connected=False, serial='X001')
        new_ips = []
        c.set_ip_change_callback(lambda ip: new_ips.append(ip))
        c.connect = MagicMock(return_value=True)
        with patch.object(RokuController, 'discover_devices',
                          return_value=[{'ip': '192.168.1.50', 'serial': 'X001',
                                         'name': 'Roku', 'model': 'Ultra'}]):
            self.assertTrue(c._rediscover_and_connect())
        self.assertEqual(new_ips, [])


class TestKeypressStatusCodes(unittest.TestCase):
    """ECP returns 202 Accepted under load — must count as success."""

    def _resp(self, code):
        r = MagicMock()
        r.status_code = code
        return r

    def test_202_is_success(self):
        c = _make_controller(connected=True)
        with patch('roku.requests.post', return_value=self._resp(202)) as post:
            self.assertTrue(c._send_keypress('Back'))
            post.assert_called_once()

    def test_500_is_failure(self):
        c = _make_controller(connected=True)
        with patch('roku.requests.post', return_value=self._resp(500)):
            self.assertFalse(c._send_keypress('Back'))

    def test_launch_202_is_success(self):
        c = _make_controller(connected=True)
        with patch('roku.requests.post', return_value=self._resp(202)):
            self.assertTrue(c.launch_app('youtube'))


class TestMonitoringLifecycle(unittest.TestCase):
    """Tests for start_monitoring() and user-initiated disconnect."""

    def test_start_monitoring_without_connection(self):
        """Startup with the Roku unreachable: monitoring must arm anyway."""
        c = RokuController()
        try:
            c.start_monitoring('192.168.1.50')
            self.assertEqual(c._ip_address, '192.168.1.50')
            self.assertIsNotNone(c._reconnect_thread)
            self.assertTrue(c._reconnect_thread.is_alive())
        finally:
            c.disconnect()

    def test_disconnect_stops_monitoring(self):
        """User disconnect must permanently stop auto-reconnect."""
        c = RokuController()
        c.start_monitoring('192.168.1.50')
        c.disconnect()
        self.assertTrue(c._stop_reconnect.is_set())
        self.assertIsNone(c._reconnect_thread)
        self.assertFalse(c._connected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
