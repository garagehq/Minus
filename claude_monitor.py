#!/usr/bin/env python3
"""
Claude Monitor - Intelligent autonomous mode monitoring and intervention.

This script is designed to be run periodically (every 5 minutes) by Claude
to check on autonomous mode health and take corrective action when stuck.

Key features:
- Multi-signal state detection (OCR, VLM, audio, frame change)
- Smart recovery with escalation (avoids repeating failed strategies)
- System health monitoring (memory, CPU, FD count)
- Detailed logging for Claude to understand what's happening
"""

import json
import os
import subprocess
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path

# State file for tracking recovery attempts
STATE_FILE = Path("/tmp/claude_monitor_state.json")
LOG_FILE = Path("/tmp/claude_monitor.log")

def log(msg, level="INFO"):
    """Log with timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def api_get(endpoint):
    """GET from Minus API."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "10", f"http://localhost{endpoint}"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout:
            return json.loads(r.stdout)
    except Exception as e:
        log(f"API GET {endpoint} failed: {e}", "ERROR")
    return None

def api_post(endpoint, data=None):
    """POST to Minus API."""
    try:
        cmd = ["curl", "-s", "-m", "10", "-X", "POST", f"http://localhost{endpoint}"]
        if data:
            cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(data)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout:
            return json.loads(r.stdout)
    except Exception as e:
        log(f"API POST {endpoint} failed: {e}", "ERROR")
    return None

