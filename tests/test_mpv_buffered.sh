#!/bin/bash
killall ustreamer vlc mpv gst-launch-1.0 2>/dev/null
fuser -k 9090/tcp 2>/dev/null
sleep 2

echo "=== Testing mpv with heavy buffering ==="

# Start ustreamer
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 4
echo "ustreamer running"

# Start mpv with aggressive caching and buffering
echo "Starting mpv with 5-second cache buffer..."
DISPLAY=:0 mpv --fs --no-audio \
    --cache=yes \
    --demuxer-max-bytes=100M \
    --demuxer-readahead-secs=5 \
    --cache-secs=5 \
    --video-sync=audio \
    --framedrop=no \
    http://localhost:9090/stream 2>&1 &
MPV_PID=$!

sleep 20
echo ""
echo "mpv ran for 20 seconds with 5s buffer."

# Check if still running
if ps -p $MPV_PID > /dev/null 2>&1; then
    echo "mpv is still running (good)"
else
    echo "mpv exited"
fi

killall mpv ustreamer 2>/dev/null
echo "Done"
