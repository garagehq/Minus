"""
DRM (Direct Rendering Manager) probing utilities for Minus.

Auto-detects connected HDMI output, preferred resolution, and suitable
DRM plane for NV12 video output on RK3588 hardware.

Includes adaptive bandwidth management for HDMI signal integrity.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Color format values for DRM connector property
COLOR_FORMAT_RGB = 0
COLOR_FORMAT_YCBCR444 = 1
COLOR_FORMAT_YCBCR422 = 2
COLOR_FORMAT_YCBCR420 = 3  # Half bandwidth - good for problematic cables

COLOR_FORMAT_NAMES = {
    0: 'RGB',
    1: 'YCbCr 4:4:4',
    2: 'YCbCr 4:2:2',
    3: 'YCbCr 4:2:0',
}


def get_color_format(connector_id: int) -> tuple:
    """
    Get the current color_format setting for a connector.

    Args:
        connector_id: DRM connector ID (e.g., 215 for HDMI-A-1)

    Returns:
        Tuple of (value: int, name: str) or (None, None) on error
    """
    try:
        proc = subprocess.run(
            ['modetest', '-M', 'rockchip', '-c'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode != 0:
            return None, None

        # Find the connector section and extract color_format value
        lines = proc.stdout.split('\n')
        in_connector = False

        for i, line in enumerate(lines):
            # Find our connector by ID at start of line
            if line.strip().startswith(str(connector_id)) and 'connected' in line:
                in_connector = True
                continue

            # Look for next connector (end of our section)
            if in_connector and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                if re.match(r'^\d+\s', line.strip()):
                    break

            # Find color_format property and its value
            if in_connector and 'color_format:' in line:
                # Value is a few lines down after "enums:" line
                for j in range(i + 1, min(i + 6, len(lines))):
                    if 'value:' in lines[j]:
                        try:
                            value = int(lines[j].split(':')[1].strip())
                            name = COLOR_FORMAT_NAMES.get(value, f'Unknown({value})')
                            return value, name
                        except (ValueError, IndexError):
                            pass
                        break

        return None, None

    except Exception as e:
        logger.warning(f"Error getting color_format: {e}")
        return None, None


def set_color_format(connector_id: int, color_format: int, max_retries: int = 5) -> bool:
    """
    Set the color_format for a connector to reduce HDMI bandwidth.

    Use COLOR_FORMAT_YCBCR420 (3) for problematic cables/displays that can't
    handle full 4K@60Hz bandwidth (18 Gbps). YCbCr 4:2:0 uses half the bandwidth.

    Uses aggressive retry logic with process cleanup between attempts since
    modetest can hang when DRM is held by other processes.

    Args:
        connector_id: DRM connector ID (e.g., 215 for HDMI-A-1)
        color_format: One of COLOR_FORMAT_* constants (0-3)
        max_retries: Maximum retry attempts (default 5)

    Returns:
        True if successful, False otherwise
    """
    import time

    format_name = COLOR_FORMAT_NAMES.get(color_format, str(color_format))
    logger.info(f"Setting color_format to {format_name} (value={color_format}) on connector {connector_id}")

    for attempt in range(max_retries):
        try:
            # Kill any stuck modetest processes before each attempt
            subprocess.run(['pkill', '-9', 'modetest'], capture_output=True, timeout=2)
            time.sleep(0.3)

            logger.info(f"modetest attempt {attempt + 1}/{max_retries}")

            # Run modetest with shorter timeout - if it doesn't complete quickly,
            # something is blocking DRM and we need to retry
            proc = subprocess.run(
                ['sudo', 'modetest', '-M', 'rockchip', '-w', f'{connector_id}:color_format:{color_format}'],
                capture_output=True, text=True, timeout=5
            )

            # modetest completed - wait for DRM state to settle
            time.sleep(0.5)

            # Verify the change
            new_value, new_name = get_color_format(connector_id)
            if new_value == color_format:
                logger.info(f"Successfully set color_format to {new_name}")
                return True
            elif new_value is None:
                # Verification failed but modetest ran - assume success
                logger.info(f"color_format set command completed, verification unavailable")
                return True
            else:
                logger.warning(f"color_format change didn't take effect (got {new_name}, expected {format_name})")
                # Continue to retry

        except subprocess.TimeoutExpired:
            logger.warning(f"modetest timeout on attempt {attempt + 1}/{max_retries}")
            # Kill the stuck modetest process
            subprocess.run(['pkill', '-9', 'modetest'], capture_output=True, timeout=2)
            time.sleep(1)  # Wait before retry

        except Exception as e:
            logger.warning(f"Error on attempt {attempt + 1}: {e}")
            time.sleep(0.5)

    logger.warning(f"Failed to set color_format after {max_retries} attempts")
    return False


def check_hdmi_i2c_errors(threshold: int = 10, window_seconds: float = 5.0) -> tuple:
    """
    Check dmesg for recent HDMI i2c errors indicating signal integrity problems.

    When HDMI signal fails (e.g., bandwidth too high for cable), the dwhdmi driver
    floods dmesg with "i2c read err!" messages. This is a reliable heuristic for
    detecting signal problems that the kernel doesn't otherwise report.

    Args:
        threshold: Number of errors that indicates a problem (default: 10)
        window_seconds: Time window in seconds to check (default: 5.0)

    Returns:
        Tuple of (has_errors: bool, error_count: int, errors_per_second: float)
    """
    try:
        import time

        # Read dmesg (standard format with timestamps like "[ 1234.567890]")
        proc = subprocess.run(
            ['dmesg'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode != 0:
            return False, 0, 0.0

        # Get current uptime to calculate age of messages
        with open('/proc/uptime', 'r') as f:
            current_uptime = float(f.read().split()[0])

        error_count = 0
        error_timestamps = []

        for line in proc.stdout.split('\n'):
            if 'dwhdmi-rockchip' in line and 'i2c read err' in line:
                # Extract timestamp from format: "[ 1234.567890] message"
                try:
                    # Find the timestamp between [ and ]
                    start = line.find('[')
                    end = line.find(']')
                    if start >= 0 and end > start:
                        timestamp_str = line[start+1:end].strip()
                        timestamp = float(timestamp_str)
                        age = current_uptime - timestamp

                        if age <= window_seconds:
                            error_count += 1
                            error_timestamps.append(timestamp)
                except (ValueError, IndexError):
                    continue

        # Calculate errors per second
        if error_timestamps and len(error_timestamps) >= 2:
            time_span = max(error_timestamps) - min(error_timestamps)
            errors_per_second = error_count / max(time_span, 0.1)
        else:
            errors_per_second = error_count / window_seconds if error_count > 0 else 0.0

        has_errors = error_count >= threshold

        # Note: Don't log here - let the caller decide whether to log based on context
        # (e.g., after fallback is applied, i2c errors may persist but aren't a problem)

        return has_errors, error_count, errors_per_second

    except subprocess.TimeoutExpired:
        logger.warning("Timeout checking dmesg for i2c errors")
        return False, 0, 0.0
    except Exception as e:
        logger.warning(f"Error checking HDMI i2c errors: {e}")
        return False, 0, 0.0


def is_connector_connected(connector_id: int) -> bool:
    """
    Check if a connector is connected (has EDID/display attached).

    This is different from "working" - a connector can be connected but
    have signal integrity issues at high bandwidth.

    Args:
        connector_id: DRM connector ID

    Returns:
        True if connector shows "connected" status
    """
    try:
        proc = subprocess.run(
            ['modetest', '-M', 'rockchip', '-c'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode != 0:
            return False

        for line in proc.stdout.split('\n'):
            if line.strip().startswith(str(connector_id)):
                return 'connected' in line and 'disconnected' not in line

        return False

    except Exception:
        return False


def probe_drm_output() -> dict:
    """
    Probe DRM outputs to find connected HDMI display and its preferred resolution.

    Returns dict with:
        - connector_id: int (e.g., 215 for HDMI-A-1, 231 for HDMI-A-2)
        - connector_name: str (e.g., 'HDMI-A-1', 'HDMI-A-2')
        - width: int (preferred resolution width)
        - height: int (preferred resolution height)
        - plane_id: int (suitable plane that supports NV12)
        - crtc_id: int (CRTC connected to this connector)
        - audio_device: str (ALSA playback device, e.g., 'hw:0,0' or 'hw:1,0')
    """
    result = {
        'connector_id': None,
        'connector_name': None,
        'width': 1920,  # fallback
        'height': 1080,  # fallback
        'plane_id': 72,  # fallback (known to support NV12)
        'crtc_id': None,
        'audio_device': 'hw:0,0',  # fallback
    }

    try:
        # Run modetest to get connector info
        proc = subprocess.run(
            ['modetest', '-M', 'rockchip', '-c'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode != 0:
            logger.warning(f"modetest failed: {proc.stderr}")
            return result

        # Parse connectors - look for connected HDMI
        # Format: "id  encoder  status  name  size (mm)  modes  encoders"
        # Example: "231  230  connected  HDMI-A-2  1150x650  25  230"
        lines = proc.stdout.split('\n')
        in_connectors = False
        connected_hdmi = None

        for line in lines:
            if 'Connectors:' in line:
                in_connectors = True
                continue
            if in_connectors and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        conn_id = int(parts[0])
                        status = parts[2]
                        name = parts[3]
                        if status == 'connected' and 'HDMI' in name:
                            connected_hdmi = {'id': conn_id, 'name': name}
                            logger.info(f"Found connected HDMI output: {name} (connector {conn_id})")
                            break
                    except (ValueError, IndexError):
                        continue

        if not connected_hdmi:
            logger.warning("No connected HDMI output found")
            return result

        result['connector_id'] = connected_hdmi['id']
        result['connector_name'] = connected_hdmi['name']

        # Get preferred resolution from modetest
        # Run modetest again to get modes for this connector
        proc = subprocess.run(
            ['modetest', '-M', 'rockchip', '-c'],
            capture_output=True, text=True, timeout=5
        )

        # Look for preferred mode after the connector line
        lines = proc.stdout.split('\n')
        found_connector = False
        for line in lines:
            # Find our connector by ID
            if line.strip().startswith(str(connected_hdmi['id'])):
                found_connector = True
                continue
            if found_connector:
                # Look for "preferred" in mode line
                # Format: "#0 1920x1080 60.00 ... flags: phsync, pvsync; type: preferred, driver"
                if 'preferred' in line and 'x' in line:
                    # Extract resolution like "1920x1080"
                    match = re.search(r'(\d+)x(\d+)', line)
                    if match:
                        result['width'] = int(match.group(1))
                        result['height'] = int(match.group(2))
                        logger.info(f"Found preferred resolution: {result['width']}x{result['height']}")
                        break
                # Stop if we hit next connector
                elif line.strip() and not line.startswith(' ') and not line.startswith('\t') and not line.startswith('#'):
                    if re.match(r'^\d+\s', line.strip()):
                        break

        # Find a suitable plane that supports NV12 and is an Overlay type
        # On RK3588 VOP2:
        #   - type=0 (Overlay) - best for video overlay
        #   - type=1 (Primary) - typically doesn't support NV12
        #   - type=2 (Cursor) - can work but not ideal
        # Planes 192, 152, 112, 72 typically support NV12 on RK3588
        proc = subprocess.run(
            ['modetest', '-M', 'rockchip', '-p'],
            capture_output=True, text=True, timeout=5
        )

        if proc.returncode == 0:
            lines = proc.stdout.split('\n')
            in_planes = False
            best_plane = None
            best_plane_type = 3  # Start with invalid type (lower is better: Overlay=0, Primary=1, Cursor=2)

            i = 0
            while i < len(lines):
                line = lines[i]

                if 'Planes:' in line:
                    in_planes = True
                    i += 1
                    continue

                if in_planes and line.strip() and not line.startswith(' ') and not line.startswith('\t'):
                    # Plane header line: "192  0  0  0,0  0,0  0  0x00000007"
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        plane_id = int(parts[0])

                        # Check next line for formats
                        if i + 1 < len(lines) and 'formats:' in lines[i + 1]:
                            has_nv12 = 'NV12' in lines[i + 1]

                            # Check for plane type in subsequent lines
                            plane_type = 3  # Default to invalid
                            for j in range(i + 2, min(i + 15, len(lines))):
                                if 'type:' in lines[j]:
                                    # Next few lines should have the type value
                                    for k in range(j + 1, min(j + 5, len(lines))):
                                        if 'value:' in lines[k]:
                                            try:
                                                plane_type = int(lines[k].split(':')[1].strip())
                                            except (ValueError, IndexError):
                                                pass
                                            break
                                    break

                            # Prefer Overlay planes (type=0) that support NV12
                            if has_nv12 and plane_type < best_plane_type:
                                best_plane = plane_id
                                best_plane_type = plane_type
                                type_name = {0: 'Overlay', 1: 'Primary', 2: 'Cursor'}.get(plane_type, 'Unknown')
                                logger.info(f"Found NV12-capable {type_name} plane: {plane_id}")

                i += 1

            if best_plane is not None:
                result['plane_id'] = best_plane
                type_name = {0: 'Overlay', 1: 'Primary', 2: 'Cursor'}.get(best_plane_type, 'Unknown')
                logger.info(f"Selected plane {best_plane} (type={type_name}) for NV12 output")

        # Determine audio output device based on connector
        # On RK3588: HDMI-A-1 -> hw:0,0 (rockchip-hdmi0), HDMI-A-2 -> hw:1,0 (rockchip-hdmi1)
        if result['connector_name']:
            if 'HDMI-A-1' in result['connector_name']:
                result['audio_device'] = 'hw:0,0'
            elif 'HDMI-A-2' in result['connector_name']:
                result['audio_device'] = 'hw:1,0'
            logger.info(f"Audio output device: {result['audio_device']} (based on {result['connector_name']})")

        logger.info(f"DRM output probe result: connector={result['connector_id']} ({result['connector_name']}), "
                   f"resolution={result['width']}x{result['height']}, plane={result['plane_id']}, "
                   f"audio={result['audio_device']}")

        return result

    except subprocess.TimeoutExpired:
        logger.warning("Timeout probing DRM output")
        return result
    except Exception as e:
        logger.warning(f"Error probing DRM output: {e}")
        return result
