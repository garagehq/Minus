#!/usr/bin/env python3
"""
Autonomous Mode Monitor - Watches system health during overnight autonomous sessions.

Monitors:
- Autonomous mode status and actions
- Memory usage and trends
- FPS and pipeline health
- VLM/OCR worker status
- Fire TV connection
- Ad detection stats
- System resources

Logs to /tmp/autonomous_monitor.log
"""

import json
import os
import subprocess
import time
from datetime import datetime

LOG_FILE = "/tmp/autonomous_monitor.log"
CHECK_INTERVAL = 60  # seconds between checks
MEMORY_WARNING_PERCENT = 80
MEMORY_CRITICAL_PERCENT = 90
FPS_WARNING_THRESHOLD = 20

def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_api(endpoint):
    """Fetch from Minus API."""
    try:
        result = subprocess.run(
            ["curl", "-s", f"http://localhost{endpoint}"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except Exception as e:
        log(f"API error {endpoint}: {e}", "ERROR")
    return None

def get_memory_info():
    """Get memory usage from /proc/meminfo."""
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()

        mem = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                value = int(parts[1])
                mem[key] = value

        total = mem.get("MemTotal", 1)
        available = mem.get("MemAvailable", 0)
        used = total - available
        percent = (used / total) * 100

        return {
            "total_mb": total // 1024,
            "used_mb": used // 1024,
            "available_mb": available // 1024,
            "percent": round(percent, 1)
        }
    except Exception as e:
        log(f"Memory check error: {e}", "ERROR")
        return None

def get_process_info():
    """Get Minus process stats."""
    try:
        result = subprocess.run(
            ["ps", "-C", "python3", "-o", "pid,rss,vsz,%mem,%cpu,etime", "--no-headers"],
            capture_output=True, text=True, timeout=5
        )
        processes = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    processes.append({
                        "pid": parts[0],
                        "rss_kb": int(parts[1]),
                        "vsz_kb": int(parts[2]),
                        "mem_percent": parts[3],
                        "cpu_percent": parts[4],
                        "elapsed": parts[5]
                    })
        return processes
    except Exception:
        return []

def get_fd_count():
    """Get file descriptor count for Minus process."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "minus.py"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split()[0]
            fd_path = f"/proc/{pid}/fd"
            if os.path.exists(fd_path):
                return len(os.listdir(fd_path))
    except Exception:
        pass
    return None

def check_audio_health():
    """Check if audio pipeline is healthy."""
    try:
        result = subprocess.run(
            ["cat", "/proc/asound/card4/pcm0c/sub0/status"],
            capture_output=True, text=True, timeout=5
        )
        capture_running = "RUNNING" in result.stdout

        result = subprocess.run(
            ["cat", "/proc/asound/card0/pcm0p/sub0/status"],
            capture_output=True, text=True, timeout=5
        )
        playback_running = "RUNNING" in result.stdout

        return {"capture": capture_running, "playback": playback_running}
    except Exception:
        return None

def restart_video_pipeline():
    """Restart video pipeline via API."""
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "http://localhost/api/video/restart"],
            capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0
    except Exception:
        return False

def main():
    log("=" * 60)
    log("Autonomous Mode Monitor Started")
    log(f"Check interval: {CHECK_INTERVAL}s")
    log("=" * 60)

    # Track stats over time
    stats = {
        "checks": 0,
        "fps_warnings": 0,
        "memory_warnings": 0,
        "pipeline_restarts": 0,
        "autonomous_issues": 0,
        "start_time": datetime.now().isoformat()
    }

    last_ads_detected = 0
    last_videos_played = 0
    consecutive_low_fps = 0

    while True:
        try:
            stats["checks"] += 1
            check_num = stats["checks"]

            # Get all status data
            status = get_api("/api/status")
            autonomous = get_api("/api/autonomous")
            memory = get_memory_info()
            fd_count = get_fd_count()
            audio = check_audio_health()

            if not status or not autonomous:
                log("Failed to get API status - service may be down", "ERROR")
                time.sleep(CHECK_INTERVAL)
                continue

            # Extract key metrics
            fps = status.get("fps", 0)
            blocking = status.get("blocking", False)
            uptime = status.get("uptime", 0)
            vlm_ready = status.get("vlm_ready", False)
            display_connected = status.get("display_connected", False)

            auto_active = autonomous.get("active", False)
            auto_stats = autonomous.get("stats", {})
            ads_detected = auto_stats.get("ads_detected", 0)
            videos_played = auto_stats.get("videos_played", 0)
            auto_errors = auto_stats.get("errors", 0)
            fire_tv_connected = autonomous.get("fire_tv_connected", False)

            # Log periodic summary (every 10 checks = ~10 minutes)
            if check_num % 10 == 1:
                log("-" * 40)
                log(f"SUMMARY (check #{check_num}, uptime {uptime//60}m)")
                log(f"  FPS: {fps:.1f} | Blocking: {blocking} | VLM: {vlm_ready}")
                log(f"  Memory: {memory['percent']}% ({memory['used_mb']}MB/{memory['total_mb']}MB)")
                log(f"  FDs: {fd_count} | Display: {display_connected}")
                log(f"  Autonomous: {auto_active} | FireTV: {fire_tv_connected}")
                log(f"  Ads: {ads_detected} | Videos: {videos_played} | Errors: {auto_errors}")
                if audio:
                    log(f"  Audio: capture={audio['capture']}, playback={audio['playback']}")
                log("-" * 40)

            # Check for issues

            # 1. FPS problems
            if fps < FPS_WARNING_THRESHOLD and display_connected:
                consecutive_low_fps += 1
                log(f"Low FPS: {fps:.1f} (consecutive: {consecutive_low_fps})", "WARN")
                stats["fps_warnings"] += 1

                # Auto-restart pipeline after 3 consecutive low FPS readings
                if consecutive_low_fps >= 3:
                    log("Attempting pipeline restart due to sustained low FPS", "WARN")
                    if restart_video_pipeline():
                        log("Pipeline restart initiated", "INFO")
                        stats["pipeline_restarts"] += 1
                    consecutive_low_fps = 0
            else:
                consecutive_low_fps = 0

            # 2. Memory issues
            if memory and memory["percent"] > MEMORY_CRITICAL_PERCENT:
                log(f"CRITICAL memory usage: {memory['percent']}%", "ERROR")
                stats["memory_warnings"] += 1
            elif memory and memory["percent"] > MEMORY_WARNING_PERCENT:
                log(f"High memory usage: {memory['percent']}%", "WARN")
                stats["memory_warnings"] += 1

            # 3. VLM not ready (should be ready during autonomous)
            if auto_active and not vlm_ready:
                log("VLM not ready during autonomous mode", "WARN")

            # 4. Fire TV disconnected during autonomous
            if auto_active and not fire_tv_connected:
                log("Fire TV disconnected during autonomous mode", "WARN")
                stats["autonomous_issues"] += 1

            # 5. Track ad detection activity
            if ads_detected > last_ads_detected:
                new_ads = ads_detected - last_ads_detected
                log(f"New ads detected: +{new_ads} (total: {ads_detected})")
                last_ads_detected = ads_detected

            if videos_played > last_videos_played:
                new_videos = videos_played - last_videos_played
                log(f"Videos played: +{new_videos} (total: {videos_played})")
                last_videos_played = videos_played

            # 6. Check for autonomous errors
            if auto_errors > 0:
                log(f"Autonomous mode errors: {auto_errors}", "WARN")

            # 7. FD leak detection
            if fd_count and fd_count > 500:
                log(f"High FD count: {fd_count} (potential leak)", "WARN")

        except Exception as e:
            log(f"Monitor error: {e}", "ERROR")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
