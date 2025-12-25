#!/bin/bash
killall ustreamer gst-launch-1.0 2>/dev/null
fuser -k 9090/tcp 2>/dev/null
sleep 2

echo "=== FPS Test with rkximagesink ==="
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 4

echo "Starting display..."
DISPLAY=:0 gst-launch-1.0 -v souphttpsrc location=http://localhost:9090/stream ! multipartdemux ! jpegparse ! mppjpegdec ! rkximagesink sync=false 2>&1 &
GST_PID=$!
sleep 8

# Make fullscreen
DISPLAY=:0 wmctrl -r :ACTIVE: -b add,fullscreen 2>/dev/null
sleep 2

# Count JPEG frames properly using python
echo "Counting frames..."
python3 -c "
import urllib.request
import time

url = 'http://localhost:9090/stream'
req = urllib.request.Request(url)

start = time.time()
frames = 0
data = b''

try:
    with urllib.request.urlopen(req, timeout=6) as resp:
        while time.time() - start < 5:
            chunk = resp.read(4096)
            if not chunk:
                break
            data += chunk
            # Count JPEG starts (FFD8)
            frames = data.count(b'\xff\xd8')
except:
    pass

elapsed = time.time() - start
print(f'Frames: {frames} in {elapsed:.1f}s = {frames/elapsed:.1f} FPS')
"

# Check if gst-launch is still running
if ps -p $GST_PID > /dev/null 2>&1; then
    echo "Display still running (good)"
else
    echo "Display crashed"
fi

killall gst-launch-1.0 ustreamer 2>/dev/null
echo "Done"