def roku_api(endpoint):
    """GET from Roku ECP API."""
    try:
        status = api_get("/api/roku/status")
        if not status or not status.get("connected"):
            return None
        ip = status.get("device_info", {}).get("ip")
        if not ip:
            return None
        r = subprocess.run(
            ["curl", "-s", "-m", "5", f"http://{ip}:8060{endpoint}"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return r.stdout
    except Exception as e:
        log(f"Roku API {endpoint} failed: {e}", "ERROR")
    return None

def send_roku_command(cmd):
    """Send command to Roku."""
    try:
        result = api_post("/api/roku/command", {"command": cmd})
        return result and result.get("success", False)
    except:
        return False

def get_audio_status():
    """Check if audio is flowing."""
    try:
        # Check ALSA capture status
        capture = subprocess.run(
            ["cat", "/proc/asound/card4/pcm0c/sub0/status"],
            capture_output=True, text=True, timeout=5
        )
        capture_running = "RUNNING" in capture.stdout

        # Check ALSA playback status
        playback = subprocess.run(
            ["cat", "/proc/asound/card0/pcm0p/sub0/status"],
            capture_output=True, text=True, timeout=5
        )
        playback_running = "RUNNING" in playback.stdout

        return {
            "capture": capture_running,
            "playback": playback_running,
            "flowing": capture_running  # Capture is the key indicator
        }
    except:
        return {"capture": False, "playback": False, "flowing": False}

def get_frame_hash():
    """Get hash of current frame for change detection."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "5", "http://localhost:9090/snapshot", "-o", "/tmp/frame_check.jpg"],
            capture_output=True, timeout=10
        )
        if r.returncode == 0 and os.path.exists("/tmp/frame_check.jpg"):
            with open("/tmp/frame_check.jpg", "rb") as f:
                return hashlib.md5(f.read()).hexdigest()[:16]
    except:
        pass
    return None

def is_frame_changing():
    """Check if frame is changing (video playing vs static)."""
    hash1 = get_frame_hash()
    if not hash1:
        return None
    time.sleep(2)
    hash2 = get_frame_hash()
    if not hash2:
        return None
    return hash1 != hash2

def get_system_health():
    """Get system health metrics."""
    health = {}

    # Memory
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
            total = mem.get("MemTotal", 1)
            available = mem.get("MemAvailable", 0)
            health["mem_percent"] = round((total - available) / total * 100, 1)
            health["mem_available_gb"] = round(available / 1024 / 1024, 1)
    except:
        pass

    # FD count for minus process
    try:
        r = subprocess.run(["pgrep", "-f", "minus.py"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            pid = r.stdout.strip().split()[0]
            fd_path = f"/proc/{pid}/fd"
            if os.path.exists(fd_path):
                health["fd_count"] = len(os.listdir(fd_path))
    except:
        pass

    # CPU (load average)
    try:
        with open("/proc/loadavg") as f:
            load = f.read().split()[0]
            health["load_avg"] = float(load)
    except:
        pass

    return health

def load_state():
    """Load persistent state."""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
    except:
        pass
    return {
        "last_check": None,
        "recovery_attempts": 0,
        "last_recovery": None,
        "last_strategy": None,
        "consecutive_stuck": 0,
        "consecutive_healthy": 0,
    }

def save_state(state):
    """Save persistent state."""
    try:
        state["last_check"] = datetime.now().isoformat()
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except:
        pass

def assess_screen_state():
    """
    Assess current screen state using multiple signals.
    Returns dict with state assessment.
    """
    result = {
        "youtube_active": False,
        "audio_flowing": False,
        "frame_changing": None,
        "ocr_hints": [],
        "vlm_state": None,
        "is_stuck": False,
        "stuck_reason": None,
    }

    # Check Roku active app
    active_app = roku_api("/query/active-app")
    if active_app:
        result["youtube_active"] = "YouTube" in active_app and 'id="837"' in active_app
        # Check for screensaver
        if "<screensaver" in active_app:
            result["is_stuck"] = True
            result["stuck_reason"] = "screensaver_active"
            return result

    # Check audio
    audio = get_audio_status()
    result["audio_flowing"] = audio.get("flowing", False)

    # Check frame changing
    result["frame_changing"] = is_frame_changing()

    # Determine if stuck
    if not result["youtube_active"]:
        result["is_stuck"] = True
        result["stuck_reason"] = "youtube_not_active"
    elif not result["audio_flowing"] and result["frame_changing"] == False:
        result["is_stuck"] = True
        result["stuck_reason"] = "no_audio_static_frame"
    elif not result["audio_flowing"] and result["frame_changing"] == True:
        # Frame changing but no audio - might be loading or muted
        pass
    elif result["audio_flowing"] and result["frame_changing"] == False:
        # Audio flowing but static frame - could be music video (OK) or lofi stream (OK)
        pass

    return result

def execute_recovery(state, screen_state):
    """
    Execute recovery based on screen state and previous attempts.
    Uses escalating strategies.
    """
    reason = screen_state.get("stuck_reason")
    attempts = state.get("recovery_attempts", 0)
    last_strategy = state.get("last_strategy")

    log(f"Executing recovery: reason={reason}, attempts={attempts}, last={last_strategy}")

    if reason == "screensaver_active":
        # Wake up from screensaver
        log("Recovery: Dismissing screensaver")
        send_roku_command("select")
        time.sleep(2)
        state["last_strategy"] = "dismiss_screensaver"
        state["recovery_attempts"] = attempts + 1
        return True

    if reason == "youtube_not_active":
        # Launch YouTube
        log("Recovery: Launching YouTube")
        api_post("/api/roku/launch/youtube")
        time.sleep(4)
        state["last_strategy"] = "launch_youtube"
        state["recovery_attempts"] = attempts + 1
        return True

    if reason == "no_audio_static_frame":
        # Escalating recovery strategies
        strategies = [
            ("play_pause", lambda: send_roku_command("play_pause")),
            ("select", lambda: send_roku_command("select")),
            ("back_and_select", lambda: (send_roku_command("back"), time.sleep(1.5),
                                          send_roku_command("down"), time.sleep(0.5),
                                          send_roku_command("select"))),
            ("home_youtube", lambda: (send_roku_command("home"), time.sleep(2),
                                       api_post("/api/roku/launch/youtube"), time.sleep(4),
                                       send_roku_command("down"), time.sleep(0.5),
                                       send_roku_command("select"))),
        ]

        # Pick next strategy (cycle through)
        strategy_idx = attempts % len(strategies)
        strategy_name, strategy_fn = strategies[strategy_idx]

        log(f"Recovery: Trying strategy '{strategy_name}' (attempt {attempts + 1})")
        strategy_fn()

        state["last_strategy"] = strategy_name
        state["recovery_attempts"] = attempts + 1
        return True

    return False

def fix_autonomous_device():
    """Fix autonomous mode device connection if needed."""
    auto = api_get("/api/autonomous")
    roku = api_get("/api/roku/status")

    if not auto or not roku:
        return False

    # Check if Roku is connected but autonomous doesn't know about it
    if roku.get("connected") and not auto.get("device_connected"):
        log("Fixing autonomous mode device connection...")
        # Reconnect Roku to trigger the autonomous mode update
        ip = roku.get("device_info", {}).get("ip")
        if ip:
            result = api_post("/api/roku/connect", {"ip": ip})
            if result and result.get("success"):
                log("Autonomous mode device connection fixed")
                return True
    return False

def run_check():
    """Run a single monitoring check."""
    print("\n" + "="*60)
    log("Claude Monitor Check Starting")
    print("="*60)

    # Fix device connection if needed
    fix_autonomous_device()

    # Load state
    state = load_state()

    # Get main status
    status = api_get("/api/status")
    if not status:
        log("Cannot reach Minus API", "ERROR")
        return

    # Get autonomous status
    auto = api_get("/api/autonomous")
    if not auto:
        log("Cannot get autonomous status", "ERROR")
        return

    # Get system health
    health = get_system_health()

    # Print status summary
    print("\n--- SYSTEM STATUS ---")
    print(f"FPS: {status.get('fps', 0):.1f}")
    print(f"Blocking: {status.get('blocking', False)}")
    print(f"Uptime: {status.get('uptime', 0) // 60}m")
    print(f"VLM Ready: {status.get('vlm_ready', False)}")
    print(f"Memory: {health.get('mem_percent', '?')}% (avail: {health.get('mem_available_gb', '?')}GB)")
    print(f"FD Count: {health.get('fd_count', '?')}")
    print(f"Load Avg: {health.get('load_avg', '?')}")

    print("\n--- AUTONOMOUS MODE ---")
    print(f"Enabled: {auto.get('enabled', False)}")
    print(f"Active: {auto.get('active', False)}")
    print(f"Device: {auto.get('device_type', '?')}")
    print(f"Connected: {auto.get('device_connected', False)}")
    stats = auto.get('stats', {})
    print(f"Session Duration: {stats.get('duration_minutes', 0)}m")
    print(f"Videos Played: {stats.get('videos_played', 0)}")
    print(f"Errors: {stats.get('errors', 0)}")

    # Assess screen state
    print("\n--- SCREEN STATE ---")
    screen = assess_screen_state()
    print(f"YouTube Active: {screen.get('youtube_active', '?')}")
    print(f"Audio Flowing: {screen.get('audio_flowing', '?')}")
    print(f"Frame Changing: {screen.get('frame_changing', '?')}")
    print(f"Is Stuck: {screen.get('is_stuck', False)}")
    if screen.get("stuck_reason"):
        print(f"Stuck Reason: {screen.get('stuck_reason')}")

    # Check for issues
    issues = []

    # Memory leak detection
    if health.get("mem_percent", 0) > 85:
        issues.append(f"HIGH MEMORY: {health['mem_percent']}%")

    # FD leak detection
    if health.get("fd_count", 0) > 500:
        issues.append(f"HIGH FD COUNT: {health['fd_count']}")

    # Screen stuck
    if screen.get("is_stuck"):
        issues.append(f"SCREEN STUCK: {screen.get('stuck_reason')}")

    # Device disconnected
    if auto.get("active") and not auto.get("device_connected"):
        issues.append("DEVICE DISCONNECTED")

    print("\n--- ISSUES ---")
    if issues:
        for issue in issues:
            print(f"  ! {issue}")
    else:
        print("  None detected")

    # Handle stuck state
    if screen.get("is_stuck"):
        state["consecutive_stuck"] += 1
        state["consecutive_healthy"] = 0

        if state["consecutive_stuck"] >= 1:  # Act immediately on stuck
            print("\n--- RECOVERY ACTION ---")
            if execute_recovery(state, screen):
                print(f"  Recovery executed: {state.get('last_strategy')}")
            else:
                print("  No recovery action available")
    else:
        state["consecutive_healthy"] += 1
        if state["consecutive_healthy"] >= 2:
            # Reset recovery state after sustained health
            state["recovery_attempts"] = 0
            state["consecutive_stuck"] = 0

    # Save state
    save_state(state)

    print("\n--- RECOVERY STATE ---")
    print(f"Consecutive Stuck: {state.get('consecutive_stuck', 0)}")
    print(f"Consecutive Healthy: {state.get('consecutive_healthy', 0)}")
    print(f"Recovery Attempts: {state.get('recovery_attempts', 0)}")
    print(f"Last Strategy: {state.get('last_strategy', 'none')}")

    print("\n" + "="*60)
    log("Check Complete")
    print("="*60 + "\n")

    return {
        "status": status,
        "auto": auto,
        "health": health,
        "screen": screen,
        "issues": issues,
        "state": state,
    }

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else 300
        log(f"Starting monitoring loop (interval: {interval}s)")
        while True:
            try:
                run_check()
            except Exception as e:
                log(f"Check failed: {e}", "ERROR")
            time.sleep(interval)
    else:
        run_check()
