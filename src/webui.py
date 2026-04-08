"""
Minus Web UI

Lightweight Flask-based web interface for monitoring and controlling Minus.
Accessible via Tailscale for remote debugging and control.

Features:
- Live video feed (proxied from ustreamer)
- Status display (blocking state, FPS, HDMI, etc.)
- Pause/resume blocking (custom duration support)
- Recent detection history
- Log viewer
- Fire TV remote control
- WiFi network management (nmcli)
- ADB RSA key management
- Screenshot gallery
- Configuration management
"""

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, Response, send_from_directory
import requests

logger = logging.getLogger('Minus.WebUI')


class WebUI:
    """Web UI server for Minus."""

    def __init__(self, minus_instance, port: int = 80, ustreamer_port: int = 9090):
        """
        Initialize web UI.

        Args:
            minus_instance: Minus instance to control
            port: Port to run web server on
            ustreamer_port: Port where ustreamer is running (for stream proxy)
        """
        self.minus = minus_instance
        self.port = port
        self.ustreamer_port = ustreamer_port
        self.server_thread = None
        self.running = False

        # Create Flask app
        self.app = Flask(
            __name__,
            template_folder=str(Path(__file__).parent / 'templates'),
            static_folder=str(Path(__file__).parent / 'static'),
        )

        # Disable Flask's default logging (we use our own)
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.WARNING)

        # Register routes
        self._register_routes()

    def _register_routes(self):
        """Register all Flask routes."""

        @self.app.route('/')
        def index():
            """Serve the main UI page."""
            return send_from_directory(
                self.app.template_folder,
                'index.html'
            )

        @self.app.route('/api/status')
        def api_status():
            """Get current status."""
            try:
                status = self.minus.get_status_dict()
                return jsonify(status)
            except Exception as e:
                logger.error(f"Error getting status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/pause/<int:minutes>', methods=['POST'])
        def api_pause(minutes):
            """Pause blocking for specified minutes (1-60)."""
            if minutes < 1 or minutes > 60:
                return jsonify({'error': 'Invalid duration. Use 1-60 minutes.'}), 400

            try:
                self.minus.pause_blocking(minutes * 60)
                return jsonify({
                    'success': True,
                    'paused_until': self.minus.blocking_paused_until,
                    'duration_minutes': minutes,
                })
            except Exception as e:
                logger.error(f"Error pausing: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/resume', methods=['POST'])
        def api_resume():
            """Resume blocking immediately."""
            try:
                self.minus.resume_blocking()
                return jsonify({'success': True})
            except Exception as e:
                logger.error(f"Error resuming: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/detections')
        def api_detections():
            """Get recent detection history."""
            try:
                detections = list(self.minus.detection_history)
                # Return in reverse order (newest first)
                return jsonify({'detections': detections[::-1]})
            except Exception as e:
                logger.error(f"Error getting detections: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/logs')
        def api_logs():
            """Get recent log lines."""
            try:
                log_file = Path('/tmp/minus.log')
                if log_file.exists():
                    # Read last 100 lines
                    with open(log_file, 'r') as f:
                        lines = f.readlines()[-100:]
                    return jsonify({'lines': [line.rstrip() for line in lines]})
                return jsonify({'lines': []})
            except Exception as e:
                logger.error(f"Error reading logs: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/preview')
        def api_preview_status():
            """Get preview window status."""
            try:
                enabled = False
                if self.minus.ad_blocker:
                    enabled = self.minus.ad_blocker.is_preview_enabled()
                return jsonify({'preview_enabled': enabled})
            except Exception as e:
                logger.error(f"Error getting preview status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/preview/enable', methods=['POST'])
        def api_preview_enable():
            """Enable the preview window."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_preview_enabled(True)
                return jsonify({'success': True, 'preview_enabled': True})
            except Exception as e:
                logger.error(f"Error enabling preview: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/preview/disable', methods=['POST'])
        def api_preview_disable():
            """Disable the preview window."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_preview_enabled(False)
                return jsonify({'success': True, 'preview_enabled': False})
            except Exception as e:
                logger.error(f"Error disabling preview: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/debug-overlay')
        def api_debug_overlay_status():
            """Get debug overlay status."""
            try:
                enabled = False
                if self.minus.ad_blocker:
                    enabled = self.minus.ad_blocker.is_debug_overlay_enabled()
                return jsonify({'debug_overlay_enabled': enabled})
            except Exception as e:
                logger.error(f"Error getting debug overlay status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/debug-overlay/enable', methods=['POST'])
        def api_debug_overlay_enable():
            """Enable the debug overlay."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_debug_overlay_enabled(True)
                return jsonify({'success': True, 'debug_overlay_enabled': True})
            except Exception as e:
                logger.error(f"Error enabling debug overlay: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/debug-overlay/disable', methods=['POST'])
        def api_debug_overlay_disable():
            """Disable the debug overlay."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_debug_overlay_enabled(False)
                return jsonify({'success': True, 'debug_overlay_enabled': False})
            except Exception as e:
                logger.error(f"Error disabling debug overlay: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/pixelated-background')
        def api_pixelated_background_status():
            """Get pixelated background status."""
            try:
                enabled = False
                if self.minus.ad_blocker:
                    enabled = self.minus.ad_blocker.is_pixelated_background_enabled()
                return jsonify({'pixelated_background_enabled': enabled})
            except Exception as e:
                logger.error(f"Error getting pixelated background status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/pixelated-background/enable', methods=['POST'])
        def api_pixelated_background_enable():
            """Enable pixelated background during ad blocking."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_pixelated_background_enabled(True)
                return jsonify({'success': True, 'pixelated_background_enabled': True})
            except Exception as e:
                logger.error(f"Error enabling pixelated background: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/pixelated-background/disable', methods=['POST'])
        def api_pixelated_background_disable():
            """Disable pixelated background during ad blocking."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.set_pixelated_background_enabled(False)
                return jsonify({'success': True, 'pixelated_background_enabled': False})
            except Exception as e:
                logger.error(f"Error disabling pixelated background: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/firetv-keepalive')
        def api_firetv_keepalive_status():
            """Get Fire TV keep-alive status."""
            try:
                enabled = False
                if self.minus.fire_tv_controller:
                    enabled = self.minus.fire_tv_controller.is_keepalive_enabled()
                return jsonify({'keepalive_enabled': enabled})
            except Exception as e:
                logger.error(f"Error getting Fire TV keep-alive status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/firetv-keepalive/enable', methods=['POST'])
        def api_firetv_keepalive_enable():
            """Enable Fire TV keep-alive pings."""
            try:
                if self.minus.fire_tv_controller:
                    self.minus.fire_tv_controller.set_keepalive_enabled(True)
                return jsonify({'success': True, 'keepalive_enabled': True})
            except Exception as e:
                logger.error(f"Error enabling Fire TV keep-alive: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/firetv-keepalive/disable', methods=['POST'])
        def api_firetv_keepalive_disable():
            """Disable Fire TV keep-alive pings."""
            try:
                if self.minus.fire_tv_controller:
                    self.minus.fire_tv_controller.set_keepalive_enabled(False)
                return jsonify({'success': True, 'keepalive_enabled': False})
            except Exception as e:
                logger.error(f"Error disabling Fire TV keep-alive: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/test/trigger-block', methods=['POST'])
        def api_test_trigger_block():
            """Trigger ad blocking for testing.

            Optional JSON body:
            - duration: seconds to block (default: 10, max: 60)
            - source: detection source ('ocr', 'vlm', 'both', 'default')
            """
            try:
                data = request.get_json() or {}

                # Validate duration
                duration = data.get('duration', 10)
                if not isinstance(duration, (int, float)) or duration < 1 or duration > 60:
                    return jsonify({
                        'success': False,
                        'error': 'duration must be a number between 1 and 60 seconds'
                    }), 400
                duration = int(duration)

                # Validate source
                source = data.get('source', 'ocr')
                valid_sources = ('ocr', 'vlm', 'both', 'default')
                if source not in valid_sources:
                    return jsonify({
                        'success': False,
                        'error': f'source must be one of: {", ".join(valid_sources)}'
                    }), 400

                if self.minus.ad_blocker:
                    # Enable test mode to prevent detection loop from hiding
                    self.minus.ad_blocker.set_test_mode(duration)

                    # Show blocking overlay
                    self.minus.ad_blocker.show(source)

                    # Schedule auto-hide after duration
                    def auto_hide():
                        time.sleep(duration)
                        if self.minus.ad_blocker:
                            self.minus.ad_blocker.clear_test_mode()
                            self.minus.ad_blocker.hide(force=True)
                            logger.info(f"[WebUI] Test blocking ended after {duration}s")

                    threading.Thread(target=auto_hide, daemon=True).start()

                    logger.info(f"[WebUI] Test blocking triggered: source={source}, duration={duration}s")
                    return jsonify({
                        'success': True,
                        'source': source,
                        'duration': duration,
                        'message': f'Blocking for {duration} seconds'
                    })
                else:
                    return jsonify({'error': 'Ad blocker not initialized'}), 500
            except Exception as e:
                logger.error(f"Error triggering test block: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/test/stop-block', methods=['POST'])
        def api_test_stop_block():
            """Stop ad blocking (for testing)."""
            try:
                if self.minus.ad_blocker:
                    self.minus.ad_blocker.clear_test_mode()
                    self.minus.ad_blocker.hide(force=True)
                    logger.info("[WebUI] Test blocking stopped")
                    return jsonify({'success': True})
                else:
                    return jsonify({'error': 'Ad blocker not initialized'}), 500
            except Exception as e:
                logger.error(f"Error stopping test block: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/stream')
        def stream_proxy():
            """Proxy the MJPEG stream from ustreamer (for CORS bypass)."""
            try:
                # Stream from ustreamer
                url = f'http://localhost:{self.ustreamer_port}/stream'
                req = requests.get(url, stream=True, timeout=10)

                def generate():
                    for chunk in req.iter_content(chunk_size=8192):
                        if chunk:
                            yield chunk

                # Pass through the Content-Type from ustreamer (includes correct boundary)
                content_type = req.headers.get('Content-Type', 'multipart/x-mixed-replace;boundary=boundarydonotcross')

                return Response(
                    generate(),
                    mimetype=content_type,
                    headers={
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0',
                    }
                )
            except Exception as e:
                logger.error(f"Stream proxy error: {e}")
                return Response(status=503)

        @self.app.route('/snapshot')
        def snapshot_proxy():
            """Proxy a single snapshot from ustreamer."""
            try:
                url = f'http://localhost:{self.ustreamer_port}/snapshot'
                req = requests.get(url, timeout=5)
                return Response(
                    req.content,
                    mimetype='image/jpeg',
                    headers={
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                    }
                )
            except Exception as e:
                logger.error(f"Snapshot proxy error: {e}")
                return Response(status=503)

        # =========================================================================
        # Fire TV Remote Control
        # =========================================================================

        @self.app.route('/api/firetv/status')
        def api_firetv_status():
            """Get Fire TV connection status."""
            try:
                if hasattr(self.minus, 'fire_tv_setup') and self.minus.fire_tv_setup:
                    setup = self.minus.fire_tv_setup
                    return jsonify({
                        'connected': setup.is_connected(),
                        'state': setup.state,
                        'device_ip': setup.device_ip if hasattr(setup, 'device_ip') else None,
                    })
                return jsonify({'connected': False, 'state': 'not_initialized'})
            except Exception as e:
                logger.error(f"Error getting Fire TV status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/firetv/command', methods=['POST'])
        def api_firetv_command():
            """Send a command to Fire TV."""
            try:
                data = request.get_json() or {}
                command = data.get('command')

                valid_commands = [
                    'up', 'down', 'left', 'right', 'select', 'back', 'home', 'menu',
                    'play', 'pause', 'play_pause', 'fast_forward', 'rewind',
                    'volume_up', 'volume_down', 'mute'
                ]

                if command not in valid_commands:
                    return jsonify({'error': f'Invalid command. Valid: {valid_commands}'}), 400

                if hasattr(self.minus, 'fire_tv_setup') and self.minus.fire_tv_setup:
                    controller = self.minus.fire_tv_setup.get_controller()
                    if controller and controller.is_connected:
                        controller.send_command(command)
                        return jsonify({'success': True, 'command': command})
                    return jsonify({'error': 'Fire TV not connected'}), 503

                return jsonify({'error': 'Fire TV not initialized'}), 500
            except Exception as e:
                logger.error(f"Error sending Fire TV command: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Current Vocabulary Word
        # =========================================================================

        @self.app.route('/api/vocabulary')
        def api_vocabulary():
            """Get current vocabulary word being displayed."""
            try:
                if self.minus.ad_blocker:
                    word_info = self.minus.ad_blocker.get_current_vocabulary()
                    return jsonify(word_info)
                return jsonify({'word': None, 'translation': None, 'example': None})
            except Exception as e:
                logger.error(f"Error getting vocabulary: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Screenshot Gallery
        # =========================================================================

        @self.app.route('/api/screenshots')
        def api_screenshots():
            """Get list of screenshots with pagination.

            Query params:
            - type: 'ads', 'non_ads', 'vlm_spastic', 'static' (default: 'ads')
            - page: page number starting from 1 (default: 1)
            - limit: items per page (default: 5, max: 20)
            """
            try:
                screenshot_type = request.args.get('type', 'ads')
                page = max(1, int(request.args.get('page', 1)))
                limit = min(20, max(1, int(request.args.get('limit', 5))))

                valid_types = ['ads', 'non_ads', 'vlm_spastic', 'static']
                if screenshot_type not in valid_types:
                    screenshot_type = 'ads'

                screenshots_dir = Path(__file__).parent.parent / 'screenshots' / screenshot_type

                if not screenshots_dir.exists():
                    return jsonify({
                        'screenshots': [],
                        'total': 0,
                        'page': page,
                        'pages': 0,
                        'has_more': False
                    })

                # Get all files sorted by modification time
                all_files = sorted(screenshots_dir.glob('*.png'), key=lambda x: x.stat().st_mtime, reverse=True)
                total = len(all_files)
                pages = (total + limit - 1) // limit  # Ceiling division

                # Paginate
                start = (page - 1) * limit
                end = start + limit
                files = all_files[start:end]

                screenshots = [{'name': f.name, 'path': f'/api/screenshots/{screenshot_type}/{f.name}'} for f in files]

                return jsonify({
                    'screenshots': screenshots,
                    'total': total,
                    'page': page,
                    'pages': pages,
                    'has_more': page < pages
                })
            except Exception as e:
                logger.error(f"Error listing screenshots: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/screenshots/<subdir>/<filename>')
        def api_screenshot_file(subdir, filename):
            """Serve a screenshot file."""
            try:
                valid_subdirs = ['ads', 'non_ads', 'vlm_spastic', 'static', 'debug']
                if subdir not in valid_subdirs:
                    return Response(status=404)
                # Sanitize filename
                if '..' in filename or '/' in filename:
                    return Response(status=400)
                screenshots_dir = Path(__file__).parent.parent / 'screenshots' / subdir
                return send_from_directory(screenshots_dir, filename)
            except Exception as e:
                logger.error(f"Error serving screenshot: {e}")
                return Response(status=404)

        # =========================================================================
        # Debug Snapshot (Screenshot + Logs)
        # =========================================================================

        @self.app.route('/api/debug/snapshot', methods=['POST'])
        def api_debug_snapshot():
            """Take a debug snapshot (screenshot + last 100 log lines).

            Saves a screenshot and a companion log file with the same timestamp
            to the screenshots/debug/ directory.

            Returns the paths and log content for immediate display.
            """
            try:
                from datetime import datetime

                # Create debug screenshots directory
                debug_dir = Path(__file__).parent.parent / 'screenshots' / 'debug'
                debug_dir.mkdir(parents=True, exist_ok=True)

                # Generate timestamp for filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]

                # Capture snapshot from ustreamer
                try:
                    url = f'http://localhost:{self.ustreamer_port}/snapshot'
                    req = requests.get(url, timeout=5)
                    if req.status_code == 200:
                        screenshot_filename = f'debug_{timestamp}.jpg'
                        screenshot_path = debug_dir / screenshot_filename
                        screenshot_path.write_bytes(req.content)
                        logger.info(f"[WebUI] Debug snapshot saved: {screenshot_filename}")
                    else:
                        screenshot_filename = None
                        logger.warning(f"[WebUI] Failed to capture snapshot: HTTP {req.status_code}")
                except Exception as e:
                    screenshot_filename = None
                    logger.warning(f"[WebUI] Failed to capture snapshot: {e}")

                # Read last 100 log lines
                log_lines = []
                log_file = Path('/tmp/minus.log')
                if log_file.exists():
                    with open(log_file, 'r') as f:
                        log_lines = [line.rstrip() for line in f.readlines()[-100:]]

                # Save log lines to companion file
                log_filename = f'debug_{timestamp}.log'
                log_path = debug_dir / log_filename
                log_path.write_text('\n'.join(log_lines))

                # Get current status for context
                status = {}
                try:
                    status = self.minus.get_status_dict()
                except Exception as e:
                    logger.debug(f"[WebUI] Failed to get status for debug snapshot: {e}")

                # Save status to companion JSON file
                import json
                status_filename = f'debug_{timestamp}.json'
                status_path = debug_dir / status_filename
                status_path.write_text(json.dumps(status, indent=2, default=str))

                return jsonify({
                    'success': True,
                    'timestamp': timestamp,
                    'screenshot': f'/api/screenshots/debug/{screenshot_filename}' if screenshot_filename else None,
                    'log_file': f'/api/screenshots/debug/{log_filename}',
                    'status_file': f'/api/screenshots/debug/{status_filename}',
                    'log_lines': log_lines,
                    'status': status,
                    'message': f'Debug snapshot saved: {timestamp}'
                })
            except Exception as e:
                logger.error(f"Error taking debug snapshot: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/debug/snapshots')
        def api_debug_snapshots():
            """List saved debug snapshots."""
            try:
                debug_dir = Path(__file__).parent.parent / 'screenshots' / 'debug'

                if not debug_dir.exists():
                    return jsonify({'snapshots': []})

                # Find all debug snapshot files (by unique timestamps)
                timestamps = set()
                for f in debug_dir.glob('debug_*.jpg'):
                    # Extract timestamp from filename
                    ts = f.stem.replace('debug_', '')
                    timestamps.add(ts)
                for f in debug_dir.glob('debug_*.log'):
                    ts = f.stem.replace('debug_', '')
                    timestamps.add(ts)

                snapshots = []
                for ts in sorted(timestamps, reverse=True):
                    snapshot = {'timestamp': ts}
                    jpg_file = debug_dir / f'debug_{ts}.jpg'
                    log_file = debug_dir / f'debug_{ts}.log'
                    json_file = debug_dir / f'debug_{ts}.json'

                    if jpg_file.exists():
                        snapshot['screenshot'] = f'/api/screenshots/debug/debug_{ts}.jpg'
                    if log_file.exists():
                        snapshot['log_file'] = f'/api/screenshots/debug/debug_{ts}.log'
                    if json_file.exists():
                        snapshot['status_file'] = f'/api/screenshots/debug/debug_{ts}.json'

                    snapshots.append(snapshot)

                return jsonify({'snapshots': snapshots[:50]})  # Limit to 50 most recent
            except Exception as e:
                logger.error(f"Error listing debug snapshots: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/debug/snapshot/<timestamp>', methods=['DELETE'])
        def api_debug_snapshot_delete(timestamp):
            """Delete a debug snapshot and its associated files."""
            try:
                # Validate timestamp format (prevent path traversal)
                if not re.match(r'^[\d_]+$', timestamp):
                    return jsonify({'error': 'Invalid timestamp format'}), 400

                debug_dir = Path(__file__).parent.parent / 'screenshots' / 'debug'
                deleted = []

                # Delete all files with this timestamp
                for ext in ['jpg', 'log', 'json']:
                    file_path = debug_dir / f'debug_{timestamp}.{ext}'
                    if file_path.exists():
                        file_path.unlink()
                        deleted.append(f'debug_{timestamp}.{ext}')

                if deleted:
                    logger.info(f"[WebUI] Deleted debug snapshot: {timestamp} ({len(deleted)} files)")
                    return jsonify({'success': True, 'deleted': deleted})
                else:
                    return jsonify({'error': 'No files found for this timestamp'}), 404
            except Exception as e:
                logger.error(f"Error deleting debug snapshot: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # WiFi Management (nmcli)
        # =========================================================================

        @self.app.route('/api/wifi/connections')
        def api_wifi_connections():
            """Get saved WiFi connections with priorities."""
            try:
                result = subprocess.run(
                    ['nmcli', '-t', '-f', 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY', 'connection', 'show'],
                    capture_output=True, text=True, timeout=10
                )
                connections = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(':')
                        # Filter for wifi connections (802-11-wireless)
                        if len(parts) >= 4 and parts[2] == '802-11-wireless':
                            connections.append({
                                'name': parts[0],
                                'uuid': parts[1],
                                'type': 'wifi',
                                'device': parts[3] if parts[3] else None,
                                'autoconnect': parts[4] == 'yes' if len(parts) > 4 else True,
                                'priority': int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                            })
                return jsonify({'connections': connections})
            except Exception as e:
                logger.error(f"Error getting WiFi connections: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/wifi/scan')
        def api_wifi_scan():
            """Scan for available WiFi networks."""
            try:
                # Trigger a rescan
                subprocess.run(['nmcli', 'device', 'wifi', 'rescan'], capture_output=True, timeout=15)
                time.sleep(2)  # Wait for scan to complete

                result = subprocess.run(
                    ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY,BSSID', 'device', 'wifi', 'list'],
                    capture_output=True, text=True, timeout=10
                )
                networks = []
                seen_ssids = set()
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split(':')
                        if len(parts) >= 3 and parts[0] and parts[0] not in seen_ssids:
                            seen_ssids.add(parts[0])
                            networks.append({
                                'ssid': parts[0],
                                'signal': int(parts[1]) if parts[1] else 0,
                                'security': parts[2] if len(parts) > 2 else 'Open',
                            })
                # Sort by signal strength
                networks.sort(key=lambda x: x['signal'], reverse=True)
                return jsonify({'networks': networks})
            except Exception as e:
                logger.error(f"Error scanning WiFi: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/wifi/connect', methods=['POST'])
        def api_wifi_connect():
            """Connect to a WiFi network."""
            try:
                data = request.get_json() or {}
                ssid = data.get('ssid')
                password = data.get('password')
                priority = data.get('priority', 0)

                if not ssid:
                    return jsonify({'error': 'SSID is required'}), 400

                # Check if connection already exists
                check = subprocess.run(
                    ['nmcli', 'connection', 'show', ssid],
                    capture_output=True, timeout=5
                )

                if check.returncode == 0:
                    # Connection exists, just activate it
                    result = subprocess.run(
                        ['nmcli', 'connection', 'up', ssid],
                        capture_output=True, text=True, timeout=30
                    )
                else:
                    # Create new connection
                    cmd = ['nmcli', 'device', 'wifi', 'connect', ssid]
                    if password:
                        cmd.extend(['password', password])
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                    # Set priority if specified
                    if result.returncode == 0 and priority:
                        subprocess.run(
                            ['nmcli', 'connection', 'modify', ssid, 'connection.autoconnect-priority', str(priority)],
                            capture_output=True, timeout=5
                        )

                if result.returncode == 0:
                    return jsonify({'success': True, 'message': f'Connected to {ssid}'})
                else:
                    return jsonify({'error': result.stderr or 'Connection failed'}), 500
            except Exception as e:
                logger.error(f"Error connecting to WiFi: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/wifi/delete', methods=['POST'])
        def api_wifi_delete():
            """Delete a saved WiFi connection."""
            try:
                data = request.get_json() or {}
                name = data.get('name')

                if not name:
                    return jsonify({'error': 'Connection name is required'}), 400

                result = subprocess.run(
                    ['nmcli', 'connection', 'delete', name],
                    capture_output=True, text=True, timeout=10
                )

                if result.returncode == 0:
                    return jsonify({'success': True, 'message': f'Deleted {name}'})
                else:
                    return jsonify({'error': result.stderr or 'Delete failed'}), 500
            except Exception as e:
                logger.error(f"Error deleting WiFi connection: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/wifi/priority', methods=['POST'])
        def api_wifi_priority():
            """Update WiFi connection priority."""
            try:
                data = request.get_json() or {}
                name = data.get('name')
                priority = data.get('priority', 0)

                if not name:
                    return jsonify({'error': 'Connection name is required'}), 400

                result = subprocess.run(
                    ['nmcli', 'connection', 'modify', name, 'connection.autoconnect-priority', str(priority)],
                    capture_output=True, text=True, timeout=10
                )

                if result.returncode == 0:
                    return jsonify({'success': True, 'message': f'Updated priority for {name}'})
                else:
                    return jsonify({'error': result.stderr or 'Update failed'}), 500
            except Exception as e:
                logger.error(f"Error updating WiFi priority: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # ADB RSA Key Management
        # =========================================================================

        @self.app.route('/api/adb/keys')
        def api_adb_keys():
            """Get ADB RSA key info."""
            try:
                adbkey_path = Path.home() / '.android' / 'adbkey'
                adbkey_pub_path = Path.home() / '.android' / 'adbkey.pub'

                result = {'exists': False, 'public_key': None, 'fingerprint': None}

                if adbkey_pub_path.exists():
                    result['exists'] = True
                    pub_key = adbkey_pub_path.read_text().strip()
                    result['public_key'] = pub_key[:50] + '...' if len(pub_key) > 50 else pub_key

                    # Generate fingerprint (MD5 of public key)
                    import hashlib
                    fingerprint = hashlib.md5(pub_key.encode()).hexdigest()
                    result['fingerprint'] = ':'.join(fingerprint[i:i+2] for i in range(0, 32, 2))

                return jsonify(result)
            except Exception as e:
                logger.error(f"Error getting ADB keys: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/adb/keys/revoke', methods=['POST'])
        def api_adb_keys_revoke():
            """Revoke (delete) ADB RSA keys."""
            try:
                adbkey_path = Path.home() / '.android' / 'adbkey'
                adbkey_pub_path = Path.home() / '.android' / 'adbkey.pub'

                deleted = []
                if adbkey_path.exists():
                    adbkey_path.unlink()
                    deleted.append('adbkey')
                if adbkey_pub_path.exists():
                    adbkey_pub_path.unlink()
                    deleted.append('adbkey.pub')

                # Disconnect Fire TV if connected
                if hasattr(self.minus, 'fire_tv_setup') and self.minus.fire_tv_setup:
                    controller = self.minus.fire_tv_setup.get_controller()
                    if controller:
                        controller.disconnect()

                if deleted:
                    logger.info(f"[WebUI] Revoked ADB keys: {deleted}")
                    return jsonify({'success': True, 'deleted': deleted, 'message': 'ADB keys revoked. You will need to re-authorize on the TV.'})
                else:
                    return jsonify({'success': True, 'deleted': [], 'message': 'No keys found to revoke.'})
            except Exception as e:
                logger.error(f"Error revoking ADB keys: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Stats (Ads Blocked, Time Saved)
        # =========================================================================

        @self.app.route('/api/stats')
        def api_stats():
            """Get blocking statistics."""
            try:
                stats = {
                    'ads_blocked_today': 0,
                    'total_blocking_time': 0,
                    'time_saved': 0,
                    'blocking_start_time': None,
                    'current_blocking_duration': 0,
                }

                if self.minus.ad_blocker:
                    stats['ads_blocked_today'] = getattr(self.minus.ad_blocker, '_total_ads_blocked', 0)
                    stats['total_blocking_time'] = getattr(self.minus.ad_blocker, '_total_blocking_time', 0)
                    stats['time_saved'] = getattr(self.minus.ad_blocker, '_total_time_saved', 0)

                    if self.minus.ad_blocker.is_visible:
                        start_time = getattr(self.minus.ad_blocker, '_current_block_start', 0)
                        if start_time:
                            stats['blocking_start_time'] = start_time
                            stats['current_blocking_duration'] = time.time() - start_time

                return jsonify(stats)
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Audio Mute Status
        # =========================================================================

        @self.app.route('/api/audio/status')
        def api_audio_status():
            """Get audio mute status."""
            try:
                muted = False
                if hasattr(self.minus, 'audio') and self.minus.audio:
                    muted = getattr(self.minus.audio, '_muted', False)
                return jsonify({'muted': muted})
            except Exception as e:
                logger.error(f"Error getting audio status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/audio/sync-reset', methods=['POST'])
        def api_audio_sync_reset():
            """Reset A/V sync by flushing the audio sync queue.

            Use this when audio and video are out of sync.
            Causes a brief audio dropout (~300ms) while the queue refills.
            """
            try:
                if hasattr(self.minus, 'audio') and self.minus.audio:
                    result = self.minus.audio.reset_av_sync()
                    logger.info(f"[WebUI] A/V sync reset: {result.get('message', 'unknown')}")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Audio not initialized'}), 500
            except Exception as e:
                logger.error(f"Error resetting A/V sync: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Webhooks
        # =========================================================================

        @self.app.route('/api/webhooks')
        def api_webhooks_get():
            """Get webhook configuration."""
            try:
                from webhooks import get_webhook_manager
                manager = get_webhook_manager()
                return jsonify({
                    'enabled': manager.enabled,
                    'urls': manager.get_urls()
                })
            except Exception as e:
                logger.error(f"Error getting webhooks: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/webhooks', methods=['POST'])
        def api_webhooks_set():
            """Configure webhooks.

            JSON body:
            - enabled: true/false to enable/disable webhooks
            - urls: list of webhook URLs
            - add_url: single URL to add
            - remove_url: single URL to remove
            """
            try:
                from webhooks import get_webhook_manager
                manager = get_webhook_manager()
                data = request.get_json() or {}

                if 'enabled' in data:
                    manager.set_enabled(bool(data['enabled']))

                if 'urls' in data:
                    with manager._lock:
                        manager.urls = list(data['urls'])

                if 'add_url' in data:
                    manager.add_url(data['add_url'])

                if 'remove_url' in data:
                    manager.remove_url(data['remove_url'])

                return jsonify({
                    'success': True,
                    'enabled': manager.enabled,
                    'urls': manager.get_urls()
                })
            except Exception as e:
                logger.error(f"Error setting webhooks: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/webhooks/test', methods=['POST'])
        def api_webhooks_test():
            """Send a test notification to all webhook URLs."""
            try:
                from webhooks import get_webhook_manager
                manager = get_webhook_manager()

                if not manager.urls:
                    return jsonify({'success': False, 'error': 'No webhook URLs configured'}), 400

                manager.notify('test', {'message': 'Test notification from Minus'})
                return jsonify({
                    'success': True,
                    'message': f'Test notification sent to {len(manager.urls)} URL(s)'
                })
            except Exception as e:
                logger.error(f"Error testing webhooks: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Health Check
        # =========================================================================

        @self.app.route('/api/health')
        def api_health():
            """Detailed health check endpoint for monitoring.

            Returns 200 OK if service is running, with detailed subsystem status.
            Use ?simple=1 for basic ok/error response suitable for uptime monitors.
            """
            try:
                simple_mode = request.args.get('simple', '0') == '1'

                health = {
                    'status': 'ok',
                    'service': 'minus',
                    'timestamp': time.time(),
                    'subsystems': {}
                }

                issues = []

                # Video subsystem
                video_status = {'status': 'not_initialized'}
                if hasattr(self.minus, 'ad_blocker') and self.minus.ad_blocker:
                    if self.minus.ad_blocker.pipeline:
                        fps = self.minus.ad_blocker.get_fps()
                        restart_count = getattr(self.minus.ad_blocker, '_restart_count', 0)
                        video_status = {
                            'status': 'ok',
                            'fps': float(fps) if fps is not None else 0.0,
                            'blocking': bool(self.minus.ad_blocker.is_visible),
                            'restart_count': int(restart_count) if isinstance(restart_count, (int, float)) else 0
                        }
                    else:
                        video_status = {'status': 'error', 'reason': 'no_pipeline'}
                        issues.append('video_pipeline_down')
                health['subsystems']['video'] = video_status

                # Audio subsystem
                audio_status = {'status': 'not_initialized'}
                if hasattr(self.minus, 'audio') and self.minus.audio:
                    if self.minus.audio.is_running:
                        restart_count = getattr(self.minus.audio, '_restart_count', 0)
                        audio_status = {
                            'status': 'ok',
                            'muted': bool(self.minus.audio.is_muted),
                            'restart_count': int(restart_count) if isinstance(restart_count, (int, float)) else 0
                        }
                    else:
                        audio_status = {'status': 'stopped'}
                        issues.append('audio_stopped')
                health['subsystems']['audio'] = audio_status

                # VLM subsystem
                vlm_status = {'status': 'disabled'}
                if hasattr(self.minus, 'vlm') and self.minus.vlm:
                    # Note: is_ready is a property, not a method
                    if self.minus.vlm.is_ready:
                        vlm_status = {'status': 'ok'}
                    else:
                        vlm_status = {'status': 'loading'}
                health['subsystems']['vlm'] = vlm_status

                # OCR subsystem
                ocr_status = {'status': 'disabled'}
                if hasattr(self.minus, 'ocr') and self.minus.ocr:
                    ocr_status = {'status': 'ok'}
                health['subsystems']['ocr'] = ocr_status

                # Fire TV subsystem
                firetv_status = {'status': 'disabled'}
                if hasattr(self.minus, 'fire_tv_controller') and self.minus.fire_tv_controller:
                    if self.minus.fire_tv_controller.is_connected():
                        firetv_status = {'status': 'connected'}
                    else:
                        firetv_status = {'status': 'disconnected'}
                health['subsystems']['fire_tv'] = firetv_status

                # Health monitor status
                if hasattr(self.minus, 'health_monitor') and self.minus.health_monitor:
                    hm_status = self.minus.health_monitor.get_status()
                    health['hdmi_signal'] = hm_status.hdmi_signal
                    health['hdmi_resolution'] = hm_status.hdmi_resolution
                    health['uptime_seconds'] = hm_status.uptime_seconds

                # Overall status
                if issues:
                    health['status'] = 'degraded'
                    health['issues'] = issues

                # Simple mode returns just status for uptime monitors
                if simple_mode:
                    return jsonify({
                        'status': health['status'],
                        'timestamp': health['timestamp']
                    })

                return jsonify(health)
            except Exception as e:
                logger.error(f"Health check error: {e}")
                return jsonify({'status': 'error', 'error': str(e)}), 500

        @self.app.route('/api/metrics')
        def api_metrics():
            """Prometheus-compatible metrics endpoint.

            Returns metrics in Prometheus text format for monitoring systems.
            """
            try:
                lines = []

                # Helper to add metric
                def add_metric(name, value, help_text, metric_type='gauge', labels=None):
                    lines.append(f'# HELP {name} {help_text}')
                    lines.append(f'# TYPE {name} {metric_type}')
                    if labels:
                        label_str = ','.join(f'{k}="{v}"' for k, v in labels.items())
                        lines.append(f'{name}{{{label_str}}} {value}')
                    else:
                        lines.append(f'{name} {value}')

                # Uptime
                uptime = 0
                if hasattr(self.minus, 'health_monitor') and self.minus.health_monitor:
                    status = self.minus.health_monitor.get_status()
                    uptime = status.uptime_seconds
                add_metric('minus_uptime_seconds', uptime, 'Time since service start')

                # Video stats
                if hasattr(self.minus, 'ad_blocker') and self.minus.ad_blocker:
                    fps = self.minus.ad_blocker.get_fps() or 0
                    add_metric('minus_video_fps', fps, 'Current video FPS')

                    blocking = 1 if self.minus.ad_blocker.is_visible else 0
                    add_metric('minus_blocking_active', blocking, 'Whether blocking is active')

                    restart_count = getattr(self.minus.ad_blocker, '_restart_count', 0)
                    if isinstance(restart_count, (int, float)):
                        add_metric('minus_video_restarts_total', restart_count, 'Total video pipeline restarts', 'counter')

                # Audio stats
                if hasattr(self.minus, 'audio') and self.minus.audio:
                    running = 1 if self.minus.audio.is_running else 0
                    add_metric('minus_audio_running', running, 'Whether audio is running')

                    muted = 1 if self.minus.audio.is_muted else 0
                    add_metric('minus_audio_muted', muted, 'Whether audio is muted')

                    restart_count = getattr(self.minus.audio, '_restart_count', 0)
                    if isinstance(restart_count, (int, float)):
                        add_metric('minus_audio_restarts_total', restart_count, 'Total audio pipeline restarts', 'counter')

                # Detection stats
                if hasattr(self.minus, 'detection_counts'):
                    counts = self.minus.detection_counts
                    add_metric('minus_ocr_detections_total', counts.get('ocr', 0), 'Total OCR ad detections', 'counter')
                    add_metric('minus_vlm_detections_total', counts.get('vlm', 0), 'Total VLM ad detections', 'counter')

                # HDMI signal
                if hasattr(self.minus, 'health_monitor') and self.minus.health_monitor:
                    status = self.minus.health_monitor.get_status()
                    signal = 1 if status.hdmi_signal else 0
                    add_metric('minus_hdmi_signal', signal, 'Whether HDMI signal is present')

                # Time saved
                if hasattr(self.minus, 'ad_blocker') and self.minus.ad_blocker:
                    time_saved = getattr(self.minus.ad_blocker, '_total_time_saved', 0)
                    if isinstance(time_saved, (int, float)):
                        add_metric('minus_time_saved_seconds', time_saved, 'Total time saved by blocking ads', 'counter')

                response = '\n'.join(lines) + '\n'
                return response, 200, {'Content-Type': 'text/plain; charset=utf-8'}
            except Exception as e:
                logger.error(f"Metrics error: {e}")
                return f'# Error generating metrics: {e}\n', 500, {'Content-Type': 'text/plain; charset=utf-8'}

        # =========================================================================
        # Video Pipeline Control
        # =========================================================================

        @self.app.route('/api/video/restart', methods=['POST'])
        def api_video_restart():
            """Force restart the video pipeline.

            Use this when video is glitching or frozen without restarting the whole service.
            """
            try:
                if hasattr(self.minus, 'ad_blocker') and self.minus.ad_blocker:
                    logger.info("[WebUI] Video pipeline restart requested")
                    # Restart the pipeline (runs in background thread)
                    self.minus.ad_blocker.restart()
                    return jsonify({'success': True, 'message': 'Video pipeline restart initiated'})
                return jsonify({'success': False, 'error': 'Ad blocker not initialized'}), 500
            except Exception as e:
                logger.error(f"Error restarting video pipeline: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Video Color Settings
        # =========================================================================

        @self.app.route('/api/video/color')
        def api_video_color_get():
            """Get current video color balance settings.

            Returns saturation, brightness, contrast, hue values.
            """
            try:
                if hasattr(self.minus, 'ad_blocker') and self.minus.ad_blocker:
                    settings = self.minus.ad_blocker.get_color_settings()
                    return jsonify(settings)
                return jsonify({'error': 'Ad blocker not initialized'}), 500
            except Exception as e:
                logger.error(f"Error getting color settings: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/video/color', methods=['POST'])
        def api_video_color_set():
            """Set video color balance settings.

            JSON body can include any of:
            - saturation: 0.0-2.0 (default 1.0, higher = more saturated)
            - brightness: -1.0 to 1.0 (default 0.0)
            - contrast: 0.0-2.0 (default 1.0)
            - hue: -1.0 to 1.0 (default 0.0)
            """
            try:
                if not hasattr(self.minus, 'ad_blocker') or not self.minus.ad_blocker:
                    return jsonify({'success': False, 'error': 'Ad blocker not initialized'}), 500

                data = request.get_json() or {}

                # Validate input ranges
                errors = []
                if 'saturation' in data:
                    if not isinstance(data['saturation'], (int, float)) or not (0.0 <= data['saturation'] <= 2.0):
                        errors.append('saturation must be a number between 0.0 and 2.0')
                if 'brightness' in data:
                    if not isinstance(data['brightness'], (int, float)) or not (-1.0 <= data['brightness'] <= 1.0):
                        errors.append('brightness must be a number between -1.0 and 1.0')
                if 'contrast' in data:
                    if not isinstance(data['contrast'], (int, float)) or not (0.0 <= data['contrast'] <= 2.0):
                        errors.append('contrast must be a number between 0.0 and 2.0')
                if 'hue' in data:
                    if not isinstance(data['hue'], (int, float)) or not (-1.0 <= data['hue'] <= 1.0):
                        errors.append('hue must be a number between -1.0 and 1.0')

                if errors:
                    return jsonify({'success': False, 'errors': errors}), 400

                result = self.minus.ad_blocker.set_color_settings(
                    saturation=data.get('saturation'),
                    brightness=data.get('brightness'),
                    contrast=data.get('contrast'),
                    hue=data.get('hue')
                )

                if result.get('success'):
                    return jsonify(result)
                else:
                    return jsonify(result), 500
            except Exception as e:
                logger.error(f"Error setting color: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # OCR/VLM Testing
        # =========================================================================

        @self.app.route('/api/ocr/test', methods=['POST'])
        def api_ocr_test():
            """Run OCR on current frame and return detected text.

            Does NOT save the screenshot (for testing only).
            Returns detected text and any ad keywords found.
            """
            try:
                if not hasattr(self.minus, 'ocr') or not self.minus.ocr:
                    return jsonify({'success': False, 'error': 'OCR not initialized'}), 500

                if not hasattr(self.minus, 'frame_capture') or not self.minus.frame_capture:
                    return jsonify({'success': False, 'error': 'Capture not initialized'}), 500

                # Capture snapshot
                import cv2
                start_time = time.time()
                frame = self.minus.frame_capture.capture()
                capture_time = time.time() - start_time

                if frame is None:
                    return jsonify({'success': False, 'error': 'Failed to capture frame'}), 500

                # Convert to RGB for OCR
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # Run OCR
                ocr_start = time.time()
                ocr_results = self.minus.ocr.ocr(frame_rgb)
                ocr_time = time.time() - ocr_start

                # Check for ad keywords
                ad_detected, matched_keywords, all_texts, is_terminal = self.minus.ocr.check_ad_keywords(ocr_results)

                return jsonify({
                    'success': True,
                    'is_ad': ad_detected,
                    'is_terminal': is_terminal,
                    'texts': all_texts[:20] if all_texts else [],  # Limit to 20 text items
                    'keywords': matched_keywords,
                    'capture_time_ms': round(capture_time * 1000),
                    'ocr_time_ms': round(ocr_time * 1000),
                })
            except Exception as e:
                logger.error(f"OCR test error: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/vlm/test', methods=['POST'])
        def api_vlm_test():
            """Run VLM on current frame and return ad detection verdict.

            Does NOT save the screenshot (for testing only).
            Returns the VLM's verdict and confidence.
            """
            try:
                if not hasattr(self.minus, 'vlm') or not self.minus.vlm:
                    return jsonify({'success': False, 'error': 'VLM not initialized'}), 500

                if not self.minus.vlm.is_ready:
                    return jsonify({'success': False, 'error': 'VLM not ready (still loading)'}), 503

                if not hasattr(self.minus, 'frame_capture') or not self.minus.frame_capture:
                    return jsonify({'success': False, 'error': 'Capture not initialized'}), 500

                # Capture snapshot
                import cv2
                import tempfile
                start_time = time.time()
                frame = self.minus.frame_capture.capture()
                capture_time = time.time() - start_time

                if frame is None:
                    return jsonify({'success': False, 'error': 'Failed to capture frame'}), 500

                # Save to temp file for VLM (VLM requires file path)
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp_path = tmp.name
                    cv2.imwrite(tmp_path, frame)

                try:
                    # Run VLM
                    vlm_start = time.time()
                    is_ad, raw_response, elapsed, confidence = self.minus.vlm.detect_ad(tmp_path)
                    vlm_time = time.time() - vlm_start

                    return jsonify({
                        'success': True,
                        'is_ad': is_ad,
                        'confidence': confidence,
                        'raw_response': raw_response[:200] if raw_response else None,  # Truncate
                        'capture_time_ms': round(capture_time * 1000),
                        'vlm_time_ms': round(vlm_time * 1000),
                    })
                finally:
                    # Clean up temp file
                    import os
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            except Exception as e:
                logger.error(f"VLM test error: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # VLM Control (Enable/Disable)
        # =========================================================================

        @self.app.route('/api/vlm/status')
        def api_vlm_status():
            """Get detailed VLM status including model load state."""
            try:
                if hasattr(self.minus, 'get_vlm_status'):
                    status = self.minus.get_vlm_status()
                    return jsonify(status)
                return jsonify({
                    'initialized': False,
                    'disabled': True,
                    'model_loaded': False
                })
            except Exception as e:
                logger.error(f"Error getting VLM status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/vlm/disable', methods=['POST'])
        def api_vlm_disable():
            """Disable VLM and unload the model from the Axera NPU.

            This completely frees the NPU resources used by the VLM model.
            Detection will continue in OCR-only mode.
            """
            try:
                if hasattr(self.minus, 'disable_vlm'):
                    result = self.minus.disable_vlm()
                    if result.get('success'):
                        return jsonify(result)
                    return jsonify(result), 500
                return jsonify({'success': False, 'error': 'VLM control not available'}), 500
            except Exception as e:
                logger.error(f"Error disabling VLM: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/vlm/enable', methods=['POST'])
        def api_vlm_enable():
            """Enable VLM and load the model to the Axera NPU.

            This loads the FastVLM-1.5B model which takes ~13 seconds.
            An overlay notification will show loading progress.
            """
            try:
                if hasattr(self.minus, 'enable_vlm'):
                    result = self.minus.enable_vlm()
                    if result.get('success'):
                        return jsonify(result)
                    return jsonify(result), 500
                return jsonify({'success': False, 'error': 'VLM control not available'}), 500
            except Exception as e:
                logger.error(f"Error enabling VLM: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Blocking Control
        # =========================================================================

        @self.app.route('/api/blocking/skip', methods=['POST'])
        def api_blocking_skip():
            """Trigger Fire TV skip button press to skip current ad.

            Sends the 'select' command to Fire TV which usually skips skippable ads.
            """
            try:
                if not hasattr(self.minus, 'fire_tv_setup') or not self.minus.fire_tv_setup:
                    return jsonify({'success': False, 'error': 'Fire TV not initialized'}), 500

                controller = self.minus.fire_tv_setup.get_controller()
                if not controller or not controller.is_connected:
                    return jsonify({'success': False, 'error': 'Fire TV not connected'}), 503

                # Send select command (usually skips ads)
                controller.send_command('select')
                logger.info("[WebUI] Skip ad command sent to Fire TV")

                # Force unblock after brief delay (don't wait for OCR to detect)
                def _unblock_after_skip():
                    import time as _time
                    _time.sleep(1.5)
                    logger.info("[WebUI] Forcing unblock after manual skip")
                    if self.minus.ad_blocker:
                        self.minus.ad_blocker.hide()
                    if self.minus.audio:
                        self.minus.audio.unmute()
                    self.minus.ocr_ad_detected = False
                    self.minus.vlm_ad_detected = False
                    self.minus.blocking_source = None
                import threading
                threading.Thread(target=_unblock_after_skip, daemon=True).start()

                return jsonify({'success': True, 'message': 'Skip command sent'})
            except Exception as e:
                logger.error(f"Error sending skip command: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Network Info
        # =========================================================================

        @self.app.route('/api/network')
        def api_network():
            """Get network information (IP addresses)."""
            try:
                result = subprocess.run(
                    ['ip', '-4', '-o', 'addr', 'show'],
                    capture_output=True, text=True, timeout=5
                )
                interfaces = []
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split()
                        if len(parts) >= 4:
                            iface = parts[1]
                            # Extract IP from "inet x.x.x.x/xx" format
                            ip_part = parts[3].split('/')[0]
                            if iface != 'lo':  # Skip loopback
                                interfaces.append({'interface': iface, 'ip': ip_part})

                # Get hostname
                hostname = subprocess.run(['hostname'], capture_output=True, text=True, timeout=5).stdout.strip()

                return jsonify({
                    'hostname': hostname,
                    'interfaces': interfaces
                })
            except Exception as e:
                logger.error(f"Error getting network info: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Clear Detections
        # =========================================================================

        @self.app.route('/api/detections/clear', methods=['POST'])
        def api_detections_clear():
            """Clear detection history."""
            try:
                if hasattr(self.minus, 'detection_history'):
                    self.minus.detection_history.clear()
                    logger.info("[WebUI] Detection history cleared")
                    return jsonify({'success': True, 'message': 'Detection history cleared'})
                return jsonify({'error': 'Detection history not available'}), 500
            except Exception as e:
                logger.error(f"Error clearing detections: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Service Control
        # =========================================================================

        @self.app.route('/api/service/restart', methods=['POST'])
        def api_service_restart():
            """Schedule service restart."""
            try:
                logger.info("[WebUI] Service restart requested")
                # Schedule restart in background thread to allow response to be sent
                def restart():
                    time.sleep(1)
                    subprocess.run(['systemctl', 'restart', 'minus'], timeout=30)
                threading.Thread(target=restart, daemon=True).start()
                return jsonify({'success': True, 'message': 'Service restart scheduled'})
            except Exception as e:
                logger.error(f"Error restarting service: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Fire TV App Launch
        # =========================================================================

        @self.app.route('/api/firetv/launch/<app>', methods=['POST'])
        def api_firetv_launch(app):
            """Launch an app on Fire TV."""
            # App package mappings
            apps = {
                'youtube': 'com.amazon.firetv.youtube',
                'netflix': 'com.netflix.ninja',
                'prime': 'com.amazon.avod',
                'hulu': 'com.hulu.plus',
                'disney': 'com.disney.disneyplus',
                'hbomax': 'com.hbo.hbonow',
                'peacock': 'com.peacocktv.peacockandroid',
                'plex': 'com.plexapp.android',
                'kodi': 'org.xbmc.kodi',
                'spotify': 'com.spotify.tv.android',
                'twitch': 'tv.twitch.android.app',
                'home': 'com.amazon.tv.launcher',
            }

            try:
                if app.lower() not in apps:
                    return jsonify({'error': f'Unknown app: {app}. Available: {list(apps.keys())}'}), 400

                package = apps[app.lower()]

                if hasattr(self.minus, 'fire_tv_setup') and self.minus.fire_tv_setup:
                    controller = self.minus.fire_tv_setup.get_controller()
                    if controller and controller.is_connected and hasattr(controller, '_device') and controller._device:
                        # Use monkey to launch the app
                        controller._device.adb_shell(f'monkey -p {package} -c android.intent.category.LAUNCHER 1')
                        logger.info(f"[WebUI] Launched {app} on Fire TV")
                        return jsonify({'success': True, 'app': app, 'package': package})
                    return jsonify({'error': 'Fire TV not connected'}), 503

                return jsonify({'error': 'Fire TV not initialized'}), 500
            except Exception as e:
                logger.error(f"Error launching app: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        # =========================================================================
        # Night Mode
        # =========================================================================

        @self.app.route('/api/nightmode')
        def api_nightmode_status():
            """Get night mode status."""
            try:
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    return jsonify(self.minus.night_mode.get_status())
                return jsonify({
                    'enabled': False,
                    'active': False,
                    'error': 'Night mode not initialized'
                })
            except Exception as e:
                logger.error(f"Error getting night mode status: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/enable', methods=['POST'])
        def api_nightmode_enable():
            """Enable night mode (scheduled 12am-8am ET)."""
            try:
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    result = self.minus.night_mode.enable()
                    logger.info("[WebUI] Night mode enabled")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Night mode not initialized'}), 500
            except Exception as e:
                logger.error(f"Error enabling night mode: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/disable', methods=['POST'])
        def api_nightmode_disable():
            """Disable night mode."""
            try:
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    result = self.minus.night_mode.disable()
                    logger.info("[WebUI] Night mode disabled")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Night mode not initialized'}), 500
            except Exception as e:
                logger.error(f"Error disabling night mode: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/toggle', methods=['POST'])
        def api_nightmode_toggle():
            """Toggle night mode on/off."""
            try:
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    result = self.minus.night_mode.toggle()
                    logger.info(f"[WebUI] Night mode toggled: enabled={result.get('enabled')}")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Night mode not initialized'}), 500
            except Exception as e:
                logger.error(f"Error toggling night mode: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/start', methods=['POST'])
        def api_nightmode_start():
            """Start night mode immediately (manual override)."""
            try:
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    result = self.minus.night_mode.start_now()
                    logger.info("[WebUI] Night mode started immediately (manual)")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Night mode not initialized'}), 500
            except Exception as e:
                logger.error(f"Error starting night mode: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/logs')
        def api_nightmode_logs():
            """Get autonomous mode logs."""
            try:
                lines = int(request.args.get('lines', 50))
                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    log_content = self.minus.night_mode.get_log_tail(lines)
                    return jsonify({'logs': log_content})
                return jsonify({'logs': 'Autonomous mode not initialized'})
            except Exception as e:
                logger.error(f"Error getting autonomous mode logs: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @self.app.route('/api/nightmode/schedule', methods=['POST'])
        def api_nightmode_schedule():
            """Set autonomous mode schedule."""
            try:
                data = request.get_json() or {}
                start_hour = int(data.get('start_hour', 0))
                end_hour = int(data.get('end_hour', 8))
                always_on = bool(data.get('always_on', False))

                if hasattr(self.minus, 'night_mode') and self.minus.night_mode:
                    result = self.minus.night_mode.set_schedule(start_hour, end_hour, always_on)
                    logger.info(f"[WebUI] Autonomous mode schedule set: {start_hour}:00-{end_hour}:00, always_on={always_on}")
                    return jsonify(result)
                return jsonify({'success': False, 'error': 'Autonomous mode not initialized'}), 500
            except Exception as e:
                logger.error(f"Error setting autonomous mode schedule: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

    def start(self):
        """Start the web server in a background thread."""
        if self.running:
            return

        self.running = True

        def run_server():
            logger.info(f"[WebUI] Starting on http://0.0.0.0:{self.port}")
            try:
                # Use threaded=True for concurrent requests
                self.app.run(
                    host='0.0.0.0',
                    port=self.port,
                    threaded=True,
                    use_reloader=False,
                    debug=False,
                )
            except Exception as e:
                logger.error(f"[WebUI] Server error: {e}")
            finally:
                self.running = False

        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()

        # Give it a moment to start
        time.sleep(0.5)
        logger.info(f"[WebUI] Server started on port {self.port}")

    def stop(self):
        """Stop the web server."""
        self.running = False
        logger.info("[WebUI] Server stopping...")
        # Flask doesn't have a clean shutdown in this mode,
        # but since it's a daemon thread, it will stop when the process exits
