#!/usr/bin/env python3
"""
Minimal stream glitch detector - tests ustreamer alone without any Minus features.
"""
import time
import sys
import urllib.request

STREAM_URL = "http://localhost:9090/stream"
GLITCH_THRESHOLD_MS = 100  # >100ms between frames = glitch

def test_stream(duration_seconds):
    print(f"Testing stream for {duration_seconds}s (glitch threshold: {GLITCH_THRESHOLD_MS}ms)")
    print(f"URL: {STREAM_URL}")
    print("-" * 60)

    glitches = []
    frame_count = 0
    last_frame_time = None
    start_time = time.time()

    try:
        req = urllib.request.Request(STREAM_URL)
        with urllib.request.urlopen(req, timeout=10) as response:
            buffer = b''

            while (time.time() - start_time) < duration_seconds:
                chunk = response.read(65536)
                if not chunk:
                    print("Stream ended!")
                    break

                buffer += chunk

                # Find complete JPEG frames (end with FFD9)
                while b'\xff\xd9' in buffer:
                    frame_end = buffer.find(b'\xff\xd9') + 2
                    now = time.time()

                    if last_frame_time is not None:
                        gap_ms = (now - last_frame_time) * 1000

                        if gap_ms > GLITCH_THRESHOLD_MS:
                            elapsed = now - start_time
                            glitches.append({'time': elapsed, 'gap_ms': gap_ms, 'frame': frame_count})
                            print(f"[GLITCH] t={elapsed:.1f}s frame={frame_count} gap={gap_ms:.0f}ms")

                    last_frame_time = now
                    frame_count += 1
                    buffer = buffer[frame_end:]

                # Progress every 30 seconds
                elapsed = time.time() - start_time
                if frame_count > 0 and frame_count % 1800 == 0:  # ~30s at 60fps
                    fps = frame_count / elapsed
                    print(f"[STATUS] t={elapsed:.0f}s frames={frame_count} fps={fps:.1f} glitches={len(glitches)}")

    except Exception as e:
        print(f"Error: {e}")

    # Final report
    duration = time.time() - start_time
    fps = frame_count / duration if duration > 0 else 0
    print("-" * 60)
    print(f"Duration: {duration:.1f}s")
    print(f"Frames: {frame_count}")
    print(f"FPS: {fps:.1f}")
    print(f"Glitches: {len(glitches)}")

    if glitches:
        gaps = [g['gap_ms'] for g in glitches]
        print(f"Gap range: {min(gaps):.0f}ms - {max(gaps):.0f}ms")
        print("First 10 glitches:")
        for g in glitches[:10]:
            print(f"  t={g['time']:.1f}s: {g['gap_ms']:.0f}ms")

    return len(glitches) == 0

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    success = test_stream(duration)
    sys.exit(0 if success else 1)
