"""
DRM (Direct Rendering Manager) probing utilities for Minus.

Auto-detects connected HDMI output, preferred resolution, and suitable
DRM plane for NV12 video output on RK3588 hardware.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)


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
