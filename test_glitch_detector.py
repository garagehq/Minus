#!/usr/bin/env python3
"""
Comprehensive stability monitor for Minus.
Monitors video glitches, CPU, NPU, memory, and pipeline health.
"""

import time
import sys
import os
import urllib.request
import json
import threading
import statistics
import subprocess
from collections import deque
from datetime import datetime


class StabilityMonitor:
    def __init__(self, test_duration=1800):
        self.test_duration = test_duration
        self.stream_url = "http://localhost:9090/stream"
        self.api_url = "http://localhost:80/api/status"

        # Video monitoring
        self.frame_times = deque(maxlen=1000)
        self.glitches = []
        self.frame_count = 0
        self.glitch_threshold_ms = 100  # >100ms between frames = glitch

        # System monitoring
        self.memory_samples = []
        self.cpu_samples = []
        self.sample_interval = 5  # Sample every 5 seconds
        self.last_cpu_times = None

        # Pipeline health
        self.pipeline_restarts = 0
        self.audio_restarts = 0
        self.api_failures = 0
        self.fps_samples = []

        # Blocking state tracking
        self.blocking_active = False
        self.last_blocking_start = None
        self.last_blocking_end = None
        self.blocking_events = []  # List of (start_time, end_time) tuples
        self.blocking_proximity_seconds = 5  # Glitches within N seconds of blocking

        # Timing
        self.start_time = None
        self.running = False

        # Threads
        self.video_thread = None
        self.monitor_thread = None

    def get_cpu_usage(self):
        """Get CPU usage percentage."""
        try:
            with open('/proc/stat', 'r') as f:
                line = f.readline()
            parts = line.split()
            # user, nice, system, idle, iowait, irq, softirq
            times = [int(x) for x in parts[1:8]]
            total = sum(times)
            idle = times[3] + times[4]  # idle + iowait

            if self.last_cpu_times:
                total_diff = total - self.last_cpu_times[0]
                idle_diff = idle - self.last_cpu_times[1]
                if total_diff > 0:
                    usage = 100 * (1 - idle_diff / total_diff)
                else:
                    usage = 0
            else:
                usage = 0

            self.last_cpu_times = (total, idle)
            return usage
        except:
            return -1

    def get_memory_usage(self):
        """Get current memory usage percentage."""
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem_total = int(lines[0].split()[1])
            mem_avail = int(lines[2].split()[1])
            return 100 * (1 - mem_avail / mem_total)
        except:
            return -1

    def get_process_memory(self):
        """Get minus process memory in MB."""
        try:
            result = subprocess.run(
                ['ps', '-C', 'python3', '-o', 'rss=', '--sort=-rss'],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                rss_kb = int(result.stdout.strip().split('\n')[0])
                return rss_kb / 1024
        except:
            pass
        return -1

    def get_rknpu_usage(self):
        """Get RK3588 NPU usage if available."""
        try:
            # Try to read NPU load from sysfs
            npu_paths = [
                '/sys/class/devfreq/fdab0000.npu/load',
                '/sys/kernel/debug/rknpu/load',
            ]
            for path in npu_paths:
                if os.path.exists(path):
                    with open(path, 'r') as f:
                        return f.read().strip()
            return None
        except:
            return None

    def get_axera_usage(self):
        """Get Axera NPU usage via axcl_smi."""
        try:
            result = subprocess.run(
                ['axcl_smi', '-q'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                # Parse NPU utilization from output
                for line in result.stdout.split('\n'):
                    if 'NPU' in line and '%' in line:
                        # Extract percentage
                        parts = line.split()
                        for p in parts:
                            if '%' in p:
                                return p.replace('%', '')
            return None
        except:
            return None

    def get_ustreamer_stats(self):
        """Get ustreamer streaming stats."""
        try:
            req = urllib.request.Request("http://localhost:9090/state")
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                result = data.get('result', {})
                source = result.get('source', {})
                stream = result.get('stream', {})
                return {
                    'captured_fps': source.get('captured_fps', 0),
                    'queued_fps': stream.get('queued_fps', 0),
                    'clients': stream.get('clients', 0),
                }
        except:
            return None

    def check_api_status(self):
        """Check API status and return stats."""
        try:
            req = urllib.request.Request(self.api_url)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                return {
                    'fps': data.get('fps', 0),
                    'video_ok': data.get('video_ok', False),
                    'uptime': data.get('uptime', 0),
                    'memory': data.get('memory_percent', 0),
                    'blocking': data.get('blocking', False),
                }
        except:
            return None

    def update_blocking_state(self, is_blocking):
        """Track blocking state transitions."""
        elapsed = time.time() - self.start_time

        if is_blocking and not self.blocking_active:
            # Blocking just started
            self.blocking_active = True
            self.last_blocking_start = elapsed
            print(f"[BLOCKING START] t={elapsed:.1f}s")
        elif not is_blocking and self.blocking_active:
            # Blocking just ended
            self.blocking_active = False
            self.last_blocking_end = elapsed
            if self.last_blocking_start is not None:
                duration = elapsed - self.last_blocking_start
                self.blocking_events.append((self.last_blocking_start, elapsed, duration))
                print(f"[BLOCKING END] t={elapsed:.1f}s (duration={duration:.1f}s)")

    def is_near_blocking(self, glitch_time):
        """Check if a glitch occurred near a blocking event."""
        proximity = self.blocking_proximity_seconds

        # Check if currently blocking
        if self.blocking_active:
            return True, "during"

        # Check if within N seconds after blocking ended
        if self.last_blocking_end is not None:
            seconds_since_end = glitch_time - self.last_blocking_end
            if 0 <= seconds_since_end <= proximity:
                return True, f"after({seconds_since_end:.1f}s)"

        # Check if within N seconds before blocking started (for any event)
        for start, end, _ in self.blocking_events:
            if start - proximity <= glitch_time <= start:
                return True, f"before({start - glitch_time:.1f}s)"
            if start <= glitch_time <= end:
                return True, "during"
            if end <= glitch_time <= end + proximity:
                return True, f"after({glitch_time - end:.1f}s)"

        return False, "normal"

    def check_log_for_issues(self):
        """Check log file for pipeline restarts and errors."""
        try:
            result = subprocess.run(
                ['tail', '-100', '/tmp/minus.log'],
                capture_output=True, text=True, timeout=5
            )
            log = result.stdout
            video_restarts = log.count('Restarting pipeline')
            audio_restarts = log.count('[AudioPassthrough] Restarting')
            return {
                'video_restarts': video_restarts,
                'audio_restarts': audio_restarts,
            }
        except:
            return None

    def monitor_video_stream(self):
        """Monitor the MJPEG stream and detect timing glitches."""
        last_frame_time = None

        try:
            req = urllib.request.Request(self.stream_url)
            with urllib.request.urlopen(req, timeout=10) as response:
                buffer = b''

                while self.running:
                    chunk = response.read(65536)
                    if not chunk:
                        print(f"[VIDEO] Stream ended unexpectedly!")
                        break

                    buffer += chunk

                    while b'\xff\xd9' in buffer:
                        frame_end = buffer.find(b'\xff\xd9') + 2
                        now = time.time()

                        if last_frame_time is not None:
                            gap_ms = (now - last_frame_time) * 1000
                            self.frame_times.append(gap_ms)

                            if gap_ms > self.glitch_threshold_ms:
                                elapsed = now - self.start_time

                                # Capture system state at glitch time
                                cpu = self.get_cpu_usage()
                                ustreamer = self.get_ustreamer_stats()

                                # Check blocking proximity
                                near_blocking, blocking_context = self.is_near_blocking(elapsed)

                                glitch_info = {
                                    'time': elapsed,
                                    'gap_ms': gap_ms,
                                    'frame': self.frame_count,
                                    'cpu': cpu,
                                    'ustreamer': ustreamer,
                                    'near_blocking': near_blocking,
                                    'blocking_context': blocking_context,
                                }
                                self.glitches.append(glitch_info)

                                # Detailed glitch output
                                extra = ""
                                if cpu > 0:
                                    extra += f" cpu={cpu:.0f}%"
                                if ustreamer:
                                    extra += f" cap={ustreamer.get('captured_fps', 0)} queue={ustreamer.get('queued_fps', 0)} clients={ustreamer.get('clients', 0)}"
                                extra += f" [{blocking_context}]"

                                print(f"[GLITCH] t={elapsed:.1f}s frame={self.frame_count} gap={gap_ms:.0f}ms{extra}")

                        last_frame_time = now
                        self.frame_count += 1
                        buffer = buffer[frame_end:]

        except Exception as e:
            print(f"[VIDEO ERROR] {e}")

    def monitor_health(self):
        """Periodic health check thread."""
        last_sample_time = 0
        last_progress_time = 0
        initial_memory = None

        while self.running:
            now = time.time()
            elapsed = now - self.start_time

            # Sample system stats
            if now - last_sample_time >= self.sample_interval:
                last_sample_time = now

                cpu = self.get_cpu_usage()
                sys_mem = self.get_memory_usage()
                proc_mem = self.get_process_memory()

                if initial_memory is None and proc_mem > 0:
                    initial_memory = proc_mem

                self.cpu_samples.append({'time': elapsed, 'cpu': cpu})
                self.memory_samples.append({
                    'time': elapsed,
                    'system_percent': sys_mem,
                    'process_mb': proc_mem
                })

            # Progress report every 30 seconds
            if now - last_progress_time >= 30:
                last_progress_time = now

                status = self.check_api_status()
                log_issues = self.check_log_for_issues()
                ustreamer = self.get_ustreamer_stats()

                fps = self.frame_count / elapsed if elapsed > 0 else 0
                self.fps_samples.append(fps)

                cpu = self.get_cpu_usage()
                sys_mem = self.get_memory_usage()
                proc_mem = self.get_process_memory()

                # Build status line
                parts = [
                    f"t={elapsed:.0f}s",
                    f"frames={self.frame_count}",
                    f"fps={fps:.1f}",
                    f"glitches={len(self.glitches)}",
                    f"cpu={cpu:.0f}%",
                    f"mem={sys_mem:.1f}%/{proc_mem:.0f}MB",
                ]

                if status:
                    parts.append(f"api_fps={status['fps']:.1f}")
                    parts.append(f"video_ok={status['video_ok']}")
                    if not status['video_ok']:
                        print(f"[PIPELINE ERROR] Video not OK!")
                    # Track blocking state transitions
                    self.update_blocking_state(status.get('blocking', False))
                    if status.get('blocking', False):
                        parts.append("BLOCKING")
                else:
                    self.api_failures += 1
                    parts.append("api=FAIL")

                if ustreamer:
                    parts.append(f"cap={ustreamer.get('captured_fps', 0)}fps")

                if log_issues:
                    if log_issues['video_restarts'] > self.pipeline_restarts:
                        diff = log_issues['video_restarts'] - self.pipeline_restarts
                        self.pipeline_restarts = log_issues['video_restarts']
                        print(f"[PIPELINE RESTART] {diff} video restart(s)!")
                    if log_issues['audio_restarts'] > self.audio_restarts:
                        diff = log_issues['audio_restarts'] - self.audio_restarts
                        self.audio_restarts = log_issues['audio_restarts']
                        print(f"[AUDIO RESTART] {diff} audio restart(s)!")
                    parts.append(f"restarts={self.pipeline_restarts}v/{self.audio_restarts}a")

                print(f"[STATUS] {' '.join(parts)}")

            time.sleep(1)

    def run(self):
        """Run the stability test."""
        print(f"{'='*70}")
        print(f"STABILITY MONITOR - {self.test_duration}s test")
        print(f"{'='*70}")
        print(f"Video stream: {self.stream_url}")
        print(f"Glitch threshold: >{self.glitch_threshold_ms}ms between frames")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}")

        self.start_time = time.time()
        self.running = True

        # Initialize CPU tracking
        self.get_cpu_usage()

        self.video_thread = threading.Thread(target=self.monitor_video_stream, daemon=True)
        self.monitor_thread = threading.Thread(target=self.monitor_health, daemon=True)

        self.video_thread.start()
        self.monitor_thread.start()

        try:
            while self.running and (time.time() - self.start_time) < self.test_duration:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED]")

        self.running = False
        time.sleep(2)

        self.print_report()

    def print_report(self):
        """Print comprehensive final report."""
        duration = time.time() - self.start_time

        print(f"\n{'='*70}")
        print(f"STABILITY REPORT")
        print(f"{'='*70}")
        print(f"Duration: {duration:.1f}s ({duration/60:.1f} minutes)")

        # Video stats
        print(f"\n--- VIDEO ---")
        print(f"Frames received: {self.frame_count}")
        avg_fps = self.frame_count/duration if duration > 0 else 0
        print(f"Average FPS: {avg_fps:.1f}")
        print(f"Glitches detected: {len(self.glitches)}")

        if self.frame_times:
            times = list(self.frame_times)
            print(f"Frame timing (ms): min={min(times):.1f} max={max(times):.1f} avg={statistics.mean(times):.1f}")

        # Analyze glitches
        if self.glitches:
            print(f"\n--- GLITCH ANALYSIS ---")
            gaps = [g['gap_ms'] for g in self.glitches]
            cpus = [g['cpu'] for g in self.glitches if g.get('cpu', 0) > 0]

            print(f"Gap times (ms): min={min(gaps):.0f} max={max(gaps):.0f} avg={statistics.mean(gaps):.0f}")
            if cpus:
                print(f"CPU at glitch: min={min(cpus):.0f}% max={max(cpus):.0f}% avg={statistics.mean(cpus):.0f}%")

            # BLOCKING CORRELATION ANALYSIS
            print(f"\n--- BLOCKING CORRELATION ---")
            near_blocking_glitches = [g for g in self.glitches if g.get('near_blocking', False)]
            normal_glitches = [g for g in self.glitches if not g.get('near_blocking', False)]

            print(f"Total glitches: {len(self.glitches)}")
            print(f"  Near blocking (within {self.blocking_proximity_seconds}s): {len(near_blocking_glitches)} ({100*len(near_blocking_glitches)/len(self.glitches):.1f}%)")
            print(f"  During normal playback: {len(normal_glitches)} ({100*len(normal_glitches)/len(self.glitches):.1f}%)")

            if near_blocking_glitches:
                contexts = {}
                for g in near_blocking_glitches:
                    ctx = g.get('blocking_context', 'unknown')
                    contexts[ctx] = contexts.get(ctx, 0) + 1
                print(f"\nNear-blocking breakdown:")
                for ctx, count in sorted(contexts.items()):
                    print(f"  {ctx}: {count}")

            if self.blocking_events:
                print(f"\nBlocking events: {len(self.blocking_events)}")
                total_blocking_time = sum(e[2] for e in self.blocking_events)
                print(f"Total blocking time: {total_blocking_time:.1f}s")

            # Show first 10 glitches with details
            print(f"\nFirst 10 glitches:")
            for g in self.glitches[:10]:
                extra = ""
                if g.get('cpu', 0) > 0:
                    extra += f" cpu={g['cpu']:.0f}%"
                if g.get('ustreamer'):
                    u = g['ustreamer']
                    extra += f" cap={u.get('captured_fps', 0)}fps"
                extra += f" [{g.get('blocking_context', '?')}]"
                print(f"  t={g['time']:.1f}s: {g['gap_ms']:.0f}ms{extra}")

            # Show normal playback glitches separately if any
            if normal_glitches:
                print(f"\nNormal playback glitches (not near blocking):")
                for g in normal_glitches[:10]:
                    extra = ""
                    if g.get('cpu', 0) > 0:
                        extra += f" cpu={g['cpu']:.0f}%"
                    print(f"  t={g['time']:.1f}s: {g['gap_ms']:.0f}ms{extra}")

        # CPU stats
        print(f"\n--- CPU ---")
        if self.cpu_samples:
            cpus = [s['cpu'] for s in self.cpu_samples if s['cpu'] > 0]
            if cpus:
                print(f"CPU usage: min={min(cpus):.0f}% max={max(cpus):.0f}% avg={statistics.mean(cpus):.0f}%")

        # Pipeline health
        print(f"\n--- PIPELINE HEALTH ---")
        print(f"Video restarts: {self.pipeline_restarts}")
        print(f"Audio restarts: {self.audio_restarts}")
        print(f"API failures: {self.api_failures}")

        # Memory stats
        print(f"\n--- MEMORY ---")
        if self.memory_samples:
            proc_mems = [s['process_mb'] for s in self.memory_samples if s['process_mb'] > 0]
            if proc_mems:
                print(f"Process memory: start={proc_mems[0]:.0f}MB end={proc_mems[-1]:.0f}MB max={max(proc_mems):.0f}MB")

        # Verdict
        print(f"\n{'='*70}")
        issues = []
        if len(self.glitches) > 0:
            issues.append(f"{len(self.glitches)} glitches")
        if self.pipeline_restarts > 0:
            issues.append(f"{self.pipeline_restarts} video restarts")
        if self.audio_restarts > 0:
            issues.append(f"{self.audio_restarts} audio restarts")

        if issues:
            print(f"RESULT: ISSUES - {', '.join(issues)}")
        else:
            print(f"RESULT: PASSED")
        print(f"{'='*70}")


def main():
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    monitor = StabilityMonitor(test_duration=duration)
    monitor.run()


if __name__ == "__main__":
    main()
