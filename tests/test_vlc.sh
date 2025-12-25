#!/bin/bash
killall ustreamer vlc gst-launch-1.0 2>/dev/null
fuser -k 9090/tcp 2>/dev/null
sleep 2

echo "=== Testing VLC for 4K MJPEG display ==="

# Start ustreamer
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 4
echo "ustreamer running"

# Start VLC in fullscreen with hardware acceleration
echo "Starting VLC fullscreen..."
DISPLAY=:0 cvlc --fullscreen --no-osd --network-caching=2000 --file-caching=2000 \
    http://localhost:9090/stream 2>&1 &
VLC_PID=$!

sleep 15
echo ""
echo "VLC ran for 15 seconds. Did it display the stream smoothly?"
echo "VLC PID: $VLC_PID"

# Check if still running
if ps -p $VLC_PID > /dev/null 2>&1; then
    echo "VLC is still running (good)"
else
    echo "VLC crashed or exited"
fi

# Cleanup
killall vlc ustreamer 2>/dev/null
echo "Done"
